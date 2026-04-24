from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import json
import secrets
import shlex
from typing import Any

import pymysql

from app.audit import AuditStore
from app.config import AppSettings
from app.confirmation import ConfirmationManager, PendingAction
from app.exceptions import (
    SecurityBlockException,
    TaskExpiredException,
    TaskNotFoundException,
)
from app.policy import PolicyDecision, PolicyEngine
from app.ssh_executor import CommandResult, SSHExecutor


OPENAI_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "check_remote_connection",
            "description": "检查 SSH 到 Linux 服务器的连通性和基础环境。",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_context",
            "description": "获取远程 Linux 服务器的系统信息。",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_disk_usage",
            "description": "查询远程 Linux 服务器的磁盘使用情况。",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_file",
            "description": "搜索远程 Linux 服务器上的文件或目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "目标路径，例如 /home/zbc 或 /etc。",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "要匹配的文件名关键字，可以为空。",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["all", "dir", "file"],
                        "description": "搜索模式：all、dir、file。",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "是否递归搜索子目录。",
                    },
                },
                "required": ["path", "keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_process_list",
            "description": "查询远程 Linux 服务器的进程列表。",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_port_status",
            "description": "查询远程 Linux 服务器的端口占用情况。",
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_user",
            "description": "在远程 Linux 服务器上创建普通用户。该操作需要高风险挂起和二次确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Linux 用户名。"},
                    "pwd": {"type": "string", "description": "该用户的初始密码。"},
                },
                "required": ["username", "pwd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_user",
            "description": "删除远程 Linux 服务器上的普通用户。该操作需要高风险挂起和二次确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "Linux 用户名。"},
                },
                "required": ["username"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_folder",
            "description": "Create a folder on the remote Linux host.",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder_name": {
                        "type": "string",
                        "description": "Folder name to create.",
                    },
                    "parent_path": {
                        "type": "string",
                        "description": "Parent directory path. Default: current directory.",
                    },
                },
                "required": ["folder_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Create a text file on the remote Linux host.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_name": {
                        "type": "string",
                        "description": "File name to create.",
                    },
                    "parent_path": {
                        "type": "string",
                        "description": "Parent directory path. Default: current directory.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Initial file content.",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "Whether to overwrite when file already exists.",
                    },
                },
                "required": ["file_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file from the remote Linux host.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path of the file to read.",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "Max lines to return, default 120 and capped at 300.",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_file",
            "description": "Append text content to a file on the remote Linux host.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path of the file to append.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Text content to append.",
                    },
                    "create_if_missing": {
                        "type": "boolean",
                        "description": "Whether to create the file when it does not exist.",
                    },
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_file",
            "description": "Rename or move a file on the remote Linux host.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_path": {
                        "type": "string",
                        "description": "Current file path.",
                    },
                    "destination_path": {
                        "type": "string",
                        "description": "New file path.",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "Whether to overwrite destination when it exists.",
                    },
                },
                "required": ["source_path", "destination_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file on the remote Linux host. This action is high-risk and requires confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path of the file to delete.",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_action",
            "description": "确认指定 Task-ID 的高风险操作。必须由用户提供刚刚输入的 sudo 密码。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "待执行高风险任务的 Task-ID，例如 Task-A8F2。",
                    },
                    "sudo_password": {
                        "type": "string",
                        "description": "用户本人刚刚输入的 sudo 密码。",
                    },
                },
                "required": ["task_id", "sudo_password"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_action",
            "description": "取消指定 Task-ID 的高风险操作。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "待取消的 Task-ID。",
                    },
                },
                "required": ["task_id"],
            },
        },
    },
]


