#!/usr/bin/env bash
# Симлинк hypr/ из репозитория в ~/.config/hypr (этап 1).
#
# По умолчанию ничего не меняет (dry-run). Режимы:
#   (без аргументов)  показать, что будет сделано
#   --apply           сделать резервную копию текущего ~/.config/hypr и создать симлинк
#   --rollback        вернуть последнюю резервную копию, убрав симлинк
#
# Резервные копии лежат в ~/.local/state/hyprdesk/backups.
# Права root не нужны, /usr и PAM не затрагиваются.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO/hypr"
TARGET="${XDG_CONFIG_HOME:-$HOME/.config}/hypr"
BACKUP_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/hyprdesk/backups"
LAST_FILE="$BACKUP_DIR/last-backup"

mode="dry-run"
case "${1:-}" in
    "") ;;
    --apply) mode="apply" ;;
    --rollback) mode="rollback" ;;
    *) echo "Неизвестный аргумент: $1" >&2; exit 2 ;;
esac

if [ "$mode" = "rollback" ]; then
    [ -r "$LAST_FILE" ] || { echo "Нет записи о резервной копии: $LAST_FILE" >&2; exit 1; }
    backup=$(cat "$LAST_FILE")
    if [ "$backup" != "none" ] && [ ! -e "$backup" ]; then
        echo "Резервная копия не найдена: $backup" >&2
        exit 1
    fi
    if [ -L "$TARGET" ]; then
        rm "$TARGET"
    elif [ -e "$TARGET" ]; then
        echo "$TARGET существует и не симлинк, откат остановлен." >&2
        exit 1
    fi
    if [ "$backup" = "none" ]; then
        # Раньше ~/.config/hypr не существовал: откат = убрать симлинк.
        echo "Симлинк убран, ~/.config/hypr отсутствует, как до установки."
        exit 0
    fi
    mv "$backup" "$TARGET"
    echo "Восстановлено из $backup"
    exit 0
fi

echo "Источник: $SRC"
echo "Цель:     $TARGET"

if [ -L "$TARGET" ] && [ "$(readlink "$TARGET")" = "$SRC" ]; then
    echo "Симлинк уже настроен, делать нечего."
    exit 0
fi

if [ "$mode" = "dry-run" ]; then
    if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
        echo "[dry-run] текущий $TARGET будет перемещён в $BACKUP_DIR/hypr.<время>"
    fi
    echo "[dry-run] будет создан симлинк $TARGET -> $SRC"
    echo "Запустите с --apply, чтобы применить."
    exit 0
fi

mkdir -p "$BACKUP_DIR" "$(dirname "$TARGET")"
backup="none"
if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
    backup="$BACKUP_DIR/hypr.$(date +%Y%m%d-%H%M%S)"
    mv "$TARGET" "$backup"
    echo "Резервная копия: $backup"
fi

# Атомарная запись записи об откате.
tmp=$(mktemp "$LAST_FILE.XXXXXX")
printf '%s\n' "$backup" >"$tmp"
mv -f "$tmp" "$LAST_FILE"

ln -s "$SRC" "$TARGET"
echo "Готово: $TARGET -> $SRC"
echo "Откат: bash scripts/link-configs.sh --rollback"
