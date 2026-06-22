# 后端 RAGAS 评估 API — 量化 RAG 质量
from fastapi import APIRouter, HTTPException  # 后端 FastAPI 核心
from pydantic import BaseModel  # 后端 请求模型校验
from app.services.evaluation_service import run_evaluation  # 后端 核心评估逻辑

router = APIRouter()  # 后端 评估路由


class EvaluationRequest(BaseModel):
    questions: list[str]  # 后端 评估问题列表
    ground_truths: list[str]  # 后端 参考答案列表（和 questions 一一对应）


@router.post("/evaluate")
async def evaluate_rag(request: EvaluationRequest):
    """
    后端 RAGAS 评估接口
    接收 { questions: [...], ground_truths: [...] }
    返回 faithfulness / answer_relevancy / context_precision / context_recall 等指标
    """
    if not request.questions:  # 后端 问题列表为空
        raise HTTPException(status_code=400, detail="questions 不能为空")
    if len(request.questions) != len(request.ground_truths):  # 后端 问题和参考答案数量不匹配
        raise HTTPException(
            status_code=400,
            detail=f"questions({len(request.questions)}) 和 ground_truths({len(request.ground_truths)}) 数量不一致"
        )

    try:
        result = await run_evaluation(
            questions=request.questions,
            ground_truths=request.ground_truths,
        )
        return result  # 后端 返回评估结果
    except ImportError as e:  # 后端 缺少依赖
        raise HTTPException(status_code=500, detail=f"缺少依赖: {e}")
    except Exception as e:  # 后端 其他评估异常
        raise HTTPException(status_code=500, detail=f"评估失败: {str(e)}")


class QuickEvaluationRequest(BaseModel):
    """后端 快速评估 — 只需问题列表，自动用检索到的上下文作为 ground_truth 参考"""
    questions: list[str]  # 后端 评估问题列表


@router.post("/evaluate/quick")
async def quick_evaluate(request: QuickEvaluationRequest):
    """
    后端 快速评估（无需参考答案）
    用检索到的 Top-1 上下文作为 ground_truth，仅计算 faithfulness 和 answer_relevancy
    适合没有人工标注参考答案时快速摸底
    """
    if not request.questions:
        raise HTTPException(status_code=400, detail="questions 不能为空")

    from app.services.evaluation_service import _run_retrieval_pipeline, _run_llm_generation  # 后端 直接复用内部函数
    import asyncio  # 后端 异步

    # 第一步：检索 + 生成
    answers = []
    all_contexts = []
    # 后端 用检索到的第一个上下文片段作为伪参考答案
    pseudo_ground_truths = []

    for query in request.questions:
        contexts = _run_retrieval_pipeline(query)
        answer = await asyncio.to_thread(_run_llm_generation, query, contexts)
        answers.append(answer)
        all_contexts.append(contexts)
        pseudo_ground_truths.append(contexts[0] if contexts else "")  # 后端 Top-1 上下文当参考答案

    # 第二步：用 batch_score() 计算各指标（绕过 evaluate() 的类型不兼容）
    from ragas.metrics.collections.faithfulness import Faithfulness  # 后端 忠实度
    from ragas.metrics.collections.answer_relevancy import AnswerRelevancy  # 后端 答案相关性
    from ragas.metrics.collections.context_precision import ContextPrecision  # 后端 上下文精确度
    # 构建各指标的 batch 输入
    faithfulness_inputs = [  # 后端 忠实度：问题+答案+上下文
        {"user_input": q, "response": a, "retrieved_contexts": c}
        for q, a, c in zip(request.questions, answers, all_contexts)
    ]
    answer_relevancy_inputs = [  # 后端 答案相关性：问题+答案
        {"user_input": q, "response": a}
        for q, a in zip(request.questions, answers)
    ]
    context_precision_inputs = [  # 后端 上下文精确度：问题+伪参考答案+上下文
        {"user_input": q, "reference": g, "retrieved_contexts": c}
        for q, g, c in zip(request.questions, pseudo_ground_truths, all_contexts)
    ]

    # 在线程池并行计算各指标（asyncio.gather 不阻塞事件循环）

    async def _compute_one_metric(metric_name, metric_cls, metric_inputs):
        """后端 在主事件循环中用 abatch_score 异步计算，每个指标独立 LLM/Embeddings"""
        import traceback  # 后端 详细错误栈
        try:
            from app.services.evaluation_service import _build_dashscope_llm, _build_dashscope_embeddings
            llm = _build_dashscope_llm()  # 后端 独立 LLM（避免跨线程事件循环冲突）
            if metric_name == "answer_relevancy":  # 后端 AnswerRelevancy 还需 embeddings
                embeddings = _build_dashscope_embeddings()  # 后端 独立嵌入客户端
                m = metric_cls(llm=llm, embeddings=embeddings)
            else:  # 后端 Faithfulness / ContextPrecision 只需 LLM
                m = metric_cls(llm=llm)
            s = await m.abatch_score(metric_inputs)  # 后端 异步，不阻塞主事件循环
            return metric_name, round(float(sum(x.value for x in s) / len(s)), 4)
        except Exception as e:
            print(f"[快速评估失败] {metric_name}: {e}")
            traceback.print_exc()
            return metric_name, f"计算失败: {e}"

    results = await asyncio.gather(
        _compute_one_metric("faithfulness", Faithfulness, faithfulness_inputs),
        _compute_one_metric("answer_relevancy", AnswerRelevancy, answer_relevancy_inputs),
        _compute_one_metric("context_precision", ContextPrecision, context_precision_inputs),
    )  # 后端 三个指标并行跑，不阻塞事件循环

    scores = {}
    for name, value in results:
        scores[name] = value

    from app.core.config import settings as _settings  # 后端 获取当前模型名
    return {
        "scores": scores,
        "note": "快速评估模式：ground_truth 由检索到的 Top-1 上下文替代，context_recall 不可用",
        "model": _settings.DEFAULT_MODEL,  # 后端 记录评估使用的模型
    }


