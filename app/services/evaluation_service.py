# 后端 RAGAS 评估服务 — 量化 RAG 回答质量（忠实度/相关性/精确度/召回率）
import json  # 后端 序列化结果
import asyncio  # 后端 异步并发
from typing import Optional  # 后端 类型标注
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


def _build_dashscope_embeddings():
    """
    后端 用 openai.AsyncOpenAI + ragas.embeddings.OpenAIEmbeddings 桥接 DashScope 嵌入接口
    RAGAS 0.4.x 指标内部可能调异步方法 → 用 AsyncOpenAI 客户端
    """
    from openai import AsyncOpenAI  # 后端 OpenAI 异步客户端
    from ragas.embeddings import OpenAIEmbeddings  # 后端 RAGAS 内置 OpenAI 嵌入类

    dashscope_client = AsyncOpenAI(
        api_key=settings.DASHSCOPE_API_KEY,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    return OpenAIEmbeddings(
        client=dashscope_client,  # 后端 DashScope 兼容端点（AsyncOpenAI）
        model=settings.EMBEDDING_MODEL,  # 后端 用和检索一致的嵌入模型（text-embedding-v2）
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


def _run_llm_generation(query: str, contexts: list[str]) -> str:
    """
    后端 使用 OpenAI 兼容端点调 DashScope 生成回答（非流式，同步）
    评估生成用 .env 配置的模型，和主聊天保持一致
    """
    from openai import OpenAI  # 后端 OpenAI 客户端（兼容 DashScope）

    client = OpenAI(
        api_key=settings.DASHSCOPE_API_KEY,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    if contexts:  # 后端 有上下文 → 构建 RAG prompt
        rag_context = "\n\n【本地知识库】\n" + "\n".join(contexts)
        user_content = f"{rag_context}\n\n【用户问题】{query}"
    else:  # 后端 无上下文 → 直接提问
        user_content = query

    messages = [
        {"role": "system", "content": "你是企业AI助理。请基于提供的知识库内容回答，回答简洁、用中文。"},
        {"role": "user", "content": user_content},
    ]

    resp = client.chat.completions.create(
        model=settings.DEFAULT_MODEL,  # 后端 用 .env 中配置的模型
        messages=messages,
    )

    if resp.choices:
        return resp.choices[0].message.content or ""
    return ""  # 后端 生成失败返回空


async def run_evaluation(
    questions: list[str],
    ground_truths: list[str],
) -> dict:
    """
    后端 核心评估函数（需要参考答案）
    流程：
      1. 对每个问题 → 检索上下文 → 生成答案
      2. 用 RAGAS collections metrics 的 batch_score() 计算 4 项指标
    返回：各指标平均分 + 每道题的详细结果
    """
    if len(questions) != len(ground_truths):
        return {"error": "questions 和 ground_truths 长度不一致"}

    # 第一步：对每个问题跑检索 + 生成
    answers = []  # 后端 存储 LLM 生成的答案
    all_contexts = []  # 后端 存储每个问题检索到的上下文列表

    for query in questions:
        contexts = _run_retrieval_pipeline(query)  # 后端 检索
        answer = await asyncio.to_thread(_run_llm_generation, query, contexts)  # 后端 在线程池生成
        answers.append(answer)
        all_contexts.append(contexts)

    # 第二步：每个指标独立 LLM/Embeddings，用 abatch_score 在主事件循环中异步计算
    # 避免 batch_score 内部 asyncio.run() 跨线程共享 AsyncOpenAI 导致 httpx 连接冲突
    from ragas.metrics.collections.faithfulness import Faithfulness  # 后端 忠实度
    from ragas.metrics.collections.answer_relevancy import AnswerRelevancy  # 后端 答案相关性
    from ragas.metrics.collections.context_precision import ContextPrecision  # 后端 上下文精确度
    from ragas.metrics.collections.context_recall import ContextRecall  # 后端 上下文召回率

    # 各指标的 batch 输入格式（每个 metric 用不同的字段组合）
    faithfulness_inputs = [  # 后端 忠实度：需要问题+答案+上下文
        {"user_input": q, "response": a, "retrieved_contexts": c}
        for q, a, c in zip(questions, answers, all_contexts)
    ]
    answer_relevancy_inputs = [  # 后端 答案相关性：需要问题+答案
        {"user_input": q, "response": a}
        for q, a in zip(questions, answers)
    ]
    context_precision_inputs = [  # 后端 上下文精确度：需要问题+参考答案+上下文
        {"user_input": q, "reference": g, "retrieved_contexts": c}
        for q, g, c in zip(questions, ground_truths, all_contexts)
    ]
    context_recall_inputs = [  # 后端 上下文召回率：需要问题+上下文+参考答案
        {"user_input": q, "retrieved_contexts": c, "reference": g}
        for q, c, g in zip(questions, all_contexts, ground_truths)
    ]

    # 每个指标独立 LLM/Embeddings 客户端，在主事件循环中用 abatch_score
    async def _compute_one(metric_name, metric_cls, metric_inputs, needs_embeddings=False):
        """后端 独立客户端 + abatch_score（异步），不跨线程、不阻塞"""
        try:
            llm = _build_dashscope_llm()  # 后端 独立 LLM
            if needs_embeddings:  # 后端 AnswerRelevancy 需要嵌入
                emb = _build_dashscope_embeddings()  # 后端 独立嵌入
                m = metric_cls(llm=llm, embeddings=emb)
            else:  # 后端 Faithfulness / ContextPrecision / ContextRecall 只需 LLM
                m = metric_cls(llm=llm)
            s = await m.abatch_score(metric_inputs)  # 后端 异步，不阻塞主事件循环
            return metric_name, round(float(sum(x.value for x in s) / len(s)), 4)
        except Exception as e:
            return metric_name, f"计算失败: {e}"

    results = await asyncio.gather(
        _compute_one("faithfulness", Faithfulness, faithfulness_inputs),
        _compute_one("answer_relevancy", AnswerRelevancy, answer_relevancy_inputs, needs_embeddings=True),
        _compute_one("context_precision", ContextPrecision, context_precision_inputs),
        _compute_one("context_recall", ContextRecall, context_recall_inputs),
    )  # 后端 四指标并行跑，不阻塞主事件循环

    scores = {}
    for name, value in results:
        scores[name] = value

    # 第三步：逐题详情
    details = []
    for i, q in enumerate(questions):
        details.append({
            "question": q,
            "answer": answers[i],
            "contexts": all_contexts[i],
            "ground_truth": ground_truths[i],
        })

    return {
        "scores": scores,  # 后端 各指标平均分
        "details": details,  # 后端 逐题详情
        "model": settings.DEFAULT_MODEL,  # 后端 评估使用的模型
    }
