# DP: 核心 RAG Agent — 检索 + LLM + 工具调用 + 流式输出 + 来源过滤
import json
import asyncio
import jieba
import dashscope
from app.core.config import settings
from app.services.tools import search_internet, get_real_weather, AGENT_TOOLS
from app.database.chroma_store import query_vector_db
from app.database.sqlite_store import save_message_with_source, get_recent_messages

dashscope.api_key = settings.DASHSCOPE_API_KEY


# DP: 兼容 dashscope 返回的 dict 和 object 两种 tool_calls 格式
def _get_attr(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# DP: 用 jieba 分词检测文档与查询是否相关，不相关则不显示来源
def _format_source(docs, query=""):
    if not docs:
        return ""
    doc = docs[0]
    query_tokens = set(jieba.cut(query))
    stop = {"的", "了", "是", "吗", "呢", "吧", "啊", "在", "有", "我", "你", "他", "这", "那", "什么", "怎么", "哪个", "多少", "为什么", "可以", "一个"}
    query_tokens = {t for t in query_tokens if len(t) > 1 and t not in stop}
    if query_tokens:
        matched = sum(1 for t in query_tokens if t in doc[:400])
        if matched == 0:
            return ""  # DP: 完全不相关，不展示
    short = doc[:150].replace("\n", " ").strip()
    if len(doc) > 150:
        short += "..."
    return short


# DP: 异步生成器 — 流式 SSE 输出给前端
async def qwen_llm_generator(query: str, session_id: str):
    final_text = ""
    source_text = ""

    try:
        # DP: 1. ChromaDB 向量检索
        retrieved_docs = query_vector_db(query, n_results=2)
        source_text = _format_source(retrieved_docs, query)

        # DP: 2. 加载最近 6 条聊天历史
        history = get_recent_messages(session_id, limit=6)

        # DP: 3. 构建 RAG 上下文消息
        rag_context = ""
        if retrieved_docs:
            rag_context = "\n\n【本地知识库】\n" + "\n".join(retrieved_docs)

        system_prompt = (
            "你是企业AI助理。优先参考【本地知识库】回答。"
            "本地资料足够时不要调工具。无法回答时才调 search_internet。问天气调 get_real_weather。"
            "回答简洁、用中文。"
        )

        messages = [{"role": "system", "content": system_prompt}]
        for h in history:
            messages.append({"role": h["role"], "content": h["content"]})
        user_content = f"{rag_context}\n\n【用户问题】{query}" if rag_context else query
        messages.append({"role": "user", "content": user_content})

        # DP: 4. 先发 THINKING 让前端立即可见，再调 LLM（线程池避免阻塞）
        yield "data: [THINKING]: 正在分析...\n\n"
        await asyncio.sleep(0)

        response = await asyncio.to_thread(
            dashscope.Generation.call,
            model=settings.DEFAULT_MODEL,
            messages=messages,
            tools=AGENT_TOOLS,
            result_format='message'
        )

        if response.status_code != 200:
            yield f"data: LLM调用失败: {response.message}\n\n"
            save_message_with_source(session_id, "assistant", f"LLM调用失败: {response.message}", "")
            return

        msg = response.output.choices[0].message
        tool_calls = _get_attr(msg, 'tool_calls', None)

        # DP: 5. 工具调用分支（天气 / 联网搜索）
        if tool_calls:
            tc = tool_calls[0]
            func = _get_attr(tc, 'function', {})
            func_name = _get_attr(func, 'name', '')
            func_args_str = _get_attr(func, 'arguments', '{}')
            func_args = json.loads(func_args_str) if isinstance(func_args_str, str) else func_args_str
            tc_id = _get_attr(tc, 'id', 'call_001')

            yield f"data: [TOOL]: {func_name}\n\n"

            # DP: 工具在线程池执行，带超时
            try:
                if func_name == "get_real_weather":
                    tool_result = await asyncio.to_thread(get_real_weather, func_args.get("location", ""))
                else:
                    tool_result = await asyncio.to_thread(search_internet, func_args.get("query", ""))
            except Exception as te:
                tool_result = f"调用失败: {str(te)}"

            # DP: 追加工具消息（OpenAI 兼容格式，tool_call_id 必填）
            messages.append({
                "role": "assistant",
                "content": _get_attr(msg, 'content', '') or '',
                "tool_calls": [{
                    "id": tc_id, "type": "function",
                    "function": {"name": func_name, "arguments": func_args_str}
                }]
            })
            messages.append({"role": "tool", "tool_call_id": tc_id, "content": str(tool_result)})

            # DP: 第二次 LLM 调用，整合工具结果
            final_resp = await asyncio.to_thread(
                dashscope.Generation.call,
                model=settings.DEFAULT_MODEL,
                messages=messages,
                result_format='message'
            )
            if final_resp.status_code == 200:
                final_text = final_resp.output.choices[0].message.content or ''
                for i in range(0, len(final_text), 6):
                    yield f"data: {final_text[i:i + 6]}\n\n"
                    await asyncio.sleep(0.005)
            else:
                yield f"data: 生成失败: {final_resp.message}\n\n"

            # DP: 工具场景结束后也发送来源
            if source_text:
                yield f"data: [SOURCE]: {source_text}\n\n"

        else:
            # DP: 6. 无工具 — 直接分块流式输出
            final_text = _get_attr(msg, 'content', '') or ''
            if final_text:
                for i in range(0, len(final_text), 6):
                    yield f"data: {final_text[i:i + 6]}\n\n"
                    await asyncio.sleep(0.005)
            else:
                yield "data: 抱歉，无法回答。\n\n"

            # DP: 7. 内容输出完后再发来源（在前端底部显示）
            if source_text:
                yield f"data: [SOURCE]: {source_text}\n\n"

    except Exception as e:
        yield f"data: 服务出错: {str(e)}\n\n"
        final_text = f"服务出错: {str(e)}"

    # DP: 8. 保存回答 + 来源到 SQLite（切换对话不丢失）
    if final_text and "服务出错" not in final_text and "LLM调用失败" not in final_text:
        save_message_with_source(session_id, "assistant", final_text, source_text)
