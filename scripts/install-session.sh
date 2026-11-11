#!/usr/bin/env bash
# Установка обёртки сессии и записей для экрана входа (этап 1). Нужен root.
#
# По умолчанию ничего не меняет (dry-run). Режимы:
#   (без аргументов)  показать, что будет установлено
#   --apply           установить (запускать через sudo)
#   --remove          удалить установленное
#
# Ставятся только НОВЫЕ файлы (существующие файлы системы не перезаписываются):
#   /usr/local/bin/hyprland-session
#   /usr/share/wayland-sessions/hyprland-managed.desktop   ("Hyprland")
#   /usr/share/wayland-sessions/hyprland-safe.desktop      ("Hyprland (safe)")
# Стандартная сессия Hyprland из пакета и сессия KDE Plasma остаются нетронутыми,
# откат = --remove либо выбор другой сессии на экране входа.
# PAM и SDDM-конфиг не изменяются.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_SRC="$REPO/hypr/session/hyprland-session"
BIN_DST="/usr/local/bin/hyprland-session"
SESS_DIR="/usr/share/wayland-sessions"
DESKTOPS=(hyprland-managed.desktop hyprland-safe.desktop)

mode="dry-run"
case "${1:-}" in
    "") ;;
    --apply) mode="apply" ;;
    --remove) mode="remove" ;;
    *) echo "Неизвестный аргумент: $1" >&2; exit 2 ;;
esac

if [ "$mode" = "dry-run" ]; then
    echo "[dry-run] install -m 755 $BIN_SRC $BIN_DST"
    for d in "${DESKTOPS[@]}"; do
        echo "[dry-run] install -m 644 $REPO/hypr/session/$d $SESS_DIR/$d"
    done
    echo "Запустите с --apply (через sudo), чтобы установить."
    exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "Нужен root: запустите через sudo." >&2
    exit 1
fi

if [ "$mode" = "remove" ]; then
    rm -f "$BIN_DST"
    for d in "${DESKTOPS[@]}"; do rm -f "$SESS_DIR/$d"; done
    echo "Удалено."
    exit 0
fi

# Защита: не перезаписываем чужие файлы с теми же именами.
for f in "$BIN_DST" "${DESKTOPS[@]/#/$SESS_DIR/}"; do
    if [ -e "$f" ] && ! cmp -s "$f" "$REPO/hypr/session/$(basename "$f")"; then
        echo "Файл уже существует и отличается: $f. Установка остановлена." >&2
        exit 1
    fi
done

install -m 755 "$BIN_SRC" "$BIN_DST"
for d in "${DESKTOPS[@]}"; do
    install -m 644 "$REPO/hypr/session/$d" "$SESS_DIR/$d"
done
echo "Установлено. Откат: sudo bash scripts/install-session.sh --remove"
