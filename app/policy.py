from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import yaml


USERNAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    disposition: str
    risk_level: str
    risk_category: str
    reason: str
    explanation: str
    requires_confirmation: bool = False
    evidence: tuple[str, ...] = field(default_factory=tuple)


class PolicyEngine:
    def __init__(self, rules_path: Path, tool_policies_path: Path) -> None:
        self._rules = self._load_yaml(rules_path)
        self._tool_policies = self._load_yaml(tool_policies_path)
        self._blocked_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self._rules.get("blocked_command_patterns", [])
        ]
        self._protected_users = set(self._rules.get("protected_users", []))
        self._blocked_search_roots = tuple(self._rules.get("blocked_search_roots", []))
        self._sensitive_write_roots = tuple(self._rules.get("sensitive_write_roots", []))
        self._write_like_actions = set(self._rules.get("write_like_actions", []))
        self._dangerous_intent_rules = [
            {
                **rule,
                "pattern": re.compile(rule["pattern"], re.IGNORECASE),
            }
            for rule in self._rules.get("dangerous_intent_rules", [])
            if isinstance(rule, dict) and rule.get("pattern")
        ]

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"Policy file not found: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Policy file must contain a mapping: {path}")
        return data

    def evaluate_action(
        self,
        *,
        action_name: str,
        command_preview: str,
        arguments: dict[str, Any],
    ) -> PolicyDecision:
        tool_policy = self._tool_policies.get(action_name, {})
        risk_level = str(tool_policy.get("risk", "low"))
        risk_category = str(tool_policy.get("category", "general_operation"))
        requires_confirmation = bool(tool_policy.get("requires_confirmation", False))

        for blocked_pattern in self._blocked_patterns:
            if blocked_pattern.search(command_preview):
                return PolicyDecision(
                    disposition="block",
                    risk_level="critical",
                    risk_category="dangerous_system_command",
                    reason="Command matched a dangerous system pattern.",
                    explanation=(
                        "This operation matches a destructive command pattern and "
                        "has been blocked for safety."
                    ),
                    evidence=(blocked_pattern.pattern,),
                )

        if action_name in {"create_user", "delete_user"}:
            username = str(arguments.get("username", "")).strip()
            if not USERNAME_PATTERN.fullmatch(username):
                return PolicyDecision(
                    disposition="block",
                    risk_level=risk_level,
                    risk_category="invalid_account_target",
                    reason="Username does not match Linux account naming rules.",
                    explanation=(
                        "The target account name is invalid, so the action has been blocked "
                        "to avoid accidental system changes."
                    ),
                    evidence=(username,),
                )
            if username in self._protected_users:
                return PolicyDecision(
                    disposition="block",
                    risk_level="critical",
                    risk_category="protected_account_change",
                    reason="Target account is protected by policy.",
                    explanation=(
                        "Protected system accounts cannot be modified through this agent."
                    ),
                    evidence=(username,),
                )
            if action_name == "delete_user":
                return PolicyDecision(
                    disposition="warn",
                    risk_level="high",
                    risk_category="user_privilege_change",
                    reason="Deleting users can impact access and ownership.",
                    explanation=(
                        "This action changes account state and may affect permissions. "
                        "Second confirmation is required."
                    ),
                    requires_confirmation=True,
                    evidence=(username,),
                )
            return PolicyDecision(
                disposition="warn",
                risk_level="high",
                risk_category="user_privilege_change",
                reason="Creating a user introduces a new access principal.",
                explanation=(
                    "This is a sensitive account operation and requires second confirmation."
                ),
                requires_confirmation=True,
                evidence=(username,),
            )

        path_values = self._extract_path_arguments(arguments)
        normalized_paths = tuple(
            self._normalize_remote_path(path_value)
            for path_value in path_values
            if path_value
        )
        normalized_path = normalized_paths[0] if normalized_paths else ""

        if action_name == "search_file":
            if self._is_blocked_search_path(normalized_path):
                return PolicyDecision(
                    disposition="block",
                    risk_level=risk_level,
                    risk_category="restricted_path_scan",
                    reason="Target path is a restricted system path.",
                    explanation=(
                        "Scanning dynamic system paths such as /proc, /sys, /dev, or /run "
                        "is blocked."
                    ),
                    evidence=(normalized_path,),
                )
            if normalized_path == "/" and bool(arguments.get("recursive", False)):
                return PolicyDecision(
                    disposition="block",
                    risk_level="high",
                    risk_category="overscoped_operation",
                    reason="Recursive scan on root path is overscoped.",
                    explanation=(
                        "Recursive scan on '/' may expose sensitive data and impact performance."
                    ),
                    evidence=(normalized_path,),
                )
            return PolicyDecision(
                disposition="allow",
                risk_level=risk_level,
                risk_category="read_only_query",
                reason="Read-only query with bounded output.",
                explanation="Search operation is allowed under bounded result limits.",
                evidence=(normalized_path or ".",),
            )

        if normalized_paths and action_name in self._write_like_actions:
            hit_sensitive_paths = tuple(
                path for path in normalized_paths if self._is_sensitive_write_path(path)
            )
            if hit_sensitive_paths:
                return PolicyDecision(
                    disposition="block",
                    risk_level="critical",
                    risk_category="core_path_modification",
                    reason="Write-like operation targets protected core system path.",
                    explanation=(
                        "Writes or deletes in protected paths (/etc, /boot, /bin, /var/log, etc.) "
                        "are blocked."
                    ),
                    evidence=hit_sensitive_paths,
                )

        if action_name == "rename_file" and bool(arguments.get("overwrite", False)):
            return PolicyDecision(
                disposition="warn",
                risk_level="high",
                risk_category="filesystem_overwrite",
                reason="Rename with overwrite can replace existing files.",
                explanation=(
                    "Overwrite behavior may cause data loss. Second confirmation is required."
                ),
                requires_confirmation=True,
                evidence=normalized_paths or ("rename_file",),
            )

        return PolicyDecision(
            disposition="allow",
            risk_level=risk_level,
            risk_category=risk_category,
            reason="Structured parameter review passed.",
            explanation="No policy redline was hit for this operation.",
            requires_confirmation=requires_confirmation,
        )

    def review_user_intent(self, user_input: str) -> PolicyDecision | None:
        for rule in self._dangerous_intent_rules:
            if rule["pattern"].search(user_input):
                return PolicyDecision(
                    disposition=str(rule.get("disposition", "block")),
                    risk_level=str(rule.get("risk_level", "critical")),
                    risk_category=str(rule.get("category", "malicious_intent")),
                    reason=str(rule.get("reason", "Detected high-risk intent.")),
                    explanation=str(
                        rule.get(
                            "explanation",
                            "Only legitimate, auditable operations are allowed.",
                        )
                    ),
                    evidence=(rule["pattern"].pattern,),
                )
        return None

    @staticmethod
    def _extract_path_argument(arguments: dict[str, Any]) -> str:
        for value in PolicyEngine._extract_path_arguments(arguments):
            return value
        return ""

    @staticmethod
    def _extract_path_arguments(arguments: dict[str, Any]) -> tuple[str, ...]:
        keys = (
            "path",
            "target_path",
            "file_path",
            "directory",
            "source_path",
            "destination_path",
            "parent_path",
        )
        seen: set[str] = set()
        results: list[str] = []
        for key in keys:
            value = arguments.get(key)
            if not isinstance(value, str):
                continue
            candidate = value.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            results.append(candidate)
        return tuple(results)

    @staticmethod
    def _normalize_remote_path(raw_path: str) -> str:
        if not raw_path:
            return "."
        value = raw_path.replace("\\", "/")
        while "//" in value:
            value = value.replace("//", "/")
        return value

    def _is_blocked_search_path(self, normalized_path: str) -> bool:
        return any(
            normalized_path == root or normalized_path.startswith(f"{root}/")
            for root in self._blocked_search_roots
        )

    def _is_sensitive_write_path(self, normalized_path: str) -> bool:
        return any(
            normalized_path == root or normalized_path.startswith(f"{root}/")
            for root in self._sensitive_write_roots
        )
