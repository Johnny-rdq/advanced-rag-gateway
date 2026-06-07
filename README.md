# 🧠 Advanced RAG Gateway — 企业级 RAG 知识网关

一个基于 **FastAPI + ChromaDB + 阿里云 DashScope** 构建的企业级 RAG（检索增强生成）知识网关。支持本地知识库检索、联网搜索、实时天气查询等工具调用，前端采用 React SPA，后端通过 SSE 流式输出，提供类 ChatGPT 的对话体验。

---

## 🏗️ 项目架构

```
advanced_rag_gateway/
├── app/
│   ├── main.py                  # FastAPI 入口，CORS / 静态文件 / 生命周期
│   ├── api/
│   │   └── chat.py              # 聊天 SSE / 会话 CRUD / 文件上传 API
│   ├── core/
│   │   ├── config.py            # 环境变量配置（模型、API Key 等）
│   │   ├── retriever.py         # 混合检索器（BM25 + 向量 + 去重）
│   │   └── reranker.py          # DashScope TextReRank 重排序
│   ├── services/
│   │   ├── agent_service.py     # RAG Agent 核心逻辑（检索→LLM→工具→流式）
│   │   └── tools.py             # 工具定义（联网搜索 + 天气查询）
│   └── database/
│       ├── chroma_store.py      # ChromaDB 向量存储（DashScope 嵌入）
│       └── sqlite_store.py      # SQLite 会话 & 聊天记录持久化
├── rag-frontend/                # React SPA 前端
├── docs/                        # 本地知识库文档目录（放 TXT/PDF）
├── requirements.txt             # Python 依赖
└── .env                         # 环境变量（API Key 等）
```

---

## ✨ 核心功能

| 功能 | 说明 |
|------|------|
| 🔍 **混合检索** | BM25 关键词检索 + ChromaDB 语义检索 → 去重 → Rerank 精排 |
| 📄 **文档管理** | 支持 TXT/PDF 上传，自动切片入库，开机自动扫描 `docs/` 目录 |
| 🌐 **联网搜索** | DuckDuckGo（免费，国内直连）优先，Tavily API 备用 |
| 🌤️ **天气查询** | 通过 wttr.in 实时查询任意城市天气，返回中文结果 |
| 💬 **流式对话** | SSE（Server-Sent Events）流式输出，打字机效果 |
| 🗂️ **会话管理** | 多会话创建/切换/删除，历史记录持久化到 SQLite |
| 🎯 **智能路由** | 本地知识库优先 → 不足时自动调用工具（搜索/天气） |
| 📎 **来源展示** | 每条回答附带资料来源（本地文档 / 网络搜索 URL） |

---

## 🚀 快速开始

### 1. 环境要求

- Python 3.10+
- Node.js 18+（用于构建 React 前端）

### 2. 安装依赖

```bash
# Python 后端依赖
pip install -r requirements.txt

# React 前端依赖（可选，仅需构建时）
cd rag-frontend && npm install && cd ..
```

### 3. 配置环境变量

在项目根目录创建 `.env` 文件：

```env
# 阿里云 DashScope API Key（必填）
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx

# LLM 模型（可选，默认 qwen-plus）
LLM_MODEL=qwen-plus

# 嵌入模型（可选，默认 text-embedding-v2）
EMBEDDING_MODEL=text-embedding-v2

# 重排模型（可选，默认 gte-rerank）
RERANK_MODEL=gte-rerank

# Tavily API Key（可选，DDG 搜索的备用方案）
TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxx
```

> 💡 **获取 API Key**：[阿里云 DashScope 控制台](https://dashscope.console.aliyun.com/)

### 4. 准备知识库

将你的 TXT 或 PDF 文档放入 `docs/` 文件夹，服务启动时会自动扫描并向量化入库。

### 5. 构建前端（可选）

```bash
cd rag-frontend
npm install
npm run build    # 生成 dist/ 目录
cd ..
```

> 如果跳过构建，系统会自动使用根目录下的 `index.html` 作为简易前端。

### 6. 启动服务

```bash
python -m app.main
```

访问：
- 🖥️ **前端界面**：http://127.0.0.1:8000
- 📡 **API 文档**：http://127.0.0.1:8000/docs
- 🔧 **调试接口**：http://127.0.0.1:8000/api/debug

---

## 🔧 API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/chat` | 流式聊天（SSE） |
| `GET` | `/api/history` | 获取会话历史 |
| `GET` | `/api/sessions` | 获取所有会话列表 |
| `POST` | `/api/sessions` | 创建新会话 |
| `GET` | `/api/sessions/{id}/messages` | 获取指定会话消息 |
| `DELETE` | `/api/sessions/{id}` | 删除指定会话 |
| `POST` | `/api/upload` | 上传文件到知识库 |
| `GET` | `/api/debug` | 查看当前配置信息 |

---

## 🧩 技术栈

| 层级 | 技术 |
|------|------|
| **后端框架** | FastAPI + Uvicorn |
| **向量数据库** | ChromaDB（持久化） |
| **嵌入模型** | 阿里云 DashScope TextEmbedding API |
| **重排序** | 阿里云 DashScope TextReRank API |
| **大语言模型** | 阿里云 DashScope（通义千问 Qwen） |
| **关键词检索** | BM25（jieba 分词） |
| **关系数据库** | SQLite（会话 & 聊天记录） |
| **联网搜索** | DuckDuckGo + Tavily（备用） |
| **前端** | React + Vite（SPA） |

---

## 🎯 检索流程

```
用户提问
    │
    ▼
┌─────────────────────────────────┐
│  混合检索                        │
│  BM25 关键词 + ChromaDB 语义     │
│  → 合并去重 → Rerank 精排 → Top2 │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│  判断：本地文档是否相关？         │
│  ├── 相关 → 注入知识库上下文     │
│  └── 不相关 → 告知 LLM 无本地资料 │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│  LLM 决策（Qwen Agent）          │
│  ├── 能回答 → 直接流式输出       │
│  ├── 需搜索 → 调用 search_internet│
│  └── 问天气 → 调用 get_real_weather│
└─────────────────────────────────┘
    │
    ▼
  流式 SSE 输出 + 资料来源展示
```

---

## 📝 开发说明

- **API Key 安全**：`.env` 文件已加入 `.gitignore`，不会被提交到仓库
- **向量库隔离**：`my_vector_db/` 目录存储 ChromaDB 持久化数据，不在版本控制中
- **模型迁移**：嵌入和重排已从本地 HuggingFace 模型迁移至阿里云 DashScope API，无需下载大文件，国内直连
- **前端开发模式**：`cd rag-frontend && npm run dev` 启动 Vite 热更新开发服务器

---

## 📄 许可证

MIT License
