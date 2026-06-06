"""
文档重排序器 — 使用 BGE-Reranker 模型对检索结果进行精排
"""
from sentence_transformers import CrossEncoder


class DocumentReranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-base", device: str = "cpu"):
        """
        初始化重排引擎
        Args:
            model_name: HuggingFace 模型名称
            device: 运行设备 ("cpu" / "cuda")
        """
        print(f"[INFO] Loading Rerank model ({model_name}), please wait...")
        try:
            self.model = CrossEncoder(model_name, max_length=512, device=device)
            print(f"[INFO] Reranker loaded! (device={device})")
        except Exception as e:
            print(f"[WARN] Reranker model load failed: {e}, rerank will be disabled")
            self.model = None

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
        if self.model is None:
            return documents[:top_k]

        # 构造输入对: [[问题, 文档1], [问题, 文档2], ...]
        sentence_pairs = [[query, doc] for doc in documents]

        # 批量预测相似度分数
        scores = self.model.predict(sentence_pairs)

        # 按分数从高到低排序
        doc_score_pairs = list(zip(documents, scores))
        doc_score_pairs.sort(key=lambda x: x[1], reverse=True)

        # 返回前 top_k 个文档
        return [doc for doc, _ in doc_score_pairs[:top_k]]


# 全局单例（延迟加载，避免启动过慢）
_global_reranker = None


def get_reranker(device: str = "cpu") -> DocumentReranker:
    """获取全局 Reranker 实例"""
    global _global_reranker
    if _global_reranker is None:
        _global_reranker = DocumentReranker(device=device)
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

    reranker = DocumentReranker(device="cpu")
    best = reranker.rerank(test_query, test_docs, top_k=1)

    print(f"\n❓ 问题: {test_query}")
    print(f"🥇 Rerank 最匹配: {best[0] if best else '无结果'}")
