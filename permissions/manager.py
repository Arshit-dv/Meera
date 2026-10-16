"""
Meera - Permission Manager
Enforces three-tier permission guards (READ, PREPARE, ACT) and handles
explicit confirmation tokens for state-altering actions.
Zero third-party dependencies.
"""
from dataclasses import dataclass, field
import logging
import time
from typing import Any, Dict, Optional, Tuple
import uuid

from permissions.policy import PermissionTier, SecurityPolicy

logger = logging.getLogger("meera.permissions.manager")


@dataclass
class PendingAction:
    token: str
    tool_name: str
    arguments: Dict[str, Any]
    created_at: float = field(default_factory=time.time)
    status: str = "pending"  # pending, approved, denied, expired


class PermissionManager:
    """
    Coordinates permission tier evaluation and confirmation token lifecycle.
    """

    def __init__(self, policy: Optional[SecurityPolicy] = None, auto_approve_act: bool = False):
        self.policy = policy or SecurityPolicy()
        self.auto_approve_act = auto_approve_act
        self._pending_actions: Dict[str, PendingAction] = {}

    def authorize(
        self,
        tier: PermissionTier,
        tool_name: str,
        arguments: Dict[str, Any],
        confirmation_token: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Evaluates tool execution clearance based on tier and parameters.
        Returns (is_authorized, reason_or_token).
        """
        # 1. READ Tier (Autonomous filesystem inspection)
        if tier == PermissionTier.READ:
            # Check path boundaries if path argument is present
            path_arg = arguments.get("path") or arguments.get("file_path") or arguments.get("directory")
            if path_arg:
                safe_path = self.policy.sanitize_path(str(path_arg))
                if not safe_path:
                    logger.warning(f"[PERM] Denied READ for path outside workspace: {path_arg}")
                    return False, f"Access denied: path '{path_arg}' is outside the authorized workspace."
            return True, "Autonomous READ authorized."

        # 2. PREPARE Tier (Sandboxed computational scratchpad)
        if tier == PermissionTier.PREPARE:
            return True, "Autonomous PREPARE computational scratchpad authorized."

        # 3. ACT Tier (Shell commands & destructive mutations)
        if tier == PermissionTier.ACT:
            cmd = arguments.get("command") or ""
            if cmd and not self.policy.is_command_safe(str(cmd)):
                logger.warning(f"[PERM] Blocked dangerous command: {cmd}")
                return False, f"Command rejected: contains blocked destructive patterns."

            if self.auto_approve_act:
                return True, "ACT execution authorized by runtime auto-approval policy."

            # Verify if provided token was explicitly approved
            if confirmation_token:
                pending = self._pending_actions.get(confirmation_token)
                if pending and pending.status == "approved" and pending.tool_name == tool_name:
                    del self._pending_actions[confirmation_token]
                    return True, "Action approved with valid confirmation token."
                elif pending and pending.status == "denied":
                    del self._pending_actions[confirmation_token]
                    return False, "Action was explicitly denied by user."
                else:
                    return False, "Invalid, unapproved, or expired confirmation token."

            # Create new confirmation request
            token = self._create_pending_action(tool_name, arguments)
            logger.info(f"[PERM] ACT action requires confirmation. Generated token: {token}")
            return False, f"CONFIRMATION_REQUIRED: Action requires explicit user approval. Token: {token}"

        return False, "Unknown permission tier."

    def _create_pending_action(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        token = f"act_{uuid.uuid4().hex[:8]}"
        self._pending_actions[token] = PendingAction(
            token=token,
            tool_name=tool_name,
            arguments=arguments,
        )
        return token

    def approve_action(self, token: str) -> bool:
        """Approves a pending confirmation token."""
        if token in self._pending_actions:
            self._pending_actions[token].status = "approved"
            return True
        return False

    def deny_action(self, token: str) -> bool:
        """Denies and revokes a pending confirmation token."""
        if token in self._pending_actions:
            self._pending_actions[token].status = "denied"
            return True
        return False

    def get_pending_action(self, token: str) -> Optional[PendingAction]:
        return self._pending_actions.get(token)

    def list_pending_actions(self) -> Dict[str, Dict[str, Any]]:
        return {
            t: {
                "token": a.token,
                "tool_name": a.tool_name,
                "arguments": a.arguments,
                "created_at": a.created_at,
                "status": a.status,
            }
            for t, a in self._pending_actions.items()
        }
