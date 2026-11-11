#!/usr/bin/env bash
# Установщик HyprlandOwn. Запуск: bash install.sh
#
# Это тонкая точка входа: вся логика живёт в Python-пакете hyprown и общая
# для терминала и графического Manager (docs/ARCHITECTURE.md). Скрипт сам
# ничего не устанавливает: он показывает меню, план и спрашивает подтверждение.
# Параметры передаются дальше, например:
#   bash install.sh --dry-run          только показать план
#   bash install.sh --yes              без вопросов (кроме стороннего COPR)
#   bash install.sh --components desktop-core,quickshell-shell
#   bash install.sh --no-copr          не подключать сторонние репозитории
set -eu

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$(id -u)" -eq 0 ]; then
    echo "Не запускайте установщик от root: конфиги должны принадлежать вашему пользователю." >&2
    echo "Запустите: bash install.sh  (пароль sudo будет запрошен только для dnf и записей входа)." >&2
    exit 1
fi

exec bash "$ROOT/bin/hyprown" install "$@"
