# AGENTS.md: как работать с HyprlandOwn (для ИИ-агентов и людей)

Прочитайте этот файл целиком до любых действий. Он описывает, что делает проект,
как его правильно запускать и где нельзя ошибаться.

## Что это

HyprlandOwn: рабочий стол на **Fedora 45 KDE** (в том числе Live USB):
**Hyprland 0.57.1** + **Quickshell/QML** (панель, холст виджетов, обои).
Проект ставит себя сам: одна команда показывает меню, план и после подтверждения
устанавливает зависимости, подключает конфиги и предлагает запуск.

Репозиторий: https://github.com/zxcmadarasdaw/hyprlandown
Разработка идёт на Windows (`E:\HyprlandLinux\dotfiles`), проверка только на Fedora.

## Как запускать (человек)

```bash
git clone https://github.com/zxcmadarasdaw/hyprlandown.git && cd hyprlandown
bash install.sh            # меню, план, подтверждение, установка
bin/hyprown preview        # рабочий стол окном внутри KDE
bin/hyprown desktop        # как войти в полноценную сессию (через SDDM)
bin/hyprown manager        # графический менеджер компонентов
bin/hyprown doctor         # диагностика
```

`install.sh` запускать **от обычного пользователя**: sudo спросит пароль только
для `dnf` и записей экрана входа. Целиком от root не запускать.

## Как запускать (ИИ-агент, без интерактива)

| Нужно | Команда |
|---|---|
| План без изменений | `bin/hyprown --plain plan --json` |
| Установить | `bin/hyprown --plain --yes install --components desktop-core,quickshell-shell` |
| Установить без сторонних репозиториев | добавить `--no-copr` |
| Состояние для UI | `bin/hyprown status --json` |
| Диагностика | `bin/hyprown doctor --json` |
| Событийный поток для GUI | `bin/hyprown --json-stream --yes component install ID` |
| Откат | `bin/hyprown recovery rollback` |
| Подключить к текущей сессии Hyprland | `bin/hyprown --yes attach --json` (отключить: `detach`) |
| Процессы сессии | `bin/hyprown session status --json` (`start-all`, `restart-all`, `stop-all`) |
| Горячие клавиши | `bin/hyprown keys list --json`, `keys check`, `keys set ... --apply --yes` |

Правила вызова:

- `--yes` подтверждает действия заранее, **кроме подключения стороннего COPR**: на COPR
  `--yes` отвечает «нет». COPR включается только живым «да» в терминале.
- Без `--yes` и без терминала команды, меняющие систему, **отказывают**, а не гадают.
- `--dry-run`: только план, ничего не меняется.
- Коды выхода: 0 успех, 1 ошибка выполнения, 2 план с проблемами или неверные аргументы,
  3 нет графической/Wayland-сессии, 4 нет Quickshell, 5 нет `shell.qml`,
  6 Attach невозможен (нет сессии Hyprland или это KDE).
- Не используйте `sudo bin/hyprown ...`: повышение прав делает сам backend, только для
  `dnf` и `scripts/install-session.sh`.

## Архитектура в одном абзаце

Вся логика в Python-пакете `hyprown/` (только стандартная библиотека, Python 3.11+).
`install.sh`, `bin/hyprown`, графический Manager (`quickshell/manager`) и тесты используют **один**
backend. Не дублируйте логику установки в shell-скриптах: добавляйте её в пакет.
Подробно: `docs/ARCHITECTURE.md`.

```
install.sh ──► bin/hyprown ──► hyprown/cli.py ──► installer ─► resolver ─► registry (manifests)
Manager QML ─► bin/hyprown --json ─┘                 │            │
                                                     ├─ pkg.py (dnf), config.py (ссылки, рендер, проверка)
                                                     ├─ session.py (Preview, Desktop), shell.py (Quickshell)
                                                     └─ recovery.py, updater.py, diagnostics.py
```

## Карта файлов

