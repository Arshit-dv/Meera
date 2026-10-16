"""
Meera - Security & Workspace Policy
Enforces dedicated workspace sandbox boundaries, protected path isolation,
and command safety.
"""
from enum import Enum
from pathlib import Path
import re
from typing import List, Optional, Set

from config.settings import BASE_DIR, WORKSPACE_DIR


class PermissionTier(str, Enum):
    READ = "READ"          # Autonomous filesystem & telemetry inspection
    PREPARE = "PREPARE"    # Sandboxed computational scratchpad
    ACT = "ACT"            # System command & state-altering execution (requires approval)


# Dangerous command patterns blocked from execution
BLOCKED_PATTERNS = [
    r"\brmdir\s+/[sS]",
    r"\bdel\s+/[fF]\s+/[sS]",
    r"\bformat\s+[a-zA-Z]:",
    r"\bdiskpart\b",
    r"\breg\s+delete\b",
    r"\bshutdown\b",
    r"\bStop-Computer\b",
    r"\bRestart-Computer\b",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;",  # Fork bomb
]

# Protected internal system files & folders strictly isolated from agent access
PROTECTED_TARGETS = {
    "agents.md",
    "models",
    "runtime",
    "storage",
    ".git",
    ".gitignore",
    ".env",
    "config",
    "agent",
    "api",
}


class SecurityPolicy:
    """
    Validates filesystem paths and terminal command operations
    to protect host system stability and internal architecture specs.
    """

    def __init__(self, workspace_root: Optional[Path] = None):
        # Default workspace is the dedicated isolated workspace/ directory
        self.workspace_root = (workspace_root or WORKSPACE_DIR).resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self._auto_approved_tiers: Set[PermissionTier] = {
            PermissionTier.READ,
            PermissionTier.PREPARE,
        }
        self._require_confirmation_tier: PermissionTier = PermissionTier.ACT

    def is_path_within_workspace(self, path: Path) -> bool:
        """Ensures path resides strictly within the designated workspace root."""
        try:
            resolved = path.resolve()
            return str(resolved).startswith(str(self.workspace_root))
        except Exception:
            return False

    def is_protected_target(self, path: Path) -> bool:
        """Checks if path points to or traverses protected engine components or models."""
        for part in path.parts:
            if part.lower() in PROTECTED_TARGETS:
                return True
        return False

    def sanitize_path(self, relative_or_absolute: str) -> Optional[Path]:
        """
        Resolves path, ensures it is within workspace bounds,
        and guarantees no access to internal models or architectural files.
        """
        target = Path(relative_or_absolute)
        if not target.is_absolute():
            target = (self.workspace_root / target).resolve()
        else:
            target = target.resolve()

        # 1. Reject any access targeting protected files (models, AGENTS.md, runtime)
        if self.is_protected_target(target):
            return None

        # 2. Must reside strictly within the designated workspace sandbox
        if self.is_path_within_workspace(target):
            return target

        return None

    def is_command_safe(self, command: str) -> bool:
        """Checks if shell command matches blocked destructive patterns."""
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return False
        return True

    def requires_confirmation(self, tier: PermissionTier) -> bool:
        """Determines if the permission tier mandates explicit user approval."""
        return tier == self._require_confirmation_tier
