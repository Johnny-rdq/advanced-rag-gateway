from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import io
import hashlib  # 后端 文件哈希去重
import json  # 后端 chunk_ids 序列化
import os  # 后端 文件路径操作
import uuid  # 后端 生成唯一文件名

from app.services.agent_service import qwen_llm_generator
from app.database.sqlite_store import (
    save_message, get_all_messages, get_messages_for_session,
    create_session, get_all_sessions, delete_session, update_session_title,
    insert_uploaded_file, get_uploaded_file_by_hash,  # 后端 上传文件记录
    get_all_uploaded_files, get_uploaded_file_by_id, delete_uploaded_file,  # 后端 文件管理
    save_evaluation, get_evaluations_for_session  # 后端 评估持久化
)
from app.database.chroma_store import add_documents_to_db, delete_chunks_by_ids  # 后端 向量库操作
from app.services.document_parser import parse_file, is_format_supported, get_supported_extensions  # 后端 统一文档解析服务
from app.core.config import settings  # 后端 上传目录配置

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

router = APIRouter()


# ==================== 调试接口 ====================

@router.get("/debug")
async def debug_config():
    """查看服务器实际使用的配置"""
    from app.core.config import settings
    return {
        "model": settings.DEFAULT_MODEL,
        "api_key_prefix": settings.DASHSCOPE_API_KEY[:12] + "..." if settings.DASHSCOPE_API_KEY else "None",
        "tavily_key_prefix": settings.TAVILY_API_KEY[:12] + "..." if settings.TAVILY_API_KEY else "None",
    }


# ==================== 请求模型 ====================

class ChatRequest(BaseModel):
    query: str
    session_id: str = "default_session"


# ==================== 聊天接口 ====================

