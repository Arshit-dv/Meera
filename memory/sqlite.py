"""
Meera - SQLite Persistent Memory Engine
Provides local, thread-safe persistence for chat sessions, message histories,
context summaries, and long-term memory facts.
Zero third-party dependencies (pure standard library sqlite3).
"""
import json
import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Union

from config.settings import MEMORY_DB_PATH
from memory.models import LongTermMemory, Message, Session, SessionSummary

logger = logging.getLogger("meera.memory.sqlite")


class SQLiteMemoryStore:
    """
    Thread-safe SQLite storage engine for Meera.
    Implements WAL mode for concurrent readers and transactional writers.
    """

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        self.db_path = Path(db_path or MEMORY_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0,
            )
            self._conn.row_factory = sqlite3.Row
            with self._conn:
                self._conn.execute("PRAGMA journal_mode=WAL;")
                self._conn.execute("PRAGMA synchronous=NORMAL;")
                self._conn.execute("PRAGMA foreign_keys=ON;")
        return self._conn

    def _init_db(self) -> None:
        """Initializes tables and indexes if they do not already exist."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        metadata TEXT NOT NULL DEFAULT '{}',
                        is_archived INTEGER NOT NULL DEFAULT 0
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp REAL NOT NULL,
                        token_count INTEGER NOT NULL DEFAULT 0,
                        metadata TEXT NOT NULL DEFAULT '{}',
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS session_summaries (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        until_message_id INTEGER NOT NULL,
                        created_at REAL NOT NULL,
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS long_term_memories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        category TEXT NOT NULL,
                        key TEXT NOT NULL,
                        value TEXT NOT NULL,
                        confidence REAL NOT NULL DEFAULT 1.0,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        source_session_id TEXT,
                        UNIQUE(category, key),
                        FOREIGN KEY (source_session_id) REFERENCES sessions(id) ON DELETE SET NULL
                    );
                """)

                # Indexes for lightning-fast queries
                conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_cat_key ON long_term_memories(category, key);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_summaries_session ON session_summaries(session_id, created_at DESC);")

    # ==========================================
    # SESSION OPERATIONS
    # ==========================================

    def create_session(
        self,
        session_id: Optional[str] = None,
        title: str = "New Conversation",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Session:
        sid = session_id or f"session_{int(time.time() * 1000)}"
        now = time.time()
        meta = metadata or {}
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute(
                    """
                    INSERT INTO sessions (id, title, created_at, updated_at, metadata, is_archived)
                    VALUES (?, ?, ?, ?, ?, 0)
                    """,
                    (sid, title, now, now, json.dumps(meta)),
                )
        return Session(id=sid, title=title, created_at=now, updated_at=now, metadata=meta, is_archived=False)

    def get_session(self, session_id: str) -> Optional[Session]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return Session(
                id=row["id"],
                title=row["title"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                metadata=json.loads(row["metadata"]),
                is_archived=bool(row["is_archived"]),
            )

    def list_sessions(
        self,
        limit: int = 50,
        offset: int = 0,
        include_archived: bool = False,
    ) -> List[Session]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            if include_archived:
                cursor.execute(
                    "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            else:
                cursor.execute(
                    "SELECT * FROM sessions WHERE is_archived = 0 ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            rows = cursor.fetchall()
            return [
                Session(
                    id=r["id"],
                    title=r["title"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    metadata=json.loads(r["metadata"]),
                    is_archived=bool(r["is_archived"]),
                )
                for r in rows
            ]

    def update_session(
        self,
        session_id: str,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_archived: Optional[bool] = None,
    ) -> bool:
        with self._lock:
            conn = self._get_connection()
            existing = self.get_session(session_id)
            if not existing:
                return False

            new_title = title if title is not None else existing.title
            new_metadata = metadata if metadata is not None else existing.metadata
            new_archived = int(is_archived) if is_archived is not None else int(existing.is_archived)
            now = time.time()

            with conn:
                conn.execute(
                    """
                    UPDATE sessions
                    SET title = ?, metadata = ?, is_archived = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (new_title, json.dumps(new_metadata), new_archived, now, session_id),
                )
            return True

    def touch_session(self, session_id: str) -> None:
        """Updates the updated_at timestamp of a session."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute(
                    "UPDATE sessions SET updated_at = ? WHERE id = ?",
                    (time.time(), session_id),
                )

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            with conn:
                cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                return cursor.rowcount > 0

    # ==========================================
    # MESSAGE OPERATIONS
    # ==========================================

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        token_count: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Message:
        with self._lock:
            # Ensure session exists
            if not self.get_session(session_id):
                # Auto-create session if it doesn't exist
                initial_title = content[:28] + ("..." if len(content) > 28 else "") if role == "user" else "New Conversation"
                self.create_session(session_id=session_id, title=initial_title)

            conn = self._get_connection()
            now = time.time()
            meta = metadata or {}
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO messages (session_id, role, content, timestamp, token_count, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (session_id, role, content, now, token_count, json.dumps(meta)),
                )
                msg_id = cursor.lastrowid
                conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))

        return Message(
            id=msg_id,
            session_id=session_id,
            role=role,
            content=content,
            timestamp=now,
            token_count=token_count,
            metadata=meta,
        )

    def get_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Message]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            if limit is not None:
                cursor.execute(
                    "SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp ASC, id ASC LIMIT ? OFFSET ?",
                    (session_id, limit, offset),
                )
            else:
                cursor.execute(
                    "SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp ASC, id ASC",
                    (session_id,),
                )
            rows = cursor.fetchall()
            return [
                Message(
                    id=r["id"],
                    session_id=r["session_id"],
                    role=r["role"],
                    content=r["content"],
                    timestamp=r["timestamp"],
                    token_count=r["token_count"],
                    metadata=json.loads(r["metadata"]),
                )
                for r in rows
            ]

    def get_message_count(self, session_id: str) -> int:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM messages WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            return row["count"] if row else 0

    def clear_messages(self, session_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM session_summaries WHERE session_id = ?", (session_id,))
                conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (time.time(), session_id))
            return True

    # ==========================================
    # CONTEXT SUMMARIZATION OPERATIONS
    # ==========================================

    def add_summary(
        self,
        session_id: str,
        summary: str,
        until_message_id: int,
    ) -> SessionSummary:
        now = time.time()
        with self._lock:
            conn = self._get_connection()
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO session_summaries (session_id, summary, until_message_id, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (session_id, summary, until_message_id, now),
                )
                summary_id = cursor.lastrowid
        return SessionSummary(
            id=summary_id,
            session_id=session_id,
            summary=summary,
            until_message_id=until_message_id,
            created_at=now,
        )

    def get_latest_summary(self, session_id: str) -> Optional[SessionSummary]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM session_summaries WHERE session_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                (session_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return SessionSummary(
                id=row["id"],
                session_id=row["session_id"],
                summary=row["summary"],
                until_message_id=row["until_message_id"],
                created_at=row["created_at"],
            )

    # ==========================================
    # LONG-TERM MEMORY STORE
    # ==========================================

    def set_long_term_memory(
        self,
        category: str,
        key: str,
        value: str,
        confidence: float = 1.0,
        source_session_id: Optional[str] = None,
    ) -> LongTermMemory:
        now = time.time()
        with self._lock:
            conn = self._get_connection()
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO long_term_memories (category, key, value, confidence, created_at, updated_at, source_session_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(category, key) DO UPDATE SET
                        value = excluded.value,
                        confidence = excluded.confidence,
                        updated_at = excluded.updated_at,
                        source_session_id = COALESCE(excluded.source_session_id, long_term_memories.source_session_id)
                    """,
                    (category, key, value, confidence, now, now, source_session_id),
                )
                # Retrieve the inserted or updated row
                cursor = conn.execute(
                    "SELECT * FROM long_term_memories WHERE category = ? AND key = ?",
                    (category, key),
                )
                row = cursor.fetchone()
        return LongTermMemory(
            id=row["id"],
            category=row["category"],
            key=row["key"],
            value=row["value"],
            confidence=row["confidence"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            source_session_id=row["source_session_id"],
        )

    def get_long_term_memory(self, category: str, key: str) -> Optional[LongTermMemory]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM long_term_memories WHERE category = ? AND key = ?",
                (category, key),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return LongTermMemory(
                id=row["id"],
                category=row["category"],
                key=row["key"],
                value=row["value"],
                confidence=row["confidence"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                source_session_id=row["source_session_id"],
            )

    def list_long_term_memories(
        self,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> List[LongTermMemory]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            if category:
                cursor.execute(
                    "SELECT * FROM long_term_memories WHERE category = ? ORDER BY updated_at DESC LIMIT ?",
                    (category, limit),
                )
            else:
                cursor.execute(
                    "SELECT * FROM long_term_memories ORDER BY category ASC, updated_at DESC LIMIT ?",
                    (limit,),
                )
            rows = cursor.fetchall()
            return [
                LongTermMemory(
                    id=r["id"],
                    category=r["category"],
                    key=r["key"],
                    value=r["value"],
                    confidence=r["confidence"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    source_session_id=r["source_session_id"],
                )
                for r in rows
            ]

    def delete_long_term_memory(self, category: str, key: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            with conn:
                cursor = conn.execute(
                    "DELETE FROM long_term_memories WHERE category = ? AND key = ?",
                    (category, key),
                )
                return cursor.rowcount > 0

    def search_long_term_memories(self, query: str, limit: int = 10) -> List[LongTermMemory]:
        """Case-insensitive keyword search across key and value fields."""
        term = f"%{query}%"
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM long_term_memories
                WHERE key LIKE ? OR value LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (term, term, limit),
            )
            rows = cursor.fetchall()
            return [
                LongTermMemory(
                    id=r["id"],
                    category=r["category"],
                    key=r["key"],
                    value=r["value"],
                    confidence=r["confidence"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    source_session_id=r["source_session_id"],
                )
                for r in rows
            ]

    def close(self) -> None:
        with self._lock:
            if self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
