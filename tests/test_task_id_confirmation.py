from __future__ import annotations

import unittest

from app.agent import ControlledLinuxServerAgent
from app.config import AppSettings
from app.tools import LinuxServerToolService


class TaskIdConfirmationTests(unittest.TestCase):
    def setUp(self) -> None:
        settings = AppSettings.load()
        self.tool_service = LinuxServerToolService(settings)
        self.agent = ControlledLinuxServerAgent(settings, self.tool_service)

    def tearDown(self) -> None:
        self.tool_service.clear_all_pending_tasks()

    def test_confirm_command_accepts_task_id_case_insensitively(self) -> None:
        pending = self.tool_service.confirmations.create(
            action_name="create_user",
            command="useradd -m -- demo",
            command_preview="useradd -m -- demo",
            sudo=True,
            timeout_seconds=60,
            risk_level="high",
            risk_category="user_privilege_change",
            reason="needs confirmation",
            explanation="high risk operation",
            arguments={"username": "demo"},
        )

        response = self.agent.run_once(
            f"确认执行 {pending.task_id.lower()}",
            interactive_password_prompt=False,
        )

        self.assertIn("requires sudo password", response)
        self.assertIsNotNone(self.tool_service.confirmations.peek(pending.task_id))

    def test_confirm_command_accepts_uppercase_prefix_task_id(self) -> None:
        pending = self.tool_service.confirmations.create(
            action_name="delete_user",
            command="userdel -r -- demo",
            command_preview="userdel -r -- demo",
            sudo=True,
            timeout_seconds=60,
            risk_level="high",
            risk_category="user_privilege_change",
            reason="needs confirmation",
            explanation="high risk operation",
            arguments={"username": "demo"},
        )

        task_suffix = pending.task_id.split("-", 1)[1]
        response = self.agent.run_once(
            f"confirm TASK-{task_suffix.lower()}",
            interactive_password_prompt=False,
        )

        self.assertIn("requires sudo password", response)
        self.assertIsNotNone(self.tool_service.confirmations.peek(pending.task_id))


if __name__ == "__main__":
    unittest.main()
