from __future__ import annotations

import argparse
from getpass import getpass
import sys

from app.agent import ControlledLinuxServerAgent
from app.config import AppSettings
from app.tools import LinuxServerToolService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Controlled Linux Server Agent"
    )
    subparsers = parser.add_subparsers(dest="command")

    chat_parser = subparsers.add_parser("chat", help="Start the interactive chat loop.")
    chat_parser.set_defaults(command="chat")

    once_parser = subparsers.add_parser("once", help="Run a single chat query.")
    once_parser.add_argument("query", help="Natural-language query for the agent.")

    check_parser = subparsers.add_parser(
        "check",
        help="Validate SSH/MySQL connectivity and show the current configuration summary.",
    )
    check_parser.add_argument(
        "--skip-mysql",
        action="store_true",
        help="Skip the optional local MySQL connectivity check.",
    )

    subparsers.add_parser(
        "bootstrap",
        help="Install the required baseline packages on the remote Linux host over SSH.",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        args.command = "chat"

    settings = AppSettings.load()
    tool_service = LinuxServerToolService(settings)
    agent = ControlledLinuxServerAgent(settings, tool_service)

    if args.command == "chat":
        return agent.chat_forever()
    if args.command == "once":
        print(agent.run_once(args.query))
        return 0
    if args.command == "check":
        print(
            tool_service.check_environment(
                include_mysql=not args.skip_mysql,
            )
        )
        return 0
    if args.command == "bootstrap":
        try:
            sudo_password = getpass("sudo password> ")
        except (EOFError, KeyboardInterrupt):
            print("已取消 bootstrap，未输入 sudo 密码。")
            return 1
        if not sudo_password:
            print("已取消 bootstrap，未输入 sudo 密码。")
            return 1
        print(tool_service.bootstrap_remote_environment(sudo_password=sudo_password))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
