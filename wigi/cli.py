"""Interactive terminal (CLI) launcher for creating, selecting, and running servers."""

from __future__ import annotations

import os
import select
import socket
import sys

from wigi.network import find_free_port, get_lan_ip, is_port_free
from wigi.server import WiGiHTTPServer
from wigi.storage import ServerProfile, ServerStore

# ANSI color helpers
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"


def init_terminal() -> None:
    """Configure UTF-8 console I/O and enable ANSI colors on Windows terminals."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except Exception:
                pass
    if os.name == "nt":
        os.system("")


def read_password(prompt: str = "Пароль: ") -> str:
    """Read a password in the terminal showing `*` for each character typed."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        sys.stdout.write(prompt)
        sys.stdout.flush()
        line = sys.stdin.readline()
        if not line:
            raise EOFError
        sys.stdout.write("\n")
        sys.stdout.flush()
        return line.rstrip("\r\n")

    sys.stdout.write(prompt)
    sys.stdout.flush()
    chars: list[str] = []

    if os.name == "nt":
        import msvcrt

        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(chars)
            if ch == "\x03":
                sys.stdout.write("\n")
                sys.stdout.flush()
                raise KeyboardInterrupt
            if ch == "\x08":
                if chars:
                    chars.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if ch in ("\x00", "\xe0"):
                msvcrt.getwch()
                continue
            if ch.isprintable():
                chars.append(ch)
                sys.stdout.write("*")
                sys.stdout.flush()
    else:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while True:
                b = os.read(fd, 1)
                if not b:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return "".join(chars)
                code = b[0]

                if code in (0x0D, 0x0A):
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return "".join(chars)
                if code == 0x03:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    raise KeyboardInterrupt
                if code == 0x04 and not chars:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    raise EOFError
                if code in (0x7F, 0x08):
                    if chars:
                        chars.pop()
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                    continue
                if code == 0x1B:
                    # Drain escape sequences (e.g. arrow keys)
                    while select.select([fd], [], [], 0.03)[0]:
                        os.read(fd, 1)
                    continue

                # Decode full UTF-8 character
                extra = 0
                if (code & 0xE0) == 0xC0:
                    extra = 1
                elif (code & 0xF0) == 0xE0:
                    extra = 2
                elif (code & 0xF8) == 0xF0:
                    extra = 3

                raw = bytearray(b)
                for _ in range(extra):
                    raw.extend(os.read(fd, 1))

                ch = bytes(raw).decode("utf-8", errors="ignore")
                if ch and ch.isprintable():
                    chars.append(ch)
                    sys.stdout.write("*")
                    sys.stdout.flush()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def prompt_line(prompt: str) -> str:
    sys.stdout.write(prompt)
    sys.stdout.flush()
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    return line.strip()


def print_banner() -> None:
    hostname = socket.gethostname()
    lan_ip = get_lan_ip()
    print()
    print(f"{CYAN}{BOLD}============================================================{RESET}")
    print(f"{CYAN}{BOLD}   WiGi — Python Серверне Середовище (Термінал-менеджер){RESET}")
    print(f"{DIM}   Пристрій: {hostname}  |  IP у мережі: {lan_ip}{RESET}")
    print(f"{CYAN}{BOLD}============================================================{RESET}")


def print_servers_summary(servers: list[ServerProfile]) -> None:
    if not servers:
        print(f"\n  {DIM}Створених серверів поки немає.{RESET}")
        return

    print(f"\n  {BOLD}Збережені сервери ({len(servers)}):{RESET}")
    for idx, srv in enumerate(servers, start=1):
        last_info = f"останній запуск: {srv.last_started_at}" if srv.last_started_at else f"створено: {srv.created_at}"
        print(f"    {CYAN}{idx}.{RESET} {BOLD}{srv.name}{RESET}  {DIM}(порт {srv.port}, {last_info}){RESET}")


def run_server_blocking(
    store: ServerStore,
    profile: ServerProfile,
    host: str = "0.0.0.0",
    override_port: int | None = None,
    return_hint: str = "Натисни Ctrl+C щоб зупинити сервер і повернутись у меню.",
) -> None:
    """Start the HTTP/API server for `profile` and block until Ctrl+C / SIGTERM."""
    desired_port = override_port if override_port is not None else profile.port
    if is_port_free(desired_port, host):
        port = desired_port
    else:
        port = find_free_port(desired_port + 1)
        print(
            f"\n  {YELLOW}! Порт {desired_port} зараз зайнятий — вибрано вільний порт {port}.{RESET}"
        )

    updated = store.mark_started(profile.id, port=port) or profile
    workspace_dir = store.ensure_workspace(updated)
    lan_ip = get_lan_ip()

    print()
    print(f"{GREEN}{BOLD}------------------------------------------------------------{RESET}")
    print(f"  {GREEN}●{RESET} {BOLD}Сервер активний:{RESET} {updated.name}")
    print(f"  {BOLD}Браузер (цей ноут):{RESET}   http://localhost:{port}")
    print(f"  {BOLD}У локальній мережі:{RESET}   http://{lan_ip}:{port}")
    print(f"  {BOLD}Папка середовища:{RESET}     {workspace_dir}")
    print(f"  {BOLD}Можливості панелі:{RESET}    Файли/Код • Термінал/Python • Git/GitHub • ENV")
    print(f"{GREEN}{BOLD}------------------------------------------------------------{RESET}")
    print(f"  {DIM}{return_hint}{RESET}\n")

    httpd = WiGiHTTPServer((host, port), updated, workspace_dir, store=store)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(f"\n  {YELLOW}Зупиняю сервер '{updated.name}'...{RESET}")
    finally:
        httpd.server_close()
        print(f"  {GREEN}✓ Сервер зупинено.{RESET}")


