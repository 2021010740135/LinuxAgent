from __future__ import annotations

from dataclasses import dataclass
import shlex

import paramiko

from app.config import AppSettings


@dataclass(frozen=True, slots=True)
class CommandResult:
    exit_status: int
    stdout: str
    stderr: str
    remote_command: str


class SSHExecutor:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._client: paramiko.SSHClient | None = None

    def _connect(self) -> paramiko.SSHClient:
        if self._client is not None:
            transport = self._client.get_transport()
            if transport is not None and transport.is_active():
                return self._client
            self._client.close()
            self._client = None

        client = paramiko.SSHClient()
        if self._settings.ssh_strict_host_key:
            client.load_system_host_keys()
        else:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs: dict[str, object] = {
            "hostname": self._settings.ssh_host,
            "port": self._settings.ssh_port,
            "username": self._settings.ssh_username,
            "timeout": 10,
            "allow_agent": False,
            "look_for_keys": False,
        }
        if self._settings.ssh_private_key_path is not None:
            connect_kwargs["key_filename"] = str(self._settings.ssh_private_key_path)
        if self._settings.ssh_password:
            connect_kwargs["password"] = self._settings.ssh_password

        client.connect(**connect_kwargs)
        self._client = client
        return client

    def validate_sudo_password(
        self,
        sudo_password: str,
        *,
        timeout: int = 15,
    ) -> tuple[bool, str]:
        if not sudo_password:
            return False, "sudo password is required."

        result = self._execute_remote_command(
            "sudo -S -k -p '' true",
            timeout=timeout,
            stdin_secret=sudo_password,
        )
        details = result.stderr or result.stdout
        return result.exit_status == 0, details

    def run(
        self,
        command: str,
        *,
        sudo: bool = False,
        timeout: int = 30,
        sudo_password: str | None = None,
    ) -> CommandResult:
        wrapped_command = f"bash -lc {shlex.quote(command)}"
        stdin_secret: str | None = None
        if sudo:
            wrapped_command = f"sudo -S -p '' {wrapped_command}"
            stdin_secret = sudo_password or self._settings.sudo_password
            if not stdin_secret:
                raise ValueError("sudo password is required for this command.")

        return self._execute_remote_command(
            wrapped_command,
            timeout=timeout,
            stdin_secret=stdin_secret,
        )

    def _execute_remote_command(
        self,
        command: str,
        *,
        timeout: int,
        stdin_secret: str | None = None,
    ) -> CommandResult:
        client = self._connect()
        stdin, stdout, stderr = client.exec_command(
            command,
            timeout=timeout,
            get_pty=False,
        )

        if stdin_secret is not None:
            stdin.write(f"{stdin_secret}\n")
            stdin.flush()
            stdin.channel.shutdown_write()

        stdout_text = stdout.read().decode("utf-8", errors="replace").strip()
        stderr_text = stderr.read().decode("utf-8", errors="replace").strip()
        exit_status = stdout.channel.recv_exit_status()

        return CommandResult(
            exit_status=exit_status,
            stdout=stdout_text,
            stderr=stderr_text,
            remote_command=command,
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
