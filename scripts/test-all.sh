#!/usr/bin/env bash
# Все автоматические тесты проекта одной командой: bash scripts/test-all.sh
# Работает на Linux и на Windows (Git Bash). Систему не меняет: dnf, Hyprland и
# Quickshell подменены (tests/helpers.py). Тесты с настоящими симлинками
# пропускаются там, где их нельзя создать (Windows без прав), на Fedora идут все.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY=python3; command -v python3 >/dev/null 2>&1 || PY=python
rc=0
echo "== bash: проверка синтаксиса скриптов"
for f in install.sh bin/hyprown scripts/*.sh hypr/session/hyprland-session hypr/scripts/*.sh; do
    bash -n "$f" || { echo "СИНТАКСИС: $f"; rc=1; }
done
echo "== python: unittest (установщик, зависимости, конфиги, shell, сессии, менеджер, откат)"
PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 "$PY" -W ignore -m unittest discover -s . -t . -p "test_*.py" || rc=1
echo "== bash: обёртка сессии (этап 1)"
bash scripts/test-session-wrapper.sh | tail -n 2 || rc=1
if command -v node >/dev/null 2>&1; then
    echo "== node: логика Quickshell (этапы 2-3)"
    node scripts/test-qs-logic.js | tail -n 1 || rc=1
else
    echo "node не найден: тест логики Quickshell пропущен"
fi
[ "$rc" -eq 0 ] && echo "ВСЁ ЗЕЛЁНОЕ (на этой системе, см. docs/FEDORA_VERIFY.md)" || echo "ЕСТЬ ОШИБКИ"
exit "$rc"
