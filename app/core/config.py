import os
from dotenv import load_dotenv

# 加载根目录下的 .env 文件
load_dotenv()

class Settings:
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
    DEFAULT_MODEL = os.getenv("LLM_MODEL", "qwen-plus")
    # 阿里云 DashScope 嵌入 & 重排模型
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v2")
    RERANK_MODEL = os.getenv("RERANK_MODEL", "gte-rerank")
    # LlamaParse OCR 解析（可选，不配则仅用 pdfplumber 解析 PDF）
    LLAMA_CLOUD_API_KEY = os.getenv("LLAMA_CLOUD_API_KEY", "")
    # 上传文件存储目录（相对路径从项目根目录算，绝对路径直接用）
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads"))

settings = Settings()