def flow_create_server(store: ServerStore) -> None:
    print(f"\n{BOLD}--- Створення нового сервера ---{RESET}")
    print(f"{DIM}(Залиш назву порожньою, щоб скасувати){RESET}")

    while True:
        name = prompt_line("  Назва сервера: ")
        if not name:
            print(f"  {DIM}Створення скасовано.{RESET}")
            return
        if store.get_by_name(name) is not None:
            print(f"  {RED}✗ Сервер з назвою '{name}' вже існує. Спробуй іншу назву.{RESET}")
            continue
        break

    while True:
        password = read_password("  Пароль сервера: ")
        if not password:
            print(f"  {RED}✗ Пароль не може бути порожнім.{RESET}")
            continue
        break

    default_port = find_free_port(8000)
    while True:
        raw_port = prompt_line(f"  Порт [Enter = {default_port}]: ")
        if not raw_port:
            port = default_port
            break
        if raw_port.isdigit() and 1 <= int(raw_port) <= 65535:
            port = int(raw_port)
            break
        print(f"  {RED}✗ Введи коректне число порту від 1 до 65535.{RESET}")

    profile = store.create_server(name=name, password=password, port=port)
    print(f"\n  {GREEN}✓ Сервер '{profile.name}' успішно створено!{RESET}")

    ans = prompt_line("  Запустити цей сервер зараз? [Y/n]: ").lower()
    if ans in ("", "y", "yes", "д", "да", "т", "так", "1"):
        run_server_blocking(store, profile)


def _select_server_from_list(servers: list[ServerProfile], title: str) -> ServerProfile | None:
    if not servers:
        print(f"\n  {YELLOW}Немає жодного створеного сервера. Спочатку створи новий (пункт 1).{RESET}")
        return None

    print(f"\n{BOLD}--- {title} ---{RESET}")
    for idx, srv in enumerate(servers, start=1):
        print(f"  [{idx}] {srv.name} {DIM}(порт {srv.port}){RESET}")
    print("  [0] Назад")

    choice = prompt_line("\n  Вибери номер або назву сервера: ")
    if not choice or choice == "0":
        return None

    if choice.isdigit():
        num = int(choice)
        if 1 <= num <= len(servers):
            return servers[num - 1]
        print(f"  {RED}✗ Невірний номер у списку.{RESET}")
        return None

    for srv in servers:
        if srv.name.lower() == choice.lower():
            return srv

    print(f"  {RED}✗ Сервер '{choice}' не знайдено.{RESET}")
    return None


def _prompt_verify_password(profile: ServerProfile) -> bool:
    for attempt in range(1, 4):
        pw = read_password(f"  Пароль сервера '{profile.name}': ")
        if not pw:
            print(f"  {DIM}Скасовано.{RESET}")
            return False
        if profile.verify_password(pw):
            return True
        remaining = 3 - attempt
        if remaining > 0:
            print(f"  {RED}✗ Невірний пароль (залишилось спроб: {remaining}).{RESET}")
        else:
            print(f"  {RED}✗ Невірний пароль. Доступ відхилено.{RESET}")
    return False


def flow_select_and_start(store: ServerStore) -> None:
    servers = store.list_servers()
    selected = _select_server_from_list(servers, "Вибір сервера для запуску")
    if selected is None:
        return

    if not _prompt_verify_password(selected):
        return

    print(f"  {GREEN}✓ Пароль підтверджено.{RESET}")
    run_server_blocking(store, selected)


