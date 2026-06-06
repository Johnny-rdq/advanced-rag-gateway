import requests
import json
from app.core.config import settings

# DP: 所有工具函数 — 天气(wttr.in) + 联网搜索(Tavily)
# ==================== Tavily 联网搜索 ====================

# 延迟初始化 Tavily 客户端
_tavily_client = None


def _get_tavily_client():
    """延迟初始化 Tavily 客户端，避免 API key 为空时报错"""
    global _tavily_client
    if _tavily_client is not None:
        return _tavily_client
    if not settings.TAVILY_API_KEY or settings.TAVILY_API_KEY.startswith("tvly-xxx"):
        return None
    try:
        from tavily import TavilyClient
        _tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
        print("[INFO] Tavily search client initialized!")
    except ImportError:
        print("[WARN] tavily-python not installed. Web search unavailable. Run: pip install tavily-python")
        _tavily_client = False
    except Exception as e:
        print(f"⚠️ Tavily 初始化失败: {e}")
        _tavily_client = False
    return _tavily_client if _tavily_client is not False else None


def search_internet(query: str) -> str:
    """Tavily 联网搜索 — 获取实时信息"""
    client = _get_tavily_client()
    if client is None:
        return "⚠️ 联网搜索功能未配置，请设置有效的 TAVILY_API_KEY。"

    try:
        response = client.search(
            query=query,
            search_depth="basic",
            max_results=3
        )
        results = response.get("results", [])
        if not results:
            return "未搜到相关信息。"

        lines = []
        for i, r in enumerate(results):
            title = r.get('title', '无标题')
            content = r.get('content', '')[:200]
            lines.append(f"[{i + 1}] {title}\n{content}")
        return "\n\n".join(lines)

    except Exception as e:
        return f"联网搜索出错: {str(e)}"


# ==================== 天气查询 ====================

def get_real_weather(location: str) -> str:
    """通过 wttr.in 获取真实天气（精简版，快速返回）"""
    try:
        # 直接用简洁文本格式，5秒超时
        url = f"https://wttr.in/{location}?format=%l:+%c+%t,+%w,+%h&lang=zh"
        response = requests.get(url, timeout=5, headers={"User-Agent": "curl"})
        if response.status_code == 200:
            text = response.text.strip()
            if text and len(text) < 500:
                return f"{location}天气: {text}"
        return f"无法获取 {location} 天气数据"
    except requests.exceptions.Timeout:
        return f"查询 {location} 天气超时"
    except Exception as e:
        return f"天气查询失败: {e}"


# ==================== 工具定义（传给 LLM） ====================

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_real_weather",
            "description": "查询指定城市的实时天气。当用户询问天气（如'今天天气怎么样'、'北京多少度'）时调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "城市名称，如'北京'、'上海'、'Tokyo'"
                    }
                },
                "required": ["location"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_internet",
            "description": "联网搜索最新资讯、新闻或本地知识库中找不到的实时信息。仅在本地文档无法回答时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或问题"
                    }
                },
                "required": ["query"]
            }
        }
    }
]
