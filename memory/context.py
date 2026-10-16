"""
Meera - Context & Memory Orchestrator
Enforces the 1024-token context ceiling, injects long-term memory facts,
manages sliding window history, and performs periodic context summarization.
"""
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from config.settings import DEFAULT_SYSTEM_PROMPT, MemoryConfig
from memory.models import LongTermMemory, Message, SessionSummary
from memory.sqlite import SQLiteMemoryStore
from model.provider import ChatMessage

logger = logging.getLogger("meera.memory.context")


def estimate_tokens(text: str) -> int:
    """
    Conservative token estimation for quantized LLMs.
    1 token ≈ 3.5 characters or 0.75 words.
    """
    if not text:
        return 0
    char_estimate = len(text) / 3.5
    word_estimate = len(text.split()) * 1.3
    return int(max(char_estimate, word_estimate)) + 1


def generate_auto_title(first_message: str) -> str:
    """Generates a clean, concise session title from the first message."""
    clean = first_message.strip().replace("\n", " ")
    # Strip markdown prefixes or code quotes
    clean = re.sub(r"^[#\s\*\-]+", "", clean)
    clean = re.sub(r"[`\"']+", "", clean).strip()
    if not clean:
        return "Conversation"
    if len(clean) > 32:
        # Cut at last whole word before 32 chars
        truncated = clean[:32]
        last_space = truncated.rfind(" ")
        if last_space > 12:
            return truncated[:last_space].strip() + "..."
        return truncated.strip() + "..."
    return clean


