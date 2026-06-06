"""
混合检索器 — 结合 BM25 关键词检索 + ChromaDB 语义检索
可作为独立工具使用，也可被 agent_service 调用
"""
import jieba
from rank_bm25 import BM25Okapi
from app.database.chroma_store import query_vector_db


class HybridRetriever:
    """混合检索器：BM25 关键词 + 向量语义检索 + 去重"""

    def __init__(self, documents: list[str] = None):
        """
        初始化混合检索器
        Args:
            documents: 可选，用于构建 BM25 索引的文档列表
        """
        self.documents = documents or []
        self._bm25 = None
        if self.documents:
            self._build_bm25_index()

    def _build_bm25_index(self):
        """构建 BM25 关键词索引"""
        tokenized_corpus = [list(jieba.cut(doc)) for doc in self.documents]
        self._bm25 = BM25Okapi(tokenized_corpus)

    def index_documents(self, documents: list[str]):
        """更新文档索引"""
        self.documents = documents
        self._build_bm25_index()

    def search_bm25(self, query: str, top_k: int = 10) -> list[str]:
        """BM25 关键词检索"""
        if not self._bm25 or not self.documents:
            return []
        tokenized_query = list(jieba.cut(query))
        return self._bm25.get_top_n(tokenized_query, self.documents, n=top_k)

    def search_chroma(self, query: str, top_k: int = 10) -> list[str]:
        """ChromaDB 语义检索"""
        return query_vector_db(query, n_results=top_k)

    def hybrid_search(self, query: str, top_k: int = 10) -> list[str]:
        """
        核心方法：执行混合检索并去重
        - BM25 关键词检索 + ChromaDB 语义检索
        - 合并后自动去重
        """
        bm25_results = self.search_bm25(query, top_k=top_k)
        chroma_results = self.search_chroma(query, top_k=top_k)

        # 合并去重（保持顺序：先 BM25 再 Chroma）
        seen = set()
        combined = []
        for doc in bm25_results + chroma_results:
            if doc not in seen:
                seen.add(doc)
                combined.append(doc)

        return combined[:top_k]


# 全局单例（用于 agent_service）
_global_retriever = None


def get_retriever(documents: list[str] = None) -> HybridRetriever:
    """获取全局 HybridRetriever 实例"""
    global _global_retriever
    if _global_retriever is None and documents:
        _global_retriever = HybridRetriever(documents)
    elif _global_retriever is None:
        _global_retriever = HybridRetriever([])
    elif documents:
        _global_retriever.index_documents(documents)
    return _global_retriever
