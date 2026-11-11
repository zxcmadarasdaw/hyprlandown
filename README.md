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

## Подключение к текущей сессии Hyprland (Live Session Attach)

Если вы уже в Hyprland, HyprlandOwn подключается **к этой же сессии**: без выхода из системы и без
второго композитора внутри первого.

```bash
bin/hyprown attach          # подключить (первый пункт меню install.sh внутри Hyprland)
bin/hyprown session status  # что запущено и кем
bin/hyprown detach          # отключить наши процессы, Hyprland остаётся
```

В KDE Attach недоступен (там нет Hyprland): используйте `bin/hyprown preview`. Конфиги меняются только
с резервной копией; что требует нового входа (например, смена основного конфига), откладывается с
предупреждением. Процессы Session Manager не зависят от терминала, не дублируются и не трогают
чужие процессы. Подробности: `docs/ARCHITECTURE.md`, проверка на Fedora: `docs/FEDORA_VERIFY.md`.

## Горячие клавиши

Единый реестр: `manifests/keybinds.toml`. `hypr/keybinds.conf` из него **генерируется** (руками не править).
Личные переназначения лежат в `~/.local/state/hyprdesk/keybinds.user.conf` и не перезаписываются без
вашего разрешения. Редактор: HyprlandOwn Manager, раздел Keybinds; в терминале: `bin/hyprown keys list|check|set|reset|live|verify`.
Назначение проверяется на конфликты с реестром, с живыми привязками `hyprctl binds` и со стандартными привязками Hyprland
(раскладка основных клавиш как в стандартном Hyprland: Super+Q терминал, Super+C закрыть окно, Super+M выход, Super+E файловый менеджер; Manager на Super+D).

## Цвета и темы (этап 4)

Пять готовых тем (Aurora Glass, Cyber Terminal, Developer Workspace, Gaming Mode, Cinema & Music) и режим
«палитра из обоев»: цвета берутся из картинки или первого кадра видео и пересчитываются при смене обоев.
Любой виджет можно перекрасить; его цвета не сбрасываются при смене обоев и темы.

```bash
bin/hyprown theme list                          # темы
bin/hyprown theme set cyber-terminal            # готовая тема
bin/hyprown theme mode wallpaper                # палитра из текущих обоев
bin/hyprown theme override clock-1 palette.primary=#FFB86C   # свой цвет виджета
bin/hyprown theme reset                         # стандартная палитра (цвета виджетов остаются)
```

Ctrl+Alt+F открывает выбор темы на рабочем столе; настройки: HyprlandOwn Manager, раздел Themes & Wallpapers.
Для палитры из обоев нужен `ffmpeg` (или ImageMagick). Схема токенов: `docs/TOKENS.md`.

## Правила

- Пароли, токены и приватные данные не сохраняются в репозитории.
- Механизм проверки пароля (PAM) не меняется.
- Экспериментальные плагины необязательны: система работает без них.
- Любое изменение, которое может сделать систему неработоспособной, сначала
  резервируется и проверяется на откат.
