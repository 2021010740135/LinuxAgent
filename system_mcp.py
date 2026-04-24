from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.config import AppSettings
from app.tools import LinuxServerToolService

settings = AppSettings.load()
service = LinuxServerToolService(settings)
mcp = FastMCP(settings.app_name)


@mcp.tool()
def check_remote_connection() -> str:
    """Check SSH connectivity and show basic remote host details."""
    return service.check_remote_connection()


@mcp.tool()
def get_system_context() -> str:
    """Get remote Linux system metadata through SSH."""
    return service.get_system_context()


@mcp.tool()
def get_disk_usage() -> str:
    """Get remote disk usage information through SSH."""
    return service.get_disk_usage()


@mcp.tool()
def search_file(
    path: str = ".",
    keyword: str = "",
    mode: str = "all",
    recursive: bool = False,
) -> str:
    """Search files or directories on the remote Linux host."""
    return service.search_file(path=path, keyword=keyword, mode=mode, recursive=recursive)


@mcp.tool()
def get_process_list() -> str:
    """Get the remote process list."""
    return service.get_process_list()


@mcp.tool()
def get_port_status() -> str:
    """Get remote port and socket usage."""
    return service.get_port_status()


@mcp.tool()
def create_user(username: str, pwd: str) -> str:
    """Create a Linux user on the remote host. This action requires confirmation."""
    return service.create_user(username=username, pwd=pwd)


@mcp.tool()
def delete_user(username: str) -> str:
    """Delete a Linux user on the remote host. This action requires confirmation."""
    return service.delete_user(username=username)


@mcp.tool()
def create_folder(folder_name: str, parent_path: str = ".") -> str:
    """Create a folder on the remote Linux host."""
    return service.create_folder(folder_name=folder_name, parent_path=parent_path)


@mcp.tool()
def create_file(
    file_name: str,
    parent_path: str = ".",
    content: str = "",
    overwrite: bool = False,
) -> str:
    """Create a text file on the remote Linux host."""
    return service.create_file(
        file_name=file_name,
        parent_path=parent_path,
        content=content,
        overwrite=overwrite,
    )


@mcp.tool()
def read_file(file_path: str, max_lines: int = 120) -> str:
    """Read a text file from the remote Linux host."""
    return service.read_file(file_path=file_path, max_lines=max_lines)


@mcp.tool()
def append_file(file_path: str, content: str, create_if_missing: bool = False) -> str:
    """Append text content to a file on the remote Linux host."""
    return service.append_file(
        file_path=file_path,
        content=content,
        create_if_missing=create_if_missing,
    )


@mcp.tool()
def rename_file(
    source_path: str,
    destination_path: str,
    overwrite: bool = False,
) -> str:
    """Rename or move a file on the remote Linux host."""
    return service.rename_file(
        source_path=source_path,
        destination_path=destination_path,
        overwrite=overwrite,
    )


@mcp.tool()
def delete_file(file_path: str) -> str:
    """Delete a file on the remote Linux host. This action requires confirmation."""
    return service.delete_file(file_path=file_path)


@mcp.tool()
def confirm_action(task_id: str, sudo_password: str) -> str:
    """Confirm a pending high-risk action with the user's sudo password."""
    return service.confirm_action(task_id=task_id, sudo_password=sudo_password)


@mcp.tool()
def cancel_action(task_id: str) -> str:
    """Cancel a pending high-risk action by Task-ID."""
    return service.cancel_action(task_id=task_id)


if __name__ == "__main__":
    mcp.run()
