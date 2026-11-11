import QtQuick
import Quickshell

// Простые часы на холсте (заготовка этапа 2; полноценные часы и календарь - этап 5).
// props: { "seconds": true|false }
Rectangle {
    id: root

    property var props: ({})
    property bool editing: false

    readonly property bool showSeconds: props.seconds !== false

    radius: Theme.radiusLarge
    color: Theme.alpha(Theme.surface, Theme.surfaceOpacity)
    border.color: Theme.alpha(Theme.border, 0.9)
    border.width: 1

    SystemClock {
        id: clock
        precision: root.showSeconds ? SystemClock.Seconds : SystemClock.Minutes
    }

    Column {
        anchors.centerIn: parent
        spacing: 4

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: Qt.formatDateTime(clock.date, root.showSeconds ? "HH:mm:ss" : "HH:mm")
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Math.max(18, Math.min(root.height * 0.38, root.width * 0.18))
            font.weight: Font.Light
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: Qt.formatDateTime(clock.date, "dddd, d MMMM")
            color: Theme.textMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.sizeBody
        }
    }
}
