import QtQuick
import "lib/canvas.js" as CanvasLib

// Рамка виджета на холсте: координаты в мире, перетаскивание и размер
// только в режиме редактирования. Содержимое выбирается по типу.
Item {
    id: frame

    // Роли из ListModel холста.
    required property int index
    required property string wid
    required property string wtype
    required property real wx
    required property real wy
    required property real ww
    required property real wh
    required property string propsJson

    property bool editing: false
    property real zoom: 1

    readonly property var props: {
        try { return JSON.parse(propsJson); } catch (e) { return {}; }
    }

    signal geometryEdited(int index, var rect)
    signal editFinished()
    signal propsEdited(int index, var props)

    x: wx
    y: wy
    width: ww
    height: wh

    // Вне режима редактирования клики по виджету не уходят в панорамирование.
    // Колесо не перехватывается: масштаб работает и над виджетами.
    MouseArea {
        anchors.fill: parent
        enabled: !frame.editing
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
    }

    Loader {
        id: content
        anchors.fill: parent
        sourceComponent: {
            switch (frame.wtype) {
            case "clock": return clockComponent;
            case "note": return noteComponent;
            default: return null;
            }
        }
    }

    Component {
        id: clockComponent
        ClockWidget {
            props: frame.props
            editing: frame.editing
        }
    }

    Component {
        id: noteComponent
        NoteWidget {
            props: frame.props
            editing: frame.editing
            onChangeProps: p => frame.propsEdited(frame.index, p)
        }
    }

    // --- Режим редактирования ---

    // Рамка выделения. Толщина делится на масштаб, чтобы на экране была постоянной.
    Rectangle {
        anchors.fill: parent
        anchors.margins: -4 / frame.zoom
        visible: frame.editing
        color: "transparent"
        radius: Theme.radiusLarge
        border.color: dragArea.pressed || resizeArea.pressed ? Theme.accent : Theme.primary
        border.width: 2 / frame.zoom
    }

    // Шапка: за неё виджет перетаскивается. Висит над виджетом и не мешает содержимому.
    Rectangle {
        id: handle
        visible: frame.editing
        x: 0
        // У верхнего края мира шапка уходит внутрь виджета, иначе её не достать.
        y: frame.wy < 40 ? 4 / frame.zoom : -height - 6 / frame.zoom
        width: frame.width
        height: 26 / frame.zoom
        radius: height / 2
        color: Theme.alpha(Theme.primary, dragArea.pressed ? 0.95 : 0.75)

        Text {
            anchors.centerIn: parent
            text: frame.wtype + "  ·  " + Math.round(frame.wx) + ", " + Math.round(frame.wy)
            color: Theme.bg
            font.family: Theme.fontFamily
            font.pixelSize: Theme.sizeSmall / frame.zoom
            font.bold: true
        }

        MouseArea {
            id: dragArea
            anchors.fill: parent
            enabled: frame.editing
            cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor
            property point start
            property real startX
            property real startY

            onPressed: mouse => {
                // Точка в координатах мира: не зависит от того, что рамка сама двигается.
                start = mapToItem(frame.parent, mouse.x, mouse.y);
                startX = frame.wx;
                startY = frame.wy;
            }
            onPositionChanged: mouse => {
                if (!pressed) return;
                const p = mapToItem(frame.parent, mouse.x, mouse.y);
                frame.geometryEdited(frame.index, CanvasLib.fitRect({
                    x: startX + p.x - start.x, y: startY + p.y - start.y, w: frame.ww, h: frame.wh
                }));
            }
            onReleased: frame.editFinished()
        }
    }

    // Уголок изменения размера.
    Rectangle {
        visible: frame.editing
        width: 18 / frame.zoom
        height: width
        radius: width / 2
        x: frame.width - width / 2
        y: frame.height - height / 2
        color: resizeArea.pressed ? Theme.accent : Theme.primary
        border.color: Theme.bg
        border.width: 2 / frame.zoom

        MouseArea {
            id: resizeArea
            anchors.fill: parent
            anchors.margins: -6 / frame.zoom
            enabled: frame.editing
            cursorShape: Qt.SizeFDiagCursor
            property point start
            property real startW
            property real startH

            onPressed: mouse => {
                start = mapToItem(frame.parent, mouse.x, mouse.y);
                startW = frame.ww;
                startH = frame.wh;
            }
            onPositionChanged: mouse => {
                if (!pressed) return;
                const p = mapToItem(frame.parent, mouse.x, mouse.y);
                frame.geometryEdited(frame.index, CanvasLib.fitRect({
                    x: frame.wx, y: frame.wy, w: startW + p.x - start.x, h: startH + p.y - start.y
                }));
            }
            onReleased: frame.editFinished()
        }
    }
}