class LinuxServerToolService:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.audit = AuditStore(settings.database_path)
        self.policy = PolicyEngine(
            settings.policy_rules_path,
            settings.tool_policies_path,
        )
        self.confirmations = ConfirmationManager(settings.confirmation_ttl_minutes)
        self.executor = SSHExecutor(settings)
        self._dispatch_table: dict[str, Callable[..., str]] = {
            "check_remote_connection": self.check_remote_connection,
            "get_system_context": self.get_system_context,
            "get_disk_usage": self.get_disk_usage,
            "search_file": self.search_file,
            "get_process_list": self.get_process_list,
            "get_port_status": self.get_port_status,
            "create_user": self.create_user,
            "delete_user": self.delete_user,
            "create_folder": self.create_folder,
            "create_file": self.create_file,
            "read_file": self.read_file,
            "append_file": self.append_file,
            "rename_file": self.rename_file,
            "delete_file": self.delete_file,
            "confirm_action": self.confirm_action,
            "cancel_action": self.cancel_action,
        }

    def openai_tools(self) -> list[dict[str, Any]]:
        return OPENAI_TOOL_DEFINITIONS

    def dispatch(self, action_name: str, arguments: dict[str, Any]) -> str:
        handler = self._dispatch_table.get(action_name)
        if handler is None:
            raise ValueError(f"未知工具: {action_name}")
        return handler(**arguments)

    def review_user_intent(self, user_input: str) -> None:
        decision = self.policy.review_user_intent(user_input)
        if decision is None:
            return
        self.audit.record(
            category="policy",
            action_name="intent_review",
            target_host=self.settings.ssh_host,
            decision="blocked_intent",
            risk_level=decision.risk_level,
            command_preview=user_input,
            metadata={
                "risk_category": decision.risk_category,
                "reason": decision.reason,
                "evidence": list(decision.evidence),
            },
        )
        raise SecurityBlockException(
            action_name="intent_review",
            reason=decision.reason,
            explanation=decision.explanation,
            risk_level=decision.risk_level,
            risk_category=decision.risk_category,
            tool_args={"user_input": user_input},
            command_preview=user_input,
            cached=False,
            requires_confirmation=False,
            evidence=decision.evidence,
        )

    def check_environment(self, *, include_mysql: bool = True) -> str:
        sections = [
            f"应用: {self.settings.app_name}",
            f"环境: {self.settings.app_env}",
            f"执行模式: {self.settings.execution_mode}",
            f"目标主机: {self.settings.default_target_host} ({self.settings.ssh_host}:{self.settings.ssh_port})",
            "",
            "[SSH 检查]",
            self.check_remote_connection(),
        ]
        if include_mysql and self.settings.mysql_enabled:
            sections.extend(["", "[MySQL 检查]", self.check_mysql_connection()])
        return "\n".join(sections)

    def prompt_for_confirmation(self) -> str:
        pending_actions = self.confirmations.list_pending()
        if not pending_actions:
            raise TaskNotFoundException("latest")
        if len(pending_actions) == 1:
            action = pending_actions[0]
            return (
                f"检测到一个待确认的高危任务：{action.task_id}。\n"
                f"任务类型: {action.action_name}\n"
                f"风险说明: {action.reason}\n"
                f"请回复 `确认执行 {action.task_id}`，随后输入 sudo 密码完成授权。"
            )

        lines = ["检测到多个待确认的高危任务，请提供准确的 Task-ID："]
        for action in pending_actions:
            lines.append(
                f"- {action.task_id} | {action.action_name} | 剩余 {self._format_ttl(action.ttl_seconds)}"
            )
        lines.append("格式示例：`确认执行 Task-A8F2`")
        return "\n".join(lines)

    def clear_all_pending_tasks(self) -> str:
        actions = self.confirmations.clear_all()
        if not actions:
            return "当前无待确认的高危任务。"

        for action in actions:
            self.audit.record(
                category="policy",
                action_name=action.action_name,
                target_host=self.settings.ssh_host,
                decision="cancelled_by_user",
                risk_level=action.risk_level,
                command_preview=action.command_preview,
                metadata={
                    **action.arguments,
                    "task_id": action.task_id,
                    "clear_mode": "cancel_all",
                },
            )
        return "已安全撤销所有待处理的高危操作。"

    def confirmation_requires_sudo(self, task_id: str) -> bool:
        pending_action = self.confirmations.peek(task_id)
        return bool(pending_action and pending_action.sudo)

    def pending_task_notice(self) -> str | None:
        pending_action = self.confirmations.peek("latest")
        if pending_action is None:
            return None
        return (
            f"(注：您还有一个任务 ID 为 {pending_action.task_id} 的高危操作正在挂起等待确认，"
            f"将在 {self._format_ttl(pending_action.ttl_seconds)} 后失效)"
        )

    def render_security_block(self, error: SecurityBlockException) -> str:
        lines = []
        if error.cached and error.task_id:
            ttl_text = (
                self._format_ttl(
                    max(
                        0,
                        int(
                            (error.expires_at - datetime.now(timezone.utc)).total_seconds()
                        ),
                    )
                )
                if error.expires_at
                else "未知"
            )
            lines.extend(
                [
                    "[高风险预警] 已拦截并挂起待确认操作",
                    f"任务 ID: {error.task_id}",
                    f"目标工具: {error.action_name}",
                    f"执行参数: {self._serialize_tool_args(error.tool_args)}",
                    f"风险类型: {error.risk_category}",
                    f"风险判定: {error.reason}",
                    f"处置解释: {error.explanation}",
                    f"授权时效: {ttl_text}",
                    f"二次确认: 回复 `确认执行 {error.task_id}`，并在下一步输入 sudo 密码。",
                ]
            )
        else:
            lines.extend(
                [
                    "[安全拦截] 操作已被直接拒绝",
                    f"目标工具/请求: {error.action_name}",
                    f"输入明细: {self._serialize_tool_args(error.tool_args)}",
                    f"风险类型: {error.risk_category}",
                    f"风险判定: {error.reason}",
                    f"处置解释: {error.explanation}",
                    "处置结果: 该请求不提供二次确认通道。",
                ]
            )
        return "\n".join(lines)

    def bootstrap_remote_environment(self, sudo_password: str | None = None) -> str:
        command = (
            "if command -v apt-get >/dev/null 2>&1; then "
            "apt-get update && "
            "DEBIAN_FRONTEND=noninteractive apt-get install -y "
            "python3 python3-venv python3-pip procps iproute2 findutils passwd sudo; "
            "else "
            "echo '当前只支持基于 apt 的 Linux 发行版'; "
            "exit 1; "
            "fi"
        )
        command_preview = "apt-get update && apt-get install baseline packages"

        if self.settings.is_dry_run:
            self.audit.record(
                category="execution",
                action_name="bootstrap_remote_environment",
                target_host=self.settings.ssh_host,
                decision="dry_run",
                risk_level="high",
                command_preview=command_preview,
            )
            return f"[DRY RUN] 将执行: {command_preview}"

        password_ok, password_message = self._validate_sudo_password(
            action_name="bootstrap_remote_environment",
            risk_level="high",
            command_preview=command_preview,
            metadata={},
            sudo_password=sudo_password,
        )
        if not password_ok:
            return password_message

        try:
            result = self.executor.run(
                command,
                sudo=True,
                timeout=300,
                sudo_password=sudo_password,
            )
        except Exception as exc:
            self.audit.record(
                category="execution",
                action_name="bootstrap_remote_environment",
                target_host=self.settings.ssh_host,
                decision="runtime_error",
                risk_level="high",
                command_preview=command_preview,
                metadata={"exception": str(exc)},
            )
            return f"bootstrap_remote_environment 执行失败: {exc}"

        self.audit.record(
            category="execution",
            action_name="bootstrap_remote_environment",
            target_host=self.settings.ssh_host,
            decision="executed" if result.exit_status == 0 else "failed",
            risk_level="high",
            command_preview=command_preview,
            exit_status=result.exit_status,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        return self._format_execution_result("bootstrap_remote_environment", result)

    def check_mysql_connection(self) -> str:
        if not self.settings.mysql_enabled:
            return "MySQL 检查已关闭。"
        try:
            connection = pymysql.connect(
                host=self.settings.mysql_host,
                port=self.settings.mysql_port,
                user=self.settings.mysql_user,
                password=self.settings.mysql_password,
                database=self.settings.mysql_database,
                charset=self.settings.mysql_charset,
                connect_timeout=5,
            )
            with connection.cursor() as cursor:
                cursor.execute("SELECT VERSION()")
                version = cursor.fetchone()
            connection.close()
            return f"MySQL 连接成功，版本: {version[0] if version else 'unknown'}"
        except Exception as exc:
            return f"MySQL 连接失败: {exc}"

    def check_remote_connection(self) -> str:
        command = (
            "printf 'Host: '; hostname; "
            "printf 'User: '; whoami; "
            "printf 'OS: '; "
            "if [ -f /etc/os-release ]; then . /etc/os-release && echo \"$PRETTY_NAME\"; "
            "else uname -s; fi; "
            "printf 'Kernel: '; uname -r; "
            "printf 'Python: '; (python3 --version 2>/dev/null || echo 'python3 not found'); "
            "printf 'Uptime: '; (uptime -p 2>/dev/null || uptime)"
        )
        try:
            result = self.executor.run(command, timeout=30)
        except Exception as exc:
            return f"SSH 连接失败: {exc}"
        return self._format_execution_result("check_remote_connection", result)

    def get_system_context(self) -> str:
        command = (
            "printf 'Host: '; hostname; "
            "printf 'User: '; whoami; "
            "printf 'OS: '; "
            "if [ -f /etc/os-release ]; then . /etc/os-release && echo \"$PRETTY_NAME\"; "
            "else uname -s; fi; "
            "printf 'Kernel: '; uname -r; "
            "printf 'Arch: '; uname -m; "
            "printf 'Load: '; uptime"
        )
        return self._run_tool(
            action_name="get_system_context",
            command=command,
            command_preview="hostname && whoami && os-release && uname && uptime",
            arguments={},
        )

    def get_disk_usage(self) -> str:
        command = "df -h --output=source,size,used,avail,pcent,target | head -n 30"
        return self._run_tool(
            action_name="get_disk_usage",
            command=command,
            command_preview=command,
            arguments={},
        )

    def search_file(
        self,
        path: str = ".",
        keyword: str = "",
        mode: str = "all",
        recursive: bool = False,
    ) -> str:
        normalized_path = self._normalize_search_path(path)
        quoted_path = shlex.quote(normalized_path)
        safe_mode = mode if mode in {"all", "dir", "file"} else "all"
        command_parts = [f"find {quoted_path}"]
        if not recursive:
            command_parts.append("-maxdepth 1")
        if safe_mode == "dir":
            command_parts.append("-type d")
        elif safe_mode == "file":
            command_parts.append("-type f")
        if keyword:
            command_parts.append(f"-iname {shlex.quote(f'*{keyword}*')}")
        command_parts.append("2>/dev/null | head -n 30")
        command = " ".join(command_parts)
        wrapped_command = (
            f"if [ ! -e {quoted_path} ]; then echo '路径不存在'; exit 1; fi; "
            f"results=$({command}); "
            "if [ -n \"$results\" ]; then "
            "printf '%s\n' \"$results\"; "
            "echo ''; "
            "echo '[安全限制] 出于范围控制，最多展示前 30 条结果。'; "
            "else echo '未找到匹配项'; fi"
        )

        return self._run_tool(
            action_name="search_file",
            command=wrapped_command,
            command_preview=(
                f"find {normalized_path} "
                f"(mode={safe_mode}, recursive={recursive}, keyword={keyword or '<empty>'})"
            ),
            arguments={
                "path": normalized_path,
                "keyword": keyword,
                "mode": safe_mode,
                "recursive": recursive,
            },
        )

    def get_process_list(self) -> str:
        command = "ps -eo pid,comm,%cpu,%mem --sort=-%cpu | head -n 20"
        return self._run_tool(
            action_name="get_process_list",
            command=command,
            command_preview=command,
            arguments={},
        )

    def get_port_status(self) -> str:
        command = "ss -tulpn | head -n 30"
        return self._run_tool(
            action_name="get_port_status",
            command=command,
            command_preview=command,
            arguments={},
        )

    def create_user(self, username: str, pwd: str) -> str:
        safe_username = username.strip()
        password_payload = shlex.quote(f"{safe_username}:{pwd}")
        command = (
            f"if id -u {shlex.quote(safe_username)} >/dev/null 2>&1; then "
            "echo '用户已存在'; "
            "exit 1; "
            "fi; "
            f"useradd -m -- {shlex.quote(safe_username)} && "
            f"printf '%s\n' {password_payload} | chpasswd && "
            f"echo '用户 {safe_username} 创建成功'"
        )
        return self._run_tool(
            action_name="create_user",
            command=command,
            command_preview=f"useradd -m -- {safe_username} && chpasswd (password redacted)",
            arguments={"username": safe_username, "pwd": "***"},
            sudo=True,
            timeout=60,
        )

    def delete_user(self, username: str) -> str:
        safe_username = username.strip()
        command = (
            f"if ! id -u {shlex.quote(safe_username)} >/dev/null 2>&1; then "
            "echo '用户不存在'; "
            "exit 1; "
            "fi; "
            f"userdel -r -- {shlex.quote(safe_username)} && "
            f"echo '用户 {safe_username} 删除成功'"
        )
        return self._run_tool(
            action_name="delete_user",
            command=command,
            command_preview=f"userdel -r -- {safe_username}",
            arguments={"username": safe_username},
            sudo=True,
            timeout=60,
        )

    def create_folder(self, folder_name: str, parent_path: str = ".") -> str:
        safe_folder_name = self._validate_single_path_component(folder_name)
        if not safe_folder_name:
            return "folder_name is required and must be a single path component."

        normalized_parent = self._normalize_search_path(parent_path or ".")
        target_path = self._join_remote_path(normalized_parent, safe_folder_name)
        quoted_target = shlex.quote(target_path)

        command = (
            f"if [ -d {quoted_target} ]; then "
            f"echo 'folder already exists: {target_path}'; "
            "else "
            f"mkdir -p -- {quoted_target} && echo 'folder created: {target_path}'; "
            "fi"
        )
        return self._run_tool(
            action_name="create_folder",
            command=command,
            command_preview=f"mkdir -p -- {target_path}",
            arguments={
                "folder_name": safe_folder_name,
                "parent_path": normalized_parent,
                "target_path": target_path,
            },
            timeout=45,
        )

    def create_file(
        self,
        file_name: str,
        parent_path: str = ".",
        content: str = "",
        overwrite: bool = False,
    ) -> str:
        safe_file_name = self._validate_single_path_component(file_name)
        if not safe_file_name:
            return "file_name is required and must be a single path component."

        normalized_parent = self._normalize_search_path(parent_path or ".")
        target_path = self._join_remote_path(normalized_parent, safe_file_name)
        quoted_parent = shlex.quote(normalized_parent)
        quoted_target = shlex.quote(target_path)
        safe_content = content if isinstance(content, str) else str(content)
        delimiter = f"AGENT_FILE_EOF_{secrets.token_hex(6)}"
        overwrite_flag = "1" if overwrite else "0"

        command = (
            f"if [ ! -d {quoted_parent} ]; then echo 'parent path not found: {normalized_parent}'; exit 1; fi; "
            f"if [ -e {quoted_target} ] && [ {overwrite_flag} -ne 1 ]; then "
            f"echo 'file already exists: {target_path}'; exit 1; "
            "fi; "
            f"cat <<'{delimiter}' > {quoted_target}\n"
            f"{safe_content}\n"
            f"{delimiter}\n"
            f"echo 'file written: {target_path}'"
        )
        return self._run_tool(
            action_name="create_file",
            command=command,
            command_preview=(
                f"write file {target_path} "
                f"(overwrite={overwrite}, content_length={len(safe_content)})"
            ),
            arguments={
                "file_name": safe_file_name,
                "parent_path": normalized_parent,
                "target_path": target_path,
                "overwrite": overwrite,
                "content_length": len(safe_content),
            },
            timeout=60,
        )

    def read_file(self, file_path: str, max_lines: int = 120) -> str:
        normalized_path = self._normalize_search_path(file_path)
        safe_max_lines = max(1, min(int(max_lines), 300))
        quoted_path = shlex.quote(normalized_path)
        command = (
            f"if [ ! -f {quoted_path} ]; then echo 'file not found: {normalized_path}'; exit 1; fi; "
            f"sed -n '1,{safe_max_lines}p' {quoted_path}"
        )
        return self._run_tool(
            action_name="read_file",
            command=command,
            command_preview=f"read first {safe_max_lines} lines from {normalized_path}",
            arguments={
                "file_path": normalized_path,
                "max_lines": safe_max_lines,
            },
            timeout=30,
        )

    def append_file(
        self,
        file_path: str,
        content: str,
        create_if_missing: bool = False,
    ) -> str:
        normalized_path = self._normalize_search_path(file_path)
        quoted_path = shlex.quote(normalized_path)
        safe_content = content if isinstance(content, str) else str(content)
        delimiter = f"AGENT_APPEND_EOF_{secrets.token_hex(6)}"
        create_flag = "1" if create_if_missing else "0"

        command = (
            f"if [ ! -e {quoted_path} ] && [ {create_flag} -ne 1 ]; then "
            f"echo 'file not found: {normalized_path}'; exit 1; "
            "fi; "
            f"if [ -e {quoted_path} ] && [ ! -f {quoted_path} ]; then "
            f"echo 'target is not a regular file: {normalized_path}'; exit 1; "
            "fi; "
            f"cat <<'{delimiter}' >> {quoted_path}\n"
            f"{safe_content}\n"
            f"{delimiter}\n"
            f"echo 'content appended: {normalized_path}'"
        )
        return self._run_tool(
            action_name="append_file",
            command=command,
            command_preview=(
                f"append file {normalized_path} "
                f"(create_if_missing={create_if_missing}, content_length={len(safe_content)})"
            ),
            arguments={
                "file_path": normalized_path,
                "target_path": normalized_path,
                "create_if_missing": create_if_missing,
                "content_length": len(safe_content),
            },
            timeout=60,
        )

    def rename_file(
        self,
        source_path: str,
        destination_path: str,
        overwrite: bool = False,
    ) -> str:
        normalized_source = self._normalize_search_path(source_path)
        normalized_destination = self._normalize_search_path(destination_path)
        quoted_source = shlex.quote(normalized_source)
        quoted_destination = shlex.quote(normalized_destination)
        overwrite_flag = "1" if overwrite else "0"

        command = (
            f"if [ ! -e {quoted_source} ]; then "
            f"echo 'source not found: {normalized_source}'; exit 1; "
            "fi; "
            f"if [ -d {quoted_source} ]; then "
            "echo 'source is a directory, rename_file only supports regular files'; exit 1; "
            "fi; "
            f"if [ -e {quoted_destination} ] && [ {overwrite_flag} -ne 1 ]; then "
            f"echo 'destination already exists: {normalized_destination}'; exit 1; "
            "fi; "
            f"if [ -e {quoted_destination} ] && [ {overwrite_flag} -eq 1 ]; then "
            f"rm -f -- {quoted_destination}; "
            "fi; "
            f"mv -- {quoted_source} {quoted_destination} && "
            f"echo 'file renamed: {normalized_source} -> {normalized_destination}'"
        )
        return self._run_tool(
            action_name="rename_file",
            command=command,
            command_preview=(
                f"rename file {normalized_source} -> {normalized_destination} "
                f"(overwrite={overwrite})"
            ),
            arguments={
                "source_path": normalized_source,
                "destination_path": normalized_destination,
                "target_path": normalized_destination,
                "overwrite": overwrite,
            },
            timeout=60,
        )

    def delete_file(self, file_path: str) -> str:
        normalized_path = self._normalize_search_path(file_path)
        quoted_path = shlex.quote(normalized_path)
        command = (
            f"if [ ! -e {quoted_path} ]; then echo 'file not found: {normalized_path}'; exit 1; fi; "
            f"if [ ! -f {quoted_path} ]; then "
            f"echo 'target is not a regular file: {normalized_path}'; exit 1; "
            "fi; "
            f"rm -f -- {quoted_path} && echo 'file deleted: {normalized_path}'"
        )
        return self._run_tool(
            action_name="delete_file",
            command=command,
            command_preview=f"rm -f -- {normalized_path}",
            arguments={
                "file_path": normalized_path,
                "target_path": normalized_path,
            },
            timeout=45,
        )

    def confirm_action(
        self,
        task_id: str,
        sudo_password: str | None = None,
    ) -> str:
        pending_action = self.confirmations.require(task_id)
        if pending_action.sudo:
            password_ok, password_message = self._validate_sudo_password(
                action_name=pending_action.action_name,
                risk_level=pending_action.risk_level,
                command_preview=pending_action.command_preview,
                metadata={**pending_action.arguments, "task_id": pending_action.task_id},
                sudo_password=sudo_password,
            )
            if not password_ok:
                return password_message

        pending_action = self.confirmations.consume(task_id)

        if self.settings.is_dry_run:
            self.audit.record(
                category="execution",
                action_name=pending_action.action_name,
                target_host=self.settings.ssh_host,
                decision="dry_run_confirmed",
                risk_level=pending_action.risk_level,
                command_preview=pending_action.command_preview,
                metadata={**pending_action.arguments, "task_id": pending_action.task_id},
            )
            return (
                "[DRY RUN] 已完成授权核销，且 sudo 密码校验通过。\n"
                f"任务 ID: {pending_action.task_id}\n"
                f"待执行命令: {pending_action.command_preview}"
            )

        try:
            result = self.executor.run(
                pending_action.command,
                sudo=pending_action.sudo,
                timeout=pending_action.timeout_seconds,
                sudo_password=sudo_password,
            )
        except Exception as exc:
            self.audit.record(
                category="execution",
                action_name=pending_action.action_name,
                target_host=self.settings.ssh_host,
                decision="runtime_error_after_confirmation",
                risk_level=pending_action.risk_level,
                command_preview=pending_action.command_preview,
                metadata={
                    **pending_action.arguments,
                    "task_id": pending_action.task_id,
                    "exception": str(exc),
                },
            )
            return f"代理执行系统指令时发生未知异常，操作已安全中断。日志记录: {exc}"

        self.audit.record(
            category="execution",
            action_name=pending_action.action_name,
            target_host=self.settings.ssh_host,
            decision=(
                "executed_after_confirmation"
                if result.exit_status == 0
                else "failed_after_confirmation"
            ),
            risk_level=pending_action.risk_level,
            command_preview=pending_action.command_preview,
            metadata={**pending_action.arguments, "task_id": pending_action.task_id},
            exit_status=result.exit_status,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        return self._format_execution_result(pending_action.action_name, result)

    def cancel_action(self, task_id: str) -> str:
        pending_action = self.confirmations.cancel(task_id)
        self.audit.record(
            category="policy",
            action_name=pending_action.action_name,
            target_host=self.settings.ssh_host,
            decision="cancelled_by_user",
            risk_level=pending_action.risk_level,
            command_preview=pending_action.command_preview,
            metadata={**pending_action.arguments, "task_id": pending_action.task_id},
        )
        return f"已安全撤销任务 {pending_action.task_id}。"

    def _run_tool(
        self,
        *,
        action_name: str,
        command: str,
        command_preview: str,
        arguments: dict[str, Any],
        sudo: bool = False,
        timeout: int = 30,
    ) -> str:
        decision = self.policy.evaluate_action(
            action_name=action_name,
            command_preview=command_preview,
            arguments=arguments,
        )

        if decision.disposition == "block":
            self.audit.record(
                category="policy",
                action_name=action_name,
                target_host=self.settings.ssh_host,
                decision="blocked",
                risk_level=decision.risk_level,
                command_preview=command_preview,
                metadata={
                    **arguments,
                    "risk_category": decision.risk_category,
                    "reason": decision.reason,
                },
            )
            raise SecurityBlockException(
                action_name=action_name,
                reason=decision.reason,
                explanation=decision.explanation,
                risk_level=decision.risk_level,
                risk_category=decision.risk_category,
                tool_args=arguments,
                command_preview=command_preview,
                cached=False,
                requires_confirmation=False,
                evidence=decision.evidence,
            )

        if decision.disposition == "warn" or decision.requires_confirmation:
            pending_action = self.confirmations.create(
                action_name=action_name,
                command=command,
                command_preview=command_preview,
                sudo=sudo,
                timeout_seconds=timeout,
                risk_level=decision.risk_level,
                risk_category=decision.risk_category,
                reason=decision.reason,
                explanation=decision.explanation,
                arguments=arguments,
            )
            self.audit.record(
                category="policy",
                action_name=action_name,
                target_host=self.settings.ssh_host,
                decision="pending_confirmation",
                risk_level=decision.risk_level,
                command_preview=command_preview,
                metadata={
                    **arguments,
                    "task_id": pending_action.task_id,
                    "risk_category": decision.risk_category,
                    "reason": decision.reason,
                },
            )
            raise SecurityBlockException(
                action_name=action_name,
                reason=decision.reason,
                explanation=decision.explanation,
                risk_level=decision.risk_level,
                risk_category=decision.risk_category,
                tool_args=arguments,
                command_preview=command_preview,
                task_id=pending_action.task_id,
                expires_at=pending_action.expire_at,
                cached=True,
                requires_confirmation=True,
                evidence=decision.evidence,
            )

        if self.settings.is_dry_run:
            self.audit.record(
                category="execution",
                action_name=action_name,
                target_host=self.settings.ssh_host,
                decision="dry_run",
                risk_level=decision.risk_level,
                command_preview=command_preview,
                metadata=arguments,
            )
            return f"[DRY RUN] 将执行: {command_preview}"

        try:
            result = self.executor.run(command, sudo=sudo, timeout=timeout)
        except Exception as exc:
            self.audit.record(
                category="execution",
                action_name=action_name,
                target_host=self.settings.ssh_host,
                decision="runtime_error",
                risk_level=decision.risk_level,
                command_preview=command_preview,
                metadata={**arguments, "exception": str(exc)},
            )
            return f"代理执行系统指令时发生未知异常，操作已安全中断。日志记录: {exc}"

        self.audit.record(
            category="execution",
            action_name=action_name,
            target_host=self.settings.ssh_host,
            decision="executed" if result.exit_status == 0 else "failed",
            risk_level=decision.risk_level,
            command_preview=command_preview,
            metadata=arguments,
            exit_status=result.exit_status,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        return self._format_execution_result(action_name, result)

    def _validate_sudo_password(
        self,
        *,
        action_name: str,
        risk_level: str,
        command_preview: str,
        metadata: dict[str, Any],
        sudo_password: str | None,
    ) -> tuple[bool, str]:
        if not sudo_password:
            return False, "该操作需要先输入 sudo 密码后才能执行。"

        try:
            is_valid, details = self.executor.validate_sudo_password(sudo_password)
        except Exception as exc:
            self.audit.record(
                category="execution",
                action_name=action_name,
                target_host=self.settings.ssh_host,
                decision="sudo_validation_error",
                risk_level=risk_level,
                command_preview=command_preview,
                metadata={**metadata, "exception": str(exc)},
            )
            return False, f"sudo 密码校验异常: {exc}"

        if is_valid:
            return True, "sudo password accepted"

        self.audit.record(
            category="policy",
            action_name=action_name,
            target_host=self.settings.ssh_host,
            decision="sudo_auth_failed",
            risk_level=risk_level,
            command_preview=command_preview,
            metadata=metadata,
        )
        if details:
            return False, f"sudo 密码校验失败: {details}"
        return False, "sudo 密码校验失败。"

    @staticmethod
    def _validate_single_path_component(name: str) -> str:
        candidate = name.strip()
        if not candidate:
            return ""
        if candidate in {".", ".."}:
            return ""
        if "/" in candidate or "\\" in candidate or "\x00" in candidate:
            return ""
        return candidate

    @staticmethod
    def _join_remote_path(parent_path: str, child_name: str) -> str:
        normalized_parent = LinuxServerToolService._normalize_search_path(parent_path)
        if normalized_parent == "/":
            return f"/{child_name}"
        return f"{normalized_parent.rstrip('/')}/{child_name}"

    @staticmethod
    def _normalize_search_path(path: str) -> str:
        if not path.strip():
            return "."
        normalized = path.replace("\\", "/")
        while "//" in normalized:
            normalized = normalized.replace("//", "/")
        return normalized

    @staticmethod
    def _format_execution_result(action_name: str, result: CommandResult) -> str:
        if result.exit_status == 0:
            if result.stdout:
                return result.stdout
            if result.stderr:
                return f"{action_name} 已执行，但有警告输出:\n{result.stderr}"
            return f"{action_name} 执行成功，无返回内容。"

        parts = [f"{action_name} 执行失败，退出码 {result.exit_status}。"]
        if result.stdout:
            parts.append(f"[stdout]\n{result.stdout}")
        if result.stderr:
            parts.append(f"[stderr]\n{result.stderr}")
        return "\n".join(parts)

    @staticmethod
    def _serialize_tool_args(arguments: dict[str, Any]) -> str:
        return json.dumps(arguments, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _format_ttl(ttl_seconds: int) -> str:
        minutes, seconds = divmod(max(0, ttl_seconds), 60)
        return f"{minutes}分{seconds:02d}秒"
