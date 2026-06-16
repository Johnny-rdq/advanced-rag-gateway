import requests
from app.core.config import settings

# 工具函数 — 天气(wttr.in) + 联网搜索(DDG免费 + Tavily备用)

# 记录最近一次联网搜索的来源 URL，供 agent_service 显示
_last_web_sources: list[str] = []


def get_last_web_sources() -> list[str]:
    """获取最近一次联网搜索的来源 URL"""
    return _last_web_sources


# ==================== DuckDuckGo 免费搜索 ====================

def _search_ddg(query: str, max_results: int = 3) -> list[dict]:
    """DuckDuckGo 免费搜索 — 无需 API Key，国内直连"""
    try:
        # 兼容新旧包名（ddgs >= 7.0 或 duckduckgo_search < 7.0）
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS  # type: ignore
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", "无标题"),
                    "content": r.get("body", ""),
                    "url": r.get("href", "")
                })
        return results
    except ImportError:
        print("[警告] ddgs 未安装，请执行: pip install ddgs")
        return []
    except Exception as e:
        print(f"[警告] DDG 搜索失败: {e}")
        return []


# ==================== Tavily 联网搜索（备用） ====================

_tavily_client = None


def _get_tavily_client():
    """延迟初始化 Tavily 客户端，DDG 失败时备用"""
    global _tavily_client
    if _tavily_client is not None:
        return _tavily_client
    if not settings.TAVILY_API_KEY or "xxx" in settings.TAVILY_API_KEY:
        return None
    try:
        from tavily import TavilyClient
        _tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
        print("[搜索] Tavily 搜索客户端已初始化（备用方案）！")
    except ImportError:
        print("[警告] tavily-python 未安装")
        _tavily_client = False
    except Exception as e:
        print(f"[警告] Tavily 初始化失败: {e}")
        _tavily_client = False
    return _tavily_client if _tavily_client is not False else None


def _search_tavily(query: str, max_results: int = 3) -> list[dict]:
    """Tavily 备用搜索"""
    client = _get_tavily_client()
    if client is None:
        return []
    try:
        response = client.search(
            query=query,
            search_depth="basic",
            max_results=max_results
        )
        results = response.get("results", [])
        return [{"title": r.get("title", "无标题"), "content": r.get("content", ""), "url": r.get("url", "")}
                for r in results]
    except Exception as e:
        print(f"[警告] Tavily 搜索失败: {e}")
        return []


# ==================== 统一搜索入口 ====================

def search_internet(query: str) -> str:
    """联网搜索 — DDG(免费)优先，Tavily 备用"""
    global _last_web_sources
    _last_web_sources = []

    # 先试 DDG（免费，无需 API Key，国内可直连）
    results = _search_ddg(query, max_results=3)

    # DDG 失败或无结果，试 Tavily
    if not results:
        results = _search_tavily(query, max_results=3)

    if not results:
        return "未搜到相关信息。"

    # 记录来源 URL
    _last_web_sources = [r.get("url", "") for r in results if r.get("url")]

    lines = []
    for i, r in enumerate(results):
        title = r.get('title', '无标题')
        content = r.get('content', '')[:200]
        lines.append(f"[{i + 1}] {title}\n{content}")
    return "\n\n".join(lines)


# ==================== 天气查询 ====================

def get_real_weather(location: str) -> str:
    """通过 wttr.in 获取真实天气（精简版，快速返回）"""
    try:
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
            "description": "联网搜索最新资讯、新闻或实时信息。禁止用于查询天气（天气请用 get_real_weather）。仅在本地文档无法回答时使用。",
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
