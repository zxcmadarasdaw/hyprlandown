import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland

// Панель сверху (этап 2): рабочие пространства, часы, статус.
// Своя на каждом мониторе; рабочие пространства - только этого монитора.
PanelWindow {
    id: bar

    required property var modelData
    screen: modelData

    readonly property string monName: modelData.name
    readonly property var hyprMonitor: Hyprland.monitorFor(modelData)
    readonly property int activeWs: (hyprMonitor && hyprMonitor.activeWorkspace) ? hyprMonitor.activeWorkspace.id : -1

    anchors {
        top: true
        left: true
        right: true
    }
    implicitHeight: 40
    WlrLayershell.namespace: "hyprdesk-bar"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    color: "transparent"

    // Рабочие пространства 1-5 видны всегда, остальные - если существуют на этом мониторе.
    readonly property var wsIds: {
        const ids = [1, 2, 3, 4, 5];
        const all = Hyprland.workspaces.values;
        for (let i = 0; i < all.length; i++) {
            const ws = all[i];
            if (ws.id > 0 && ws.monitor && ws.monitor.name === monName && ids.indexOf(ws.id) < 0)
                ids.push(ws.id);
        }
        return ids.sort((a, b) => a - b);
    }

    function wsExists(id) {
        const all = Hyprland.workspaces.values;
        for (let i = 0; i < all.length; i++)
            if (all[i].id === id) return true;
        return false;
    }

    SystemClock {
        id: clock
        precision: SystemClock.Minutes
    }

    Rectangle {
        anchors.fill: parent
        anchors.topMargin: 6
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        radius: Theme.radiusMedium
        color: Theme.alpha(Theme.surface, 0.82)
        border.color: Theme.alpha(Theme.border, 0.9)
        border.width: 1

        // Рабочие пространства
        Row {
            anchors.left: parent.left
            anchors.leftMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6

            Repeater {
                model: bar.wsIds
                delegate: Rectangle {
                    required property int modelData
                    readonly property bool active: modelData === bar.activeWs
                    readonly property bool exists: Hyprland.workspaces.values && bar.wsExists(modelData)

                    width: active ? 34 : 24
                    height: 22
                    radius: 11
                    color: active ? Theme.primary
                         : wsMouse.containsMouse ? Theme.alpha(Theme.primary, 0.3)
                         : exists ? Theme.alpha(Theme.text, 0.14) : "transparent"
                    border.color: Theme.alpha(Theme.text, exists || active ? 0 : 0.25)
                    border.width: 1

                    Behavior on width {
                        NumberAnimation { duration: Theme.durationFast; easing.type: Easing.OutCubic }
                    }

                    Text {
                        anchors.centerIn: parent
                        text: parent.modelData
                        color: parent.active ? Theme.bg : Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.sizeSmall
                        font.bold: parent.active
                    }

                    MouseArea {
                        id: wsMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: Hyprland.dispatch("workspace " + parent.modelData)
                    }
                }
            }
        }

        // Часы
        Text {
            anchors.centerIn: parent
            text: Qt.formatDateTime(clock.date, "HH:mm  ·  ddd d MMM")
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.sizeBody
        }

        // Статус
        Row {
            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6

            StatusChip {
                visible: CanvasStore.editMode
                label: "✎ Редактирование: готово"
                tint: Theme.primary
                onClicked: CanvasStore.setEditMode(false)
            }
            StatusChip {
                visible: CanvasStore.readOnly || WallpaperStore.readOnly
                label: "⚠ Состояние от новой версии: не сохраняется"
                tint: Theme.warning
            }
            StatusChip {
                visible: bar.monName in WallpaperStore.videoErrors
                label: "⚠ Видео-обои не запустились"
                tint: Theme.error
                onClicked: WallpaperStore.openPicker(bar.monName)
            }
            StatusChip {
                readonly property real zoom: CanvasStore.zooms[bar.monName] || 1
                label: Math.round(zoom * 100) + "%"
                tint: Theme.textMuted
                onClicked: CanvasStore.cameraResetRequested(bar.monName)
            }
            StatusChip {
                label: "▦ Обои"
                tint: Theme.accent
                onClicked: WallpaperStore.openPicker(bar.monName)
            }
        }
    }
}
