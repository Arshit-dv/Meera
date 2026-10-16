"""
Meera - Agent Core
Coordinates context building, conversation history, model execution,
persistent SQLite multi-session memory, and guardrailed tool execution.
"""
import logging
from typing import Any, Dict, Iterator, List, Optional, Tuple

from config.settings import DEFAULT_SYSTEM_PROMPT, MemoryConfig
from memory.context import ContextManager, generate_auto_title
from memory.models import Message, Session
from memory.sqlite import SQLiteMemoryStore
from model.manager import ModelManager
from model.provider import ChatMessage, GenerationRequest
from permissions.manager import PermissionManager
from skills.academic_surfer import AcademicSurfer
from skills.manifest import SkillManifest
from skills.orchestrator import MultiAgentOrchestrator
from skills.registry import SkillRegistry
from skills.scheduler import TaskScheduler
from skills.teams_connector import TeamsConnector
from tools.base import ToolResult
from tools.registry import ToolRegistry

logger = logging.getLogger("meera.agent.core")


class AgentCore:
    """
    Core orchestrator for Meera.
    Integrates persistent SQLite memory, sliding window, auto-summarization,
    guardrailed tool execution (READ, PREPARE, ACT), skills engine,
    and background task scheduling.
    """

    def __init__(
        self,
        model_manager: Optional[ModelManager] = None,
        memory_store: Optional[SQLiteMemoryStore] = None,
        memory_config: Optional[MemoryConfig] = None,
        tool_registry: Optional[ToolRegistry] = None,
        skill_registry: Optional[SkillRegistry] = None,
        scheduler: Optional[TaskScheduler] = None,
        orchestrator: Optional[MultiAgentOrchestrator] = None,
        academic_surfer: Optional[AcademicSurfer] = None,
        teams_connector: Optional[TeamsConnector] = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        active_session_id: Optional[str] = None,
        enable_tools: bool = True,
    ):
        self.model_manager = model_manager or ModelManager()
        self.memory_store = memory_store or SQLiteMemoryStore()
        self.memory_config = memory_config or MemoryConfig()
        self.tool_registry = tool_registry or ToolRegistry()
        self.skill_registry = skill_registry or SkillRegistry()
        self.scheduler = scheduler or TaskScheduler()
        self.academic_surfer = academic_surfer or AcademicSurfer(memory_store=self.memory_store)
        self.teams_connector = teams_connector or TeamsConnector(memory_store=self.memory_store)
        self.orchestrator = orchestrator or MultiAgentOrchestrator(
            model_manager=self.model_manager,
            tool_registry=self.tool_registry,
        )
        self.system_prompt = system_prompt
        self.enable_tools = enable_tools
        self.context_manager = ContextManager(
            memory_store=self.memory_store,
            config=self.memory_config,
            base_system_prompt=system_prompt,
        )
        self._active_session_id = active_session_id
        # Start scheduler worker
        self.scheduler.start()

    @property
    def active_session_id(self) -> Optional[str]:
        """Returns the current active session ID, reusing an existing session or None if no sessions exist."""
        if self._active_session_id:
            if not self.memory_store.get_session(self._active_session_id):
                self._active_session_id = None

        if not self._active_session_id:
            existing = self.memory_store.list_sessions(limit=1)
            if existing:
                self._active_session_id = existing[0].id
        return self._active_session_id

    def ensure_active_session(self) -> str:
        """Ensures an active session exists, creating one only when an actual chat occurs."""
        sid = self.active_session_id
        if not sid:
            session = self.memory_store.create_session(title="New Conversation")
            self._active_session_id = session.id
            return session.id
        return sid

    @active_session_id.setter
    def active_session_id(self, sid: Optional[str]) -> None:
        self._active_session_id = sid

    @property
    def history(self) -> List[ChatMessage]:
        """Provides backwards-compatible access to current active session history."""
        sid = self.active_session_id
        if not sid:
            return []
        msgs = self.memory_store.get_messages(sid)
        return [ChatMessage(role=m.role, content=m.content) for m in msgs]

    def build_context(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        reserve_generation_tokens: int = 300,
        enable_tools: Optional[bool] = None,
    ):
        """
        Assembles system instructions, historical context, tool schemas, and user message.
        Uses a sliding context window to stay safely within the 1024 context budget.
        """
        sid = session_id or self.ensure_active_session()
        use_tools = self.enable_tools if enable_tools is None else enable_tools
        tools_prompt = self.tool_registry.get_prompt_schema() if use_tools else ""
        skill_prompt = self.skill_registry.get_prompt_extension(user_message).strip()

        combined_prompt_parts = []
        if tools_prompt:
            combined_prompt_parts.append(tools_prompt)
        if skill_prompt:
            combined_prompt_parts.append(skill_prompt)

        combined_prompt = "\n\n".join(combined_prompt_parts) if combined_prompt_parts else None

        return self.context_manager.build_context(
            session_id=sid,
            user_message=user_message,
            reserve_generation_tokens=reserve_generation_tokens,
            tools_prompt=combined_prompt,
        )

    def chat(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
        confirmation_token: Optional[str] = None,
    ) -> str:
        """
        Processes a user message, handles guardrailed tool execution loops,
        and returns the full assistant response.
        """
        sid = session_id or self.ensure_active_session()
        self._maybe_auto_title(sid, user_message)

        context = self.build_context(user_message, session_id=sid)
        request = GenerationRequest(
            messages=context,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )

        response = self.model_manager.generate(request)
        initial_reply = response.content.strip()

        # Check for tool call
        tool_call = self.tool_registry.parse_tool_call(initial_reply) if self.enable_tools else None
        if tool_call:
            tool_name, args = tool_call
            logger.info(f"[AGENT] Invoking tool '{tool_name}' with args: {args}")

            # Execute tool through permission guards
            tool_result = self.tool_registry.execute(
                tool_name=tool_name,
                arguments=args,
                confirmation_token=confirmation_token,
            )

            # Check if confirmation is required
            if tool_result.metadata.get("permission_denied") and "CONFIRMATION_REQUIRED" in tool_result.error:
                assistant_reply = (
                    f"◈ Requested Action: `{tool_name}({args})`\n\n"
                    f"▲ **Explicit User Confirmation Required** [ACT Tier]\n"
                    f"{tool_result.error}\n\n"
                    f"To authorize this action, approve token via `/api/tools/approve` or reply to confirm."
                )
            else:
                # Format feedback loop for model follow-up turn
                obs_content = tool_result.output if tool_result.success else f"Error: {tool_result.error}"
                followup_messages = list(context)
                followup_messages.append(ChatMessage(role="assistant", content=initial_reply))
                followup_messages.append(ChatMessage(role="user", content=f"[OBSERVATION: {obs_content}]"))

                second_request = GenerationRequest(
                    messages=followup_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=False,
                )
                second_response = self.model_manager.generate(second_request)
                assistant_reply = second_response.content.strip()
                if not assistant_reply:
                    assistant_reply = f"◈ Tool Result:\n{obs_content}"
        else:
            assistant_reply = initial_reply

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
        confirmation_token: Optional[str] = None,
    ) -> Iterator[str]:
        """
        Processes a user message and yields response tokens as they arrive,
        streaming tool invocation and observation feedback into the canvas.
        """
        sid = session_id or self.ensure_active_session()
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

        full_initial = "".join(accumulated_chunks).strip()

        # Check for tool call in accumulated text
        tool_call = self.tool_registry.parse_tool_call(full_initial) if self.enable_tools else None
        if tool_call:
            tool_name, args = tool_call
            yield f"\n\n◈ [TOOL EXECUTION] `{tool_name}`: {args}\n"

            tool_result = self.tool_registry.execute(
                tool_name=tool_name,
                arguments=args,
                confirmation_token=confirmation_token,
            )

            if tool_result.metadata.get("permission_denied") and "CONFIRMATION_REQUIRED" in tool_result.error:
                confirm_msg = (
                    f"\n▲ [CONFIRMATION REQUIRED] {tool_result.error}\n"
                    f"Approve action via Command Center or API token."
                )
                yield confirm_msg
                final_reply = full_initial + confirm_msg
            else:
                obs_content = tool_result.output if tool_result.success else f"Error: {tool_result.error}"
                yield f"⬡ [OBSERVATION]: {obs_content[:200]}...\n\n"

                # Second turn generation
                followup_messages = list(context)
                followup_messages.append(ChatMessage(role="assistant", content=full_initial))
                followup_messages.append(ChatMessage(role="user", content=f"[OBSERVATION: {obs_content}]"))

                second_request = GenerationRequest(
                    messages=followup_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                )

                second_chunks: List[str] = []
                for chunk in self.model_manager.stream(second_request):
                    if chunk.delta:
                        second_chunks.append(chunk.delta)
                        yield chunk.delta

                final_reply = "".join(second_chunks).strip() or obs_content
        else:
            final_reply = full_initial

        # Persist messages in SQLite
        self.memory_store.add_message(session_id=sid, role="user", content=user_message)
        self.memory_store.add_message(session_id=sid, role="assistant", content=final_reply)

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
            session = self.memory_store.create_session(title="New Conversation")
            self._active_session_id = session.id

    def get_history(self, session_id: Optional[str] = None) -> List[Dict[str, str]]:
        """Returns current chat history in dict format."""
        sid = session_id or self.active_session_id
        msgs = self.memory_store.get_messages(sid)
        return [{"role": m.role, "content": m.content} for m in msgs]

    def status(self) -> Dict[str, Any]:
        """Returns high-level status of Agent Core, Memory Engine, Tool Registry, Skills, and Scheduler."""
        sessions = self.memory_store.list_sessions(limit=10)
        active_sid = self._active_session_id or (sessions[0].id if sessions else None)
        active_count = self.memory_store.get_message_count(active_sid) if active_sid else 0
        long_term_count = len(self.memory_store.list_long_term_memories())
        tools_list = self.tool_registry.list_tools()
        pending_actions = self.tool_registry.permission_manager.list_pending_actions()
        active_skill = self.skill_registry.active_skill
        tasks = self.scheduler.list_tasks()

        return {
            "agent": "Meera Core V1 (Skills Engine & Orchestration Enabled)",
            "active_session_id": active_sid,
            "active_session_messages": active_count,
            "total_sessions": len(sessions),
            "long_term_memories": long_term_count,
            "active_skill": active_skill.id if active_skill else None,
            "available_skills": [s.id for s in self.skill_registry.list_skills()],
            "scheduled_tasks_count": len(tasks),
            "registered_tools": [
                {"name": t.name, "tier": t.tier.value, "description": t.description}
                for t in tools_list
            ],
            "pending_actions_count": len(pending_actions),
            "model_manager": self.model_manager.health(),
        }
