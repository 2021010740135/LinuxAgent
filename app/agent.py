from __future__ import annotations

from getpass import getpass
import json
import re
from typing import Any

from openai import OpenAI

from app.config import AppSettings
from app.confirmation import PendingAction
from app.exceptions import (
    SecurityBlockException,
    TaskExpiredException,
    TaskNotFoundException,
)
from app.tools import LinuxServerToolService


TASK_ID_PATTERN = re.compile(r"(Task-[A-Z0-9]{4})", re.IGNORECASE)

SYSTEM_PROMPT = """你是一个专业的 Linux 运维代理，负责通过 SSH 控制远程 Linux 主机。
你必须把用户需求转成安全、可解释、可审计的操作。

规则:
1. 先判断需求，再调用最合适的工具，不要编造结果。
2. 查询类任务可直接执行。
3. 高风险任务必须走 Task-ID + sudo 密码二次确认流程。
4. 若请求被安全策略判定为破坏性或非法，必须直接拒绝。
5. 回复保持简洁，并说明结果和原因。
"""


class ControlledLinuxServerAgent:
    def __init__(self, settings: AppSettings, tool_service: LinuxServerToolService) -> None:
        self.settings = settings
        self.tool_service = tool_service
        self.message_history: list[dict[str, Any]] = []
        self.client = (
            OpenAI(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
            )
            if settings.llm_enabled
            else None
        )

    def chat_forever(self) -> int:
        print(
            f"{self.settings.app_name} ready, current target: "
            f"{self.settings.default_target_host} ({self.settings.ssh_host})"
        )
        print("Type exit/quit to stop. High-risk actions require Task-ID confirmation.")
        while True:
            user_input = input("\n需求> ").strip()
            if user_input.lower() in {"exit", "quit"}:
                print("Session ended.")
                return 0
            if not user_input:
                continue
            print(self.run_once(user_input))

    def run_once(
        self,
        user_input: str,
        *,
        sudo_password: str | None = None,
        interactive_password_prompt: bool = True,
    ) -> str:
        shortcut_result = self._try_handle_confirmation_shortcut(
            user_input=user_input,
            sudo_password=sudo_password,
            interactive_password_prompt=interactive_password_prompt,
        )
        if shortcut_result is not None:
            self.message_history.append({"role": "user", "content": user_input})
            self.message_history.append({"role": "assistant", "content": shortcut_result})
            return shortcut_result

        try:
            self.tool_service.review_user_intent(user_input)
        except SecurityBlockException as exc:
            warning = self.tool_service.render_security_block(exc)
            self.message_history.append({"role": "user", "content": user_input})
            self.message_history.append({"role": "assistant", "content": warning})
            return warning

        if self.client is None:
            response = (
                "LLM is disabled. Please set AGENT_LLM_ENABLED=true and provide a valid API key."
            )
            self.message_history.append({"role": "user", "content": user_input})
            self.message_history.append({"role": "assistant", "content": response})
            return self._append_pending_notice(response)

        self.message_history.append({"role": "user", "content": user_input})

        for _ in range(6):
            response = self.client.chat.completions.create(
                model=self.settings.llm_model,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}, *self.message_history],
                tools=self.tool_service.openai_tools(),
            )
            message = response.choices[0].message

            if message.tool_calls:
                self.message_history.append(
                    {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": [
                            {
                                "id": tool_call.id,
                                "type": "function",
                                "function": {
                                    "name": tool_call.function.name,
                                    "arguments": tool_call.function.arguments or "{}",
                                },
                            }
                            for tool_call in message.tool_calls
                        ],
                    }
                )
                for tool_call in message.tool_calls:
                    arguments = self._load_tool_arguments(tool_call.function.arguments)
                    try:
                        tool_result = self.tool_service.dispatch(tool_call.function.name, arguments)
                    except SecurityBlockException as exc:
                        warning = self.tool_service.render_security_block(exc)
                        self.message_history.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_call.function.name,
                                "content": warning,
                            }
                        )
                        self.message_history.append({"role": "assistant", "content": warning})
                        return warning
                    except TaskNotFoundException:
                        message_text = "No pending high-risk task found, or Task-ID is invalid."
                        self.message_history.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_call.function.name,
                                "content": message_text,
                            }
                        )
                        self.message_history.append({"role": "assistant", "content": message_text})
                        return message_text
                    except TaskExpiredException:
                        message_text = "Security session expired. Please issue the request again."
                        self.message_history.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_call.function.name,
                                "content": message_text,
                            }
                        )
                        self.message_history.append({"role": "assistant", "content": message_text})
                        return message_text
                    except Exception as exc:  # noqa: BLE001
                        message_text = (
                            "Unexpected error while executing operation; action was safely interrupted. "
                            f"Details: {exc}"
                        )
                        self.message_history.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_call.function.name,
                                "content": message_text,
                            }
                        )
                        self.message_history.append({"role": "assistant", "content": message_text})
                        return message_text

                    self.message_history.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.function.name,
                            "content": tool_result,
                        }
                    )
                continue

            content = message.content or "Done."
            content = self._append_pending_notice(content)
            self.message_history.append({"role": "assistant", "content": content})
            return content

        fallback = "Too many tool calls in one round; please split your request and try again."
        fallback = self._append_pending_notice(fallback)
        self.message_history.append({"role": "assistant", "content": fallback})
        return fallback

    def reset_conversation(self, *, clear_pending_tasks: bool = True) -> str | None:
        self.message_history.clear()
        if clear_pending_tasks:
            return self.tool_service.clear_all_pending_tasks()
        return None

    def list_pending_actions(self) -> list[PendingAction]:
        return self.tool_service.confirmations.list_pending()

    @staticmethod
    def _load_tool_arguments(raw_arguments: str | None) -> dict[str, Any]:
        if not raw_arguments:
            return {}
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _normalize_task_id(task_id: str) -> str:
        candidate = task_id.strip()
        _prefix, separator, suffix = candidate.partition("-")
        if not separator or not suffix:
            return candidate
        return f"Task-{suffix.upper()}"

    def _try_handle_confirmation_shortcut(
        self,
        *,
        user_input: str,
        sudo_password: str | None,
        interactive_password_prompt: bool,
    ) -> str | None:
        normalized = user_input.strip()
        lowered = normalized.lower()

        task_match = TASK_ID_PATTERN.search(normalized)
        task_id = self._normalize_task_id(task_match.group(1)) if task_match else None

        if task_id and ("confirm" in lowered or "确认" in normalized):
            return self._confirm_with_prompt(
                task_id=task_id,
                sudo_password=sudo_password,
                interactive_password_prompt=interactive_password_prompt,
            )

        if task_id and ("cancel" in lowered or "取消" in normalized):
            return self._safe_cancel(task_id)

        if normalized in {"确认", "确认执行"} or lowered in {"confirm", "confirm latest"}:
            return self._prompt_for_task_id()

        if normalized in {"取消", "算了吧", "退出"} or lowered in {"cancel", "cancel all"}:
            return self.tool_service.clear_all_pending_tasks()

        return None

    def _confirm_with_prompt(
        self,
        *,
        task_id: str,
        sudo_password: str | None,
        interactive_password_prompt: bool,
    ) -> str:
        if not self.tool_service.confirmation_requires_sudo(task_id):
            try:
                return self.tool_service.confirm_action(task_id)
            except TaskNotFoundException:
                return "Task-ID does not exist or was already consumed."
            except TaskExpiredException:
                return "Security session expired. Please issue the request again."
            except Exception as exc:  # noqa: BLE001
                return (
                    "Unexpected error while executing operation; action was safely interrupted. "
                    f"Details: {exc}"
                )

        resolved_sudo_password = sudo_password
        if not resolved_sudo_password and interactive_password_prompt:
            try:
                resolved_sudo_password = getpass("sudo password> ")
            except (EOFError, KeyboardInterrupt):
                return "Confirmation cancelled; no sudo password provided."

        if not resolved_sudo_password:
            return "This action requires sudo password. Please provide it and confirm again."

        try:
            return self.tool_service.confirm_action(task_id, sudo_password=resolved_sudo_password)
        except TaskNotFoundException:
            return "Task-ID does not exist or was already consumed."
        except TaskExpiredException:
            return "Security session expired. Please issue the request again."
        except Exception as exc:  # noqa: BLE001
            return (
                "Unexpected error while executing operation; action was safely interrupted. "
                f"Details: {exc}"
            )

    def _safe_cancel(self, task_id: str) -> str:
        try:
            return self.tool_service.cancel_action(task_id)
        except TaskNotFoundException:
            return "Task-ID does not exist or was already consumed."
        except TaskExpiredException:
            return "Security session expired. Please issue the request again."
        except Exception as exc:  # noqa: BLE001
            return (
                "Unexpected error while executing operation; action was safely interrupted. "
                f"Details: {exc}"
            )

    def _prompt_for_task_id(self) -> str:
        try:
            return self.tool_service.prompt_for_confirmation()
        except TaskNotFoundException:
            return "There is no pending high-risk task."
        except Exception as exc:  # noqa: BLE001
            return (
                "Unexpected error while executing operation; action was safely interrupted. "
                f"Details: {exc}"
            )

    def _append_pending_notice(self, content: str) -> str:
        notice = self.tool_service.pending_task_notice()
        if not notice:
            return content
        if notice in content:
            return content
        return f"{content}\n\n{notice}"
