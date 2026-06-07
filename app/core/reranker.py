"""
DP: 文档重排序器 — 使用阿里云 DashScope TextReRank API 精排
替代本地 BGE-Reranker (CrossEncoder)，无需下载 HF 模型，直接调 API
"""
import dashscope
from app.core.config import settings


class DocumentReranker:
    def __init__(self, model: str = None):
        """
        初始化重排引擎
        Args:
            model: DashScope Reranker 模型名称（默认 gte-rerank）
        """
        self.model = model or settings.RERANK_MODEL
        print(f"[INFO] Reranker ready! (model={self.model}, via DashScope API)")

    def rerank(self, query: str, documents: list[str], top_k: int = 3) -> list[str]:
        """
        对检索到的文档进行重排序
        Args:
            query: 用户查询
            documents: 待排序的文档列表
            top_k: 返回前 k 个最相关文档
        Returns:
            排序后的文档列表
        """
        if not documents:
            return []

        # DP: 调阿里云 DashScope TextReRank API，替代本地 CrossEncoder
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
                print(f"[WARN] Rerank API failed ({resp.status_code}): {resp.message}")
                return documents[:top_k]
        except Exception as e:
            print(f"[WARN] Rerank API error: {e}")
            return documents[:top_k]


# 全局单例（延迟加载）
_global_reranker = None


def get_reranker() -> DocumentReranker:
    """获取全局 Reranker 实例"""
    global _global_reranker
    if _global_reranker is None:
        _global_reranker = DocumentReranker()
    return _global_reranker


# ========== 本地测试 ==========
if __name__ == "__main__":
    test_query = "谁负责审批财务报销？"
    test_docs = [
        "公司的无线上网密码是123456。",
        "财务报销流程由工号888的王总亲自审批，其他都不算数。",
        "关于休假，每年有5天带薪年假。",
        "员工食堂每天中午12点准时开饭。"
    ]

    reranker = DocumentReranker()
    best = reranker.rerank(test_query, test_docs, top_k=1)

    print(f"\n❓ 问题: {test_query}")
    print(f"🥇 Rerank 最匹配: {best[0] if best else '无结果'}")
