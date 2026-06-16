from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import io

from app.services.agent_service import qwen_llm_generator
from app.database.sqlite_store import (
    save_message, get_all_messages, get_messages_for_session,
    create_session, get_all_sessions, delete_session, update_session_title
)
from app.database.chroma_store import add_documents_to_db

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
async def upload_file(file: UploadFile = File(...)):
    """上传文件并存入向量库"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    content = await file.read()
    text = ""

    # 支持 PDF 和 TXT
    if file.filename.lower().endswith('.pdf') and pdfplumber:
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
        except Exception as e:
            return JSONResponse(
                status_code=400,
                content={"message": f"PDF 解析失败: {str(e)}"}
            )
    elif file.filename.lower().endswith(('.txt', '.md', '.csv')):
        try:
            text = content.decode('utf-8', errors='ignore')
        except Exception:
            text = content.decode('gbk', errors='ignore')
    else:
        return JSONResponse(
            status_code=400,
            content={"message": f"不支持的文件格式: {file.filename}。支持 .txt, .pdf, .md, .csv"}
        )

    if not text.strip():
        return JSONResponse(
            status_code=400,
            content={"message": "文件为空或无法解析出文本内容！"}
        )

    # 按 400 字分段
    chunks = [text[i:i + 400] for i in range(0, len(text), 400) if text[i:i + 400].strip()]
    add_documents_to_db(chunks)

    return JSONResponse(content={
        "message": f"✅ 成功解析 {file.filename}，已将 {len(chunks)} 个知识片段存入向量库！",
        "chunks": len(chunks)
    })
