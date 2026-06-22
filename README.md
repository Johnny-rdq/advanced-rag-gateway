# 🧠 Advanced RAG Gateway — 企业级 RAG 知识网关

基于 **FastAPI + ChromaDB + 阿里云 DashScope** 构建的企业级 RAG（检索增强生成）知识网关。支持本地知识库检索、文件上传管理、RAGAS 自动评估、联网搜索、实时天气查询等，前端采用 React SPA，后端通过 SSE 流式输出，提供类 ChatGPT 的对话体验。

---

## 🏗️ 项目架构

```
advanced_rag_gateway/
├── app/
│   ├── main.py                      # FastAPI 入口，CORS / 静态文件 / 生命周期
│   ├── api/
│   │   ├── chat.py                  # 聊天 SSE / 会话 CRUD / 文件上传 / 评估持久化 API
│   │   └── evaluation.py            # RAGAS 评估 API（快速评估 + 直接评估）
│   ├── core/
│   │   ├── config.py                # 环境变量配置（模型/API Key/上传目录）
│   │   ├── retriever.py             # 混合检索器（BM25 + 向量 + 去重）
│   │   └── reranker.py              # DashScope TextReRank 重排序
│   ├── services/
│   │   ├── agent_service.py         # RAG Agent 核心逻辑（OpenAI 兼容端点）
│   │   ├── evaluation_service.py    # RAGAS 评估服务（LLM/Embedding 工厂）
│   │   ├── document_parser.py       # 统一文档解析服务（PDF/DOCX/PPTX/图片）
│   │   └── tools.py                 # 工具定义（联网搜索 + 天气查询）
│   └── database/
│       ├── chroma_store.py          # ChromaDB 向量存储（DashScope 嵌入）
│       └── sqlite_store.py          # SQLite 会话/消息/文件/评估记录持久化
├── rag-frontend/                    # React SPA 前端（Tailwind CSS + Vite）
├── docs/                            # 本地知识库文档目录
├── uploads/                         # 上传文件持久化存储
├── Dockerfile                       # Docker 多阶段构建
├── docker-compose.yml               # Docker Compose 编排
├── requirements.txt                 # Python 依赖
└── .env.example                     # 环境变量模板
```

---

## ✨ 核心功能

| 功能 | 说明 |
|------|------|
| 🔍 **混合检索** | BM25 关键词检索 + ChromaDB 语义检索 → 去重 → Rerank 精排 |
| 📄 **文件管理** | 上传 TXT/PDF/DOCX/PPTX/图片等，SHA256 去重，持久化存储，前端列表管理 |
| 📊 **自动评估** | 每条 AI 回复自动触发 RAGAS 评估（忠实度/相关性/精确度），三指标并行计算 |
| 💾 **评估持久化** | 评估分数存入 SQLite，刷新页面或重启服务不丢失 |
| 🌐 **联网搜索** | DuckDuckGo（免费，国内直连）优先，Tavily API 备用 |
| 🌤️ **天气查询** | 通过 wttr.in 实时查询任意城市天气 |
| 💬 **流式对话** | SSE 流式输出，打字机效果 |
| 🗂️ **会话管理** | 多会话创建/切换/删除，历史记录持久化到 SQLite |
| 🎯 **智能路由** | 本地知识库优先 → 不足时自动调用工具 |
| 📎 **来源展示** | 每条回答附带资料来源 |

---

## 🚀 快速开始

### 方式一：Docker 部署（推荐）

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 DashScope API Key

# 2. 启动服务
docker compose up -d

# 3. 访问
# 前端：http://localhost:8000
# API 文档：http://localhost:8000/docs
```

### 方式二：本地运行

#### 1. 环境要求

- Python 3.11+
- Node.js 22+（用于构建前端）

#### 2. 安装依赖

```bash
pip install -r requirements.txt
cd rag-frontend && npm install && npm run build && cd ..
```

#### 3. 配置环境变量

```env
# 阿里云 DashScope API Key（必填）
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx

# LLM 模型（可选，推荐 qwen3.6-flash 或 qwen3.6-plus）
LLM_MODEL=qwen3.6-flash

# 嵌入模型（可选）
EMBEDDING_MODEL=text-embedding-v2

# 重排模型（可选）
RERANK_MODEL=qwen3-vl-rerank

