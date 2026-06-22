# 后端 RAGAS 评估服务 — LLM 客户端 + 检索管道（供 evaluation API 复用）
from app.core.config import settings  # 后端 DashScope API Key / 模型名


def _build_dashscope_llm():
    """
    后端 用 openai.AsyncOpenAI + ragas.llm_factory 桥接 DashScope OpenAI 兼容接口
    RAGAS 0.4.x collections 指标内部调 agenerate() → 必须用 AsyncOpenAI 客户端
    """
    from openai import AsyncOpenAI  # 后端 OpenAI 异步客户端（RAGAS 内部调 agenerate 需要）
    from ragas.llms import llm_factory  # 后端 RAGAS LLM 工厂函数

    dashscope_client = AsyncOpenAI(
        api_key=settings.DASHSCOPE_API_KEY,  # 后端 DashScope API Key
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",  # 后端 DashScope 兼容端点
    )
    return llm_factory(
        model=settings.DEFAULT_MODEL,  # 后端 用.env中配置的模型（如 qwen3.6-flash）
        client=dashscope_client,  # 后端 传入 AsyncOpenAI（支持 agenerate）
        temperature=0,  # 后端 评估任务不需要创造性，0 保证一致性
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
