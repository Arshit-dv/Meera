"""
Meera - Memory Package
Persistent SQLite storage, multi-session management, sliding context window,
and long-term knowledge memory.
"""
from memory.context import ContextManager, estimate_tokens, generate_auto_title
from memory.models import (
    AcademicDeadline,
    LibraryItem,
    LongTermMemory,
    Message,
    PluginItem,
    Project,
    Session,
    SessionSummary,
)
from memory.sqlite import SQLiteMemoryStore

__all__ = [
    "SQLiteMemoryStore",
    "ContextManager",
    "Session",
    "Message",
    "SessionSummary",
    "LongTermMemory",
    "Project",
    "AcademicDeadline",
    "LibraryItem",
    "PluginItem",
    "estimate_tokens",
    "generate_auto_title",
]

