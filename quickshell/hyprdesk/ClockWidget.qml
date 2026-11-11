import QtQuick
import Quickshell

// Простые часы на холсте (заготовка этапа 2; полноценные часы и календарь - этап 5).
// props: { "seconds": true|false }
Rectangle {
    id: root

    property var props: ({})
    // Тема виджета: WidgetTheme с его переопределениями (WidgetFrame) или общая root.tk.
    property var tk: Theme
    property bool editing: false

    readonly property bool showSeconds: props.seconds !== false

    radius: root.tk.radiusLarge
    color: root.tk.alpha(root.tk.surface, root.tk.surfaceOpacity)
    border.color: root.tk.alpha(root.tk.border, 0.9)
    border.width: root.tk.borderWidth

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
            color: root.tk.text
            font.family: root.tk.fontFamily
            font.pixelSize: Math.max(18, Math.min(root.height * 0.38, root.width * 0.18))
            font.weight: Font.Light
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: Qt.formatDateTime(clock.date, "dddd, d MMMM")
            color: root.tk.textMuted
            font.family: root.tk.fontFamily
            font.pixelSize: root.tk.sizeBody
        }
    }
}
