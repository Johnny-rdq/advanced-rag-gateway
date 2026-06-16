import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.api import chat
from app.database.sqlite_store import init_db
from app.database.chroma_store import auto_load_docs


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.config import settings
    init_db()
    auto_load_docs()
    print(
        f"\n[启动] Advanced RAG Gateway 启动成功！\n"
        f"[模型] {settings.DEFAULT_MODEL}\n"
        f"[接口] http://127.0.0.1:8000/api\n"
        f"[前端] http://127.0.0.1:8000\n"
    )
    yield

app = FastAPI(title="Advanced Agentic RAG Gateway", lifespan=lifespan)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 路由
app.include_router(chat.router, prefix="/api")

# ==================== 静态文件服务 ====================

# 获取项目根目录
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# React 构建产物目录
REACT_DIST = os.path.join(ROOT_DIR, "rag-frontend", "dist")

# 自动检测 React/HTML 前端，React 优先
if os.path.exists(REACT_DIST):
    # 挂载静态资源
    assets_dir = os.path.join(REACT_DIST, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def serve_react(full_path: str = ""):
        """服务 React 前端（SPA 模式），排除 API 路径"""
        # 不要让前端路由拦截 API 请求
        if full_path.startswith("api/"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        file_path = os.path.join(REACT_DIST, full_path) if full_path else os.path.join(REACT_DIST, "index.html")
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        # SPA fallback
        return FileResponse(os.path.join(REACT_DIST, "index.html"))

else:
    # 没有 React 构建，使用简单 HTML 前端
    @app.get("/")
    async def serve_frontend():
        index_path = os.path.join(ROOT_DIR, "index.html")
        return FileResponse(index_path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
