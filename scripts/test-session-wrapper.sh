#!/usr/bin/env bash
# Тест обёртки hyprland-session с поддельным Hyprland.
# Работает только во временных каталогах, систему и ~/.config не трогает.
# Запуск: bash scripts/test-session-wrapper.sh

set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WRAPPER="$REPO/hypr/session/hyprland-session"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

export HYPRDESK_STATE_DIR="$TMP/state"
export HYPRDESK_CONF_DIR="$TMP/conf"
export XDG_RUNTIME_DIR="$TMP"
export FAKE_LOG="$TMP/fake.log"
export HYPRLAND_BIN="$TMP/fakehypr"
export HYPRDESK_GRACE_SEC=0
export FAKE_PID="$TMP/fake.pid"
MARKER="$HYPRDESK_STATE_DIR/session.marker"

mkdir -p "$HYPRDESK_CONF_DIR/safe"
touch "$HYPRDESK_CONF_DIR/hyprland.conf" "$HYPRDESK_CONF_DIR/safe/hyprland-safe.conf"

cat >"$HYPRLAND_BIN" <<'EOF'
#!/usr/bin/env bash
echo "$@" >>"$FAKE_LOG"
echo $$ >"$FAKE_PID"
case "${FAKE_MODE:-exit0}" in
    exit0) exit 0 ;;
    crash) exit 1 ;;
    hang) sleep 30 ;;
    slow-exit0) sleep 1; exit 0 ;;
    stubborn) trap '' TERM; sleep 30 ;;
esac
EOF
chmod +x "$HYPRLAND_BIN"

pass=0
fail=0
check() {
    if eval "$2"; then
        echo "PASS: $1"
        pass=$((pass + 1))
    else
        echo "FAIL: $1"
        fail=$((fail + 1))
    fi
}
last_args() { tail -n 1 "$FAKE_LOG" 2>/dev/null; }
reset() { rm -rf "$HYPRDESK_STATE_DIR"; : >"$FAKE_LOG"; }

# 1. Штатный выход: маркера нет после, запущен основной конфиг.
reset
FAKE_MODE=exit0 bash "$WRAPPER"
check "штатный выход снимает маркер" '[ ! -e "$MARKER" ]'
check "обычный старт берёт основной конфиг" 'last_args | grep -q "hyprland.conf"'

# 2. Аварийный выход: маркер остаётся.
reset
FAKE_MODE=crash bash "$WRAPPER"
check "аварийный выход оставляет маркер" '[ -e "$MARKER" ]'

# 3. Следующий вход при маркере: safe-конфиг; штатный выход снимает маркер.
FAKE_MODE=exit0 bash "$WRAPPER"
check "при маркере стартует safe-конфиг" 'last_args | grep -q "hyprland-safe.conf"'
check "штатный выход из safe снимает маркер" '[ ! -e "$MARKER" ]'

# 4. После этого вход снова обычный.
FAKE_MODE=exit0 bash "$WRAPPER"
check "после снятия маркера вход снова обычный" 'last_args | grep -q "hyprland.conf" && ! last_args | grep -q safe'

# 4b. Флаг force-safe (hyprown recovery safe-mode on): safe-режим без аварии,
# --force-normal его обходит, после снятия флага вход снова обычный.
reset
mkdir -p "$HYPRDESK_STATE_DIR"
: >"$HYPRDESK_STATE_DIR/force-safe"
FAKE_MODE=exit0 bash "$WRAPPER"
check "force-safe запускает safe-конфиг" 'last_args | grep -q "hyprland-safe.conf"'
FAKE_MODE=exit0 bash "$WRAPPER" --force-normal
check "--force-normal обходит force-safe" 'last_args | grep -q "hyprland.conf" && ! last_args | grep -q safe'
rm -f "$HYPRDESK_STATE_DIR/force-safe"
FAKE_MODE=exit0 bash "$WRAPPER"
check "без флага вход снова обычный" 'last_args | grep -q "hyprland.conf" && ! last_args | grep -q safe'

# 5. Явный --safe без маркера.
reset
FAKE_MODE=exit0 bash "$WRAPPER" --safe
check "--safe запускает safe-конфиг" 'last_args | grep -q "hyprland-safe.conf"'

