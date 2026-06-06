import os
import hashlib
import chromadb
from chromadb.utils import embedding_functions

# 持久化保存路径
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "my_vector_db")


# DP: 加载 BGE 中文嵌入模型，失败回退默认
def _get_embedding_function():
    """获取嵌入函数 — 优先使用 ModelScope 中文模型，失败则回退到默认"""
    try:
        from modelscope import snapshot_download
        model_dir = snapshot_download('BAAI/bge-small-zh-v1.5')
        print(f"[INFO] Loading embedding model: {model_dir}")
        return embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=model_dir,
            device="cpu"
        )
    except Exception as e:
        print(f"[WARN] Chinese embedding model failed ({e}), using default")
        try:
            return embedding_functions.DefaultEmbeddingFunction()
        except Exception:
            # Fallback: let ChromaDB use built-in all-MiniLM-L6-v2
            return None


embedding_fn = _get_embedding_function()

chroma_client = chromadb.PersistentClient(path=DB_PATH)

# 尝试获取或创建集合，处理嵌入函数冲突（旧数据与新模型不兼容）
COLLECTION_NAME = "top_secret_docs"
try:
    knowledge_collection = chroma_client.get_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
    )
    print(f"[INFO] Connected to existing collection '{COLLECTION_NAME}' ({knowledge_collection.count()} docs)")
except ValueError:
    # 嵌入函数不匹配：旧集合用的是默认嵌入，新的是 BGE 模型 => 重建
    print("[INFO] Embedding function mismatch, recreating collection...")
    try:
        chroma_client.delete_collection(name=COLLECTION_NAME)
    except Exception:
        pass
    knowledge_collection = chroma_client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"}
    )
    print(f"[INFO] Created new collection '{COLLECTION_NAME}'")
except Exception as e:
    # 集合不存在等情况
    knowledge_collection = chroma_client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"}
    )
    print(f"[INFO] Created collection '{COLLECTION_NAME}'")


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
    print(f"[INFO] Successfully wrote {len(doc_chunks)} chunks to ChromaDB!")


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
        print(f"[ERROR] Vector query failed: {e}")
    return []


def get_collection_count() -> int:
    """返回当前向量库中的文档数"""
    return knowledge_collection.count()


def auto_load_docs():
    """开机自动扫描 docs 文件夹，智能判定是否需要重新入库"""
    if knowledge_collection.count() > 0:
        print(f"[INFO] Vector DB cache hit! {knowledge_collection.count()} chunks already exist, skipping load.")
        return

    docs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "docs")
    if not os.path.exists(docs_dir):
        os.makedirs(docs_dir, exist_ok=True)
        print("[INFO] Created empty docs folder. You can put files in it anytime!")
        return

    print("[INFO] Vector DB is empty, scanning docs folder...")
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
                print(f"[INFO] Loaded [{filename}] -> {len(chunks)} chunks")
        except Exception as e:
            print(f"[WARN] Failed to read [{filename}]: {e}")

    if all_chunks:
        add_documents_to_db(all_chunks)
        print(f"[INFO] Knowledge base built! Total {len(all_chunks)} chunks.")
    else:
        print("[INFO] No parseable documents found in docs folder.")
