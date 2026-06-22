import sqlite3
import os
import json  # 后端 序列化评估分数
import uuid
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "rag_system.db")


def init_db():
    """初始化数据库 — 创建消息表和会话表"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 会话表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            title TEXT DEFAULT '新对话',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # context 列存储 RAG 来源，切换对话不丢失
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            content TEXT,
            context TEXT DEFAULT '',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    ''')

    # 兼容旧表迁移（无 context 列则添加）
    try:
        cursor.execute("SELECT context FROM chat_messages LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE chat_messages ADD COLUMN context TEXT DEFAULT ''")
        print("[数据库] 已添加 context 列到 chat_messages")

    # 上传文件记录表（持久化，重启不丢失）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS uploaded_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            file_hash TEXT NOT NULL UNIQUE,
            file_size INTEGER NOT NULL,
            chunk_count INTEGER NOT NULL,
            parsed_text TEXT DEFAULT '',
            chunk_ids TEXT DEFAULT '',
            uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 评估结果表（持久化，刷新/重启不丢失）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            question TEXT NOT NULL,
            answer TEXT DEFAULT '',
            scores TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()
    print("[数据库] SQLite 数据库初始化完成！")


# ==================== 会话管理 ====================

def create_session() -> dict:
    """创建新会话，返回 session_id 和 title"""
    session_id = uuid.uuid4().hex[:12]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO sessions (session_id, title) VALUES (?, ?)",
        (session_id, "新对话")
    )
    conn.commit()
    conn.close()
    return {"session_id": session_id, "title": "新对话"}


def get_all_sessions() -> list:
    """获取所有会话列表"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT session_id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {"session_id": r[0], "title": r[1], "created_at": r[2], "updated_at": r[3]}
        for r in rows
    ]


def delete_session(session_id: str):
    """删除会话及其所有消息"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
    cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


def update_session_title(session_id: str, title: str):
    """更新会话标题（取前20字）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (title[:20], session_id)
    )
    conn.commit()
    conn.close()


def ensure_session_exists(session_id: str):
    """确保会话存在，不存在则创建"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT session_id FROM sessions WHERE session_id = ?", (session_id,))
    exists = cursor.fetchone()
    if not exists:
        cursor.execute("INSERT INTO sessions (session_id, title) VALUES (?, ?)", (session_id, "新对话"))
        conn.commit()
    conn.close()


# ==================== 消息管理 ====================

def save_message(session_id: str, role: str, content: str, context: str = ""):
    """保存单条聊天记录"""
    ensure_session_exists(session_id)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO chat_messages (session_id, role, content, context) VALUES (?, ?, ?, ?)",
        (session_id, role, content, context or "")
    )
    if role == "user":
        cursor.execute(
            "UPDATE sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ? AND title = '新对话'",
            (content[:20], session_id)
        )
    else:
        cursor.execute(
            "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
            (session_id,)
        )
    conn.commit()
    conn.close()


# 别名，方便 agent_service 调用
save_message_with_source = save_message


def get_all_messages(session_id: str = "default_session") -> list:
    """获取指定会话的所有历史记录（含来源）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role, content, context FROM chat_messages WHERE session_id = ? ORDER BY timestamp ASC",
        (session_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1], "context": r[2] or ""} for r in rows]


