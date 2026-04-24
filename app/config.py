from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    return int(value.strip())


def _resolve_path(root_dir: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return (root_dir / candidate).resolve()


@dataclass(frozen=True, slots=True)
class AppSettings:
    root_dir: Path
    app_name: str
    app_env: str
    debug: bool
    database_path: Path
    policy_rules_path: Path
    tool_policies_path: Path
    confirmation_ttl_minutes: int
    execution_mode: str
    default_target_host: str
    ssh_host: str
    ssh_port: int
    ssh_username: str
    ssh_password: str
    ssh_private_key_path: Path | None
    ssh_strict_host_key: bool
    sudo_password: str
    mysql_enabled: bool
    mysql_host: str
    mysql_port: int
    mysql_database: str
    mysql_user: str
    mysql_password: str
    mysql_charset: str
    llm_enabled: bool
    llm_model: str
    llm_base_url: str
    llm_api_key: str

    @property
    def is_dry_run(self) -> bool:
        return self.execution_mode.lower() == "dry_run"

    @classmethod
    def load(cls, env_file: str = ".env") -> "AppSettings":
        root_dir = Path(__file__).resolve().parents[1]
        load_dotenv(root_dir / env_file)

        private_key = os.getenv("AGENT_SSH_PRIVATE_KEY_PATH", "").strip()
        private_key_path = _resolve_path(root_dir, private_key) if private_key else None

        return cls(
            root_dir=root_dir,
            app_name=os.getenv("AGENT_APP_NAME", "Controlled Linux Server Agent"),
            app_env=os.getenv("AGENT_APP_ENV", "development"),
            debug=_parse_bool(os.getenv("AGENT_DEBUG"), default=False),
            database_path=_resolve_path(
                root_dir,
                os.getenv("AGENT_DATABASE_PATH", "data/audit.sqlite3"),
            ),
            policy_rules_path=_resolve_path(
                root_dir,
                os.getenv("AGENT_POLICY_RULES_PATH", "app/config/policy_rules.yaml"),
            ),
            tool_policies_path=_resolve_path(
                root_dir,
                os.getenv("AGENT_TOOL_POLICIES_PATH", "app/config/tool_policies.yaml"),
            ),
            confirmation_ttl_minutes=_parse_int(
                os.getenv("AGENT_CONFIRMATION_TTL_MINUTES"),
                default=10,
            ),
            execution_mode=os.getenv("AGENT_EXECUTION_MODE", "dry_run"),
            default_target_host=os.getenv("AGENT_DEFAULT_TARGET_HOST", "linux-host"),
            ssh_host=os.getenv("AGENT_SSH_HOST", ""),
            ssh_port=_parse_int(os.getenv("AGENT_SSH_PORT"), default=22),
            ssh_username=os.getenv("AGENT_SSH_USERNAME", ""),
            ssh_password=os.getenv("AGENT_SSH_PASSWORD", ""),
            ssh_private_key_path=private_key_path,
            ssh_strict_host_key=_parse_bool(
                os.getenv("AGENT_SSH_STRICT_HOST_KEY"),
                default=True,
            ),
            sudo_password=os.getenv("AGENT_SUDO_PASSWORD", ""),
            mysql_enabled=_parse_bool(os.getenv("AGENT_MYSQL_ENABLED"), default=False),
            mysql_host=os.getenv("AGENT_MYSQL_HOST", "127.0.0.1"),
            mysql_port=_parse_int(os.getenv("AGENT_MYSQL_PORT"), default=3306),
            mysql_database=os.getenv("AGENT_MYSQL_DATABASE", ""),
            mysql_user=os.getenv("AGENT_MYSQL_USER", ""),
            mysql_password=os.getenv("AGENT_MYSQL_PASSWORD", ""),
            mysql_charset=os.getenv("AGENT_MYSQL_CHARSET", "utf8mb4"),
            llm_enabled=_parse_bool(os.getenv("AGENT_LLM_ENABLED"), default=False),
            llm_model=os.getenv("AGENT_LLM_MODEL", "deepseek-chat"),
            llm_base_url=os.getenv("AGENT_LLM_BASE_URL", "https://api.deepseek.com/v1"),
            llm_api_key=os.getenv(
                "AGENT_LLM_API_KEY",
                os.getenv("DEEPSEEK_API_KEY", ""),
            ),
        )
