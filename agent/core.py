"""
Meera - Agent Core
Coordinates context building, conversation history, model execution,
and persistent SQLite multi-session memory.
"""
import logging
from typing import Any, Dict, Iterator, List, Optional

from config.settings import DEFAULT_SYSTEM_PROMPT, MemoryConfig
from memory.context import ContextManager, generate_auto_title
from memory.models import Message, Session
from memory.sqlite import SQLiteMemoryStore
from model.manager import ModelManager
from model.provider import ChatMessage, GenerationRequest

logger = logging.getLogger("meera.agent.core")


class AgentCore:
    """
    Core orchestrator for Meera.
    Decoupled from specific models, interfaces, and tools.
    Integrates persistent SQLite memory, sliding window, and auto-summarization.
    """

    def __init__(
        self,
        model_manager: Optional[ModelManager] = None,
        memory_store: Optional[SQLiteMemoryStore] = None,
        memory_config: Optional[MemoryConfig] = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        active_session_id: Optional[str] = None,
    ):
        self.model_manager = model_manager or ModelManager()
        self.memory_store = memory_store or SQLiteMemoryStore()
        self.memory_config = memory_config or MemoryConfig()
        self.system_prompt = system_prompt
        self.context_manager = ContextManager(
            memory_store=self.memory_store,
            config=self.memory_config,
            base_system_prompt=system_prompt,
        )
        self._active_session_id = active_session_id

    @property
    def active_session_id(self) -> str:
        """Returns or creates the current active session ID."""
        if not self._active_session_id:
            session = self.memory_store.create_session(title="New Conversation")
            self._active_session_id = session.id
        return self._active_session_id

    @active_session_id.setter
    def active_session_id(self, sid: Optional[str]) -> None:
        self._active_session_id = sid

    @property
    def history(self) -> List[ChatMessage]:
        """Provides backwards-compatible access to current active session history."""
        msgs = self.memory_store.get_messages(self.active_session_id)
        return [ChatMessage(role=m.role, content=m.content) for m in msgs]

    def build_context(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        reserve_generation_tokens: int = 300,
    ) -> List[ChatMessage]:
        """
        Assembles system instructions, historical context, and the new user message.
        Uses a sliding context window to stay safely within the 1024 context budget.
        """
        sid = session_id or self.active_session_id
        return self.context_manager.build_context(
            session_id=sid,
            user_message=user_message,
            reserve_generation_tokens=reserve_generation_tokens,
        )

    def chat(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> str:
        """Processes a user message and returns the full assistant response."""
        sid = session_id or self.active_session_id

        # Update title if it is the first turn
        self._maybe_auto_title(sid, user_message)

        context = self.build_context(user_message, session_id=sid)
        request = GenerationRequest(
            messages=context,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )

        response = self.model_manager.generate(request)
        assistant_reply = response.content.strip()

        # Persist messages in SQLite
        self.memory_store.add_message(session_id=sid, role="user", content=user_message)
        self.memory_store.add_message(session_id=sid, role="assistant", content=assistant_reply)

        # Trigger periodic summarization if threshold reached
        self.context_manager.summarize_session_if_needed(sid, self.model_manager)

        return assistant_reply

    def chat_stream(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> Iterator[str]:
        """Processes a user message and yields response tokens as they arrive."""
        sid = session_id or self.active_session_id

        self._maybe_auto_title(sid, user_message)

        context = self.build_context(user_message, session_id=sid)
        request = GenerationRequest(
            messages=context,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        accumulated_chunks: List[str] = []
        for chunk in self.model_manager.stream(request):
            if chunk.delta:
                accumulated_chunks.append(chunk.delta)
                yield chunk.delta

        full_reply = "".join(accumulated_chunks).strip()

        # Persist messages in SQLite
        self.memory_store.add_message(session_id=sid, role="user", content=user_message)
        self.memory_store.add_message(session_id=sid, role="assistant", content=full_reply)

        # Trigger periodic summarization if threshold reached
        self.context_manager.summarize_session_if_needed(sid, self.model_manager)

    def _maybe_auto_title(self, session_id: str, first_message: str) -> None:
        """Auto-titles a session if it has default title and no prior messages."""
        session = self.memory_store.get_session(session_id)
        if session and (session.title == "New Conversation" or not session.title):
            msg_count = self.memory_store.get_message_count(session_id)
            if msg_count == 0:
                new_title = generate_auto_title(first_message)
                self.memory_store.update_session(session_id, title=new_title)

    def reset_conversation(self, session_id: Optional[str] = None) -> None:
        """Clears current active conversation history or starts a fresh session."""
        if session_id:
            self.memory_store.clear_messages(session_id)
        else:
            # Create a new active session
            session = self.memory_store.create_session(title="New Conversation")
            self._active_session_id = session.id

    def get_history(self, session_id: Optional[str] = None) -> List[Dict[str, str]]:
        """Returns current chat history in dict format."""
        sid = session_id or self.active_session_id
        msgs = self.memory_store.get_messages(sid)
        return [{"role": m.role, "content": m.content} for m in msgs]

    def status(self) -> Dict[str, Any]:
        """Returns high-level status of the Agent Core, Memory Engine, and Model Manager."""
        sessions = self.memory_store.list_sessions(limit=10)
        active_count = self.memory_store.get_message_count(self.active_session_id)
        long_term_count = len(self.memory_store.list_long_term_memories())
        return {
            "agent": "Meera Core V1 (Persistent Memory Enabled)",
            "active_session_id": self.active_session_id,
            "active_session_messages": active_count,
            "total_sessions": len(sessions),
            "long_term_memories": long_term_count,
            "model_manager": self.model_manager.health(),
        }
