# Архитектура установщика и менеджера

## Принцип

Один backend (`hyprown/`), несколько оболочек над ним: терминальный установщик, графический
Manager, тесты, другие ИИ. Оболочки не содержат логики установки, они вызывают
CLI `bin/hyprown` и читают его JSON.

## Модули backend

| Модуль | Роль (по ТЗ) | Что делает |
|---|---|---|
| `manifest.py` | Component Registry (данные) | Читает и проверяет `packages.toml` и `component.toml`. Доверие: хэш манифеста |
| `registry.py` | Component Registry | Каталог компонентов и состояние (`components.json`: установлен/включён/ошибка) |
| `resolver.py` | Dependency Resolver | Замыкание по `requires`, порядок, проверка циклов, план пакетов (есть / в репозитории / нужен COPR / недоступен) |
| `pkg.py` | Package Manager Adapter | Единственное место, знающее про dnf/rpm: present, available, version, copr, install |
| `config.py` | Configuration Manager | Ссылки с резервными копиями и откатом, рендер конфигов, `--verify-config`, отпечаток запущенной сессии, профили производительности |
| `session.py` | Session Manager | Preview Mode, готовность Desktop Mode, поиск запущенного Hyprland |
| `shell.py` | (часть Session Manager) | Супервизор Quickshell, IPC, запуск Manager |
| `updater.py` | Update Manager | `git fetch/pull --ff-only` со снимком, горячая перезагрузка |
| `recovery.py` | Recovery Manager | Снимки состояния, журнал установок и откат, принудительный safe-режим |
| `diagnostics.py` | Diagnostics Engine | Проверки только для чтения, общие для терминала, Manager и скриптов |
| `installer.py` | оркестратор | План -> подтверждения -> применение -> проверка -> журнал; удаление, активация |
| `runner.py` | инфраструктура | Единственный `subprocess`; `dry_run`; повышение прав; `FakeRunner` для тестов |
| `ui.py` | инфраструктура | Терминальный интерфейс (шаги с таймером, без выдуманных процентов) и `JsonUI` (JSONL) |
| `system.py` | инфраструктура | ОС, Live USB, GPU, место на диске, тип сессии |
| `context.py` | инфраструктура | `Ctx`: пути, окружение, раннер. Тесты подставляют временные каталоги |

## Поток установки

```
install.sh → bin/hyprown install
  1. detect(): ОС, Live, GPU, место                      (system.py)
  2. выбор компонентов: меню или --components             (cli.py)
  3. build_plan(): замыкание зависимостей, статусы пакетов,
     блокировки, предупреждения, оценка места             (resolver.py, installer.py)
  4. показ плана, подтверждение                           (ничего не изменено до этого места)
  5. apply():
       снимок состояния + журнал транзакции
       COPR: отдельный запрос на каждый источник, --yes НЕ соглашается
       dnf install по компонентам (ошибка одного не ломает остальные)
       ссылки на конфиги с резервной копией
       login-session: scripts/install-session.sh через sudo/pkexec после подтверждения
       отметка в components.json
  6. проверка: ссылки, shell.qml, синтаксис конфига, версии
  7. предложение Preview / Desktop / Manager
```

Привилегированные действия: только `dnf ...` и `scripts/install-session.sh`. Графический Manager
работает от пользователя; для `dnf` появляется системный запрос polkit (`pkexec`).

## Конфиги: как гарантируется «используется наш»

1. Установщик создаёт ссылки `~/.config/hypr` и `~/.config/quickshell/hyprdesk` на репозиторий
   (компоненты `desktop-core`, `quickshell-shell`), существующее уходит в резервную копию.
2. Preview и проверки используют `config.render()`: самодостаточный конфиг с абсолютными путями
   (в Preview ещё `$mainMod = ALT`) и явный `Hyprland -c`.
3. Запущенная сессия проверяется по **отпечатку**: значения `rounding`, `gaps_in`, `gaps_out`
   из `hypr/appearance.conf` сравниваются с `hyprctl -j getoption`. Стандартные значения Hyprland
   другие, поэтому автогенерированный конфиг распознаётся (`bin/hyprown config fingerprint`).
4. Профиль производительности лежит в `~/.local/state/hyprdesk/performance.conf`, его подключает
   `hypr/hyprland.conf`; рендер создаёт файл, чтобы `source` не указывал в пустоту.

## Quickshell: жизненный цикл

`exec-once = ~/.local/bin/hyprown shell run` запускает **супервизор** (`shell.py`):

1. находит `shell.qml` (`HYPRDESK_SHELL_DIR`, затем `~/.config/quickshell/hyprdesk`, затем репозиторий) и берёт realpath;
2. читает `qs --help` и строит стратегии: `-p <shell.qml>` → `-p <каталог>` → `-c hyprdesk`;
3. держит один экземпляр на сессию Hyprland (pid-файл в `$XDG_RUNTIME_DIR/hyprown`);
4. перезапускает после падения; быстрое падение (< 3 с) переключает стратегию; больше 5 падений за минуту: отказ и уведомление;
5. штатный выход (код 0 после долгой работы) не воскрешает; исчезновение Wayland-сокета завершает супервизор;
6. лог: `~/.local/state/hyprdesk/logs/quickshell.log`; запущен в новой сессии процессов, терминал не нужен.

IPC (`hyprown ipc canvas toggleEdit`) использует тот же селектор, что запустил оболочку
(`~/.local/state/hyprdesk/shell.json`).

## Сессии

- **Preview**: `Hyprland -c <рендер>` вложенным окном внутри KDE, маркер аварии реальной сессии не трогается.
- **Desktop**: только через SDDM. Компонент `login-session` ставит `/usr/local/bin/hyprland-session`
  и две записи в `/usr/share/wayland-sessions` (существующие файлы не перезаписываются).
  Обёртка сама уходит в safe-режим после аварии или при флаге `force-safe`.

## Live USB

Определяется по `rd.live.image`/`root=live:` в `/proc/cmdline`. Установщик: предупреждает, что всё
пропадёт после перезагрузки, проверяет свободное место, не ставит `login-session` по умолчанию,
не трогает загрузчик и разделы.

## Графический установщик (архитектура)

Quickshell на чистой Live-системе может отсутствовать, поэтому первая установка всегда через CLI.
Графический установщик: тот же Manager в режиме «Setup»: окно получает план из
`hyprown plan --json`, показывает его, а установку запускает `hyprown --json-stream --yes install`
и рисует события `step_start/step_end/warn/error/result`. Протокол уже используется страницей
Components. Оформление: Aurora Glass (`quickshell/manager/Tk.qml`, тёмная и светлая тема).
Отдельного бинарного установщика, который работал бы без Qt, не планируется.

## Что не делается

Загрузчик, разделы, PAM, SDDM-конфиг, пароли, автоматическое переключение работающей сессии KDE,
автоматическое удаление системных пакетов.
