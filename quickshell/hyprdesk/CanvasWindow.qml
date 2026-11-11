import QtQuick
import Quickshell
import Quickshell.Wayland
import "lib/canvas.js" as CanvasLib

// Холст виджетов одного монитора (этап 2).
//
// Слой Bottom: выше обоев (Background), ниже обычных окон. Поэтому окна
// всегда получают клики первыми, а холст видит ввод только там, где окон нет.
// Клавиатуру холст не забирает (keyboardFocus None), кроме режима редактирования.
//
// Мир большого размера (CanvasLib.WORLD), камера = сдвиг + масштаб.
// Пустое место: тянуть левой или средней кнопкой - панорамирование; колесо - масштаб.
// Виджеты двигаются и меняют размер только в режиме редактирования (Super+Shift+C).
PanelWindow {
    id: win

    required property var modelData
    screen: modelData

    readonly property string monName: modelData.name
    readonly property bool editing: CanvasStore.editMode

    property real camX: 0
    property real camY: 0
    property real camZoom: 1
    property bool cameraReady: false
    property var savedCamera: null

    anchors {
        top: true
        bottom: true
        left: true
        right: true
    }
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.layer: WlrLayer.Bottom
    WlrLayershell.namespace: "hyprdesk-canvas"
    WlrLayershell.keyboardFocus: editing ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None
    color: "transparent"

    ListModel {
        id: widgetModel
    }

    function camera() {
        return { x: camX, y: camY, zoom: camZoom };
    }

    function setCamera(c) {
        camX = c.x;
        camY = c.y;
        camZoom = c.zoom;
    }

    function load() {
        const layout = CanvasStore.layoutFor(monName);
        widgetModel.clear();
        for (const w of layout.widgets) {
            widgetModel.append({
                wid: w.id, wtype: w.type,
                wx: w.x, wy: w.y, ww: w.w, wh: w.h,
                propsJson: JSON.stringify(w.props || {})
            });
        }
        savedCamera = layout.camera;
        cameraReady = false;
        fitCamera();
    }

    // Камера применяется, когда известен размер окна (после показа на экране).
    function fitCamera() {
        if (width <= 0 || height <= 0) return;
        if (!cameraReady) {
            setCamera(savedCamera
                ? CanvasLib.clampCamera(savedCamera, width, height)
                : CanvasLib.centeredCamera(width, height));
            cameraReady = true;
        } else {
            setCamera(CanvasLib.clampCamera(camera(), width, height));
        }
    }

    function snapshot() {
        const widgets = [];
        for (let i = 0; i < widgetModel.count; i++) {
            const w = widgetModel.get(i);
            let props = {};
            try { props = JSON.parse(w.propsJson); } catch (e) {}
            widgets.push({ id: w.wid, type: w.wtype, x: w.wx, y: w.wy, w: w.ww, h: w.wh, props: props });
        }
        return { camera: camera(), widgets: widgets };
    }

    function save() {
        if (cameraReady) CanvasStore.commit(monName, snapshot());
    }

    function resetCamera() {
        setCamera(CanvasLib.centeredCamera(width, height));
        save();
    }

    onCamZoomChanged: CanvasStore.reportZoom(monName, camZoom)
    onWidthChanged: fitCamera()
    onHeightChanged: fitCamera()
    Component.onCompleted: load()

    Connections {
        target: CanvasStore
        function onCameraResetRequested(monitor) {
            if (monitor === "" || monitor === win.monName) win.resetCamera();
        }
    }

    Item {
        id: viewport
        anchors.fill: parent
        focus: true
        Keys.onEscapePressed: CanvasStore.setEditMode(false)

        // Пустое место: панорамирование и масштаб.
        MouseArea {
            id: panArea
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton | Qt.MiddleButton
            cursorShape: pressed ? Qt.ClosedHandCursor : Qt.ArrowCursor
            property real lastX: 0
            property real lastY: 0

            onPressed: mouse => {
                lastX = mouse.x;
                lastY = mouse.y;
            }
            onPositionChanged: mouse => {
                if (!pressed) return;
                win.setCamera(CanvasLib.pan(win.camera(), mouse.x - lastX, mouse.y - lastY, win.width, win.height));
                lastX = mouse.x;
                lastY = mouse.y;
            }
            onReleased: win.save()
            onWheel: wheel => {
                const delta = wheel.angleDelta.y !== 0 ? wheel.angleDelta.y : wheel.angleDelta.x;
                if (delta === 0) return;
                const factor = Math.pow(1.0015, delta);
                win.setCamera(CanvasLib.zoomAt(win.camera(), wheel.x, wheel.y, factor, win.width, win.height));
                win.save();
            }
        }

        Item {
            id: world
            x: win.camX
            y: win.camY
            width: CanvasLib.WORLD.width
            height: CanvasLib.WORLD.height
            scale: win.camZoom
            transformOrigin: Item.TopLeft

            // Граница мира видна только в режиме редактирования.
            Rectangle {
                anchors.fill: parent
                visible: win.editing
                color: Theme.alpha(Theme.bg, 0.18)
                border.color: Theme.alpha(Theme.primary, 0.5)
                border.width: 2 / win.camZoom
            }

            Repeater {
                model: widgetModel
                delegate: WidgetFrame {
                    editing: win.editing
                    zoom: win.camZoom
                    onGeometryEdited: (index, rect) => {
                        widgetModel.setProperty(index, "wx", rect.x);
                        widgetModel.setProperty(index, "wy", rect.y);
                        widgetModel.setProperty(index, "ww", rect.w);
                        widgetModel.setProperty(index, "wh", rect.h);
                    }
                    onEditFinished: win.save()
                    onPropsEdited: (index, props) => {
                        widgetModel.setProperty(index, "propsJson", JSON.stringify(props));
                        win.save();
                    }
                }
            }
        }

        // Подсказка режима редактирования.
        Rectangle {
            visible: win.editing
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 24
            width: hint.implicitWidth + 32
            height: hint.implicitHeight + 16
            radius: Theme.radiusMedium
            color: Theme.alpha(Theme.surface, 0.9)
            border.color: Theme.primary
            Text {
                id: hint
                anchors.centerIn: parent
                text: "Редактирование: тяни за шапку, размер - уголок справа снизу. Выход: Super+Shift+C или Esc"
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.sizeBody
            }
        }
    }
}
