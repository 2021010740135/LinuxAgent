from __future__ import annotations

import os
import unittest

from app.config import AppSettings
from app.exceptions import SecurityBlockException
from app.tools import LinuxServerToolService


class FileToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_execution_mode = os.environ.get("AGENT_EXECUTION_MODE")
        os.environ["AGENT_EXECUTION_MODE"] = "dry_run"
        settings = AppSettings.load()
        self.service = LinuxServerToolService(settings)

    def tearDown(self) -> None:
        if self._original_execution_mode is None:
            os.environ.pop("AGENT_EXECUTION_MODE", None)
        else:
            os.environ["AGENT_EXECUTION_MODE"] = self._original_execution_mode

    def test_create_folder_returns_dry_run_preview(self) -> None:
        result = self.service.create_folder("deploy_logs", "/home/zbc")
        self.assertIn("[DRY RUN]", result)
        self.assertIn("/home/zbc/deploy_logs", result)

    def test_create_file_rejects_invalid_name(self) -> None:
        result = self.service.create_file("../passwd", "/home/zbc", "x")
        self.assertIn("single path component", result)

    def test_create_file_blocks_sensitive_path(self) -> None:
        with self.assertRaises(SecurityBlockException):
            self.service.create_file("agent.conf", "/etc", "x=1", overwrite=True)

    def test_read_file_returns_dry_run_preview(self) -> None:
        result = self.service.read_file("/home/zbc/note.txt", max_lines=20)
        self.assertIn("[DRY RUN]", result)
        self.assertIn("20", result)

    def test_append_file_returns_dry_run_preview(self) -> None:
        result = self.service.append_file("/home/zbc/note.txt", "line2", create_if_missing=False)
        self.assertIn("[DRY RUN]", result)
        self.assertIn("append file /home/zbc/note.txt", result)

    def test_append_file_blocks_sensitive_path(self) -> None:
        with self.assertRaises(SecurityBlockException):
            self.service.append_file("/etc/ssh/sshd_config", "PermitRootLogin no")

    def test_rename_file_returns_dry_run_preview(self) -> None:
        result = self.service.rename_file(
            "/home/zbc/a.txt",
            "/home/zbc/b.txt",
            overwrite=False,
        )
        self.assertIn("[DRY RUN]", result)
        self.assertIn("/home/zbc/a.txt -> /home/zbc/b.txt", result)

    def test_rename_file_with_overwrite_requires_confirmation(self) -> None:
        with self.assertRaises(SecurityBlockException) as ctx:
            self.service.rename_file(
                "/home/zbc/a.txt",
                "/home/zbc/b.txt",
                overwrite=True,
            )
        self.assertTrue(ctx.exception.cached)
        self.assertEqual("rename_file", ctx.exception.action_name)

    def test_delete_file_requires_confirmation(self) -> None:
        with self.assertRaises(SecurityBlockException) as ctx:
            self.service.delete_file("/home/zbc/temp.log")
        self.assertTrue(ctx.exception.cached)
        self.assertEqual("delete_file", ctx.exception.action_name)

    def test_delete_file_blocks_sensitive_path(self) -> None:
        with self.assertRaises(SecurityBlockException) as ctx:
            self.service.delete_file("/etc/passwd")
        self.assertFalse(ctx.exception.cached)
        self.assertEqual("core_path_modification", ctx.exception.risk_category)


if __name__ == "__main__":
    unittest.main()
