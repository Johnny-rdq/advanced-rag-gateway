import os
from dotenv import load_dotenv

# 加载根目录下的 .env 文件
load_dotenv()

class Settings:
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
    DEFAULT_MODEL = os.getenv("LLM_MODEL", "qwen-plus")
    # DP: 阿里云 DashScope 嵌入 & 重排模型，替代本地 HF 模型，无需魔法
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v2")
    RERANK_MODEL = os.getenv("RERANK_MODEL", "gte-rerank")

settings = Settings()