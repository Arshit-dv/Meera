"""
Meera - Filesystem Inspection Tools (READ Tier)
Autonomous, safe inspection of directory contents and text files within workspace.
"""
from pathlib import Path
import re
import time
from typing import Any, Dict, Optional

from config.settings import BASE_DIR
from permissions.policy import PermissionTier, SecurityPolicy
from tools.base import BaseTool, ToolResult


class ListDirectoryTool(BaseTool):
    """Lists contents of a directory within the workspace."""

    def __init__(self, policy: Optional[SecurityPolicy] = None):
        super().__init__(
            name="list_directory",
            description="List files and folders in a relative workspace directory",
            tier=PermissionTier.READ,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to directory (default '.')"},
                },
                "required": [],
            },
        )
        self.policy = policy or SecurityPolicy()

    def execute(self, path: str = ".", **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        target = self.policy.sanitize_path(path)
        if not target or not target.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"Path '{path}' not found or outside authorized workspace",
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )

        if not target.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Path '{path}' is not a directory",
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )

        entries = []
        try:
            for item in sorted(target.iterdir()):
                # Skip hidden git or cache
                if item.name.startswith((".", "__pycache__")):
                    continue
                type_flag = "[DIR]" if item.is_dir() else "[FILE]"
                size_str = f" ({item.stat().st_size} bytes)" if item.is_file() else ""
                entries.append(f"{type_flag} {item.name}{size_str}")

            output = f"Directory listing for '{path}':\n" + "\n".join(entries if entries else ["(empty directory)"])
            return ToolResult(
                success=True,
                output=output,
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )


class ReadFileTool(BaseTool):
    """Safely reads file contents within the workspace with line limits."""

    def __init__(self, policy: Optional[SecurityPolicy] = None):
        super().__init__(
            name="read_file",
            description="Read content of a text file inside workspace (up to max_lines)",
            tier=PermissionTier.READ,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"},
                    "max_lines": {"type": "integer", "description": "Maximum lines to read (default 100)"},
                },
                "required": ["path"],
            },
        )
        self.policy = policy or SecurityPolicy()

    def execute(self, path: str, max_lines: int = 100, **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        target = self.policy.sanitize_path(path)
        if not target or not target.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"File '{path}' not found or outside authorized workspace",
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )

        if not target.is_file():
            return ToolResult(
                success=False,
                output="",
                error=f"Path '{path}' is not a file",
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )

        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                lines = [f.readline() for _ in range(max_lines)]
            # Filter empty lines at EOF
            content = "".join([l for l in lines if l])
            total_chars = len(content)
            output = f"File content '{path}' (read {len(lines)} lines, {total_chars} chars):\n\n{content}"
            return ToolResult(
                success=True,
                output=output,
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )


class SearchFilesTool(BaseTool):
    """Searches workspace files for a text pattern."""

    def __init__(self, policy: Optional[SecurityPolicy] = None):
        super().__init__(
            name="search_files",
            description="Search text or pattern across files in workspace",
            tier=PermissionTier.READ,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search pattern or string"},
                    "extension": {"type": "string", "description": "File extension to filter (e.g. '.py')"},
                },
                "required": ["query"],
            },
        )
        self.policy = policy or SecurityPolicy()

    def execute(self, query: str, extension: str = "", **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        matches = []
        try:
            pattern = re.compile(query, re.IGNORECASE)
            root = self.policy.workspace_root
            for p in root.rglob("*"):
                # Skip virtualenvs, git, cache, models, runtime
                if any(ignored in p.parts for ignored in (".git", "__pycache__", "models", "runtime", "storage", ".gemini")):
                    continue
                if p.is_file():
                    if extension and not p.name.endswith(extension):
                        continue
                    try:
                        with open(p, "r", encoding="utf-8", errors="ignore") as f:
                            for idx, line in enumerate(f, 1):
                                if pattern.search(line):
                                    rel = p.relative_to(root)
                                    matches.append(f"{rel}:{idx} {line.strip()[:100]}")
                                    if len(matches) >= 20:
                                        break
                    except Exception:
                        pass
                if len(matches) >= 20:
                    break

            output = f"Search results for '{query}' ({len(matches)} matches):\n" + "\n".join(matches if matches else ["No matches found."])
            return ToolResult(
                success=True,
                output=output,
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
            )
