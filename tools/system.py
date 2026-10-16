"""
Meera - System Execution Tools (ACT Tier)
Shell command execution guarded by security policy and confirmation tokens.
"""
from pathlib import Path
import subprocess
import time
from typing import Optional

from config.settings import BASE_DIR
from permissions.policy import PermissionTier, SecurityPolicy
from tools.base import BaseTool, ToolResult


class RunCommandTool(BaseTool):
    """
    Executes shell commands on the host machine.
    Requires explicit user authorization under the ACT tier.
    """

    def __init__(self, policy: Optional[SecurityPolicy] = None, timeout_seconds: int = 15):
        super().__init__(
            name="run_command",
            description="Execute a shell or PowerShell command on host machine (requires ACT confirmation)",
            tier=PermissionTier.ACT,
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The exact shell command line string to run"},
                },
                "required": ["command"],
            },
        )
        self.policy = policy or SecurityPolicy()
        self.timeout_seconds = timeout_seconds

    def execute(self, command: str, **kwargs) -> ToolResult:
        start_time = time.perf_counter()

        if not self.policy.is_command_safe(command):
            return ToolResult(
                success=False,
                output="",
                error=f"Command rejected: contains blocked destructive patterns.",
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )

        try:
            # Run in PowerShell on Windows
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", command],
                cwd=str(self.policy.workspace_root),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )

            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()
            elapsed_ms = (time.perf_counter() - start_time) * 1000

            if proc.returncode == 0:
                output = stdout if stdout else "(Command executed successfully with no output)"
                return ToolResult(
                    success=True,
                    output=output,
                    execution_time_ms=elapsed_ms,
                    metadata={"returncode": proc.returncode},
                )
            else:
                combined = f"{stdout}\n{stderr}".strip()
                return ToolResult(
                    success=False,
                    output=combined,
                    error=f"Command exited with return code {proc.returncode}: {stderr}",
                    execution_time_ms=elapsed_ms,
                    metadata={"returncode": proc.returncode},
                )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"Command timed out after {self.timeout_seconds} seconds.",
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Command failed to launch: {str(e)}",
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )
