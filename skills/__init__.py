"""
Meera - Skills Package
Skills engine, background task scheduler, and multi-agent orchestration.
"""
from skills.academic import get_academic_skill
from skills.career import get_career_skill
from skills.coding import get_coding_skill
from skills.manifest import SkillManifest
from skills.orchestrator import MultiAgentOrchestrator, SubAgent, SubAgentTask
from skills.registry import SkillRegistry
from skills.scheduler import ScheduledTask, TaskScheduler

__all__ = [
    "SkillManifest",
    "SkillRegistry",
    "TaskScheduler",
    "ScheduledTask",
    "SubAgent",
    "SubAgentTask",
    "MultiAgentOrchestrator",
    "get_coding_skill",
    "get_academic_skill",
    "get_career_skill",
]
