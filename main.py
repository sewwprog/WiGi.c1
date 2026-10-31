#!/usr/bin/env python3
"""Entry point for WiGi Python server launcher."""

from __future__ import annotations

import argparse
import signal
import sys

from wigi.cli import (
    GREEN,
    RED,
    RESET,
    init_terminal,
    print_servers_summary,
    read_password,
    run_interactive_menu,
    run_server_blocking,
)
from wigi.network import find_free_port
from wigi.storage import ServerStore


def _install_sigterm_handler() -> None:
    def _handle_sigterm(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _handle_sigterm)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WiGi — термінальний менеджер та запуск Python-серверів (локально / у мережі)."
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Показати список створених серверів і вийти.",
    )
    parser.add_argument(
        "--create",
        metavar="NAME",
        help="Створити новий сервер із вказаною назвою.",
    )
    parser.add_argument(
        "--start",
        metavar="NAME",
        help="Запустити вже створений сервер за назвою.",
    )
    parser.add_argument(
        "--password",
        metavar="PASSWORD",
        help="Пароль сервера (для --create або --start; якщо не передано — запитає в терміналі).",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Порт для створення або запуску сервера (за замовчуванням 8000 / авто).",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Хост прослуховування (за замовчуванням 0.0.0.0 — доступно на ноуті та в мережі).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _install_sigterm_handler()
    init_terminal()
    args = parse_args(argv)
    store = ServerStore()

    if args.list:
        print_servers_summary(store.list_servers())
        print()
        return 0

    if args.create:
        pw = args.password if args.password is not None else read_password("Пароль для нового сервера: ")
        port = args.port if args.port is not None else find_free_port(8000)
        try:
            profile = store.create_server(name=args.create, password=pw, port=port)
        except ValueError as exc:
            print(f"{RED}✗ {exc}{RESET}", file=sys.stderr)
            return 1
        print(f"{GREEN}✓ Сервер '{profile.name}' створено (порт {profile.port}).{RESET}")
        if args.start and args.start.strip().lower() == profile.name.lower():
            run_server_blocking(
                store,
                profile,
                host=args.host,
                override_port=args.port,
                return_hint="Натисни Ctrl+C щоб зупинити сервер.",
            )
            return 0
        if not args.start:
            return 0

    if args.start:
        profile = store.get_by_name(args.start)
        if profile is None:
            print(f"{RED}✗ Сервер '{args.start}' не знайдено.{RESET}", file=sys.stderr)
            return 1
        pw = args.password if args.password is not None else read_password(f"Пароль сервера '{profile.name}': ")
        if not profile.verify_password(pw):
            print(f"{RED}✗ Невірний пароль для сервера '{profile.name}'.{RESET}", file=sys.stderr)
            return 1
        run_server_blocking(
            store,
            profile,
            host=args.host,
            override_port=args.port,
            return_hint="Натисни Ctrl+C щоб зупинити сервер.",
        )
        return 0

    return run_interactive_menu(store)


if __name__ == "__main__":
    raise SystemExit(main())
