from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


class AuditStore:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _initialize(self) -> None:
        with sqlite3.connect(self._database_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    category TEXT NOT NULL,
                    action_name TEXT NOT NULL,
                    target_host TEXT,
                    decision TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    command_preview TEXT,
                    metadata_json TEXT,
                    exit_status INTEGER,
                    stdout TEXT,
                    stderr TEXT
                )
                """
            )

    def record(
        self,
        *,
        category: str,
        action_name: str,
        target_host: str,
        decision: str,
        risk_level: str,
        command_preview: str | None = None,
        metadata: dict[str, Any] | None = None,
        exit_status: int | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
    ) -> None:
        payload = json.dumps(metadata or {}, ensure_ascii=False)
        with sqlite3.connect(self._database_path) as connection:
            connection.execute(
                """
                INSERT INTO audit_events (
                    created_at,
                    category,
                    action_name,
                    target_host,
                    decision,
                    risk_level,
                    command_preview,
                    metadata_json,
                    exit_status,
                    stdout,
                    stderr
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    category,
                    action_name,
                    target_host,
                    decision,
                    risk_level,
                    command_preview,
                    payload,
                    exit_status,
                    stdout,
                    stderr,
                ),
            )
