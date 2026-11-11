#!/usr/bin/env bash
# Показывает встроенное уведомление Hyprland о запуске safe-сессии.
# Текст приходит из обёртки через HYPRDESK_NOTICE. Секретов здесь нет.
sleep 1
msg="${HYPRDESK_NOTICE:-Запущена безопасная сессия Hyprland (safe).}"
hyprctl notify 0 15000 "rgb(ffb86c)" "$msg"