def get_recent_messages(session_id: str, limit: int = 20) -> list:
    """获取最近 N 条消息，用于 LLM 上下文"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role, content FROM chat_messages WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
        (session_id, limit)
    )
    rows = cursor.fetchall()
    conn.close()
    # 返回时按时间正序排列
    rows.reverse()
    return [{"role": r[0], "content": r[1]} for r in rows]


# ==================== 上传文件管理 ====================

def insert_uploaded_file(filename: str, original_filename: str, file_hash: str, file_size: int, chunk_count: int, parsed_text: str = "", chunk_ids: str = "") -> int:
    """插入上传文件记录，返回自增 ID"""
    conn = sqlite3.connect(DB_PATH)  # 后端 连接 SQLite
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO uploaded_files (filename, original_filename, file_hash, file_size, chunk_count, parsed_text, chunk_ids) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (filename, original_filename, file_hash, file_size, chunk_count, parsed_text, chunk_ids)  # 后端 绑定参数防注入
    )
    conn.commit()
    file_id = cursor.lastrowid  # 后端 获取自增主键
    conn.close()
    return file_id  # 后端 返回新记录 ID


def get_uploaded_file_by_hash(file_hash: str) -> dict | None:
    """根据文件哈希查记录（去重用）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, filename, original_filename, file_hash, file_size, chunk_count, parsed_text, chunk_ids, uploaded_at FROM uploaded_files WHERE file_hash = ?",
        (file_hash,)  # 后端 哈希唯一索引，最多一条
    )
    row = cursor.fetchone()
    conn.close()
    if not row:  # 后端 未找到
        return None
    return {
        "id": row[0], "filename": row[1], "original_filename": row[2],
        "file_hash": row[3], "file_size": row[4], "chunk_count": row[5],
        "parsed_text": row[6], "chunk_ids": row[7], "uploaded_at": row[8]
    }  # 后端 返回字典方便上层使用


def get_all_uploaded_files() -> list[dict]:
    """获取所有已上传文件列表"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, filename, original_filename, file_hash, file_size, chunk_count, uploaded_at FROM uploaded_files ORDER BY uploaded_at DESC"
    )  # 后端 按上传时间倒序，最新的在前面
    rows = cursor.fetchall()
    conn.close()
    return [
        {"id": r[0], "filename": r[1], "original_filename": r[2],
         "file_hash": r[3], "file_size": r[4], "chunk_count": r[5], "uploaded_at": r[6]}
        for r in rows
    ]  # 后端 不返回 parsed_text（太大），前端不需要


def get_uploaded_file_by_id(file_id: int) -> dict | None:
    """根据 ID 获取单条上传记录（删除时用）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, filename, original_filename, file_hash, file_size, chunk_count, parsed_text, chunk_ids, uploaded_at FROM uploaded_files WHERE id = ?",
        (file_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "filename": row[1], "original_filename": row[2],
        "file_hash": row[3], "file_size": row[4], "chunk_count": row[5],
        "parsed_text": row[6], "chunk_ids": row[7], "uploaded_at": row[8]
    }


def delete_uploaded_file(file_id: int) -> None:
    """删除上传文件记录"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM uploaded_files WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()  # 后端 删除记录（磁盘和向量库由调用方处理）


def get_messages_for_session(session_id: str) -> dict:
    """获取会话的所有消息（用于前端，含来源）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role, content, context FROM chat_messages WHERE session_id = ? ORDER BY timestamp ASC",
        (session_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    messages = [{"role": r[0], "content": r[1], "context": r[2] or ""} for r in rows]
    return {"session_id": session_id, "messages": messages}


# ==================== 评估结果管理 ====================

def save_evaluation(session_id: str, question: str, answer: str, scores: dict) -> int:
    """保存一条评估结果，返回自增 ID"""
    conn = sqlite3.connect(DB_PATH)  # 后端 连接 SQLite
    cursor = conn.cursor()
    scores_json = json.dumps(scores)  # 后端 序列化评分
    cursor.execute(
        "INSERT INTO evaluations (session_id, question, answer, scores) VALUES (?, ?, ?, ?)",
        (session_id, question, answer, scores_json)  # 后端 绑定参数
    )
    conn.commit()
    eval_id = cursor.lastrowid  # 后端 获取自增主键
    conn.close()
    return eval_id  # 后端 返回新记录 ID


def get_evaluations_for_session(session_id: str) -> dict[str, dict]:
    """获取指定会话的所有评估结果，返回 {question: scores} 映射"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT question, scores FROM evaluations WHERE session_id = ? ORDER BY created_at ASC",
        (session_id,)  # 后端 按时间正序
    )
    rows = cursor.fetchall()
    conn.close()
    result = {}
    for r in rows:
        try:
            result[r[0]] = json.loads(r[1])  # 后端 JSON 反序列化
        except Exception:
            result[r[0]] = {}  # 后端 损坏数据返回空
    return result  # 后端 {question: {faithfulness: 1.0, ...}, ...}
