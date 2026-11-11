import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "lib/wallpaper.js" as WallLib

// Сетка превью обоев (этап 3). Открывается на мониторе, где был фокус.
// Клавиши: стрелки - выбор, Enter - на этот монитор, Shift+Enter - на все,
// Delete/Backspace - вернуть обои по умолчанию, Esc - закрыть.
PanelWindow {
    id: picker

    readonly property string monName: WallpaperStore.pickerMonitor
    screen: {
        const list = Quickshell.screens;
        for (let i = 0; i < list.length; i++)
            if (list[i].name === monName) return list[i];
        return list.length > 0 ? list[0] : null;
    }

    readonly property string current: WallpaperStore.pathFor(monName)

    anchors {
        top: true
        bottom: true
        left: true
        right: true
    }
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "hyprdesk-wallpaper-picker"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    color: Theme.alpha(Theme.bg, 0.55)

    function apply(path, allMonitors) {
        WallpaperStore.setPath(allMonitors ? "" : monName, path);
    }

    // Клик мимо панели закрывает сетку.
    MouseArea {
        anchors.fill: parent
        onClicked: WallpaperStore.closePicker()
    }

    Rectangle {
        id: panel
        anchors.centerIn: parent
        width: Math.min(parent.width - 80, 1180)
        height: Math.min(parent.height - 120, 760)
        radius: Theme.radiusLarge
        color: Theme.alpha(Theme.surface, 0.95)
        border.color: Theme.border
        border.width: 1

        // Клики внутри панели не закрывают её.
        MouseArea {
            anchors.fill: parent
        }

        Column {
            id: headerCol
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: 20
            spacing: 4

            Text {
                text: "Обои · " + picker.monName
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.sizeTitle
            }
            Text {
                width: parent.width
                elide: Text.ElideMiddle
                text: "Папка: " + WallpaperStore.folder
                      + "   ·   Enter - этот монитор, Shift+Enter - все, Del - по умолчанию, Esc - закрыть"
                color: Theme.textMuted
                font.family: Theme.fontFamily
                font.pixelSize: Theme.sizeSmall
            }
        }

        Text {
            anchors.centerIn: parent
            visible: grid.count === 0
            horizontalAlignment: Text.AlignHCenter
            text: "В папке нет обоев.\nПоложи картинки (jpg, png, webp, svg) или видео (mp4, webm, mkv) в\n"
                  + WallpaperStore.folder
            color: Theme.textMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.sizeBody
        }

        GridView {
            id: grid
            anchors.top: headerCol.bottom
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: 20
            clip: true
            focus: true
            model: WallpaperStore.files
            cellWidth: Math.floor(width / Math.max(1, Math.floor(width / 260)))
            cellHeight: cellWidth * 0.62 + 28
            keyNavigationWraps: true
            highlightMoveDuration: Theme.durationFast

            Component.onCompleted: {
                const list = WallpaperStore.fileList();
                const i = list.indexOf(picker.current);
                if (i >= 0) currentIndex = i;
            }

            Keys.onEscapePressed: WallpaperStore.closePicker()
            Keys.onReturnPressed: event => {
                if (currentItem) picker.apply(currentItem.filePath, event.modifiers & Qt.ShiftModifier);
            }
            Keys.onEnterPressed: event => {
                if (currentItem) picker.apply(currentItem.filePath, event.modifiers & Qt.ShiftModifier);
            }
            Keys.onDeletePressed: picker.apply("", false)
            Keys.onPressed: event => {
                if (event.key === Qt.Key_Backspace) {
                    picker.apply("", false);
                    event.accepted = true;
                }
            }

            delegate: Item {
                id: cell
                required property int index
                required property string filePath
                required property string fileName

                readonly property string kind: WallLib.kindOf(filePath)
                readonly property string thumbPath: kind === "video" ? Paths.thumbFor(filePath) : filePath
                readonly property bool isCurrent: filePath === picker.current
                property bool thumbTried: false

                width: grid.cellWidth
                height: grid.cellHeight

                Rectangle {
                    id: card
                    anchors.fill: parent
                    anchors.margins: 6
                    radius: Theme.radiusMedium
                    color: Theme.surfaceAlt
                    border.width: cell.GridView.isCurrentItem ? 3 : (cell.isCurrent ? 2 : 1)
                    border.color: cell.GridView.isCurrentItem ? Theme.accent
                                : cell.isCurrent ? Theme.primary : Theme.border
                    clip: true

                    Image {
                        id: thumb
                        anchors.top: parent.top
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.margins: 3
                        height: parent.height - 30
                        source: Paths.fileUrl(cell.thumbPath)
                        sourceSize.width: 360
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        cache: false
                        onStatusChanged: {
                            // Превью видео ещё нет: делаем кадр через ffmpeg (если он есть).
                            if (status === Image.Error && cell.kind === "video" && !cell.thumbTried) {
                                cell.thumbTried = true;
                                thumbGen.running = true;
                            }
                        }
                    }

                    Text {
                        anchors.centerIn: thumb
                        visible: thumb.status !== Image.Ready
                        text: cell.kind === "video" ? "▶" : "…"
                        color: Theme.textMuted
                        font.pixelSize: 32
                    }

                    Rectangle {
                        visible: cell.kind === "video"
                        anchors.top: parent.top
                        anchors.right: parent.right
                        anchors.margins: 8
                        width: 46
                        height: 20
                        radius: 10
                        color: Theme.alpha(Theme.bg, 0.75)
                        Text {
                            anchors.centerIn: parent
                            text: "видео"
                            color: Theme.text
                            font.pixelSize: 11
                        }
                    }

                    Text {
                        anchors.bottom: parent.bottom
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.margins: 8
                        elide: Text.ElideMiddle
                        text: (cell.isCurrent ? "● " : "") + cell.fileName
                        color: cell.isCurrent ? Theme.primary : Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.sizeSmall
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: mouse => {
                        grid.currentIndex = cell.index;
                        picker.apply(cell.filePath, mouse.modifiers & Qt.ShiftModifier);
                    }
                }

                // Кадр из видео -> кэш превью. Пишется во временный файл, потом переименовывается.
                Process {
                    id: thumbGen
                    command: ["sh", "-c",
                        'mkdir -p "$(dirname "$2")" && ' +
                        'ffmpeg -nostdin -loglevel error -y -ss 1 -i "$1" -frames:v 1 -vf scale=360:-2 "$2.tmp.jpg" && ' +
                        'mv -f "$2.tmp.jpg" "$2"',
                        "hyprdesk-thumb", cell.filePath, cell.thumbPath]
                    onExited: (code, status) => {
                        if (code === 0) {
                            thumb.source = "";
                            thumb.source = Paths.fileUrl(cell.thumbPath);
                        }
                    }
                }
            }
        }
    }
}
