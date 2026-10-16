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
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from config.settings import MEMORY_DB_PATH
from memory.models import AcademicDeadline, LibraryItem, LongTermMemory, Message, PluginItem, Project, Session, SessionSummary

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
                    CREATE TABLE IF NOT EXISTS projects (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        color TEXT NOT NULL DEFAULT '#A3E635',
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        metadata TEXT NOT NULL DEFAULT '{}'
                    );
                """)
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
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS academic_deadlines (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        due_date TEXT NOT NULL,
                        platform TEXT NOT NULL DEFAULT 'lms',
                        group_name TEXT NOT NULL DEFAULT '',
                        url TEXT NOT NULL DEFAULT '',
                        is_completed INTEGER NOT NULL DEFAULT 0,
                        priority TEXT NOT NULL DEFAULT 'normal',
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        metadata TEXT NOT NULL DEFAULT '{}'
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS academic_config (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS library_items (
                        id TEXT PRIMARY KEY,
                        filename TEXT NOT NULL,
                        filepath TEXT NOT NULL,
                        file_type TEXT NOT NULL DEFAULT 'pdf',
                        file_size INTEGER NOT NULL DEFAULT 0,
                        title TEXT NOT NULL DEFAULT '',
                        tags TEXT NOT NULL DEFAULT '',
                        description TEXT NOT NULL DEFAULT '',
                        created_at REAL NOT NULL,
                        metadata TEXT NOT NULL DEFAULT '{}'
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS plugins (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        category TEXT NOT NULL DEFAULT 'integration',
                        is_enabled INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'disconnected',
                        config TEXT NOT NULL DEFAULT '{}',
                        updated_at REAL NOT NULL
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS teams_alerts (
                        id TEXT PRIMARY KEY,
                        team_name TEXT NOT NULL,
                        channel_name TEXT NOT NULL,
                        author TEXT NOT NULL,
                        snippet TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        is_read INTEGER NOT NULL DEFAULT 0
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS deleted_deadlines (
                        id TEXT PRIMARY KEY,
                        title_key TEXT DEFAULT '',
                        deleted_at REAL NOT NULL
                    );
                """)
                try:
                    conn.execute("ALTER TABLE deleted_deadlines ADD COLUMN title_key TEXT DEFAULT '';")
                except Exception:
                    pass

                # Indexes for lightning-fast queries
                conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at DESC);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_cat_key ON long_term_memories(category, key);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_summaries_session ON session_summaries(session_id, created_at DESC);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_deadlines_due ON academic_deadlines(due_date ASC);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_deadlines_platform ON academic_deadlines(platform);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_library_created ON library_items(created_at DESC);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_library_type ON library_items(file_type);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_teams_alerts_created ON teams_alerts(created_at DESC);")

                # Purge any legacy sample deadlines, documents, or placeholder plugins
                conn.execute("DELETE FROM academic_deadlines WHERE id LIKE 'lms_cs%' OR id LIKE 'teams_os%' OR id LIKE 'teams_ai%' OR id LIKE 'lms_math%' OR id LIKE 'sample%' OR id LIKE 'seed%' OR id LIKE 'mock%';")
                conn.execute("DELETE FROM academic_deadlines WHERE title LIKE '%Guest Lecture%' OR description LIKE '%Guest Lecture%' OR due_date LIKE '2025%' OR due_date LIKE '%11-20%' OR due_date LIKE '%10-14%';")
                conn.execute("DELETE FROM teams_alerts WHERE id LIKE 'sample%' OR id LIKE 'mock%' OR snippet LIKE '%sample%' OR team_name LIKE '%mock%' OR author LIKE '%sample%';")
                conn.execute("DELETE FROM sessions WHERE id IN ('session_1791714694395', 'session_1791733096456');")
                conn.execute("DELETE FROM messages WHERE session_id IN ('session_1791714694395', 'session_1791733096456');")
                conn.execute("DELETE FROM session_summaries WHERE session_id IN ('session_1791714694395', 'session_1791733096456');")
                
                # Enforce Fall 2026 current semester cutoff and purge expired past-week items & past semesters
                now_dt = datetime.now()
                week_ago_date = (now_dt - timedelta(days=7)).strftime("%Y-%m-%d")
                today_date = now_dt.strftime("%Y-%m-%d")
                conn.execute("DELETE FROM academic_deadlines WHERE due_date != '' AND (due_date < ? OR due_date < '2026-08-01');", (week_ago_date,))
                conn.execute("DELETE FROM academic_deadlines WHERE due_date IS NULL OR due_date = '';")
                conn.execute("DELETE FROM academic_deadlines WHERE is_completed = 1 AND due_date != '' AND due_date < ?;", (today_date,))
                conn.execute("""
                    DELETE FROM academic_deadlines 
                    WHERE title LIKE '%2024%' OR title LIKE '%2025%' OR title LIKE '%2023%' 
                       OR title LIKE '%Spring 26%' OR title LIKE '%Winter 26%' OR title LIKE '%25-26%'
                       OR title LIKE '%spring-26%' OR title LIKE '%winter-26%'
                       OR group_name LIKE '%24-25%' OR group_name LIKE '%2024%' OR group_name LIKE '%2025%' 
                       OR group_name LIKE '%23-24%' OR group_name LIKE '%25-26%'
                       OR group_name LIKE '%Spring 26%' OR group_name LIKE '%Winter 26%';
                """)
                
                # Delete any alerts older than 7 days by both message timestamp and insertion time, and purge archived years
                week_ago_ts = time.time() - (7 * 86400)
                conn.execute("DELETE FROM teams_alerts WHERE timestamp = '' OR timestamp IS NULL OR timestamp < ? OR timestamp LIKE '2024%' OR timestamp LIKE '2025%' OR timestamp LIKE '2023%';", (week_ago_date,))
                conn.execute("DELETE FROM teams_alerts WHERE team_name LIKE '%24-25%' OR team_name LIKE '%2024%' OR team_name LIKE '%23-24%' OR team_name LIKE '%25-26%';")
                conn.execute("DELETE FROM teams_alerts WHERE created_at < ?;", (week_ago_ts,))

                conn.execute("DELETE FROM plugins WHERE id IN ('github', 'mcp');")
                conn.execute("DELETE FROM library_items WHERE id = 'doc_cs401_manual';")
                conn.execute("UPDATE plugins SET status = 'disconnected', is_enabled = 0 WHERE id = 'lms' AND (config = '{}' OR config IS NULL OR config NOT LIKE '%url%');")
                conn.execute("UPDATE plugins SET status = 'disconnected', is_enabled = 0 WHERE id = 'teams' AND NOT EXISTS (SELECT 1 FROM academic_config WHERE key = 'teams_access_token');")

                # Baseline connectors: LMS & Microsoft Teams (Default: disconnected)
                real_plugins = [
                    ("lms", "College LMS Portal", "Connect and surf course materials, syllabus, and assignment deadlines.", "lms", 0, "disconnected", "{}"),
                    ("teams", "Microsoft Teams", "Connect class teams, project channels, and lab meeting announcements.", "teams", 0, "disconnected", "{}"),
                ]
                now = time.time()
                for pid, pname, pdesc, pcat, penabled, pstatus, pcfg in real_plugins:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO plugins (id, name, description, category, is_enabled, status, config, updated_at) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (pid, pname, pdesc, pcat, penabled, pstatus, pcfg, now),
                    )

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
        project_id: Optional[str] = None,
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
            sessions = []
            for r in rows:
                meta = json.loads(r["metadata"])
                if project_id is not None:
                    if project_id == "none":
                        if meta.get("project_id"):
                            continue
                    elif meta.get("project_id") != project_id:
                        continue
                sessions.append(
                    Session(
                        id=r["id"],
                        title=r["title"],
                        created_at=r["created_at"],
                        updated_at=r["updated_at"],
                        metadata=meta,
                        is_archived=bool(r["is_archived"]),
                    )
                )

            # Pinned sessions stay anchored at top, then ordered by updated_at descending
            sessions.sort(
                key=lambda s: (
                    1 if s.metadata.get("pinned") else 0,
                    s.updated_at,
                ),
                reverse=True,
            )
            return sessions

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
            if metadata is not None:
                new_metadata = dict(existing.metadata)
                new_metadata.update(metadata)
            else:
                new_metadata = existing.metadata
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
                conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM session_summaries WHERE session_id = ?", (session_id,))
                cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                return cursor.rowcount > 0

    # ==========================================
    # PROJECT OPERATIONS
    # ==========================================

    def create_project(
        self,
        name: str,
        description: str = "",
        color: str = "#A3E635",
        project_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Project:
        pid = project_id or f"proj_{int(time.time() * 1000)}"
        now = time.time()
        meta_dict = metadata or {}
        meta_json = json.dumps(meta_dict)

        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute(
                    """
                    INSERT INTO projects (id, name, description, color, created_at, updated_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (pid, name, description, color, now, now, meta_json),
                )

        return Project(
            id=pid,
            name=name,
            description=description,
            color=color,
            created_at=now,
            updated_at=now,
            metadata=meta_dict,
        )

    def get_project(self, project_id: str) -> Optional[Project]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return Project(
                id=row["id"],
                name=row["name"],
                description=row["description"],
                color=row["color"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                metadata=json.loads(row["metadata"]),
            )

    def list_projects(self) -> List[Project]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM projects ORDER BY updated_at DESC")
            rows = cursor.fetchall()
            return [
                Project(
                    id=r["id"],
                    name=r["name"],
                    description=r["description"],
                    color=r["color"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    metadata=json.loads(r["metadata"]),
                )
                for r in rows
            ]

    def update_project(
        self,
        project_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        color: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        with self._lock:
            conn = self._get_connection()
            existing = self.get_project(project_id)
            if not existing:
                return False

            new_name = name if name is not None else existing.name
            new_desc = description if description is not None else existing.description
            new_color = color if color is not None else existing.color
            if metadata is not None:
                new_meta = dict(existing.metadata)
                new_meta.update(metadata)
            else:
                new_meta = existing.metadata
            now = time.time()

            with conn:
                conn.execute(
                    """
                    UPDATE projects
                    SET name = ?, description = ?, color = ?, metadata = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (new_name, new_desc, new_color, json.dumps(new_meta), now, project_id),
                )
            return True

    def delete_project(self, project_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            with conn:
                # Unassign any sessions attached to this project
                cursor = conn.cursor()
                cursor.execute("SELECT id, metadata FROM sessions")
                for row in cursor.fetchall():
                    meta = json.loads(row["metadata"])
                    if meta.get("project_id") == project_id:
                        meta.pop("project_id", None)
                        meta.pop("project_name", None)
                        conn.execute(
                            "UPDATE sessions SET metadata = ? WHERE id = ?",
                            (json.dumps(meta), row["id"]),
                        )
                # Delete project
                cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
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

    # ==========================================
    # ACADEMIC DEADLINES & CONFIG OPERATIONS
    # ==========================================

    def add_deadline(self, deadline: AcademicDeadline) -> bool:
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO academic_deadlines 
                    (id, title, description, due_date, platform, group_name, url, is_completed, priority, created_at, updated_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        deadline.id,
                        deadline.title,
                        deadline.description,
                        deadline.due_date,
                        deadline.platform,
                        deadline.group_name,
                        deadline.url,
                        1 if deadline.is_completed else 0,
                        deadline.priority,
                        deadline.created_at,
                        deadline.updated_at,
                        json.dumps(deadline.metadata),
                    ),
                )
                return True

    def get_deadline(self, deadline_id: str) -> Optional[AcademicDeadline]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM academic_deadlines WHERE id = ?", (deadline_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_deadline(row)

    def list_deadlines(
        self,
        platform: Optional[str] = None,
        is_completed: Optional[bool] = None,
        date_from: Optional[str] = None,
    ) -> List[AcademicDeadline]:
        now_dt = datetime.now()
        week_ago_str = (now_dt - timedelta(days=7)).strftime("%Y-%m-%d")
        today_str = now_dt.strftime("%Y-%m-%d")
        effective_from = date_from if date_from and date_from >= week_ago_str else week_ago_str

        with self._lock:
            conn = self._get_connection()
            # Permanently purge deleted tombstones, past semester / past week expired deadlines
            with conn:
                conn.execute("DELETE FROM academic_deadlines WHERE id IN (SELECT id FROM deleted_deadlines);")
                conn.execute("DELETE FROM academic_deadlines WHERE due_date != '' AND (due_date < ? OR due_date < '2026-08-01');", (week_ago_str,))
                conn.execute("DELETE FROM academic_deadlines WHERE due_date IS NULL OR due_date = '';")
                conn.execute("DELETE FROM academic_deadlines WHERE is_completed = 1 AND due_date != '' AND due_date < ?;", (today_str,))
                conn.execute("""
                    DELETE FROM academic_deadlines 
                    WHERE title LIKE '%2024%' OR title LIKE '%2025%' OR title LIKE '%2023%' 
                       OR title LIKE '%Spring 26%' OR title LIKE '%Winter 26%' OR title LIKE '%25-26%'
                       OR title LIKE '%spring-26%' OR title LIKE '%winter-26%'
                       OR group_name LIKE '%24-25%' OR group_name LIKE '%2024%' OR group_name LIKE '%2025%' 
                       OR group_name LIKE '%23-24%' OR group_name LIKE '%25-26%'
                       OR group_name LIKE '%Spring 26%' OR group_name LIKE '%Winter 26%';
                """)

            cursor = conn.cursor()
            query = "SELECT * FROM academic_deadlines WHERE 1=1"
            params: List[Any] = []
            if platform:
                query += " AND platform = ?"
                params.append(platform)
            if is_completed is not None:
                query += " AND is_completed = ?"
                params.append(1 if is_completed else 0)
            
            # Strict cutoff: must be due within past 7 days or upcoming in 2026
            query += " AND due_date >= ? AND due_date >= '2026-08-01'"
            params.append(effective_from)
            query += " ORDER BY due_date ASC, created_at ASC"
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [
                self._row_to_deadline(r) for r in rows
                if (r["due_date"] or "")[:4] >= "2026"
                and (r["due_date"] or "")[:10] >= "2026-08-01"
                and (r["due_date"] or "")[:10] >= week_ago_str
                and not (r["is_completed"] and (r["due_date"] or "")[:10] < today_str)
                and not any(y in (r["title"] or "").lower() for y in ("2023", "2024", "2025", "24-25", "25-26", "spring 26", "winter 26", "spring-26", "winter-26"))
                and not any(y in (r["group_name"] or "").lower() for y in ("2023", "2024", "2025", "24-25", "23-24", "25-26", "spring 26", "winter 26", "spring-26", "winter-26"))
            ]

    def update_deadline(
        self,
        deadline_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        due_date: Optional[str] = None,
        platform: Optional[str] = None,
        group_name: Optional[str] = None,
        url: Optional[str] = None,
        is_completed: Optional[bool] = None,
        priority: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        with self._lock:
            conn = self._get_connection()
            fields = []
            values = []
            if title is not None:
                fields.append("title = ?")
                values.append(title)
            if description is not None:
                fields.append("description = ?")
                values.append(description)
            if due_date is not None:
                fields.append("due_date = ?")
                values.append(due_date)
            if platform is not None:
                fields.append("platform = ?")
                values.append(platform)
            if group_name is not None:
                fields.append("group_name = ?")
                values.append(group_name)
            if url is not None:
                fields.append("url = ?")
                values.append(url)
            if is_completed is not None:
                fields.append("is_completed = ?")
                values.append(1 if is_completed else 0)
            if priority is not None:
                fields.append("priority = ?")
                values.append(priority)
            if metadata is not None:
                fields.append("metadata = ?")
                values.append(json.dumps(metadata))

            if not fields:
                return True

            fields.append("updated_at = ?")
            values.append(time.time())
            values.append(deadline_id)

            sql = f"UPDATE academic_deadlines SET {', '.join(fields)} WHERE id = ?"
            with conn:
                cursor = conn.execute(sql, values)
                return cursor.rowcount > 0

    def delete_deadline(self, deadline_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            with conn:
                # Find deadline to capture title & due date signature
                cursor = conn.cursor()
                cursor.execute("SELECT title, due_date FROM academic_deadlines WHERE id = ?", (deadline_id,))
                row = cursor.fetchone()
                title_key = ""
                if row:
                    t = (row["title"] or "").strip().lower()
                    d = (row["due_date"] or "")[:10]
                    title_key = f"{t}_{d}"

                conn.execute(
                    "INSERT OR REPLACE INTO deleted_deadlines (id, title_key, deleted_at) VALUES (?, ?, ?);",
                    (deadline_id, title_key, time.time()),
                )
                del_cur = conn.execute("DELETE FROM academic_deadlines WHERE id = ?", (deadline_id,))
                return del_cur.rowcount > 0

    def upsert_deadlines(self, deadlines: List[AcademicDeadline]) -> int:
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("SELECT id, title_key FROM deleted_deadlines")
            deleted_rows = cur.fetchall()
            deleted_ids = {row[0] for row in deleted_rows if row[0]}
            deleted_keys = {row[1] for row in deleted_rows if len(row) > 1 and row[1]}

            now_dt = datetime.now()
            week_ago_str = (now_dt - timedelta(days=7)).strftime("%Y-%m-%d")
            today_str = now_dt.strftime("%Y-%m-%d")

            valid_deadlines = []
            for d in deadlines:
                if not d.due_date:
                    continue
                if d.id in deleted_ids:
                    continue
                d_key = f"{(d.title or '').strip().lower()}_{d.due_date[:10]}"
                if d_key in deleted_keys:
                    continue
                if d.due_date[:4] < "2026" or d.due_date[:10] < "2026-08-01" or d.due_date[:10] < week_ago_str:
                    continue
                # Skip completed tasks if due date has passed
                if d.is_completed and d.due_date[:10] < today_str:
                    continue
                t_lower = (d.title or "").lower()
                g_lower = (d.group_name or "").lower()
                if any(y in t_lower or y in g_lower for y in ("2023", "2024", "2025", "24-25", "25-26", "spring 26", "winter 26", "even 26", "spring-26", "winter-26")):
                    continue
                valid_deadlines.append(d)
            count = 0
            with conn:
                for d in valid_deadlines:
                    conn.execute(
                        """
                        INSERT INTO academic_deadlines 
                        (id, title, description, due_date, platform, group_name, url, is_completed, priority, created_at, updated_at, metadata)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            title = excluded.title,
                            description = excluded.description,
                            due_date = excluded.due_date,
                            platform = excluded.platform,
                            group_name = excluded.group_name,
                            url = excluded.url,
                            priority = excluded.priority,
                            updated_at = excluded.updated_at
                        """,
                        (
                            d.id,
                            d.title,
                            d.description,
                            d.due_date,
                            d.platform,
                            d.group_name,
                            d.url,
                            1 if d.is_completed else 0,
                            d.priority,
                            d.created_at,
                            d.updated_at,
                            json.dumps(d.metadata),
                        ),
                    )
                    count += 1
        return count

    def purge_older_than_3_months(self) -> Dict[str, int]:
        """Permanently deletes any schedules, deadlines, or alerts older than 3 months (90 days)."""
        with self._lock:
            conn = self._get_connection()
            cutoff_ts = time.time() - (90 * 86400)
            cutoff_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
            with conn:
                c1 = conn.execute("DELETE FROM academic_deadlines WHERE due_date != '' AND due_date < ?;", (cutoff_date,))
                c2 = conn.execute("DELETE FROM academic_deadlines WHERE (due_date IS NULL OR due_date = '') AND created_at < ?;", (cutoff_ts,))
                c3 = conn.execute("DELETE FROM teams_alerts WHERE created_at < ?;", (cutoff_ts,))
                return {
                    "deadlines_deleted": c1.rowcount + c2.rowcount,
                    "alerts_deleted": c3.rowcount,
                }

    def get_academic_config(self) -> Dict[str, str]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM academic_config")
            rows = cursor.fetchall()
            return {r["key"]: r["value"] for r in rows}

    def set_academic_config(self, key: str, value: str) -> None:
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO academic_config (key, value) VALUES (?, ?)",
                    (key, value),
                )

    def _row_to_deadline(self, r: sqlite3.Row) -> AcademicDeadline:
        try:
            meta = json.loads(r["metadata"]) if r["metadata"] else {}
        except Exception:
            meta = {}
        return AcademicDeadline(
            id=r["id"],
            title=r["title"],
            description=r["description"] or "",
            due_date=r["due_date"] or "",
            platform=r["platform"] or "lms",
            group_name=r["group_name"] or "",
            url=r["url"] or "",
            is_completed=bool(r["is_completed"]),
            priority=r["priority"] or "normal",
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            metadata=meta,
        )

    # ==========================================
    # LIBRARY & DOCUMENT ARCHIVE OPERATIONS
    # ==========================================

    def add_library_item(self, item: LibraryItem) -> bool:
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO library_items 
                    (id, filename, filepath, file_type, file_size, title, tags, description, created_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        item.filename,
                        item.filepath,
                        item.file_type,
                        item.file_size,
                        item.title,
                        item.tags,
                        item.description,
                        item.created_at,
                        json.dumps(item.metadata),
                    ),
                )
                return True

    def list_library_items(
        self,
        query: Optional[str] = None,
        file_type: Optional[str] = None,
    ) -> List[LibraryItem]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            sql = "SELECT * FROM library_items WHERE 1=1"
            params: List[Any] = []
            if file_type:
                sql += " AND file_type = ?"
                params.append(file_type.lower())
            if query:
                term = f"%{query}%"
                sql += " AND (title LIKE ? OR filename LIKE ? OR tags LIKE ? OR description LIKE ?)"
                params.extend([term, term, term, term])
            sql += " ORDER BY created_at DESC"
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [self._row_to_library_item(r) for r in rows]

    def get_library_item(self, item_id: str) -> Optional[LibraryItem]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM library_items WHERE id = ?", (item_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_library_item(row)

    def delete_library_item(self, item_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            with conn:
                cursor = conn.execute("DELETE FROM library_items WHERE id = ?", (item_id,))
                return cursor.rowcount > 0

    def _row_to_library_item(self, r: sqlite3.Row) -> LibraryItem:
        try:
            meta = json.loads(r["metadata"]) if r["metadata"] else {}
        except Exception:
            meta = {}
        return LibraryItem(
            id=r["id"],
            filename=r["filename"],
            filepath=r["filepath"],
            file_type=r["file_type"],
            file_size=r["file_size"],
            title=r["title"] or r["filename"],
            tags=r["tags"] or "",
            description=r["description"] or "",
            created_at=r["created_at"],
            metadata=meta,
        )

    # ==========================================
    # PLUGINS & INTEGRATION CONNECTORS OPERATIONS
    # ==========================================

    def list_plugins(self) -> List[PluginItem]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM plugins ORDER BY id ASC")
            rows = cursor.fetchall()
            return [self._row_to_plugin_item(r) for r in rows]

    def get_plugin(self, plugin_id: str) -> Optional[PluginItem]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM plugins WHERE id = ?", (plugin_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_plugin_item(row)

    def update_plugin(
        self,
        plugin_id: str,
        is_enabled: Optional[bool] = None,
        status: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        with self._lock:
            conn = self._get_connection()
            fields = []
            values = []
            if is_enabled is not None:
                fields.append("is_enabled = ?")
                values.append(1 if is_enabled else 0)
            if status is not None:
                fields.append("status = ?")
                values.append(status)
            if config is not None:
                fields.append("config = ?")
                values.append(json.dumps(config))

            if not fields:
                return True

            fields.append("updated_at = ?")
            values.append(time.time())
            values.append(plugin_id)

            sql = f"UPDATE plugins SET {', '.join(fields)} WHERE id = ?"
            with conn:
                cursor = conn.execute(sql, values)
                return cursor.rowcount > 0

    def _row_to_plugin_item(self, r: sqlite3.Row) -> PluginItem:
        try:
            cfg = json.loads(r["config"]) if r["config"] else {}
        except Exception:
            cfg = {}

        # Dynamically enforce real connection status
        status = r["status"] or "disconnected"
        is_enabled = bool(r["is_enabled"])
        if r["id"] == "lms":
            # LMS is only connected if a valid feed URL is configured
            if not cfg.get("url"):
                status = "disconnected"
                is_enabled = False
        elif r["id"] == "teams":
            # Teams is connected only if authenticated with access token or webcal URL
            has_token = bool(self.get_academic_config().get("teams_access_token"))
            if not has_token and not cfg.get("url"):
                status = "disconnected"
                is_enabled = False

        return PluginItem(
            id=r["id"],
            name=r["name"],
            description=r["description"] or "",
            category=r["category"] or "integration",
            is_enabled=is_enabled,
            status=status,
            config=cfg,
            updated_at=r["updated_at"],
        )

    # ==========================================
    # TEAMS ALERTS & CHANNEL ANNOUNCEMENTS
    # ==========================================

    def upsert_teams_alerts(self, alerts: List[Dict[str, Any]], days_back: int = 7) -> int:
        if not alerts:
            return 0
        cutoff = time.time() - (days_back * 86400)
        recent_alerts = [a for a in alerts if a.get("created_at", 0) >= cutoff]
        if not recent_alerts:
            return 0
        with self._lock:
            conn = self._get_connection()
            count = 0
            with conn:
                for a in recent_alerts:
                    cur = conn.execute(
                        """
                        INSERT OR REPLACE INTO teams_alerts 
                        (id, team_name, channel_name, author, snippet, timestamp, created_at, is_read)
                        VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT is_read FROM teams_alerts WHERE id = ?), 0))
                        """,
                        (
                            a["id"],
                            a.get("team_name", "Teams"),
                            a.get("channel_name", "General"),
                            a.get("author", "Instructor"),
                            a.get("snippet", ""),
                            a.get("timestamp", ""),
                            a.get("created_at", time.time()),
                            a["id"],
                        ),
                    )
                    count += cur.rowcount
            return count

    def list_teams_alerts(self, unread_only: bool = False, limit: int = 50, days_back: int = 7) -> List[Dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            cutoff = time.time() - (days_back * 86400)
            week_ago_iso = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            # Prune old alerts from persistent database by both timestamp and created_at
            with conn:
                conn.execute("DELETE FROM teams_alerts WHERE timestamp = '' OR timestamp IS NULL OR timestamp < ? OR timestamp LIKE '2024%' OR timestamp LIKE '2025%' OR timestamp LIKE '2023%';", (week_ago_iso,))
                conn.execute("DELETE FROM teams_alerts WHERE team_name LIKE '%24-25%' OR team_name LIKE '%2024%' OR team_name LIKE '%23-24%';")
                conn.execute("DELETE FROM teams_alerts WHERE created_at < ?;", (cutoff,))
            cur = conn.cursor()
            if unread_only:
                cur.execute(
                    "SELECT * FROM teams_alerts WHERE is_read = 0 AND created_at >= ? AND timestamp != '' AND timestamp >= ? AND team_name NOT LIKE '%24-25%' AND team_name NOT LIKE '%2024%' ORDER BY created_at DESC LIMIT ?",
                    (cutoff, week_ago_iso, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM teams_alerts WHERE created_at >= ? AND timestamp != '' AND timestamp >= ? AND team_name NOT LIKE '%24-25%' AND team_name NOT LIKE '%2024%' ORDER BY created_at DESC LIMIT ?",
                    (cutoff, week_ago_iso, limit),
                )
            rows = cur.fetchall()
            return [
                {
                    "id": r["id"],
                    "team_name": r["team_name"],
                    "channel_name": r["channel_name"],
                    "author": r["author"],
                    "snippet": r["snippet"],
                    "timestamp": r["timestamp"],
                    "created_at": r["created_at"],
                    "is_read": bool(r["is_read"]),
                }
                for r in rows
                if r["timestamp"] and r["timestamp"][:10] >= week_ago_iso and r["created_at"] >= cutoff
            ]

    def mark_teams_alert_read(self, alert_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            with conn:
                if alert_id == "all":
                    conn.execute("UPDATE teams_alerts SET is_read = 1")
                    week_ago_iso = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
                    cutoff = time.time() - (7 * 86400)
                    conn.execute("DELETE FROM teams_alerts WHERE timestamp = '' OR timestamp IS NULL OR timestamp < ? OR timestamp LIKE '2024%' OR timestamp LIKE '2025%' OR timestamp LIKE '2023%';", (week_ago_iso,))
                    conn.execute("DELETE FROM teams_alerts WHERE team_name LIKE '%24-25%' OR team_name LIKE '%2024%' OR team_name LIKE '%23-24%';")
                    conn.execute("DELETE FROM teams_alerts WHERE created_at < ?;", (cutoff,))
                    return True
                cur = conn.execute("UPDATE teams_alerts SET is_read = 1 WHERE id = ?", (alert_id,))
                return cur.rowcount > 0

    def delete_teams_alert(self, alert_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            with conn:
                if alert_id == "all":
                    conn.execute("DELETE FROM teams_alerts;")
                    return True
                cur = conn.execute("DELETE FROM teams_alerts WHERE id = ?;", (alert_id,))
                return cur.rowcount > 0

    def get_unread_alerts_count(self, days_back: int = 7) -> int:
        with self._lock:
            conn = self._get_connection()
            cur = conn.cursor()
            cutoff = time.time() - (days_back * 86400)
            week_ago_iso = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
            cur.execute(
                "SELECT COUNT(*) FROM teams_alerts WHERE is_read = 0 AND created_at >= ? AND timestamp != '' AND timestamp >= ? AND team_name NOT LIKE '%24-25%' AND team_name NOT LIKE '%2024%'",
                (cutoff, week_ago_iso),
            )
            row = cur.fetchone()
            return row[0] if row else 0

    def close(self) -> None:
        with self._lock:
            if self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
