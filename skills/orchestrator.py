"""
Meera - Multi-Agent Orchestration Protocol
Enables the primary agent to delegate complex sub-tasks to isolated, specialized sub-agents
with dedicated context windows, safeguarding against 1024-token budget overflow.
"""
from dataclasses import dataclass, field
import logging
import time
from typing import Any, Dict, List, Optional

from model.manager import ModelManager
from model.provider import ChatMessage, GenerationRequest
from permissions.manager import PermissionManager
from skills.manifest import SkillManifest
from tools.base import ToolResult
from tools.registry import ToolRegistry

logger = logging.getLogger("meera.skills.orchestrator")


@dataclass
class SubAgentTask:
    task_id: str
    role_name: str
    objective: str
    assigned_skill: Optional[SkillManifest] = None
    input_data: str = ""
    result: Optional[str] = None
    success: bool = False
    execution_time_ms: float = 0.0


class SubAgent:
    """
    Lightweight, isolated worker agent.
    Operates in an independent context window to protect the host VRAM budget.
    """

    def __init__(
        self,
        name: str,
        persona: str,
        model_manager: ModelManager,
        tool_registry: Optional[ToolRegistry] = None,
        skill: Optional[SkillManifest] = None,
    ):
        self.name = name
        self.persona = persona
        self.model_manager = model_manager
        self.tool_registry = tool_registry
        self.skill = skill

    def run_task(self, objective: str, input_data: str = "") -> str:
        """Executes a focused single-objective prompt within an isolated context."""
        start_time = time.perf_counter()

        system_prompt = f"You are a specialized Meera sub-agent: {self.name}.\nPersona: {self.persona}"
        if self.skill:
            system_prompt += f"\n{self.skill.system_prompt_extension}"

        tools_prompt = self.tool_registry.get_prompt_schema() if self.tool_registry else None
        if tools_prompt:
            system_prompt += f"\n\n{tools_prompt}"

        user_content = f"Objective: {objective}"
        if input_data:
            user_content += f"\nContext/Data: {input_data}"
        user_content += "\nProvide a concise, focused output."

        context = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_content),
        ]

        req = GenerationRequest(
            messages=context,
            temperature=0.3,
            max_tokens=350,
            stream=False,
        )

        resp = self.model_manager.generate(req)
        raw_output = resp.content.strip()

        # Handle tool call if needed
        if self.tool_registry:
            tool_call = self.tool_registry.parse_tool_call(raw_output)
            if tool_call:
                tool_name, args = tool_call
                tool_res = self.tool_registry.execute(tool_name, args)
                obs = tool_res.output if tool_res.success else tool_res.error

                context.append(ChatMessage(role="assistant", content=raw_output))
                context.append(ChatMessage(role="user", content=f"[OBSERVATION: {obs}] Formulate concise conclusion."))

                followup_req = GenerationRequest(messages=context, temperature=0.3, max_tokens=300, stream=False)
                followup_resp = self.model_manager.generate(followup_req)
                raw_output = followup_resp.content.strip() or obs

        logger.info(f"[ORCHESTRATOR] Sub-agent '{self.name}' completed task in {(time.perf_counter() - start_time)*1000:.1f}ms")
        return raw_output


class MultiAgentOrchestrator:
    """
    Coordinates sub-agent lifecycle and parallel/sequential execution.
    Synthesizes outputs into unified, high-density briefings.
    """

    def __init__(self, model_manager: ModelManager, tool_registry: Optional[ToolRegistry] = None):
        self.model_manager = model_manager
        self.tool_registry = tool_registry
        self._active_tasks: List[SubAgentTask] = []

    def create_subagent(
        self,
        name: str,
        persona: str,
        skill: Optional[SkillManifest] = None,
    ) -> SubAgent:
        return SubAgent(
            name=name,
            persona=persona,
            model_manager=self.model_manager,
            tool_registry=self.tool_registry,
            skill=skill,
        )

    def execute_plan(self, tasks: List[SubAgentTask]) -> Dict[str, str]:
        """Executes a list of sub-agent tasks and collects results."""
        results: Dict[str, str] = {}
        for task in tasks:
            start = time.perf_counter()
            subagent = self.create_subagent(
                name=task.role_name,
                persona=f"Specialist assigned to: {task.objective}",
                skill=task.assigned_skill,
            )
            try:
                task_output = subagent.run_task(task.objective, task.input_data)
                task.result = task_output
                task.success = True
                task.execution_time_ms = (time.perf_counter() - start) * 1000
                results[task.task_id] = task_output
            except Exception as e:
                logger.error(f"[ORCHESTRATOR] Task '{task.task_id}' failed: {e}")
                task.result = f"Failed: {str(e)}"
                task.success = False
                results[task.task_id] = f"Error: {str(e)}"

        return results

    def synthesize_results(self, user_goal: str, results: Dict[str, str]) -> str:
        """Synthesizes isolated sub-agent outputs into a coherent final response."""
        briefing_lines = [f"Goal: {user_goal}", "\n[Sub-Agent Findings]"]
        for task_id, res in results.items():
            briefing_lines.append(f"◈ {task_id}:\n{res}\n")

        prompt = "\n".join(briefing_lines) + "\nSynthesize these findings into a unified, high-level summary."

        req = GenerationRequest(
            messages=[
                ChatMessage(role="system", content="You are the Meera Primary Orchestrator. Deliver a unified executive synthesis."),
                ChatMessage(role="user", content=prompt),
            ],
            temperature=0.4,
            max_tokens=400,
            stream=False,
        )

        resp = self.model_manager.generate(req)
        return resp.content.strip()
