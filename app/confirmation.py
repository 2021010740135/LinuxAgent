from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import secrets
import threading
from typing import Any

from app.exceptions import TaskExpiredException, TaskNotFoundException


@dataclass(slots=True)
class PendingAction:
    task_id: str
    created_at: datetime
    expire_at: datetime
    action_name: str
    command: str
    command_preview: str
    sudo: bool
    timeout_seconds: int
    risk_level: str
    risk_category: str
    reason: str
    explanation: str
    arguments: dict[str, Any]

    @property
    def ttl_seconds(self) -> int:
        remaining = int((self.expire_at - datetime.now(timezone.utc)).total_seconds())
        return max(0, remaining)


class ConfirmationManager:
    def __init__(self, ttl_minutes: int) -> None:
        self._ttl = timedelta(minutes=ttl_minutes)
        self._pending: dict[str, PendingAction] = {}
        self._lock = threading.Lock()

    def create(
        self,
        *,
        action_name: str,
        command: str,
        command_preview: str,
        sudo: bool,
        timeout_seconds: int,
        risk_level: str,
        risk_category: str,
        reason: str,
        explanation: str,
        arguments: dict[str, Any],
    ) -> PendingAction:
        with self._lock:
            now = datetime.now(timezone.utc)
            self._cleanup_locked(now)
            task_id = self._generate_task_id_locked()
            action = PendingAction(
                task_id=task_id,
                created_at=now,
                expire_at=now + self._ttl,
                action_name=action_name,
                command=command,
                command_preview=command_preview,
                sudo=sudo,
                timeout_seconds=timeout_seconds,
                risk_level=risk_level,
                risk_category=risk_category,
                reason=reason,
                explanation=explanation,
                arguments=arguments,
            )
            self._pending[task_id] = action
            return action

    def peek(self, task_id: str = "latest") -> PendingAction | None:
        with self._lock:
            now = datetime.now(timezone.utc)
            self._cleanup_locked(now)
            try:
                return self._resolve_action_locked(task_id, now)
            except (TaskNotFoundException, TaskExpiredException):
                return None

    def require(self, task_id: str = "latest") -> PendingAction:
        with self._lock:
            now = datetime.now(timezone.utc)
            return self._resolve_action_locked(task_id, now)

    def consume(self, task_id: str = "latest") -> PendingAction:
        with self._lock:
            now = datetime.now(timezone.utc)
            action = self._resolve_action_locked(task_id, now)
            return self._pending.pop(action.task_id)

    def cancel(self, task_id: str = "latest") -> PendingAction:
        return self.consume(task_id)

    def remove(self, task_id: str) -> PendingAction | None:
        with self._lock:
            normalized_task_id = self._normalize_task_id(task_id)
            return self._pending.pop(normalized_task_id, None)

    def clear_all(self) -> list[PendingAction]:
        with self._lock:
            now = datetime.now(timezone.utc)
            self._cleanup_locked(now)
            actions = list(self._pending.values())
            self._pending.clear()
            return actions

    def list_pending(self) -> list[PendingAction]:
        with self._lock:
            now = datetime.now(timezone.utc)
            self._cleanup_locked(now)
            return sorted(
                self._pending.values(),
                key=lambda action: action.created_at,
                reverse=True,
            )

    def _resolve_action_locked(self, task_id: str, now: datetime) -> PendingAction:
        if task_id.strip().lower() == "latest":
            self._cleanup_locked(now)
            if not self._pending:
                raise TaskNotFoundException("latest")
            return max(
                self._pending.values(),
                key=lambda action: action.created_at,
            )

        normalized_task_id = self._normalize_task_id(task_id)
        action = self._pending.get(normalized_task_id)
        if action is None:
            self._cleanup_locked(now)
            raise TaskNotFoundException(normalized_task_id)
        if now > action.expire_at:
            self._pending.pop(normalized_task_id, None)
            raise TaskExpiredException(normalized_task_id)
        self._cleanup_locked(now)
        return action

    @staticmethod
    def _normalize_task_id(task_id: str) -> str:
        candidate = task_id.strip()
        prefix, separator, suffix = candidate.partition("-")
        if not separator or not suffix:
            return candidate
        return f"Task-{suffix.upper()}"

    def _cleanup_locked(self, now: datetime) -> None:
        expired_task_ids = [
            task_id
            for task_id, action in self._pending.items()
            if now > action.expire_at
        ]
        for task_id in expired_task_ids:
            self._pending.pop(task_id, None)

    def _generate_task_id_locked(self) -> str:
        while True:
            task_id = f"Task-{secrets.token_hex(2).upper()}"
            if task_id not in self._pending:
                return task_id
