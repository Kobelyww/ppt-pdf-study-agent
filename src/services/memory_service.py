from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime
import sqlite3
import json


@dataclass
class Message:
    """消息"""

    role: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ShortTermMemory:
    """短期记忆"""

    def __init__(self, max_tokens: int = 50000):
        self.max_tokens = max_tokens
        self.messages: List[Message] = []
        self.compressed_prefix: str = ""

    def add_message(self, message: Message) -> None:
        """添加消息"""
        self.messages.append(message)
        # 检查是否需要压缩
        if self._estimate_tokens() > self.max_tokens:
            self._compress()

    def get_context(self, max_tokens: int = 3000) -> str:
        """获取上下文"""
        context_parts = []
        if self.compressed_prefix:
            context_parts.append(self.compressed_prefix)

        for msg in self.messages[-10:]:  # 最近10条消息
            context_parts.append(f"{msg.role}: {msg.content}")

        return "\n".join(context_parts)

    def _estimate_tokens(self) -> int:
        """估算token数量"""
        # 简单估算：每个字符约0.5个token
        total_chars = sum(len(msg.content) for msg in self.messages)
        return int(total_chars * 0.5)

    def _compress(self) -> None:
        """压缩旧消息"""
        # 保留最近5条消息，压缩其他消息
        if len(self.messages) > 5:
            old_messages = self.messages[:-5]
            self.messages = self.messages[-5:]

            # 生成压缩摘要
            compressed = "\n".join(
                [f"{msg.role}: {msg.content[:100]}..." for msg in old_messages[:3]]
            )
            self.compressed_prefix = compressed


class LongTermMemory:
    """长期记忆"""

    def __init__(self, db_path: str = ":memory:"):
        self.db = sqlite3.connect(db_path)
        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库"""
        cursor = self.db.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                category TEXT,
                importance REAL DEFAULT 0.5,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT
            )
        """
        )
        self.db.commit()

    def store(self, content: str, category: str = None, importance: float = 0.5) -> int:
        """存储记忆"""
        cursor = self.db.cursor()
        cursor.execute(
            "INSERT INTO memories (content, category, importance) VALUES (?, ?, ?)",
            (content, category, importance),
        )
        self.db.commit()
        return cursor.lastrowid

    def recall(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """召回记忆"""
        cursor = self.db.cursor()
        cursor.execute(
            "SELECT * FROM memories WHERE content LIKE ? ORDER BY importance DESC LIMIT ?",
            (f"%{query}%", top_k),
        )
        rows = cursor.fetchall()
        return [
            {
                "id": row[0],
                "content": row[1],
                "category": row[2],
                "importance": row[3],
                "created_at": row[4],
            }
            for row in rows
        ]


class MemoryService:
    """记忆服务"""

    def __init__(self, stm_max_tokens: int = 50000, ltm_db_path: str = ":memory:"):
        self.stm = ShortTermMemory(max_tokens=stm_max_tokens)
        self.ltm = LongTermMemory(db_path=ltm_db_path)

    def add_message(self, role: str, content: str) -> None:
        """添加消息"""
        message = Message(role=role, content=content)
        self.stm.add_message(message)

    def get_context(self) -> str:
        """获取上下文"""
        return self.stm.get_context()

    def store_important(self, content: str, category: str = None) -> int:
        """存储重要信息到长期记忆"""
        return self.ltm.store(content, category, importance=0.8)

    def recall(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """召回记忆"""
        return self.ltm.recall(query, top_k)
