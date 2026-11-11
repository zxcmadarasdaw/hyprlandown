import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

// Выбор темы (этап 4, Ctrl+Alt+F): готовые темы и режим «из обоев».
// Клавиши: стрелки - выбор, Enter - применить, W - из обоев, Esc - закрыть.
// Список тем и их цвета даёт `hyprown theme list --json`; применяет тоже CLI,
// оболочка подхватывает tokens.json сама (Theme.qml).
PanelWindow {
    id: picker

    readonly property string monName: Theme.pickerMonitor
    screen: {
        const list = Quickshell.screens;
        for (let i = 0; i < list.length; i++)
            if (list[i].name === monName) return list[i];
        return list.length > 0 ? list[0] : null;
    }

    property var info: null
    property string error: ""
    // Плитки: готовые темы + «Из обоев» последней.
    readonly property var tiles: {
        const out = [];
        if (info) for (let i = 0; i < info.presets.length; i++) out.push({kind: "preset", p: info.presets[i]});
        out.push({kind: "wallpaper"});
        return out;
    }

    function activeIndex() {
        if (!info) return 0;
        if (info.mode === "wallpaper") return tiles.length - 1;
        for (let i = 0; i < tiles.length; i++)
            if (tiles[i].kind === "preset" && tiles[i].p.id === info.preset) return i;
        return 0;
    }

    function apply(i) {
        const t = tiles[i];
        if (!t) return;
        if (t.kind === "preset") Theme.setPreset(t.p.id);
        else Theme.useWallpaper(WallpaperStore.pathFor(monName));
        Theme.closePicker();
    }

    anchors {
        top: true
        bottom: true
        left: true
        right: true
    }
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "hyprdesk-theme-picker"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    color: Theme.alpha(Theme.bg, 0.55)

    Process {
        id: listProc
        running: true
        command: [Theme.cli, "--plain", "theme", "list", "--json"]
        property string buf: ""
        stdout: SplitParser { onRead: data => listProc.buf += data + "\n" }
        onExited: (code, st) => {
            try {
                picker.info = JSON.parse(listProc.buf);
                grid.currentIndex = picker.activeIndex();
            } catch (e) {
                picker.error = "Не удалось получить список тем (hyprown theme list, код " + code + ")";
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        onClicked: Theme.closePicker()
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(parent.width - 80, 980)
        height: Math.min(parent.height - 120, 560)
        radius: Theme.radiusLarge
        color: Theme.alpha(Theme.surface, 0.96)
        border.color: Theme.border
        border.width: 1

        MouseArea { anchors.fill: parent }

        Column {
            id: header
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: 20
            spacing: 4
            Text {
                text: "Тема" + (picker.info ? "  ·  сейчас: " + (picker.info.mode === "wallpaper" ? "из обоев" : picker.info.preset) : "")
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.sizeTitle
            }
            Text {
                width: parent.width
                wrapMode: Text.WordWrap
                text: picker.error !== "" ? picker.error
                      : "Стрелки - выбор, Enter - применить, W - палитра из обоев, Esc - закрыть. "
                        + "Свои цвета виджетов сохраняются при любой смене."
                color: picker.error !== "" ? Theme.error : Theme.textMuted
                font.family: Theme.fontFamily
                font.pixelSize: Theme.sizeSmall
            }
        }

        GridView {
            id: grid
            anchors.top: header.bottom
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: 20
            clip: true
            focus: true
            model: picker.tiles
            cellWidth: Math.floor(width / 3)
            cellHeight: 190
            keyNavigationWraps: true
            highlightMoveDuration: Theme.durationFast

            Keys.onEscapePressed: Theme.closePicker()
            Keys.onReturnPressed: picker.apply(currentIndex)
            Keys.onEnterPressed: picker.apply(currentIndex)
            Keys.onPressed: event => {
                if (event.key === Qt.Key_W) {
                    picker.apply(picker.tiles.length - 1);
                    event.accepted = true;
                }
            }

            delegate: Item {
                id: cell
                required property var modelData
                required property int index
                readonly property bool isPreset: modelData.kind === "preset"
                readonly property var pal: isPreset ? modelData.p.palette
                                         : (picker.info && picker.info.wallpaper ? picker.info.wallpaper.palette : null)
                readonly property bool active: picker.info !== null && index === picker.activeIndex()
                width: grid.cellWidth
                height: grid.cellHeight

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 8
                    radius: Theme.radiusMedium
                    color: cell.pal ? cell.pal.bg : Theme.alpha(Theme.surfaceAlt, 0.8)
                    border.width: grid.currentIndex === cell.index ? 3 : 1
                    border.color: grid.currentIndex === cell.index ? Theme.primary
                                  : cell.active ? Theme.accent : Theme.border

                    Column {
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 8

                        Text {
                            width: parent.width
                            elide: Text.ElideRight
                            text: (cell.active ? "● " : "") + (cell.isPreset ? cell.modelData.p.name : "Из обоев")
                            color: cell.pal ? cell.pal.text : Theme.text
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.sizeBody + 2
                            font.bold: true
                        }
                        Row {
                            spacing: 6
                            visible: cell.pal !== null
                            Repeater {
                                model: ["surface", "primary", "secondary", "accent", "text"]
                                delegate: Rectangle {
                                    required property string modelData
                                    width: 30
                                    height: 30
                                    radius: 15
                                    color: cell.pal ? cell.pal[modelData] : "transparent"
                                    border.color: Theme.alpha(Theme.text, 0.25)
                                    border.width: 1
                                }
                            }
                        }
                        Text {
                            width: parent.width
                            wrapMode: Text.WordWrap
                            maximumLineCount: 3
                            elide: Text.ElideRight
                            text: cell.isPreset ? cell.modelData.p.description
                                  : (cell.pal ? "Палитра последних обоев. Меняется вместе с обоями."
                                              : "Палитра построится из текущих обоев этого монитора.")
                            color: cell.pal ? cell.pal.text : Theme.textMuted
                            opacity: 0.8
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.sizeSmall
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onEntered: grid.currentIndex = cell.index
                        onClicked: picker.apply(cell.index)
                    }
                }
            }
        }
    }
}
