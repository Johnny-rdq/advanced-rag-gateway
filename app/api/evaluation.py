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
    import asyncio  # 后端 wait_for 超时兜底，防止 abatch_score 卡死
    import traceback  # 后端 详细错误日志
    from app.core.config import settings  # 后端 配置（连通性测试用）
    from app.services.evaluation_service import _run_retrieval_pipeline, _build_instructor_llm

    # 上下文来源：优先用前端传来的原始上下文（AI 生成时用的），没有才重新检索
    if request.context_text and request.context_text.strip():  # 后端 用 AI 生成时的上下文
        raw_contexts = [c.strip() for c in request.context_text.split("\n\n") if c.strip()]  # 后端 先按段落拆
        if len(raw_contexts) <= 1:  # 后端 段落拆分不开就按行拆
            raw_contexts = [c.strip() for c in request.context_text.split("\n") if c.strip()]
        contexts = raw_contexts[:3]  # 后端 最多取3段
    else:  # 后端 兜底：重新检索
        contexts = _run_retrieval_pipeline(request.question)

    from ragas.metrics.collections.faithfulness import Faithfulness  # 后端 忠实度（核心指标：检测幻觉）
    from openai import AsyncOpenAI  # 后端 连通性测试
    from httpx import Timeout  # 后端 连通性测试超时

    t0 = time.time()  # 后端 开始计时
    score = None
    error_detail = None

    print(f"[评估] 开始，question={request.question[:60]}...")

    # 诊断步骤：先做一个简单连通性测试（15s超时），快速确认 API 能通
    t_conn = time.time()
    try:
        _test_client = AsyncOpenAI(
            api_key=settings.DASHSCOPE_API_KEY,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            timeout=Timeout(12.0, connect=8.0),  # 后端 连通性测试短超时
            max_retries=0,  # 后端 不重试，快速失败
        )
        _test_resp = await asyncio.wait_for(
            _test_client.chat.completions.create(
                model=settings.DEFAULT_MODEL,
                messages=[{"role": "user", "content": "回复一个字：好"}],
                max_tokens=10,
            ),
            timeout=15.0,  # 后端 15s 兜底
        )
        _test_text = _test_resp.choices[0].message.content[:30] if _test_resp.choices else "empty"
        print(f"[评估] 连通性测试✅ ({time.time() - t_conn:.1f}s): {_test_text}")
    except Exception as conn_err:
        t_elapsed = time.time() - t_conn
        print(f"[评估] 连通性测试❌ ({t_elapsed:.1f}s): {conn_err}")
        # 如果基础连通性都不行，直接返回错误，不浪费时间
        return {
            "scores": {"faithfulness": None},
            "elapsed_seconds": round(t_elapsed, 1),
            "error": f"API 连通性测试失败（{t_elapsed:.1f}s）：{str(conn_err)[:200]}",
            "note": "基础连通性失败，跳过完整评估",
            "model": settings.DEFAULT_MODEL,
        }

    try:
        t_build = time.time()
        llm = _build_instructor_llm()  # 后端 绕过 llm_factory，自己控制 instructor mode
        m = Faithfulness(llm=llm)
        print(f"[评估] LLM客户端+Faithfulness构造 ({time.time() - t_build:.1f}s)")

        t_score = time.time()
        s = await asyncio.wait_for(
            m.abatch_score(
                [{"user_input": request.question, "response": request.answer, "retrieved_contexts": contexts}]
            ),
            timeout=80.0,  # 后端 总超时80s（连通性已通过，80s足够2次LLM调用）
        )
        print(f"[评估] abatch_score 完成 ({time.time() - t_score:.1f}s)")
        score = round(float(sum(x.value for x in s) / len(s)), 4)
    except asyncio.TimeoutError:  # 后端 80秒超时无响应
        error_detail = "评估超时（80秒无响应）。可能原因：1) RAGAS prompt 太长导致模型处理慢  2) instructor JSON模式与千问不兼容"
        print(f"[评估] 超时❌ ({time.time() - t0:.0f}s)")
    except Exception as e:  # 后端 捕获并记录详细错误
        err_msg = str(e)
        print(f"[评估] 失败❌ ({time.time() - t0:.1f}s): {err_msg[:200]}")
        if "hosts" in err_msg.lower() or "parse" in err_msg.lower():
            error_detail = f"hosts文件解析失败。请修复 C:\\Windows\\System32\\drivers\\etc\\hosts。原始错误: {err_msg[:300]}"
        else:
            error_detail = err_msg[:500]
        traceback.print_exc()
    elapsed = round(time.time() - t0, 1)  # 后端 计时（秒）

    from app.core.config import settings as _settings
    return {
        "scores": {"faithfulness": score},
        "elapsed_seconds": elapsed,
        "error": error_detail,
        "note": "仅计算忠实度（Faithfulness）— 检测回答是否基于上下文、有无幻觉",
        "model": _settings.DEFAULT_MODEL,
    }
