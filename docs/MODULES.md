# Система модулей

Любая будущая функция (Media Hub, Calendar Widget, Workspace Universe, Liquid Glass, Window Physics,
Dynamic Islands, Terminal Overlay, Login Screen Studio) подключается как **компонент**:
папка `components/<id>/` с файлом `component.toml`. Менеджер находит её сам (`hyprown component list`).

## Доверие

- **Доверенный каталог**: `components/` в репозитории. Компоненты оттуда можно ставить.
- **Недоверенный каталог**: `~/.local/share/hyprown/catalog/<имя>/component.toml`. Виден в менеджере,
  но не ставится, пока пользователь не выполнит `hyprown trust <id>` после просмотра манифеста.
  Одобрение привязано к sha256 файла: любое изменение его снимает.
  Недоверенный манифест не может просить системные файлы (`session.system_files`), `session-files` и `copr`.
  Он не может занять id доверенного компонента.
- В манифесте **нет исполняемых полей**: нельзя указать команду, скрипт, URL или имя пакета, которого
  нет в `manifests/packages.toml`. Пути ссылок только относительные внутри репозитория (без `..`),
  назначения только под `@config/`, `@data/`, `@bin/`.

## Схема `component.toml` (schema = 1)

```toml
schema = 1
id = "calendar-widget"            # a-z, 0-9, дефис; 2-41 символ
name = "Calendar Widget"
version = "0.1.0"
summary = "Одна строка для менеджера."
kind = "widget"                   # core | widget | theme | plugin | tool
default = false                   # предлагается ли в установщике по умолчанию
experimental = false              # попадёт в раздел Experimental Plugins
requires = ["quickshell-shell"]   # другие компоненты (ставятся первыми)
permissions = ["packages", "user-config"]
                                  # packages | copr | user-config | session-files | autostart

[compat]                          # совместимость
fedora_min = 42
hyprland_min = "0.50.0"

[packages]                        # только id из manifests/packages.toml
required = ["quickshell"]         # без них компонент не ставится
recommended = ["ffmpeg"]          # без них ставится, но с предупреждением
[packages.gpu]
amd = ["mesa-va"]                 # дополнительно, если найдена такая видеокарта

[[links]]                         # способ установки: ссылки (с резервной копией)
name = "calendar"                 # имя записи отката
src = "quickshell/calendar"       # относительно репозитория
dst = "@config/quickshell/calendar"

[session]
system_files = false              # true: только для доверенных (записи экрана входа, нужен root)

[activation]
mode = "quickshell-restart"       # none | quickshell-restart | hyprland-reload | relogin
```

## Жизненный цикл

| Действие | Что происходит | Откат |
|---|---|---|
| Установить | план -> подтверждение -> пакеты -> ссылки -> отметка | `hyprown recovery rollback` возвращает копии конфигов; пакеты остаются |
| Активировать | `enabled = true` и действие `activation.mode` | Отключить |
| Отключить | `enabled = false` и то же действие | Активировать |
| Удалить | ссылки возвращаются к копиям, отметка снимается; пакеты не удаляются | переустановка |

Честность активации: `quickshell-restart` перезапускает только оболочку (горячо); `hyprland-reload`
выполняет `hyprctl reload`; `relogin` говорит, что нужен выход и вход, и сам ничего не перезапускает.
Если оболочка не запущена, менеджер так и пишет: «применится при запуске».

## Что нужно доделать для виджетов

Манифест и менеджер готовы, но загрузчик модулей внутри `quickshell/hyprdesk` ещё не написан: сейчас
`CanvasWindow` знает только встроенные виджеты (часы, заметка). Для первого настоящего виджета-модуля
нужно: договориться о каталоге `Widget.qml` в модуле и читать список включённых модулей из
`components.json` в оболочке. Это отдельный этап; контракт манифеста при этом не изменится.

## Пример: добавить hyprlock как компонент (уже сделано)

См. `components/hyprlock/component.toml`: 10 строк, пакет из `packages.toml`, по умолчанию выключен.
