"""
Meera - Skill Manifest Architecture
Defines compact, resource-conscious contracts for specialized agent skills.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SkillManifest:
    """
    Lightweight specification for a specialized Meera skill.
    Keeps token footprint minimal (~60-80 tokens) under the 1024 context ceiling.
    """
    id: str
    name: str
    description: str
    system_prompt_extension: str
    keywords: List[str] = field(default_factory=list)
    recommended_tools: List[str] = field(default_factory=list)
    example_prompts: List[str] = field(default_factory=list)
    is_active: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "keywords": self.keywords,
            "recommended_tools": self.recommended_tools,
            "example_prompts": self.example_prompts,
            "is_active": self.is_active,
        }
