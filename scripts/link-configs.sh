#!/usr/bin/env bash
# Совместимая обёртка: ссылки конфигов теперь создаёт общий backend (hyprown).
#   (без аргументов)  показать, что будет сделано
#   --apply           сделать резервные копии и создать ссылки
#   --rollback        вернуть резервные копии
# Формат записей отката (~/.local/state/hyprdesk/backups/last-backup-<имя>) тот же,
# что в этапах 1-3, поэтому ранее созданные копии откатываются без изменений.
set -euo pipefail
HP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/bin/hyprown"
case "${1:-}" in
    "") exec bash "$HP" --dry-run config link ;;
    --apply) exec bash "$HP" config link ;;
    --rollback) exec bash "$HP" config unlink ;;
    *) echo "Неизвестный аргумент: $1" >&2; exit 2 ;;
esac
