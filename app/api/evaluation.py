# 后端 RAGAS 评估 API — 仅忠实度（Faithfulness），手动触发
from fastapi import APIRouter  # 后端 FastAPI 核心
from pydantic import BaseModel  # 后端 请求模型校验

router = APIRouter()  # 后端 评估路由


class AnswerEvalRequest(BaseModel):
    """后端 评估已有回答 — 不重新生成，直接用聊天中的回答评估"""
    question: str  # 后端 用户问题
    answer: str  # 后端 AI 已有的回答（来自聊天，不需要 LLM 重新生成）
    context_text: str = ""  # 后端 AI 生成时使用的原始上下文（前端 msg.context），避免评估时重新检索拿到不同的上下文


@router.post("/evaluate/answer")
async def evaluate_answer(request: AnswerEvalRequest):
    """
    后端 评估已有回答 — 仅计算忠实度（Faithfulness），~10秒
    优先使用前端传入的 context_text（AI 生成时的上下文），
    避免评估上下文和生成上下文不一致
    """
    import time  # 后端 计时
    import traceback  # 后端 详细错误日志
    from app.services.evaluation_service import _run_retrieval_pipeline, _build_dashscope_llm

    # 上下文来源：优先用前端传来的原始上下文（AI 生成时用的），没有才重新检索
    if request.context_text and request.context_text.strip():  # 后端 用 AI 生成时的上下文
        # 按双换行或单换行拆成多个上下文片段（和检索返回的格式一致）
        raw_contexts = [c.strip() for c in request.context_text.split("\n\n") if c.strip()]  # 后端 先按段落拆
        if len(raw_contexts) <= 1:  # 后端 段落拆分不开就按行拆
            raw_contexts = [c.strip() for c in request.context_text.split("\n") if c.strip()]
        contexts = raw_contexts[:3]  # 后端 最多取3段
    else:  # 后端 兜底：重新检索
        contexts = _run_retrieval_pipeline(request.question)

    from ragas.metrics.collections.faithfulness import Faithfulness  # 后端 忠实度（核心指标：检测幻觉）

    t0 = time.time()  # 后端 开始计时
    # Faithfulness 内部两步：1) 拆解回答为陈述句  2) 逐句 NLI 校验是否被上下文支撑
    # 共 2 次 LLM 调用，约 8~15 秒
    try:
        llm = _build_dashscope_llm()  # 后端 独立 LLM 客户端
        m = Faithfulness(llm=llm)
        s = await m.abatch_score(
            [{"user_input": request.question, "response": request.answer, "retrieved_contexts": contexts}]
        )  # 后端 异步，不阻塞主事件循环
        score = round(float(sum(x.value for x in s) / len(s)), 4)
        error_detail = None  # 后端 无错误
    except Exception as e:  # 后端 捕获并记录详细错误
        print(f"[评估失败] faithfulness: {e}")
        traceback.print_exc()
        score = None  # 后端 计算失败，分数为空
        error_detail = str(e)  # 后端 返回错误详情给前端
    elapsed = round(time.time() - t0, 1)  # 后端 计时（秒）

    from app.core.config import settings as _settings
    return {
        "scores": {"faithfulness": score},
        "elapsed_seconds": elapsed,
        "error": error_detail,
        "note": "仅计算忠实度（Faithfulness）— 检测回答是否基于上下文、有无幻觉",
        "model": _settings.DEFAULT_MODEL,
    }