# 6. --force-normal игнорирует маркер.
reset
FAKE_MODE=crash bash "$WRAPPER"
FAKE_MODE=exit0 bash "$WRAPPER" --force-normal
check "--force-normal игнорирует маркер" 'last_args | grep -q "hyprland.conf" && ! last_args | grep -q safe'

# 7. Сигнал TERM самой обёртке = завершение сеанса, маркер снимается.
reset
FAKE_MODE=hang bash "$WRAPPER" &
wpid=$!
sleep 1
kill -TERM "$wpid" 2>/dev/null
wait "$wpid" 2>/dev/null
check "TERM обёртке считается штатным выходом" '[ ! -e "$MARKER" ]'

# 8. Нет основного конфига: safe-сессия.
reset
mv "$HYPRDESK_CONF_DIR/hyprland.conf" "$TMP/hyprland.conf.off"
FAKE_MODE=exit0 bash "$WRAPPER"
check "нет основного конфига: стартует safe" 'last_args | grep -q "hyprland-safe.conf"'
mv "$TMP/hyprland.conf.off" "$HYPRDESK_CONF_DIR/hyprland.conf"

# 9. Нет safe-конфига: аварийный минимальный.
reset
mv "$HYPRDESK_CONF_DIR/safe/hyprland-safe.conf" "$TMP/safe.off"
FAKE_MODE=exit0 bash "$WRAPPER" --safe
check "нет safe-конфига: аварийный минимальный" 'last_args | grep -q "hyprdesk-safe"'
mv "$TMP/safe.off" "$HYPRDESK_CONF_DIR/safe/hyprland-safe.conf"

# 10. --dry-run ничего не запускает и не пишет.
reset
out=$(bash "$WRAPPER" --dry-run)
check "--dry-run не создаёт маркер и не запускает Hyprland" '[ ! -e "$MARKER" ] && [ ! -s "$FAKE_LOG" ]'
check "--dry-run показывает режим" 'echo "$out" | grep -q "mode=normal"'

# 11. Атомарная запись: рядом с маркером нет временных файлов.
reset
FAKE_MODE=crash bash "$WRAPPER"
check "после записи маркера нет временных файлов" '[ "$(ls "$HYPRDESK_STATE_DIR" | grep -c "session.marker\.")" -eq 0 ]'

# 12. Аварийный конфиг из теста 9 удалён после выхода.
check "аварийный конфиг удаляется после выхода" '! ls "$TMP"/hyprdesk-safe.* >/dev/null 2>&1'

# 13. TERM снимает маркер сразу, даже если Hyprland не выходит
#     и обёртку потом добивают SIGKILL (таймаут systemd при выключении).
reset
FAKE_MODE=stubborn bash "$WRAPPER" &
wpid=$!
sleep 1
kill -TERM "$wpid" 2>/dev/null
sleep 0.5
check "TERM снимает маркер до завершения Hyprland" '[ ! -e "$MARKER" ]'
kill -KILL "$wpid" 2>/dev/null
kill -KILL "$(cat "$FAKE_PID" 2>/dev/null)" 2>/dev/null
wait "$wpid" 2>/dev/null

# 14. Гонка при выключении: Hyprland упал раньше, сигнал обёртке пришёл
#     в течение GRACE_SEC -> штатный выход.
reset
HYPRDESK_GRACE_SEC=3 FAKE_MODE=crash bash "$WRAPPER" &
wpid=$!
sleep 0.7
kill -TERM "$wpid" 2>/dev/null
wait "$wpid" 2>/dev/null
check "сигнал в окне ожидания после падения = штатный выход" '[ ! -e "$MARKER" ]'

# 15. Чужой маркер (вторая сессия перезаписала его) не снимается.
reset
FAKE_MODE=slow-exit0 bash "$WRAPPER" &
wpid=$!
sleep 0.5
printf 'started=0\npid=1\ntoken=foreign\nmode=normal\n' >"$MARKER"
wait "$wpid" 2>/dev/null
check "штатный выход не снимает маркер другой сессии" 'grep -qx "token=foreign" "$MARKER"'

echo
echo "Итог: PASS=$pass FAIL=$fail"
[ "$fail" -eq 0 ]
