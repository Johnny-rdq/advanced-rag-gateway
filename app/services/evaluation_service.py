# 后端 RAGAS 评估服务 — LLM 客户端 + 检索管道（供 evaluation API 复用）
from httpx import Timeout  # 后端 httpx 超时对象，必须用对象而非 float，否则 DNS 异常时可能不生效
from app.core.config import settings  # 后端 DashScope API Key / 模型名


def _build_instructor_llm():
    """
    后端 直接创建 instructor 包装的 LLM（绕过 ragas.llm_factory 的 Mode.JSON 硬编码）
    RAGAS 的 llm_factory 内部固定使用 Mode.JSON，千问/DashScope 可能不完全兼容
    这里用 Mode.TOOLS（function calling）或降级到 Mode.MD_JSON（markdown 提取）
    """
    from openai import AsyncOpenAI  # 后端 OpenAI 异步客户端
    from instructor import from_openai, Mode  # 后端 instructor 客户端包装
    from ragas.llms.base import InstructorLLM, InstructorModelArgs  # 后端 RAGAS LLM 包装

    # 后端 用 httpx.Timeout 对象显式设置超时（float 在 httpx 0.28+ 解析 hosts 文件异常时可能不生效）
    _httpx_timeout = Timeout(60.0, connect=10.0, read=55.0, write=30.0, pool=5.0)
    dashscope_client = AsyncOpenAI(
        api_key=settings.DASHSCOPE_API_KEY,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout=_httpx_timeout,
        max_retries=1,  # 后端 最多重试1次，避免无限重试
    )

    # 后端 DashScope 千问 thinking mode 与 tool_choice=required 互斥
    # Mode.TOOLS 会设 tool_choice="required" → 400 错误
    # Mode.JSON 用 response_format (json_object) → 千问可能不完全支持
    # Mode.MD_JSON 纯文本提取 markdown JSON → 最兼容，不依赖任何特殊 API 参数
    _mode = Mode.MD_JSON  # 后端 markdown JSON 提取，兼容 thinking mode
    patched_client = from_openai(dashscope_client, mode=_mode)
    print(f"[评估-LLM] instructor 包装完成，mode={_mode}（兼容千问 thinking mode）")

    return InstructorLLM(
        client=patched_client,
        model=settings.DEFAULT_MODEL,
        provider="openai",
        model_args=InstructorModelArgs(temperature=0.0, max_tokens=4096),
        extra_body={"enable_thinking": False},  # 后端 禁用千问 thinking，评估任务不需要思考，大幅加速
    )


def _run_retrieval_pipeline(query: str) -> list[str]:
    """后端 复用现有混合检索管道，获取 Top-2 上下文片段"""
    from app.database.chroma_store import knowledge_collection
    from app.core.retriever import HybridRetriever
    from app.core.reranker import DocumentReranker

    # 获取全部文档构建 BM25 索引
    try:
        all_docs = knowledge_collection.get()["documents"] or []
    except Exception:
        all_docs = []

    if not all_docs:  # 后端 向量库为空，无法检索
        return []

    retriever = HybridRetriever(all_docs)  # 后端 BM25 + ChromaDB 混合检索
    reranker = DocumentReranker()  # 后端 DashScope 重排序

    candidates = retriever.hybrid_search(query, top_k=10)  # 后端 粗排取10条
    if not candidates:
        return []
    candidates = reranker.rerank(query, candidates, top_k=3)  # 后端 精排取3条给评估
    return candidates[:2]  # 后端 返回 Top-2（和对话流程保持一致）
