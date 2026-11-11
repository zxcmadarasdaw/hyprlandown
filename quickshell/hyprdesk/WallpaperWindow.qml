import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "lib/wallpaper.js" as WallLib

// Обои одного монитора (этап 3). Слой Background: ниже холста виджетов и окон.
// Окно привязано к экрану и не двигается вместе с холстом.
//
// Картинка: рисуется здесь (Image).
// Видео: mpvpaper на том же слое Background, аппаратное декодирование
// (hwdec из gpu.conf: amd -> vaapi, nvidia -> nvdec). Пока видео не поднялось
// или если оно упало, видны встроенные обои по умолчанию.
PanelWindow {
    id: win

    required property var modelData
    screen: modelData

    readonly property string monName: modelData.name
    readonly property string path: WallpaperStore.pathFor(monName)
    readonly property string kind: WallLib.kindOf(path)
    readonly property bool wantVideo: kind === "video" && WallpaperStore.videoCleanupDone
    readonly property string hwdec: WallpaperStore.hwdec

    property bool videoUp: false
    property bool stopping: false
    property bool alive: true

    anchors {
        top: true
        bottom: true
        left: true
        right: true
    }
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.layer: WlrLayer.Background
    WlrLayershell.namespace: "hyprdesk-wallpaper"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    // Пустая маска: обои никогда не принимают ввод.
    mask: Region {}
    color: Theme.bg

    // Когда видео поднялось, окно с картинкой убираем: два слоя Background
    // без гарантированного порядка не должны перекрывать друг друга.
    visible: !videoUp

    // Встроенные обои по умолчанию: градиент палитры. Работают без файлов.
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop { position: 0.0; color: Theme.bg }
            GradientStop { position: 0.55; color: Theme.surfaceAlt }
            GradientStop { position: 1.0; color: Theme.bg }
        }
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: Theme.alpha(Theme.primary, 0.18) }
                GradientStop { position: 0.5; color: "transparent" }
                GradientStop { position: 1.0; color: Theme.alpha(Theme.secondary, 0.16) }
            }
        }
    }

    Image {
        id: image
        anchors.fill: parent
        visible: win.kind === "image" && status === Image.Ready
        source: win.kind === "image" ? Paths.fileUrl(win.path) : ""
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
        smooth: true
        sourceSize.width: win.width * ((win.screen && win.screen.devicePixelRatio) || 1)
        sourceSize.height: win.height * ((win.screen && win.screen.devicePixelRatio) || 1)
        onStatusChanged: {
            if (status === Image.Error)
                console.warn("hyprdesk: не удалось открыть обои " + win.path + ", показаны обои по умолчанию");
        }
    }

    // --- Видео ---

    function startVideo() {
        mpv.command = [
            "mpvpaper",
            "-l", "background",
            "-p",                       // пауза, когда обои закрыты окнами
            "-o", WallLib.mpvOptions(hwdec) + " title=hyprdesk-wallpaper",
            monName,
            path
        ];
        mpv.running = true;
        upTimer.restart();
    }

    function restartVideo() {
        upTimer.stop();
        videoUp = false;
        if (mpv.running) {
            stopping = true;          // перезапуск продолжится в onRunningChanged
            mpv.running = false;
        } else if (wantVideo) {
            startVideo();
        }
    }

    onPathChanged: restartVideo()
    onWantVideoChanged: restartVideo()
    onHwdecChanged: if (wantVideo) restartVideo()

    Process {
        id: mpv
        onRunningChanged: {
            if (running || !win.alive) return;
            upTimer.stop();
            win.videoUp = false;
            if (win.stopping) {
                win.stopping = false;
                if (win.wantVideo) win.startVideo();
                return;
            }
            if (win.wantVideo) {
                // Не установлен mpvpaper, файл не открылся или процесс упал:
                // остаются встроенные обои, в панели виден статус.
                console.warn("hyprdesk: видео-обои не запустились на " + win.monName);
                WallpaperStore.setVideoError(win.monName, win.path);
            }
        }
    }

    // mpvpaper показывает первый кадр не сразу: картинку убираем с задержкой,
    // чтобы не мигал пустой фон.
    Timer {
        id: upTimer
        interval: 900
        onTriggered: if (mpv.running) win.videoUp = true
    }

    Component.onCompleted: if (wantVideo) startVideo()
    Component.onDestruction: {
        alive = false;
        mpv.running = false;
    }
}
