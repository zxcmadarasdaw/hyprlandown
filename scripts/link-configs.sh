#!/usr/bin/env bash
# Симлинки конфигов из репозитория в ~/.config (этапы 1-3):
#   hypr/                -> ~/.config/hypr
#   quickshell/hyprdesk/ -> ~/.config/quickshell/hyprdesk
#
# По умолчанию ничего не меняет (dry-run). Режимы:
#   (без аргументов)  показать, что будет сделано
#   --apply           сделать резервную копию текущих папок и создать симлинки
#   --rollback        вернуть последние резервные копии, убрав симлинки
#
# Резервные копии лежат в ~/.local/state/hyprdesk/backups, запись об откате
# для каждой цели своя (last-backup-<имя>). Права root не нужны, /usr и PAM не затрагиваются.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
BACKUP_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/hyprdesk/backups"

# имя | источник | цель
LINKS=(
    "hypr|$REPO/hypr|$CONF/hypr"
    "quickshell|$REPO/quickshell/hyprdesk|$CONF/quickshell/hyprdesk"
)

mode="dry-run"
case "${1:-}" in
    "") ;;
    --apply) mode="apply" ;;
    --rollback) mode="rollback" ;;
    *) echo "Неизвестный аргумент: $1" >&2; exit 2 ;;
esac

record_file() {
    # Этап 1 писал запись для hypr в файл last-backup: читаем её, если новой нет.
    local name=$1
    if [ "$name" = "hypr" ] && [ ! -e "$BACKUP_DIR/last-backup-hypr" ] && [ -e "$BACKUP_DIR/last-backup" ]; then
        echo "$BACKUP_DIR/last-backup"
    else
        echo "$BACKUP_DIR/last-backup-$name"
    fi
}

atomic_write() {
    local target=$1 tmp
    tmp=$(mktemp "$target.XXXXXX")
    cat >"$tmp"
    mv -f "$tmp" "$target"
}

rollback_one() {
    local name=$1 target=$2 rec backup
    rec=$(record_file "$name")
    if [ ! -r "$rec" ]; then
        echo "[$name] нет записи о резервной копии ($rec), пропускаю."
        return 0
    fi
    backup=$(cat "$rec")
    if [ "$backup" != "none" ] && [ ! -e "$backup" ]; then
        echo "[$name] резервная копия не найдена: $backup" >&2
        return 1
    fi
    if [ -L "$target" ]; then
        rm "$target"
    elif [ -e "$target" ]; then
        echo "[$name] $target существует и не симлинк, откат остановлен." >&2
        return 1
    fi
    if [ "$backup" = "none" ]; then
        echo "[$name] симлинк убран, $target отсутствует, как до установки."
    else
        mv "$backup" "$target"
        echo "[$name] восстановлено из $backup"
    fi
    rm -f "$rec"
}

apply_one() {
    local name=$1 src=$2 target=$3 backup="none"
    echo "[$name] $target -> $src"
    if [ -L "$target" ] && [ "$(readlink "$target")" = "$src" ]; then
        echo "[$name] симлинк уже настроен, делать нечего."
        return 0
    fi
    if [ "$mode" = "dry-run" ]; then
        if [ -e "$target" ] || [ -L "$target" ]; then
            echo "[dry-run] текущий $target будет перемещён в $BACKUP_DIR/$name.<время>"
        fi
        echo "[dry-run] будет создан симлинк $target -> $src"
        return 0
    fi
    mkdir -p "$BACKUP_DIR" "$(dirname "$target")"
    if [ -e "$target" ] || [ -L "$target" ]; then
        backup="$BACKUP_DIR/$name.$(date +%Y%m%d-%H%M%S)"
        mv "$target" "$backup"
        echo "[$name] резервная копия: $backup"
    fi
    printf '%s\n' "$backup" | atomic_write "$BACKUP_DIR/last-backup-$name"
    ln -s "$src" "$target"
    echo "[$name] готово."
}

status=0
for entry in "${LINKS[@]}"; do
    IFS='|' read -r name src target <<<"$entry"
    if [ "$mode" = "rollback" ]; then
        rollback_one "$name" "$target" || status=1
    else
        apply_one "$name" "$src" "$target" || status=1
    fi
done

case "$mode" in
    dry-run) echo "Запустите с --apply, чтобы применить." ;;
    apply) echo "Откат: bash scripts/link-configs.sh --rollback" ;;
esac
exit "$status"
