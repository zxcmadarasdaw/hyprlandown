import QtQuick

// Кнопка-метка статуса в панели.
Rectangle {
    id: chip

    property string label: ""
    property color tint: Theme.primary

    signal clicked()

    width: text.implicitWidth + 20
    height: 24
    radius: 12
    color: Theme.alpha(tint, mouse.containsMouse ? 0.32 : 0.18)
    border.color: Theme.alpha(tint, 0.6)
    border.width: 1

    Text {
        id: text
        anchors.centerIn: parent
        text: chip.label
        color: Theme.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.sizeSmall
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: chip.clicked()
    }
}
