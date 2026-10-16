"""
Meera - Skill Registry
Manages discovery, manual activation, and zero-overhead intent routing for specialized skills.
"""
import logging
from typing import Dict, List, Optional

from skills.academic import get_academic_skill
from skills.career import get_career_skill
from skills.coding import get_coding_skill
from skills.manifest import SkillManifest

logger = logging.getLogger("meera.skills.registry")


class SkillRegistry:
    """
    Central repository for Meera agent skills.
    Ensures zero token overhead when skills are dormant,
    and injects compact instructions only when a skill is active.
    """

    def __init__(self):
        self._skills: Dict[str, SkillManifest] = {}
        self._active_skill_id: Optional[str] = None
        self._register_default_skills()

    def _register_default_skills(self) -> None:
        self.register_skill(get_coding_skill())
        self.register_skill(get_academic_skill())
        self.register_skill(get_career_skill())

    def register_skill(self, skill: SkillManifest) -> None:
        self._skills[skill.id] = skill
        logger.debug(f"[SKILL] Registered '{skill.id}' ({skill.name})")

    def get_skill(self, skill_id: str) -> Optional[SkillManifest]:
        return self._skills.get(skill_id)

    def list_skills(self) -> List[SkillManifest]:
        res = []
        for s in self._skills.values():
            s.is_active = (s.id == self._active_skill_id)
            res.append(s)
        return res

    @property
    def active_skill(self) -> Optional[SkillManifest]:
        if self._active_skill_id and self._active_skill_id in self._skills:
            return self._skills[self._active_skill_id]
        return None

    def activate_skill(self, skill_id: Optional[str]) -> bool:
        """Sets the active skill, or clears active skill if None/empty."""
        if not skill_id or skill_id == "none":
            self._active_skill_id = None
            logger.info("[SKILL] Deactivated active skill (reverted to baseline)")
            return True

        if skill_id in self._skills:
            self._active_skill_id = skill_id
            logger.info(f"[SKILL] Activated skill '{skill_id}'")
            return True

        return False

    def auto_detect_skill(self, user_query: str) -> Optional[SkillManifest]:
        """
        Lightweight keyword match to auto-route queries to specialized skills
        if no skill was explicitly locked by the user.
        """
        if self._active_skill_id:
            return self.active_skill

        query_lower = user_query.lower()
        best_match: Optional[SkillManifest] = None
        best_score = 0

        for skill in self._skills.values():
            score = sum(1 for kw in skill.keywords if kw in query_lower)
            if score > best_score:
                best_score = score
                best_match = skill

        # Threshold of at least 2 matching domain keywords for auto-routing
        if best_score >= 2:
            return best_match
        return None

    def get_prompt_extension(self, user_query: Optional[str] = None) -> str:
        """
        Returns compact prompt extension for the active or auto-detected skill.
        Consumes zero tokens if no skill is active.
        """
        skill = self.active_skill
        if not skill and user_query:
            skill = self.auto_detect_skill(user_query)

        if skill:
            return f"\n\n{skill.system_prompt_extension}"
        return ""
