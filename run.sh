#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/sewwprog/WiGi.c1.git"
INSTALL_DIR="${WIGI_DIR:-$HOME/WiGi.c1}"
BRANCH="${WIGI_BRANCH:-main}"

if ! command -v git >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then
  echo "Встановлюю git та python3..."
  sudo apt-get update && sudo apt-get install -y git python3
fi

if [ -d "$INSTALL_DIR/.git" ]; then
  echo "Оновлюю WiGi з GitHub ($BRANCH)..."
  git -C "$INSTALL_DIR" fetch origin "$BRANCH" --quiet || true
  git -C "$INSTALL_DIR" checkout "$BRANCH" --quiet 2>/dev/null || true
  git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH" || true
else
  echo "Завантажую WiGi з GitHub у $INSTALL_DIR..."
  git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# Якщо скрипт запущено через pipe (curl ... | bash), підключаємо клавіатуру термінала
if [ ! -t 0 ] && ( : < /dev/tty ) 2>/dev/null; then
  exec python3 main.py "$@" < /dev/tty
else
  exec python3 main.py "$@"
fi
