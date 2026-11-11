import QtQuick

// Кнопка Aurora Glass.
Rectangle {
    id: b
    property string label: ""
    property color tint: Tk.primary
    property bool enabled: true
    signal clicked()
    implicitWidth: t.implicitWidth + 28
    implicitHeight: 32
    radius: 16
    opacity: enabled ? 1 : 0.4
    color: Tk.alpha(tint, m.containsMouse && enabled ? 0.34 : 0.18)
    border.color: Tk.alpha(tint, 0.65)
    border.width: 1
    Behavior on color { ColorAnimation { duration: Tk.durationFast } }
    Text {
        id: t
        anchors.centerIn: parent
        text: b.label
        color: Tk.text
        font.family: Tk.fontFamily
        font.pixelSize: Tk.sizeBody
    }
    MouseArea {
        id: m
        anchors.fill: parent
        hoverEnabled: true
        enabled: b.enabled
        cursorShape: Qt.PointingHandCursor
        onClicked: b.clicked()
    }
}
