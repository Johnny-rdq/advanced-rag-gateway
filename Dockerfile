# ============ 第一阶段：构建 React 前端 ============
FROM node:22-alpine AS frontend-builder

WORKDIR /frontend

# 安装前端依赖（使用淘宝 npm 镜像）
COPY rag-frontend/package.json rag-frontend/package-lock.json ./
RUN npm config set registry https://registry.npmmirror.com && npm ci

# 构建 React 前端
COPY rag-frontend/ ./
RUN npm run build

# ============ 第二阶段：Python 后端运行 ============
FROM python:3.11-slim

WORKDIR /app

# 安装 Python 依赖（使用清华 PyPI 镜像）
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host pypi.tuna.tsinghua.edu.cn -r requirements.txt

# 复制后端代码
COPY app/ ./app/

# 复制前端构建产物
COPY --from=frontend-builder /frontend/dist ./rag-frontend/dist

# 创建必要的目录
RUN mkdir -p docs my_vector_db uploads

# 暴露端口
EXPOSE 8000

# 启动服务
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