def flow_manage_server(store: ServerStore) -> None:
    servers = store.list_servers()
    selected = _select_server_from_list(servers, "Керування сервером")
    if selected is None:
        return

    if not _prompt_verify_password(selected):
        return

    ws_path = store.ensure_workspace(selected)
    print(f"\n  {BOLD}Сервер:{RESET} {selected.name}  {DIM}(ID: {selected.id}, порт: {selected.port}){RESET}")
    print(f"  {BOLD}Папка:{RESET}  {ws_path}")
    if selected.description:
        print(f"  {BOLD}Опис:{RESET}   {selected.description}")

    print(f"\n  {BOLD}Дії з сервером:{RESET}")
    print(f"    {CYAN}[1]{RESET} Перейменувати / змінити опис")
    print(f"    {CYAN}[2]{RESET} Змінити пароль")
    print(f"    {CYAN}[3]{RESET} Змінити порт")
    print(f"    {CYAN}[4]{RESET} Клонувати сервер (створити копію середовища)")
    print(f"    {CYAN}[0]{RESET} Назад")

    sub = prompt_line("\n  Вибір > ")
    if sub == "1":
        new_name = prompt_line(f"  Нова назва [{selected.name}]: ") or selected.name
        new_desc = prompt_line(f"  Опис [{selected.description}]: ")
        try:
            updated = store.rename_server(
                selected.id,
                new_name=new_name,
                description=new_desc if new_desc else selected.description,
            )
            print(f"  {GREEN}✓ Оновлено назву сервера: '{updated.name}'.{RESET}")
        except ValueError as exc:
            print(f"  {RED}✗ {exc}{RESET}")
    elif sub == "2":
        new_pw = read_password("  Новий пароль сервера: ")
        if not new_pw:
            print(f"  {YELLOW}Пароль не може бути порожнім.{RESET}")
            return
        store.change_password(selected.id, new_pw)
        print(f"  {GREEN}✓ Пароль сервера '{selected.name}' змінено.{RESET}")
    elif sub == "3":
        raw_port = prompt_line(f"  Новий порт (поточний {selected.port}): ")
        if raw_port.isdigit() and 1 <= int(raw_port) <= 65535:
            store.change_port(selected.id, int(raw_port))
            print(f"  {GREEN}✓ Новий порт збережено: {raw_port}.{RESET}")
        else:
            print(f"  {RED}✗ Некоректний порт.{RESET}")
    elif sub == "4":
        clone_name = prompt_line(f"  Назва для копії (напр. {selected.name}-copy): ")
        if not clone_name:
            return
        clone_pw = read_password("  Пароль для копії сервера: ")
        if not clone_pw:
            print(f"  {RED}✗ Пароль не може бути порожнім.{RESET}")
            return
        try:
            cloned = store.clone_server(
                source_id=selected.id,
                new_name=clone_name,
                new_password=clone_pw,
                port=find_free_port(selected.port + 1),
            )
            print(f"  {GREEN}✓ Створено копію сервера '{cloned.name}' (порт {cloned.port}).{RESET}")
        except ValueError as exc:
            print(f"  {RED}✗ {exc}{RESET}")


def flow_delete_server(store: ServerStore) -> None:
    servers = store.list_servers()
    selected = _select_server_from_list(servers, "Видалення сервера")
    if selected is None:
        return

    if not _prompt_verify_password(selected):
        return

    confirm = prompt_line(
        f"  Точно видалити сервер '{selected.name}' разом з його папкою? [y/N]: "
    ).lower()
    if confirm in ("y", "yes", "д", "да", "т", "так"):
        store.delete_server(selected.id, remove_workspace=True)
        print(f"  {GREEN}✓ Сервер '{selected.name}' видалено.{RESET}")
    else:
        print(f"  {DIM}Видалення скасовано.{RESET}")


def run_interactive_menu(store: ServerStore) -> int:
    """Main interactive terminal loop."""
    init_terminal()

    while True:
        try:
            print_banner()
            servers = store.list_servers()
            print_servers_summary(servers)

            print(f"\n  {BOLD}Меню:{RESET}")
            print(f"    {CYAN}[1]{RESET} Створити новий сервер (назва + пароль)")
            print(f"    {CYAN}[2]{RESET} Вибрати вже створений сервер")
            if servers:
                print(f"    {CYAN}[3]{RESET} Керування сервером (назва / пароль / порт / клон)")
                print(f"    {CYAN}[4]{RESET} Видалити сервер")
            print(f"    {CYAN}[0]{RESET} Вихід")

            choice = prompt_line("\n  Твій вибір > ")

            if choice == "1":
                flow_create_server(store)
            elif choice == "2":
                flow_select_and_start(store)
            elif choice == "3" and servers:
                flow_manage_server(store)
            elif choice == "4" and servers:
                flow_delete_server(store)
            elif choice in ("0", "q", "exit", "вихід"):
                print(f"\n  {DIM}До зустрічі!{RESET}")
                return 0
            else:
                print(f"  {YELLOW}Обери пункт меню (1, 2{', 3, 4' if servers else ''} або 0).{RESET}")
        except (KeyboardInterrupt, EOFError):
            print(f"\n\n  {DIM}Вихід із терміналу WiGi.{RESET}")
            return 0
