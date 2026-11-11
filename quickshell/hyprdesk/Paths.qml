pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Пути состояния и кэша. Тот же каталог состояния, что у обёртки сессии (этап 1):
// ~/.local/state/hyprdesk. Состояние не хранится в репозитории.
Singleton {
    id: root

    readonly property string home: Quickshell.env("HOME") || "/tmp"
    readonly property string stateDir: (Quickshell.env("XDG_STATE_HOME") || home + "/.local/state") + "/hyprdesk"
    readonly property string cacheDir: (Quickshell.env("XDG_CACHE_HOME") || home + "/.cache") + "/hyprdesk"
    readonly property string configDir: Quickshell.env("XDG_CONFIG_HOME") || home + "/.config"

    readonly property string canvasFile: stateDir + "/canvas.json"
    readonly property string wallpaperFile: stateDir + "/wallpaper.json"
    readonly property string tokensFile: stateDir + "/tokens.json"
    readonly property string gpuConf: configDir + "/hypr/gpu.conf"
    readonly property string thumbDir: cacheDir + "/thumbs"
    readonly property string defaultWallpaperFolder: home + "/Pictures/Wallpapers"

    // Каталоги создаются один раз при старте. Запись состояния идёт позже
    // (после действий пользователя), поэтому гонки с mkdir нет.
    property bool dirsReady: false

    // file:// URL с экранированием (пробелы, #, кириллица в именах файлов).
    function fileUrl(path) {
        if (!path) return "";
        return "file://" + path.split("/").map(encodeURIComponent).join("/");
    }

    function thumbFor(path) {
        return thumbDir + "/" + Qt.md5(path) + ".jpg";
    }

    Process {
        running: true
        command: ["mkdir", "-p", root.stateDir, root.thumbDir]
        onExited: root.dirsReady = true
    }
}
