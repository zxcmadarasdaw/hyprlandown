import QtQuick
import QtQuick.Layouts
import Quickshell

// HyprlandOwn Manager. Запуск: hyprown manager  (qs -p quickshell/manager/shell.qml).
// Работает от обычного пользователя; все действия идут через CLI hyprown (общий backend).
// Привилегированные шаги (dnf) подтверждаются отдельным системным запросом пароля.
ShellRoot {
    FloatingWindow {
        id: win
        title: "HyprlandOwn Manager"
        visible: true
        implicitWidth: 1040
        implicitHeight: 700
        color: Tk.bg
        onVisibleChanged: if (!visible) Qt.quit()

        property int page: 0
        readonly property var sections: [
            "Dashboard", "Components", "Dependencies", "Widgets", "Themes & Wallpapers",
            "Experimental Plugins", "Updates", "Diagnostics", "Recovery", "Performance"
        ]

        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: Tk.bg }
                GradientStop { position: 1.0; color: Qt.darker(Tk.surfaceAlt, 1.3) }
            }
        }

        RowLayout {
            anchors.fill: parent; anchors.margins: 14; spacing: 14

            Rectangle {
                Layout.preferredWidth: 220; Layout.fillHeight: true
                radius: Tk.radius; color: Tk.alpha(Tk.surface, 0.7); border.color: Tk.border; border.width: 1
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 10; spacing: 4
                    Text { text: "HyprlandOwn"; color: Tk.primary; font.pixelSize: Tk.sizeTitle; font.bold: true; font.family: Tk.fontFamily; Layout.bottomMargin: 8 }
                    Repeater {
                        model: win.sections
                        delegate: Rectangle {
                            required property string modelData
                            required property int index
                            Layout.fillWidth: true; height: 36; radius: 10
                            color: win.page === index ? Tk.alpha(Tk.primary, 0.28) : nav.containsMouse ? Tk.alpha(Tk.primary, 0.12) : "transparent"
                            Behavior on color { ColorAnimation { duration: Tk.durationFast } }
                            Text { anchors.verticalCenter: parent.verticalCenter; x: 12; text: modelData; color: Tk.text; font.pixelSize: Tk.sizeBody; font.family: Tk.fontFamily }
                            MouseArea { id: nav; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: win.page = index }
                        }
                    }
                    Item { Layout.fillHeight: true }
                    Btn { Layout.fillWidth: true; label: Tk.dark ? "Светлая тема" : "Тёмная тема"; tint: Tk.textMuted; onClicked: Tk.dark = !Tk.dark }
                }
            }

            Rectangle {
                Layout.fillWidth: true; Layout.fillHeight: true
                radius: Tk.radius; color: Tk.alpha(Tk.surface, 0.55); border.color: Tk.border; border.width: 1
                // Страница пересоздаётся при переключении: данные всегда свежие.
                Loader {
                    anchors.fill: parent; anchors.margins: 16
                    sourceComponent: [dash, comps, deps, widgets, themes, plugins, updates, diag, recovery, perf][win.page]
                }
            }
        }

        Component { id: dash; ActionPage {
            title: "Dashboard"; autoRun: "[\"status\",\"--json\"]"
            hint: "Версия, компоненты, состояние оболочки, профиль производительности."
            actions: [{label: "Обновить", args: ["status", "--json"]}, {label: "Готовность Desktop Mode", args: ["desktop", "--json"]}]
        } }
        Component { id: comps; ComponentsPage { title: "Components"; filter: "all" } }
        Component { id: deps; ActionPage {
            title: "Dependencies"; autoRun: "[\"deps\",\"--json\"]"
            hint: "Пакеты, нужные компонентам проекта, и что из них не установлено. Ставятся через Components."
            actions: [{label: "Проверить снова", args: ["deps", "--json"]}]
        } }
        Component { id: widgets; ComponentsPage { title: "Widgets"; filter: "widget" } }
        Component { id: themes; ActionPage {
            title: "Themes & Wallpapers"
            hint: "Обои переключаются живьём через IPC оболочки. Темы по токенам появятся на этапе 4 (docs/TOKENS.md)."
            actions: [
                {label: "Следующие обои", args: ["ipc", "wallpaper", "next"]},
                {label: "Предыдущие", args: ["ipc", "wallpaper", "prev"]},
                {label: "Сетка превью", args: ["ipc", "wallpaper", "picker"]},
                {label: "Статус обоев", args: ["ipc", "wallpaper", "status"]},
                {label: "Сбросить на градиент", args: ["ipc", "wallpaper", "reset"], confirm: true}
            ]
        } }
        Component { id: plugins; ComponentsPage { title: "Experimental Plugins"; filter: "experimental" } }
        Component { id: updates; ActionPage {
            title: "Updates"
            hint: "Обновляется только репозиторий проекта (git pull --ff-only) со снимком состояния. Сеть используется только по нажатию."
            actions: [
                {label: "Проверить обновления", args: ["update", "check", "--json"]},
                {label: "Обновить", args: ["--yes", "update", "apply", "--json"], confirm: true},
                {label: "Применить без перезапуска сессии", args: ["update", "reload"]}
            ]
        } }
        Component { id: diag; DiagnosticsPage {} }
        Component { id: recovery; ActionPage {
            title: "Recovery"; autoRun: "[\"recovery\",\"list\"]"
            hint: "Снимки состояния, откат последней установки, принудительный safe-режим. Откат возвращает сохранённые копии конфигов, пакеты не удаляются."
            actions: [
                {label: "Список", args: ["recovery", "list"]},
                {label: "Сделать снимок", args: ["recovery", "snapshot", "manual"]},
                {label: "Откатить последнюю установку", args: ["--yes", "recovery", "rollback"], confirm: true, tint: "danger"},
                {label: "Safe-режим при следующем входе: вкл", args: ["recovery", "safe-mode", "on"]},
                {label: "Safe-режим: выкл", args: ["recovery", "safe-mode", "off"]},
                {label: "Сбросить состояние оболочки", args: ["recovery", "reset-shell"], confirm: true, tint: "danger"}
            ]
        } }
        Component { id: perf; ActionPage {
            title: "Performance"; autoRun: "[\"perf\",\"get\",\"--json\"]"
            hint: "quality: как в appearance.conf. balanced: мягче блюр и тени. lite: без блюра, теней и анимаций. Применяется горячо (hyprctl reload)."
            actions: [
                {label: "quality", args: ["perf", "set", "quality"]},
                {label: "balanced", args: ["perf", "set", "balanced"]},
                {label: "lite", args: ["perf", "set", "lite"]},
                {label: "Текущий профиль", args: ["perf", "get", "--json"]}
            ]
        } }
    }
}
