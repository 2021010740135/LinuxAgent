# Controlled Linux Server Agent

This project provides a Linux operations agent over SSH with policy control, confirmation workflow, and audit logging.

## Capabilities

- Environment checks: host context, disk usage, process list, and port status
- File discovery: bounded file/directory search
- File operations: create folder, create file, read file, append file, rename file, delete file
- Account operations: create/delete users with confirmation + sudo verification
- Multi-channel access: CLI (`main.py`), web chat (`streamlit_app.py`), and MCP server (`system_mcp.py`)

## Quick start

1. Prepare `.env` based on `.env.example`
2. Install dependencies:

```bash
uv sync
```

3. Validate connectivity:

```bash
uv run python main.py check
```

4. Run terminal chat:

```bash
uv run python main.py chat
```

5. Run web chat:

```bash
uv run streamlit run streamlit_app.py
```

## High-risk confirmation flow

1. Risky action is intercepted and suspended as `Task-XXXX`
2. User confirms with `confirm Task-XXXX` (or Chinese confirmation text)
3. User provides `sudo` password
4. System validates password and executes atomically

## Useful commands

```bash
uv run python main.py once "check system context"
uv run python main.py once "search directories under /home containing nginx"
uv run python main.py once "create folder deploy_logs under /home/zbc"
uv run python main.py once "create file note.txt under /home/zbc with content hello"
uv run python main.py once "append line done to /home/zbc/note.txt"
uv run python main.py once "rename /home/zbc/note.txt to /home/zbc/note.done.txt"
uv run python main.py once "read first 20 lines of /home/zbc/note.done.txt"
uv run python main.py once "delete /home/zbc/note.done.txt"
uv run python main.py check --skip-mysql
uv run python system_mcp.py
```

## Notes

- Set `AGENT_EXECUTION_MODE=dry_run` to preview commands safely
- Writes to protected roots such as `/etc`, `/boot`, `/bin`, `/sbin`, `/usr/bin`, `/var/log` are blocked by policy
- Audit logs are stored at `AGENT_DATABASE_PATH`