@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
    """流式聊天接口"""
    # 保存用户消息
    save_message(request.session_id, "user", request.query)

    return StreamingResponse(
        qwen_llm_generator(request.query, request.session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/history")
async def get_history(session_id: str = "default_session"):
    """获取会话历史消息"""
    messages = get_all_messages(session_id)
    return {"session_id": session_id, "messages": messages}


# ==================== 会话管理接口（供 React 前端使用） ====================

@router.get("/sessions")
async def list_sessions():
    """获取所有会话列表"""
    sessions = get_all_sessions()
    return sessions


@router.post("/sessions")
async def new_session():
    """创建新会话"""
    session = create_session()
    return session


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    """获取指定会话的所有消息"""
    result = get_messages_for_session(session_id)
    return result


@router.delete("/sessions/{session_id}")
async def remove_session(session_id: str):
    """删除指定会话"""
    delete_session(session_id)
    return {"message": "会话已删除"}


# ==================== 文件上传接口 ====================

@router.post("/upload")
async def upload_file(file: UploadFile = File(...), session_id: str = Form("default_session")):
    """上传文件并存入向量库 — 支持 TXT/PDF/DOCX/PPTX/图片等，自动去重持久化，结果消息写入会话"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    if not is_format_supported(file.filename):  # 后端 检查格式是否支持
        supported = ", ".join(get_supported_extensions())  # 后端 列出当前支持的格式
        return JSONResponse(
            status_code=400,
            content={"message": f"不支持的文件格式: {file.filename}。当前支持: {supported}"}
        )

    content = await file.read()  # 后端 读取全部字节

    # 计算 SHA256 哈希 — 相同文件去重
    file_hash = hashlib.sha256(content).hexdigest()  # 后端 内容哈希，不同文件名相同内容算同一个
    existing = get_uploaded_file_by_hash(file_hash)  # 后端 查 SQLite 是否已有
    if existing:  # 后端 命中缓存，跳过解析和入库
        msg = f"📎 文件已存在（{existing['original_filename']}），复用缓存，无需重复上传"  # 后端 通知消息
        save_message(session_id, "assistant", msg)  # 后端 持久化到会话
        return JSONResponse(content={
            "message": msg,
            "cached": True,  # 后端 前端可据此展示不同提示
            "chunks": existing["chunk_count"],
            "file_id": existing["id"],
            "original_filename": existing["original_filename"],
        })

    text = parse_file(content, file.filename)  # 后端 调用统一解析服务（自动选择 pdfplumber / LlamaParse）

    if not text.strip():
        fail_msg = f"❌ 文件 {file.filename} 解析失败：内容为空或无法识别。如果是扫描件/图片型PDF，请配置 LLAMA_CLOUD_API_KEY。"  # 后端 失败消息
        save_message(session_id, "assistant", fail_msg)  # 后端 持久化失败通知
        return JSONResponse(
            status_code=400,
            content={"message": fail_msg}
        )

    # 按 400 字分段
    chunks = [text[i:i + 400] for i in range(0, len(text), 400) if text[i:i + 400].strip()]
    chunk_ids = add_documents_to_db(chunks)  # 后端 入向量库，获取 chunk ID 列表

    # 保存文件到 uploads 目录
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)  # 后端 确保目录存在
    saved_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"  # 后端 加随机前缀防文件名冲突
    save_path = os.path.join(settings.UPLOAD_DIR, saved_name)  # 后端 拼接完整路径
    with open(save_path, "wb") as f:  # 后端 写入磁盘
        f.write(content)

    # 写入 SQLite 记录（持久化，重启不丢失）
    file_id = insert_uploaded_file(
        filename=saved_name,  # 后端 存盘文件名
        original_filename=file.filename,  # 后端 原始文件名（展示用）
        file_hash=file_hash,  # 后端 哈希（去重键）
        file_size=len(content),  # 后端 文件大小（字节）
        chunk_count=len(chunks),  # 后端 分块数
        parsed_text=text,  # 后端 缓存解析文本（将来可复用）
        chunk_ids=json.dumps(chunk_ids),  # 后端 JSON 序列化 chunk ID 列表
    )

    success_msg = f"✅ 成功解析 {file.filename}，已将 {len(chunks)} 个知识片段存入向量库！"  # 后端 成功消息
    save_message(session_id, "assistant", success_msg)  # 后端 持久化到会话历史

    return JSONResponse(content={
        "message": success_msg,
        "chunks": len(chunks),
        "file_id": file_id,  # 后端 返回记录 ID
        "file_size": len(content),  # 后端 返回文件大小
    })


# ==================== 文件管理接口 ====================

@router.get("/files")
async def list_files():
    """获取所有已上传文件列表（持久化，重启不丢失）"""
    files = get_all_uploaded_files()  # 后端 从 SQLite 读取
    return files  # 后端 返回列表（id, filename, original_filename, file_hash, file_size, chunk_count, uploaded_at）


@router.delete("/files/{file_id}")
async def delete_file(file_id: int):
    """删除上传文件 — 级联删除：向量库片段 → 磁盘文件 → 数据库记录"""
    record = get_uploaded_file_by_id(file_id)  # 后端 查 SQLite
    if not record:  # 后端 文件不存在
        raise HTTPException(status_code=404, detail="文件不存在")

    # 1. 从 ChromaDB 删除向量片段
    if record.get("chunk_ids"):  # 后端 有 chunk IDs 才删
        try:
            chunk_list = json.loads(record["chunk_ids"])  # 后端 反序列化 JSON
            delete_chunks_by_ids(chunk_list)  # 后端 批量删除
        except (json.JSONDecodeError, Exception) as e:  # 后端 JSON 损坏或 ChromaDB 异常
            print(f"[删除] 向量库删除失败: {e}")

    # 2. 从磁盘删除文件
    file_path = os.path.join(settings.UPLOAD_DIR, record["filename"])  # 后端 拼接完整路径
    if os.path.exists(file_path):  # 后端 文件存在才删
        os.remove(file_path)  # 后端 删除磁盘文件

    # 3. 从 SQLite 删除记录
    delete_uploaded_file(file_id)  # 后端 删除数据库记录

    return {"message": f"已删除 {record['original_filename']}"}


# ==================== 评估持久化接口 ====================

class SaveEvalRequest(BaseModel):
    session_id: str  # 后端 所属会话
    question: str  # 后端 用户问题（作为匹配键）
    answer: str = ""  # 后端 AI 回答
    scores: dict  # 后端 {faithfulness: 1.0, answer_relevancy: 0.72, context_precision: 1.0}


@router.post("/evaluations")
async def save_eval(request: SaveEvalRequest):
    """保存评估结果到 SQLite，刷新/重启不丢失"""
    eval_id = save_evaluation(  # 后端 写入数据库
        session_id=request.session_id,
        question=request.question,
        answer=request.answer,
        scores=request.scores,
    )
    return {"id": eval_id, "message": "评估已保存"}


@router.get("/evaluations/{session_id}")
async def get_evals(session_id: str):
    """获取指定会话的所有评估结果 — {question: {scores}}"""
    evals = get_evaluations_for_session(session_id)  # 后端 从 SQLite 读取
    return evals  # 后端 返回 {question: {faithfulness: 1.0, ...}, ...}
