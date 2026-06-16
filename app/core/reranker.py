"""文档重排序器 — 使用阿里云 DashScope TextReRank API 精排"""
import dashscope
from app.core.config import settings


class DocumentReranker:
    def __init__(self, model: str = None):
        self.model = model or settings.RERANK_MODEL
        print(f"[重排] Reranker 就绪 (模型={self.model}, 通过 DashScope API)")

    def rerank(self, query: str, documents: list[str], top_k: int = 3) -> list[str]:
        """对检索到的文档进行重排序，返回前 top_k 个最相关文档"""
        if not documents:
            return []

        # 调阿里云 DashScope TextReRank API
        try:
            resp = dashscope.TextReRank.call(
                model=self.model,
                query=query,
                documents=documents,
                top_n=top_k,
                return_documents=True,
            )
            if resp.status_code == 200:
                results = resp.output.get("results", [])
                return [r["document"]["text"] for r in results[:top_k]]
            else:
                print(f"[警告] 重排 API 失败 ({resp.status_code}): {resp.message}")
                return documents[:top_k]
        except Exception as e:
            print(f"[警告] 重排 API 异常: {e}")
            return documents[:top_k]


# 全局单例（延迟加载）
_global_reranker = None


def get_reranker() -> DocumentReranker:
    """获取全局 Reranker 实例"""
    global _global_reranker
    if _global_reranker is None:
        _global_reranker = DocumentReranker()
    return _global_reranker
