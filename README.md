# dotfiles: рабочий стол Fedora + Hyprland + Quickshell

Конфигурация рабочего стола на Fedora Linux: Hyprland как композитор,
Quickshell для виджетов и панелей, SDDM с собственной QML-темой для экрана входа.

## Быстрый старт (Fedora 45 KDE, в том числе Live USB)

```bash
git clone https://github.com/zxcmadarasdaw/hyprlandown.git && cd hyprlandown
bash install.sh          # меню, план, подтверждение, установка зависимостей и конфигов
bin/hyprown preview      # рабочий стол окном внутри KDE
bin/hyprown manager      # графический менеджер компонентов
```

Подробно: `AGENTS.md` (для людей и ИИ), `docs/ARCHITECTURE.md`, `docs/MODULES.md`,
`docs/TROUBLESHOOTING.md`, `docs/FEDORA_VERIFY.md` (что ещё не проверено на Fedora).
Ручная пошаговая установка (устарела, оставлена для справки): `FEDORA_SETUP.txt`.

Полное техническое задание и план этапов: `PROJECT_BRIEF_v5.txt`
(копия лежит в docs/).

## Структура

```
dotfiles/
├── hypr/        конфиги Hyprland (hyprland.conf, monitors.conf, input.conf, keybinds.conf)
├── quickshell/hyprdesk/  оболочка: обои, холст виджетов, панель (qs -c hyprdesk)
│   ├── shell.qml           слои по мониторам + IPC для хоткеев
│   └── lib/*.js            логика камеры и обоев (тесты: scripts/test-qs-logic.js)
├── wallpapers/  тестовые обои (SVG)
├── sddm/        тема экрана входа (QML)
├── docs/        документация, чек-листы, описание GPU_SWITCH и тестов
│   ├── TOKENS.md              схема токенов темы (версия схемы 1)
│   ├── tokens.default.json    пример значений: Aurora Glass
│   ├── STAGE1_CHECKLIST.md    чек-лист проверки этапа 1 на Fedora
│   └── STAGE2_3_CHECKLIST.md  чек-лист этапов 2 и 3
├── hyprown/     backend установщика и менеджера (Python): install, doctor, preview, shell, recovery
├── components/  манифесты компонентов (модули), manifests/packages.toml: справочник пакетов
├── bin/hyprown  CLI проекта; install.sh: точка входа установщика
├── quickshell/manager/  графический HyprlandOwn Manager
├── tests/       Python-тесты (запуск: bash scripts/test-all.sh)
├── scripts/     test-all.sh, fedora-diagnose.sh, install-session.sh, link-configs.sh, тесты этапов 1-3
├── versions.txt проверенные версии Hyprland, Quickshell, SDDM и плагинов
└── install.sh   установщик (тонкая точка входа в hyprown)
```

## Статус

Этап 0 (подготовка) готов. Этап 1 (Hyprland: база и safe-сессия): файлы
написаны, ревью обёртки (Opus) сделано, ждут проверки на Fedora по
`docs/STAGE1_CHECKLIST.md`. Установка не выполнялась.

Этапы 2 (Quickshell: холст виджетов и панель) и 3 (обои: картинки, видео
через mpvpaper, сетка превью): код написан, логика покрыта тестами
(`node scripts/test-qs-logic.js`), QML проверен qmllint на синтаксис.
В живом Quickshell/Hyprland не запускался — проверка по `docs/STAGE2_3_CHECKLIST.md`.

## Установка и менеджер (этап 4а)

Реализованы единый установщик (`install.sh`), Preview Mode, супервизор Quickshell, система модулей
(`components/`), основа HyprlandOwn Manager, диагностика, откат и safe-режим. Логика проверена
тестами на Windows с моками; **на Fedora не запускалась**: `docs/FEDORA_VERIFY.md`.
Выбор GPU (amd/nvidia, этап 14) пока определяется автоматически и только для декодера видео-обоев.

## Правила

- Пароли, токены и приватные данные не сохраняются в репозитории.
- Механизм проверки пароля (PAM) не меняется.
- Экспериментальные плагины необязательны: система работает без них.
- Любое изменение, которое может сделать систему неработоспособной, сначала
  резервируется и проверяется на откат.
