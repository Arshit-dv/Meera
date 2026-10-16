"""
Meera - Tool Registry & Execution Dispatcher
Coordinates tool discovery, compact prompt schema generation,
call parsing, and permission-guarded execution.
"""
import ast
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from permissions.manager import PermissionManager
from permissions.policy import PermissionTier
from tools.base import BaseTool, ToolResult
from tools.computational import PythonEvalTool
from tools.filesystem import ListDirectoryTool, ReadFileTool, SearchFilesTool
from tools.system import RunCommandTool

logger = logging.getLogger("meera.tools.registry")


class ToolRegistry:
    """
    Central repository of tools available to Meera.
    Enforces permission guardrails and parses tool invocations from LLM outputs.
    """

    def __init__(self, permission_manager: Optional[PermissionManager] = None):
        self.permission_manager = permission_manager or PermissionManager()
        self._tools: Dict[str, BaseTool] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Initializes core default tools across READ, PREPARE, and ACT tiers."""
        self.register_tool(ListDirectoryTool(self.permission_manager.policy))
        self.register_tool(ReadFileTool(self.permission_manager.policy))
        self.register_tool(SearchFilesTool(self.permission_manager.policy))
        self.register_tool(PythonEvalTool())
        self.register_tool(RunCommandTool(self.permission_manager.policy))

    def register_tool(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool
        logger.debug(f"[TOOL] Registered '{tool.name}' [{tool.tier.value}]")

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_tools(self) -> List[BaseTool]:
        return list(self._tools.values())

    def get_prompt_schema(self) -> str:
        """
        Generates a token-compact schema string tailored for the 1024-token budget.
        """
        lines = ["[AVAILABLE TOOLS]"]
        for tool in self._tools.values():
            lines.append(f"- {tool.get_compact_schema()}")
        lines.append("\nTo use a tool, respond with: [TOOL: tool_name(arg_name=\"value\")]")
        return "\n".join(lines)

    def parse_tool_call(self, text: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Parses tool invocations from text. Supports:
        1. [TOOL: tool_name(key="val", count=10)]
        2. ```json {"tool": "name", "arguments": {...}} ```
        """
        # Pattern 1: [TOOL: name(args)]
        call_match = re.search(r"\[TOOL:\s*([a-zA-Z0-9_]+)\s*\((.*?)\)\]", text, re.DOTALL)
        if call_match:
            tool_name = call_match.group(1).strip()
            raw_args = call_match.group(2).strip()
            args: Dict[str, Any] = {}

            if raw_args:
                # Parse keyword arguments e.g. path="config/settings.py", max_lines=50
                arg_pattern = re.finditer(r'([a-zA-Z0-9_]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([0-9\.]+)|([a-zA-Z0-9_]+))', raw_args)
                for m in arg_pattern:
                    k = m.group(1)
                    v = m.group(2) if m.group(2) is not None else m.group(3)
                    if v is None:
                        val_raw = m.group(4) or m.group(5)
                        try:
                            if "." in val_raw:
                                v = float(val_raw)
                            elif val_raw.isdigit():
                                v = int(val_raw)
                            elif val_raw.lower() in ("true", "false"):
                                v = val_raw.lower() == "true"
                            else:
                                v = val_raw
                        except Exception:
                            v = val_raw
                    args[k] = v

                # Fallback for single positional string argument e.g. [TOOL: read_file("main.py")]
                if not args and raw_args.strip().startswith(('"', "'")):
                    clean_str = raw_args.strip().strip('"\'')
                    tool = self.get_tool(tool_name)
                    if tool and tool.parameters.get("required"):
                        first_req = tool.parameters["required"][0]
                        args[first_req] = clean_str

            return tool_name, args

        # Pattern 2: JSON block
        json_match = re.search(r'```(?:json)?\s*(\{\s*"tool":\s*"[^"]+".*?\})\s*```', text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                return data.get("tool"), data.get("arguments", {})
            except Exception:
                pass

        return None

    def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        confirmation_token: Optional[str] = None,
    ) -> ToolResult:
        """
        Validates permissions through PermissionManager and executes the tool.
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                output="",
                error=f"Tool '{tool_name}' is not recognized in Meera tool registry.",
            )

        # 1. Authorize execution via PermissionManager
        authorized, reason = self.permission_manager.authorize(
            tier=tool.tier,
            tool_name=tool_name,
            arguments=arguments,
            confirmation_token=confirmation_token,
        )

        if not authorized:
            return ToolResult(
                success=False,
                output="",
                error=reason,
                metadata={"permission_denied": True, "tier": tool.tier.value},
            )

        # 2. Execute tool
        try:
            return tool.execute(**arguments)
        except Exception as e:
            logger.error(f"[TOOL] Exception executing '{tool_name}': {e}")
            return ToolResult(
                success=False,
                output="",
                error=f"Execution error: {str(e)}",
            )
