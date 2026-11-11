# Что нужно проверить на Fedora

Все автоматические тесты выполнялись на **Windows с моками** (dnf, Hyprland, Quickshell подменены).
Они проверяют логику, а не работу Linux-сессии. Ничего ниже не проверено, пока не отмечено вами.

Перед началом: `bash scripts/test-all.sh` на Fedora (тесты с настоящими симлинками на Windows пропускались).
Прислать: отметки ✓/✗, вывод `bash scripts/fedora-diagnose.sh` и тексты ошибок.

## A. Установка

- [ ] `bash install.sh --dry-run` показывает план без изменений; Fedora 45 определена
- [ ] На Live: предупреждение о временной установке; `login-session` не выбран по умолчанию
- [ ] `hyprland`: есть ли он в репозиториях; если нет, предупреждение о COPR и отдельный вопрос; `--yes` НЕ включает COPR
- [ ] После подтверждения COPR `sdegler/hyprland` ставится Hyprland 0.57.1 (`Hyprland --version`)
- [ ] Quickshell: пакет есть в репозиториях? Если нет, существует ли COPR `errornointernet/quickshell` (имя из `packages.toml` НЕ проверено)
- [ ] Имена rpm верны: `qt6-qtdeclarative`, `ffmpeg-free`, `mesa-va-drivers`, `libva-utils`, `mpv`, `kitty`, `fuzzel`
- [ ] `mpvpaper` в Fedora: есть или нет (если нет, установка продолжается с предупреждением)
- [ ] Повторный `bash install.sh` ничего лишнего не ставит и не пересоздаёт ссылки
- [ ] `ls -l ~/.config/hypr ~/.config/quickshell/hyprdesk ~/.local/bin/hyprown` указывают в репозиторий; прежние папки лежат в `~/.local/state/hyprdesk/backups`
- [ ] `bin/hyprown recovery rollback` возвращает прежние папки

## B. Конфиг и Quickshell

- [ ] `bin/hyprown config verify` без ошибок; `Hyprland --verify-config` не ругается на формат 0.57.1
- [ ] В живой сессии `bin/hyprown config fingerprint` → «значения совпадают» и `hyprctl configerrors` пусто
- [ ] `bin/hyprown shell probe` показывает опции `--path`/`--config`/`--no-duplicate` (**приложите вывод**: от него зависят стратегии запуска)
- [ ] Панель, виджеты, обои видны после входа; закрытие терминала их не убивает
- [ ] Повторный `bin/hyprown shell start` не создаёт вторую панель
- [ ] `kill -9 $(pgrep -x quickshell)`: супервизор поднимает оболочку снова (лог `quickshell.log`)
- [ ] Хоткеи через `hyprown ipc` работают: Super+E, Super+W, Super+Shift+W, Super+Ctrl+R
- [ ] Super+M и кнопка «⚙ Manager» на панели открывают Manager

## C. Сессии

- [ ] `bin/hyprown preview` из KDE: окно Hyprland с панелью, виджетами, обоями; Alt+Shift+E закрывает; KDE цел
- [ ] Preview не создаёт и не оставляет `session.marker`
- [ ] После `login-session`: на экране SDDM есть «Hyprland» и «Hyprland (safe)»; вход работает
- [ ] После аварии (`pkill -9 Hyprland`) следующий вход в safe; `recovery safe-mode on/off` работает

## D. Manager

- [ ] Все 10 разделов открываются без ошибок QML (`~/.local/state/hyprdesk/logs/manager.log`)
- [ ] `FloatingWindow` и закрытие окна завершают процесс (`Qt.quit()`)
- [ ] Components: «Установить» показывает план до действий; для dnf появляется запрос пароля polkit
- [ ] Активировать/Отключить/Удалить дают честные сообщения (горячо или «нужен перезапуск»)
- [ ] Performance: профили применяются через `hyprctl reload`
- [ ] Светлая тема переключается

## D2. Attach и клавиши (не проверялось на реальной графике)

Внутри обычной сессии Hyprland (не вложенной):

- [ ] `bin/hyprown session status` видит сессию и не путает её с чужим экземпляром.
- [ ] `bin/hyprown attach`: панель и обои появились без выхода; второго Hyprland нет.
- [ ] Повторный `attach` ничего не дублирует (`pgrep -a quickshell` показывает один процесс).
- [ ] Закрыть терминал: оболочка продолжает работать.
- [ ] `bin/hyprown detach`: Hyprland жив, оболочка остановлена; `detach --restore-config` вернул конфиги.
- [ ] В KDE `attach` отказывает с кодом 6 и объяснением.
- [ ] `bin/hyprown keys live`: Super+M, Super+E, Super+W, Super+Space, Super+Enter не заняты чужими привязками.
- [ ] Manager -> Keybinds: переназначить комбинацию, увидеть конфликт, применить; личное не затирается.
- [ ] Preview: комбинации с ALT работают (Alt+Space перехватывает KDE, редактор предупредит).

## E. Не реализовано (не ждите этого)

- Загрузчик модулей виджетов внутри `quickshell/hyprdesk` (манифесты и менеджер готовы, см. `docs/MODULES.md`)
- Автоматическое удаление системных пакетов (только вручную `dnf remove`)
- Интеграция `hyprpaper` и `hyprlock` (пакеты ставятся как необязательные компоненты, без конфигов)
- Отдельный графический установщик до установки Quickshell (первая установка всегда терминальная)
