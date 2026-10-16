"""
Meera - Base Tool Architecture
Defines abstract contracts for tools, arguments, and execution results.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
import time
from typing import Any, Dict, Optional

from permissions.policy import PermissionTier


@dataclass
class ToolResult:
    success: bool
    output: str
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
            "metadata": self.metadata,
        }

    def __str__(self) -> str:
        if self.success:
            return self.output
        return f"[ERROR] {self.error or 'Tool execution failed'}"


class BaseTool(ABC):
    """
    Abstract contract for all Meera agent tools.
    Every tool specifies its permission tier (READ, PREPARE, ACT) and parameters schema.
    """

    def __init__(
        self,
        name: str,
        description: str,
        tier: PermissionTier,
        parameters: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.description = description
        self.tier = tier
        self.parameters = parameters or {"type": "object", "properties": {}}

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """Executes the tool logic with validated arguments."""
        pass

    def get_compact_schema(self) -> str:
        """Compact single-line schema string to conserve context tokens."""
        props = self.parameters.get("properties", {})
        param_list = []
        for p_name, p_info in props.items():
            p_type = p_info.get("type", "any")
            req = "*" if p_name in self.parameters.get("required", []) else ""
            param_list.append(f"{p_name}{req}:{p_type}")
        params_str = ", ".join(param_list)
        return f"[{self.tier.value}] {self.name}({params_str}) - {self.description}"
