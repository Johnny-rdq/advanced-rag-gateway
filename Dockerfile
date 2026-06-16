# ============ 第一阶段：构建 React 前端 ============
FROM node:18-alpine AS frontend-builder

WORKDIR /frontend

# 安装前端依赖
COPY rag-frontend/package.json rag-frontend/package-lock.json ./
RUN npm ci

# 构建 React 前端
COPY rag-frontend/ ./
RUN npm run build

# ============ 第二阶段：Python 后端运行 ============
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码
COPY app/ ./app/

# 复制前端构建产物
COPY --from=frontend-builder /frontend/dist ./rag-frontend/dist

# 创建必要的目录
RUN mkdir -p docs my_vector_db

# 暴露端口
EXPOSE 8000

# 启动服务
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