class ContextManager:
    """
    Orchestrates memory retrieval, sliding context building, and token budgeting.
    Strictly safeguards against 1024-token VRAM explosions on the RTX 2050.
    """

    def __init__(
        self,
        memory_store: SQLiteMemoryStore,
        config: Optional[MemoryConfig] = None,
        base_system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ):
        self.store = memory_store
        self.config = config or MemoryConfig()
        self.base_system_prompt = base_system_prompt

    def build_system_prompt(
        self,
        relevant_memories: Optional[List[LongTermMemory]] = None,
        tools_prompt: Optional[str] = None,
    ) -> str:
        """
        Injects system persona along with verified long-term memories, current date/time, and compact tool schemas.
        """
        from datetime import datetime
        now_str = datetime.now().strftime("%A, %B %d, %Y")
        prompt = f"{self.base_system_prompt.strip()}\n[Current Date: {now_str}]"

        memories = relevant_memories
        if memories is None:
            memories = self.store.list_long_term_memories(limit=self.config.max_long_term_memories_inject)

        if memories:
            memory_lines = []
            for m in memories:
                memory_lines.append(f"- [{m.category.upper()}] {m.key}: {m.value}")
            prompt += "\n\n[Persistent Long-Term Memory & User Profile]\n" + "\n".join(memory_lines)

        if tools_prompt:
            prompt += "\n\n" + tools_prompt.strip()

        return prompt

    def build_context(
        self,
        session_id: str,
        user_message: str,
        reserve_generation_tokens: int = 300,
        tools_prompt: Optional[str] = None,
    ) -> List[ChatMessage]:
        """
        Assembles the exact message payload for model inference:
        1. Base system prompt + long-term memory facts + tool schemas
        2. Session context summary (if older turns were summarized)
        3. Sliding window of recent turns (strictly budget-checked)
        4. User message
        """
        token_ceiling = self.config.context_token_ceiling
        budget_for_context = token_ceiling - reserve_generation_tokens

        # 1. System Prompt & Memories & Tools
        system_content = self.build_system_prompt(tools_prompt=tools_prompt)
        system_tokens = estimate_tokens(system_content)

        # 2. User Message
        user_tokens = estimate_tokens(user_message)

        remaining_budget = budget_for_context - system_tokens - user_tokens
        if remaining_budget < 60:
            logger.warning("[CONTEXT] Tight token budget; trimming system prompt")
            system_content = self.base_system_prompt
            remaining_budget = budget_for_context - estimate_tokens(system_content) - user_tokens

        messages: List[ChatMessage] = [ChatMessage(role="system", content=system_content)]

        # 3. Check for Existing Context Summary
        summary = self.store.get_latest_summary(session_id)
        summary_tokens = 0
        if summary and summary.summary:
            summary_text = f"[Context Summary of Earlier Conversation]\n{summary.summary}"
            summary_tokens = estimate_tokens(summary_text)
            if remaining_budget >= summary_tokens + 80:
                messages.append(ChatMessage(role="system", content=summary_text))
                remaining_budget -= summary_tokens

        # 4. Sliding Window of Messages
        all_session_messages = self.store.get_messages(session_id)
        
        # Only take up to max_sliding_window_turns recent messages
        recent_candidates = all_session_messages[-self.config.max_sliding_window_turns:]
        
        # Build backwards to fit within remaining budget
        selected_recent: List[ChatMessage] = []
        for msg in reversed(recent_candidates):
            msg_tokens = msg.token_count or estimate_tokens(msg.content)
            if remaining_budget - msg_tokens > 20:
                selected_recent.insert(0, ChatMessage(role=msg.role, content=msg.content))
                remaining_budget -= msg_tokens
            else:
                break

        messages.extend(selected_recent)
        messages.append(ChatMessage(role="user", content=user_message))

        return messages

    def summarize_session_if_needed(self, session_id: str, model_manager: Optional[Any] = None) -> Optional[SessionSummary]:
        """
        Periodically compresses older conversation history into a concise summary
        when history exceeds the auto-summarize threshold.
        """
        all_messages = self.store.get_messages(session_id)
        if len(all_messages) < self.config.auto_summarize_threshold:
            return None

        latest_summary = self.store.get_latest_summary(session_id)
        last_summarized_id = latest_summary.until_message_id if latest_summary else 0

        # Messages eligible for summarization (all messages except the recent sliding window)
        summarize_cutoff_index = len(all_messages) - self.config.max_sliding_window_turns
        messages_to_summarize = [
            m for m in all_messages[:summarize_cutoff_index]
            if m.id and m.id > last_summarized_id
        ]

        if len(messages_to_summarize) < 4:
            return None

        # Build transcript of turns to summarize
        transcript_lines = []
        for m in messages_to_summarize:
            content_snippet = m.content[:180].replace("\n", " ")
            transcript_lines.append(f"{m.role.capitalize()}: {content_snippet}")
        transcript = "\n".join(transcript_lines)

        summary_text = ""
        # If model is loaded, we can ask for a quick summary
        if model_manager and hasattr(model_manager, "is_loaded") and model_manager.is_loaded():
            try:
                from model.provider import GenerationRequest
                prompt = (
                    "Summarize the key decisions and facts from this conversation snippet in 2-3 concise sentences:\n\n"
                    f"{transcript}\n\nSummary:"
                )
                req = GenerationRequest(
                    messages=[
                        ChatMessage(role="system", content="You are a precise technical summarizer."),
                        ChatMessage(role="user", content=prompt),
                    ],
                    temperature=0.3,
                    max_tokens=120,
                    stream=False,
                )
                resp = model_manager.generate(req)
                if resp.content.strip():
                    summary_text = resp.content.strip()
            except Exception as e:
                logger.warning(f"[CONTEXT] Model summarization skipped: {e}")

        # Fallback to structured extractive summary if model generation was unavailable
        if not summary_text:
            key_points = []
            if latest_summary:
                key_points.append(latest_summary.summary)
            for m in messages_to_summarize:
                if m.role == "user":
                    clean = m.content.strip().split("\n")[0][:90]
                    key_points.append(f"User discussed: {clean}")
            summary_text = " | ".join(key_points[-4:])

        last_id = messages_to_summarize[-1].id
        if last_id:
            return self.store.add_summary(session_id, summary_text, last_id)
        return None
