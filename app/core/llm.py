import dashscope
from app.core.config import settings

dashscope.api_key = settings.DASHSCOPE_API_KEY

def get_llm_response(messages, tools=None):
    """通用的大模型基础调用接口"""
    response = dashscope.Generation.call(
        model=settings.DEFAULT_MODEL,
        messages=messages,
        tools=tools,
        result_format='message'
    )
    return response