class AnswerEvalRequest(BaseModel):
    """后端 评估已有回答 — 不重新生成，直接用聊天中的回答评估"""
    question: str  # 后端 用户问题
    answer: str  # 后端 AI 已有的回答（来自聊天，不需要 LLM 重新生成）


@router.post("/evaluate/answer")
async def evaluate_answer(request: AnswerEvalRequest):
    """
    后端 直接评估已有回答（不重新生成，比 /evaluate/quick 快很多）
    流程：检索上下文 → 异步并行计算三指标 → 返回分数
    每个指标独立创建 LLM/Embeddings 客户端，在主事件循环中用 abatch_score，
    避免 batch_score 内部 asyncio.run() 跨线程共享 AsyncOpenAI 导致 httpx 连接冲突
    """
    import asyncio  # 后端 异步并行
    import traceback  # 后端 详细错误日志
    from app.services.evaluation_service import _run_retrieval_pipeline, _build_dashscope_llm, _build_dashscope_embeddings

    # 检索上下文
    contexts = _run_retrieval_pipeline(request.question)
    pseudo_gt = contexts[0] if contexts else ""  # 后端 Top-1 上下文当伪参考答案

    from ragas.metrics.collections.faithfulness import Faithfulness  # 后端 忠实度
    from ragas.metrics.collections.answer_relevancy import AnswerRelevancy  # 后端 答案相关性
    from ragas.metrics.collections.context_precision import ContextPrecision  # 后端 上下文精确度

    # 每个指标独立 LLM/Embeddings 客户端 → 避免跨线程事件循环冲突
    async def _compute_one(metric_name, metric_cls, metric_inputs, needs_embeddings=False):
        """后端 在主事件循环中用 abatch_score 异步计算，不阻塞、不跨线程"""
        try:
            llm = _build_dashscope_llm()  # 后端 独立 LLM 客户端
            if needs_embeddings:  # 后端 AnswerRelevancy 需要嵌入模型
                embeddings = _build_dashscope_embeddings()  # 后端 独立嵌入客户端
                m = metric_cls(llm=llm, embeddings=embeddings)
            else:  # 后端 Faithfulness / ContextPrecision 只需 LLM
                m = metric_cls(llm=llm)
            # 关键：用 abatch_score（异步）替代 batch_score（内部 asyncio.run 开新事件循环）
            s = await m.abatch_score(metric_inputs)
            return metric_name, round(float(sum(x.value for x in s) / len(s)), 4)
        except Exception as e:  # 后端 捕获并记录详细错误
            print(f"[评估失败] {metric_name}: {e}")
            traceback.print_exc()
            return metric_name, f"计算失败: {e}"

    results = await asyncio.gather(
        _compute_one("faithfulness", Faithfulness,
            [{"user_input": request.question, "response": request.answer, "retrieved_contexts": contexts}]),
        _compute_one("answer_relevancy", AnswerRelevancy,
            [{"user_input": request.question, "response": request.answer}],
            needs_embeddings=True),
        _compute_one("context_precision", ContextPrecision,
            [{"user_input": request.question, "reference": pseudo_gt, "retrieved_contexts": contexts}]),
    )  # 后端 三指标并行跑，不阻塞主事件循环

    scores = {}
    for name, value in results:
        scores[name] = value

    from app.core.config import settings as _settings
    return {
        "scores": scores,
        "note": "直接评估模式：使用已有回答，未重新生成，不阻塞聊天",
        "model": _settings.DEFAULT_MODEL,
    }
