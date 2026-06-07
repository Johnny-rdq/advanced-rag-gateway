import sqlite3
import os
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

    # DP: context 列存储 RAG 来源，切换对话不丢失
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

    # DP: 兼容旧表迁移
    try:
        cursor.execute("SELECT context FROM chat_messages LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE chat_messages ADD COLUMN context TEXT DEFAULT ''")
        print("[数据库] 已添加 context 列到 chat_messages")

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
