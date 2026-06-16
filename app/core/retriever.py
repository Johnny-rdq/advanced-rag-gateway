"""混合检索器 — 结合 BM25 关键词检索 + ChromaDB 语义检索"""
import jieba
from rank_bm25 import BM25Okapi
from app.database.chroma_store import query_vector_db


class HybridRetriever:
    """混合检索器：BM25 关键词 + 向量语义检索 + 去重"""

    def __init__(self, documents: list[str] = None):
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
        """核心方法：BM25 + ChromaDB 混合检索并去重"""
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