# Tavily API Key（可选，DDG 搜索的备用方案）
TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxx

# 上传文件存储目录（可选）
UPLOAD_DIR=uploads

# LlamaParse OCR 解析（可选，解析文档扫描件/图片型PDF）
LLAMA_CLOUD_API_KEY=llx-xxxxxxxxxxxxxxxx
```

#### 4. 准备知识库

将文档放入 `docs/` 文件夹，启动时自动向量化入库。也可通过前端界面上传文件。

#### 5. 启动服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
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
| `POST` | `/api/upload` | 上传文件到知识库（SHA256 去重） |
| `GET` | `/api/files` | 获取已上传文件列表 |
| `DELETE` | `/api/files/{id}` | 删除已上传文件（级联删除向量库片段） |
| `POST` | `/api/evaluate/quick` | 快速评估（重新生成答案） |
| `POST` | `/api/evaluate/answer` | 直接评估已有回答（不重新生成，更快） |
| `POST` | `/api/evaluations` | 保存评估结果 |
| `GET` | `/api/evaluations/{session_id}` | 获取会话的评估历史 |
| `GET` | `/api/debug` | 查看当前配置 |

---

## 🧩 技术栈

| 层级 | 技术 |
|------|------|
| **后端框架** | FastAPI + Uvicorn |
| **向量数据库** | ChromaDB（持久化） |
| **嵌入模型** | 阿里云 DashScope TextEmbedding API |
| **重排序** | 阿里云 DashScope TextReRank API |
| **大语言模型** | 阿里云 DashScope（通义千问 Qwen，OpenAI 兼容端点） |
| **关键词检索** | BM25（jieba 分词） |
| **关系数据库** | SQLite（会话/消息/文件/评估记录） |
| **RAG 评估** | RAGAS（忠实度/相关性/精确度，三指标并行） |
| **联网搜索** | DuckDuckGo + Tavily（备用） |
| **前端** | React + Vite + Tailwind CSS + Lucide Icons |

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
┌─────────────────────────────────┐
│  SSE 流式输出 + 资料来源展示     │
│  → 自动触发 RAGAS 评估（三指标并行）│
│  → 评估分数自动存入 SQLite       │
└─────────────────────────────────┘
```

---

## 🐳 Docker 部署详解

### 构建与启动

```bash
# 构建镜像
docker compose build

# 后台启动
docker compose up -d

# 查看日志
docker compose logs -f

# 停止
docker compose down
```

### 持久化数据

以下目录/文件通过 volume 挂载，容器删除后数据不丢失：

- `my_vector_db/` — ChronaDB 向量库数据
- `app/database/rag_system.db` — SQLite（会话/消息/文件/评估记录）
- `uploads/` — 用户上传的原始文件
- `docs/` — 知识库文档

### 模型选择

推荐使用 `qwen3.6-flash`（免费额度充足，速度快）或 `qwen3.6-plus`（质量更高）。

> **注意**：`qwen3.6` 系列模型仅支持 OpenAI 兼容端点（`/compatible-mode/v1`），不支持 DashScope 原生 API。本项目已全部迁移到 OpenAI 兼容端点。

---

## 🐛 已知问题 & 修复记录

| 日期 | 问题 | 修复 |
|------|------|------|
| 2026-06-16 | ChromaDB 1.5.x 查询时报缺少 `embed_query` 方法 | 新增 `embed_query` 方法，兼容 ChromaDB 1.x 协议 |
| 2026-06-17 | Docker 构建失败：Vite 需要 Node.js 20.19+ | 升级 `node:18-alpine` → `node:22-alpine` |
| 2026-06-17 | Docker 构建 pip 下载慢/超时 | 切换清华 PyPI 镜像 + 淘宝 npm 镜像 |
| 2026-06-22 | `qwen3.6-flash`/`qwen3.6-plus` 报 URL 错误 | DashScope 原生 API 不支持 qwen3.6 系列，全部迁移到 OpenAI 兼容端点 |
| 2026-06-22 | RAGAS 评估超时（>2分钟） | 三指标并行计算 + 直接用已有回答评估（不重新生成），耗时从 114s 降到 62s |
| 2026-06-22 | 评估分数刷新后显示 `?%` | 修复前端评估加载逻辑，消息和评估并行请求，去掉 setTimeout 延迟 |

---

## 📄 许可证

MIT License