| Путь | Назначение |
|---|---|
| `install.sh` | Тонкая точка входа, зовёт `bin/hyprown install` |
| `bin/hyprown` | Шим: находит репозиторий (даже через симлинк), запускает `python -m hyprown` |
| `hyprown/` | Backend: `cli`, `installer`, `resolver`, `registry`, `manifest`, `pkg`, `config`, `session`, `shell`, `procman`, `attach`, `sessenv`, `menu`, `keybinds`, `recovery`, `updater`, `diagnostics`, `system`, `runner`, `ui`, `context` |
| `manifests/keybinds.toml` | **Единый реестр горячих клавиш.** `hypr/keybinds.conf` из него генерируется (`keys render --write`), руками не править. Личные правки: `~/.local/state/hyprdesk/keybinds.user.conf` |
| `manifests/packages.toml` | Центральный справочник пакетов (rpm, COPR-источники, проверки версий) |
| `components/<id>/component.toml` | Манифесты компонентов (доверенный каталог проекта) |
| `hypr/` | Конфиги Hyprland (этап 1) |
| `hypr/session/hyprland-session` | Обёртка сессии с маркером аварии и safe-режимом |
| `quickshell/hyprdesk/` | Панель, холст, обои (этапы 2-3) |
| `quickshell/manager/` | Графический HyprlandOwn Manager |
| `scripts/` | `install-session.sh` (root-помощник), `link-configs.sh` (обёртка), `test-all.sh`, `fedora-diagnose.sh` |
| `tests/` | Python-тесты (моки, без реальной системы) |
| `docs/` | Архитектура, модули, проверка на Fedora, диагностика проблем |

## Границы безопасности (нарушать нельзя)

- Не менять загрузчик, разделы, PAM, SDDM-конфиг; не удалять KDE; не трогать Windows.
- Не сохранять пароли и токены; не запускать код из интернета.
- Пользовательские конфиги не перезаписываются без резервной копии (`~/.local/state/hyprdesk/backups`).
- Привилегии только через `Runner.run(..., privileged=True)` после подтверждения.
- Манифесты **описывают, а не исполняют**: в них нельзя указать команду, скрипт или
  произвольный пакет. Новые виды действий добавляются в код, а не в манифест.
- Не делайте `git push` без разрешения владельца.
- Attach/Session Manager: не запускать второй Hyprland, не завершать чужие процессы (kill только
  после проверки владения по pid-файлу и cmdline), не менять SDDM, KDE, загрузчик, драйверы.
- Горячие клавиши: новую привязку добавлять в `manifests/keybinds.toml`, а не в `hypr/*.conf`;
  пользовательские комбинации не перезаписывать без явного разрешения (`keys set` проверяет конфликты).
- Флаги `--yes`, `--json`, `--plain` допустимы и до, и после подкоманды. `--yes` не отвечает «да» на
  вопросы `yes_ok` (COPR и подобные).

## Как добавить компонент (модуль)

1. Создайте `components/<id>/component.toml` (схема: `docs/MODULES.md`).
2. Новые пакеты добавьте в `manifests/packages.toml`, в манифесте компонента ссылайтесь по id.
3. Запустите `bash scripts/test-all.sh`: тест проверит манифест, существование источников ссылок и порядок зависимостей.
4. Менеджер увидит компонент автоматически (`bin/hyprown component list`).

## Тесты

```bash
bash scripts/test-all.sh      # синтаксис скриптов, Python-тесты, обёртка сессии, логика QML
```

Важно: тесты на Windows используют моки. **Они не доказывают, что сессия Linux работает.**
Что требует проверки на Fedora: `docs/FEDORA_VERIFY.md`. Не утверждайте, что Linux-сессия
протестирована, пока этот чек-лист не пройден на Fedora.

## Известные факты о проблемах запуска

Первопричины и способ проверки: `docs/TROUBLESHOOTING.md`. Коротко:

- «You're using an autogenerated config» значит, Hyprland не нашёл `~/.config/hypr/hyprland.conf`.
  `Hyprland --verify-config` этого не доказывает и не опровергает: проверяйте
  **запущенную** сессию командой `bin/hyprown config fingerprint`.
- `qs -p` ждёт путь к **файлу** `shell.qml`; `qs -c имя` ищет `~/.config/quickshell/имя`.
  Запуск идёт только через `bin/hyprown shell run`.

## Стиль и язык

Комментарии, сообщения пользователю и документация на русском. Код без лишней сложности,
каждый модуль backend отвечает за одну область. Файлы с LF-переводами строк (`.gitattributes`).
