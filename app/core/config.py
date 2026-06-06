import os
from dotenv import load_dotenv

# 加载根目录下的 .env 文件
load_dotenv()

class Settings:
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
    DEFAULT_MODEL = os.getenv("LLM_MODEL", "qwen-plus")

settings = Settings()