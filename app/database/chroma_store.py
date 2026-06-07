import os
import hashlib
import chromadb
import dashscope
from app.core.config import settings

dashscope.api_key = settings.DASHSCOPE_API_KEY

# 持久化保存路径
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "my_vector_db")


# DP: 阿里云 DashScope EmbeddingFunction — 替代 sentence-transformers + BGE 本地模型
# 直接调国内 API，无需从 HuggingFace/ModelScope 下载模型，告别魔法
class DashScopeEmbeddingFunction:
    """自定义 ChromaDB 嵌入函数，调用阿里云 DashScope TextEmbedding API"""

    def __init__(self, model: str = "text-embedding-v2", batch_size: int = 25):
        """
        Args:
            model: DashScope 嵌入模型名称（text-embedding-v1/v2/v3）
            batch_size: 每批发送的文本数（v2 上限 25）
        """
        self.model = model
        self.batch_size = batch_size

    def name(self) -> str:
        """DP: ChromaDB 要求 embedding function 必须有 name() 方法"""
        return f"dashscope-{self.model}"

    def __call__(self, input: list[str]) -> list[list[float]]:
        """ChromaDB 调用入口 — 接收文本列表，返回嵌入向量列表"""
        if not input:
            return []

        all_embeddings = []
        # DP: 分批调阿里云 TextEmbedding API（v2 单批上限25条）
        for i in range(0, len(input), self.batch_size):
            batch = input[i:i + self.batch_size]
            resp = dashscope.TextEmbedding.call(
                model=self.model,
                input=batch,
            )
            if resp.status_code == 200:
                for emb_item in resp.output["embeddings"]:
                    all_embeddings.append(emb_item["embedding"])
            else:
                raise RuntimeError(
                    f"DashScope Embedding API 调用失败 (HTTP {resp.status_code}): {resp.message}"
                )

        return all_embeddings


# 初始化嵌入函数
embedding_fn = DashScopeEmbeddingFunction(model=settings.EMBEDDING_MODEL)

chroma_client = chromadb.PersistentClient(path=DB_PATH)

# 尝试获取或创建集合
COLLECTION_NAME = "top_secret_docs"
try:
    knowledge_collection = chroma_client.get_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
    )
    print(f"[向量库] 已连接现有集合 '{COLLECTION_NAME}' ({knowledge_collection.count()} 条文档)")
except Exception:
    # DP: 集合不存在或嵌入函数不匹配 → 删掉旧数据重建
    print("[向量库] 集合不匹配或不存在，正在重建...")
    try:
        chroma_client.delete_collection(name=COLLECTION_NAME)
    except Exception:
        pass
    knowledge_collection = chroma_client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"}
    )
    print(f"[向量库] 已创建新集合 '{COLLECTION_NAME}'")


# DP: SHA256 替代不稳定的 hash() 生成文档 ID
def _stable_id(text: str, index: int) -> str:
    """用 SHA256 生成稳定 ID，替代不稳定的 hash()"""
    h = hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
    return f"chunk_{index}_{h}"


def add_documents_to_db(doc_chunks: list):
    """将文本切片存入向量数据库（去重写入）"""
    if not doc_chunks:
        return
    chunk_ids = [_stable_id(chunk, i) for i, chunk in enumerate(doc_chunks)]
    # upsert: 已存在的 ID 会更新，新 ID 会插入
    knowledge_collection.upsert(documents=doc_chunks, ids=chunk_ids)
    print(f"[向量库] 成功写入 {len(doc_chunks)} 条文档片段到 ChromaDB！")


def query_vector_db(query: str, n_results: int = 5):
    """向量检索 — 返回最相关的文档片段"""
    if knowledge_collection.count() == 0:
        return []
    try:
        results = knowledge_collection.query(
            query_texts=[query],
            n_results=min(n_results, knowledge_collection.count())
        )
        if results.get('documents') and len(results['documents'][0]) > 0:
            return results['documents'][0]
    except Exception as e:
        print(f"[错误] 向量查询失败: {e}")
    return []


def get_collection_count() -> int:
    """返回当前向量库中的文档数"""
    return knowledge_collection.count()


def auto_load_docs():
    """开机自动扫描 docs 文件夹，智能判定是否需要重新入库"""
    if knowledge_collection.count() > 0:
        print(f"[向量库] 缓存命中！已存在 {knowledge_collection.count()} 条文档片段，跳过加载。")
        return

    docs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "docs")
    if not os.path.exists(docs_dir):
        os.makedirs(docs_dir, exist_ok=True)
        print("[知识库] 已创建空的 docs 文件夹，随时可以放入文件！")
        return

    print("[知识库] 向量库为空，正在扫描 docs 文件夹...")
    try:
        import pdfplumber
    except ImportError:
        pdfplumber = None

    all_chunks = []
    for filename in os.listdir(docs_dir):
        filepath = os.path.join(docs_dir, filename)
        if not os.path.isfile(filepath):
            continue

        text = ""
        try:
            if filename.endswith(".pdf") and pdfplumber:
                with pdfplumber.open(filepath) as pdf:
                    for page in pdf.pages:
                        ext = page.extract_text()
                        if ext:
                            text += ext + "\n"
            elif filename.endswith(".txt"):
                with open(filepath, "r", encoding="utf-8") as f:
                    text = f.read()

            if text.strip():
                chunks = [text[i:i + 400] for i in range(0, len(text), 400) if text[i:i + 400].strip()]
                all_chunks.extend(chunks)
                print(f"[知识库] 已加载 [{filename}] → {len(chunks)} 条片段")
        except Exception as e:
            print(f"[警告] 读取文件 [{filename}] 失败: {e}")

    if all_chunks:
        add_documents_to_db(all_chunks)
        print(f"[知识库] 知识库构建完成！共 {len(all_chunks)} 条文档片段。")
    else:
        print("[知识库] docs 文件夹中未找到可解析的文档。")
