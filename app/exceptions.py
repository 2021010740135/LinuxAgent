from __future__ import annotations

from datetime import datetime
from typing import Any


class AgentSecurityException(Exception):
    """Base class for security workflow exceptions."""


class TaskNotFoundException(AgentSecurityException):
    def __init__(self, task_id: str) -> None:
        super().__init__(f"Task not found: {task_id}")
        self.task_id = task_id


class TaskExpiredException(AgentSecurityException):
    def __init__(self, task_id: str) -> None:
        super().__init__(f"Task expired: {task_id}")
        self.task_id = task_id


class SecurityBlockException(AgentSecurityException):
    def __init__(
        self,
        *,
        action_name: str,
        reason: str,
        explanation: str,
        risk_level: str,
        risk_category: str,
        tool_args: dict[str, Any],
        command_preview: str,
        task_id: str | None = None,
        expires_at: datetime | None = None,
        cached: bool = False,
        requires_confirmation: bool = False,
        evidence: tuple[str, ...] = (),
    ) -> None:
        super().__init__(reason)
        self.action_name = action_name
        self.reason = reason
        self.explanation = explanation
        self.risk_level = risk_level
        self.risk_category = risk_category
        self.tool_args = tool_args
        self.command_preview = command_preview
        self.task_id = task_id
        self.expires_at = expires_at
        self.cached = cached
        self.requires_confirmation = requires_confirmation
        self.evidence = evidence
