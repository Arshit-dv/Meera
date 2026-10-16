"""
Meera - Memory Data Models
Defines structured entities for sessions, messages, summaries, and persistent memories.
"""
from dataclasses import dataclass, field
import time
from typing import Any, Dict, Optional


@dataclass
class Session:
    id: str
    title: str = "New Conversation"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_archived: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "is_archived": self.is_archived,
        }


@dataclass
class Message:
    session_id: str
    role: str
    content: str
    id: Optional[int] = None
    timestamp: float = field(default_factory=time.time)
    token_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "token_count": self.token_count,
            "metadata": self.metadata,
        }


@dataclass
class SessionSummary:
    session_id: str
    summary: str
    until_message_id: int
    id: Optional[int] = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "summary": self.summary,
            "until_message_id": self.until_message_id,
            "created_at": self.created_at,
        }


@dataclass
class LongTermMemory:
    category: str
    key: str
    value: str
    id: Optional[int] = None
    confidence: float = 1.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    source_session_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "key": self.key,
            "value": self.value,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source_session_id": self.source_session_id,
        }


@dataclass
class Project:
    id: str
    name: str
    description: str = ""
    color: str = "#A3E635"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "color": self.color,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }


@dataclass
class AcademicDeadline:
    id: str
    title: str
    description: str = ""
    due_date: str = ""  # ISO format string YYYY-MM-DD or YYYY-MM-DDTHH:MM
    platform: str = "lms"  # 'lms' or 'teams'
    group_name: str = ""  # e.g., 'CS401: Compiler Design' or 'Operating Systems Lab'
    url: str = ""
    is_completed: bool = False
    priority: str = "normal"  # 'low', 'normal', 'high', 'urgent'
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "due_date": self.due_date,
            "platform": self.platform,
            "group_name": self.group_name,
            "url": self.url,
            "is_completed": self.is_completed,
            "priority": self.priority,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }


@dataclass
class LibraryItem:
    id: str
    filename: str
    filepath: str
    file_type: str = "pdf"
    file_size: int = 0
    title: str = ""
    tags: str = ""
    description: str = ""
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "filename": self.filename,
            "filepath": self.filepath,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "title": self.title,
            "tags": self.tags,
            "description": self.description,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


@dataclass
class PluginItem:
    id: str
    name: str
    description: str = ""
    category: str = "integration"
    is_enabled: bool = False
    status: str = "disconnected"
    config: Dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "is_enabled": self.is_enabled,
            "status": self.status,
            "config": self.config,
            "updated_at": self.updated_at,
        }


