#!/usr/bin/env bash
# Отдельная программа диагностики Fedora для HyprlandOwn. Ничего не меняет и не
# устанавливает, не требует Python и root. Сохраняет отчёт, который можно
# прислать целиком: bash scripts/fedora-diagnose.sh
# Отчёт: ~/hyprown-diagnose-<время>.txt. Пароли и токены не собираются;
# переменные окружения выводятся только из белого списка.
set -u
OUT="${1:-$HOME/hyprown-diagnose-$(date +%Y%m%d-%H%M%S).txt}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sec() { printf '\n===== %s =====\n' "$*"; }
run() { printf '$ %s\n' "$*"; "$@" 2>&1 | head -n 60; }
{
sec "Система"
run cat /etc/os-release
run uname -a
echo "cmdline: $(cat /proc/cmdline 2>/dev/null)"
case "$(cat /proc/cmdline 2>/dev/null)" in *rd.live.image*|*root=live:*) echo "РЕЖИМ: Live USB";; *) echo "РЕЖИМ: установленная система";; esac
run systemd-detect-virt
run df -h / "$HOME" /tmp
run free -m
sec "Сессия"
for v in XDG_SESSION_TYPE XDG_CURRENT_DESKTOP WAYLAND_DISPLAY DISPLAY XDG_RUNTIME_DIR HYPRLAND_INSTANCE_SIGNATURE HYPRDESK_SESSION_MODE; do
    echo "$v=${!v:-}"
done
sec "GPU"
for c in /sys/class/drm/card[0-9]; do echo "$c vendor=$(cat "$c/device/vendor" 2>/dev/null)"; done
command -v lspci >/dev/null && lspci | grep -iE 'vga|3d|display'
sec "Пакеты"
for b in Hyprland hyprctl qs quickshell kitty fuzzel mpv mpvpaper ffmpeg hyprpaper hyprlock python3 git; do
    printf '%-12s %s\n' "$b" "$(command -v "$b" || echo 'НЕТ')"
done
run Hyprland --version
run qs --version
sec "CLI Quickshell (точный интерфейс установленной версии)"
run qs --help
run qs ipc --help
sec "Репозитории dnf"
command -v dnf >/dev/null && { run dnf copr list; run dnf repolist; run dnf -q repoquery --available hyprland quickshell mpvpaper; }
sec "Ссылки конфигов"
for p in "$HOME/.config/hypr" "$HOME/.config/quickshell/hyprdesk" "$HOME/.local/bin/hyprown"; do
    if [ -L "$p" ]; then echo "$p -> $(readlink "$p") (цель: $( [ -e "$p" ] && echo есть || echo ОТСУТСТВУЕТ ))"
    elif [ -e "$p" ]; then echo "$p: обычный файл/каталог (НЕ ссылка)"; else echo "$p: НЕТ"; fi
done
echo "Проект: $ROOT"
ls -l "$ROOT/quickshell/hyprdesk/shell.qml"
sec "Записи входа"
ls -l /usr/share/wayland-sessions/ /usr/local/bin/hyprland-session 2>&1
sec "Запущенная сессия Hyprland (если есть)"
if command -v hyprctl >/dev/null && [ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]; then
    run hyprctl configerrors
    run hyprctl version
    run hyprctl -j getoption decoration:rounding
    run hyprctl -j getoption general:gaps_out
    echo "(в нашем конфиге rounding=22, gaps_out=10; 0 и 20 значит автогенерированный конфиг)"
else
    echo "Hyprland не запущен в этом терминале."
fi
sec "Процессы"
pgrep -a 'qs|quickshell|Hyprland|mpvpaper' 2>&1 | head
sec "Состояние HyprlandOwn"
S="${XDG_STATE_HOME:-$HOME/.local/state}/hyprdesk"
ls -la "$S" 2>&1 | head -30
for f in logs/quickshell.log logs/hyprown.log logs/preview.log session.log; do
    echo "--- $f (хвост)"; tail -n 25 "$S/$f" 2>&1
done
sec "hyprown doctor"
[ -x "$ROOT/bin/hyprown" ] && bash "$ROOT/bin/hyprown" --plain doctor 2>&1 | head -n 80
} >"$OUT" 2>&1
echo "Отчёт сохранён: $OUT"
