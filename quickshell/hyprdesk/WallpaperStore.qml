pragma Singleton
import QtQuick
import Qt.labs.folderlistmodel
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import "lib/wallpaper.js" as WallLib

// Обои (этап 3): выбор файла по каждому монитору, папка, декодер для видео.
// Файл: ~/.local/state/hyprdesk/wallpaper.json (схема в lib/wallpaper.js).
Singleton {
    id: root

    property var state: WallLib.normalizeState(null)
    property bool readOnly: false
    // Меняется при каждом изменении state, чтобы привязки в окнах пересчитывались.
    property int revision: 0

    readonly property string folder: state.folder || Paths.defaultWallpaperFolder
    readonly property string gpu: WallLib.parseGpu(gpuFile.loadedText)
    readonly property string hwdec: WallLib.hwdecFor(gpu, state.hwdec)

    // Список файлов в папке (общий для хоткеев и сетки превью).
    property alias files: folderModel

    // Сетка превью
    property bool pickerOpen: false
    property string pickerMonitor: ""

    // Мониторы, на которых видео не запустилось (имя -> путь), для статуса в панели.
    property var videoErrors: ({})

    // Старые процессы mpvpaper от прошлого запуска (после падения Quickshell)
    // убираются до запуска новых. Помечены опцией mpv title=hyprdesk-wallpaper.
    property bool videoCleanupDone: false

    function focusedMonitor() {
        const m = Hyprland.focusedMonitor;
        return m ? m.name : "";
    }

    function pathFor(monitor) {
        revision; // зависимость для привязок
        return WallLib.pathFor(state, monitor);
    }

    function fileList() {
        const out = [];
        for (let i = 0; i < folderModel.count; i++)
            out.push(folderModel.get(i, "filePath"));
        return out;
    }

    // monitor = "" - для всех мониторов.
    function setPath(monitor, path) {
        if (readOnly) {
            console.warn("hyprdesk: wallpaper.json создан более новой версией, смена обоев не сохраняется");
            return;
        }
        state = WallLib.withPath(state, monitor, path);
        clearVideoError(monitor);
        revision++;
        file.setText(WallLib.serialize(state));
    }

    function step(monitor, dir) {
        const list = fileList();
        if (list.length === 0) {
            console.warn("hyprdesk: в папке обоев нет файлов: " + folder);
            return;
        }
        setPath(monitor, WallLib.nextIn(list, pathFor(monitor), dir));
    }

    function openPicker(monitor) {
        pickerMonitor = monitor || focusedMonitor();
        pickerOpen = true;
    }

    function closePicker() {
        pickerOpen = false;
    }

    function setVideoError(monitor, path) {
        const e = Object.assign({}, videoErrors);
        e[monitor] = path;
        videoErrors = e;
    }

    function clearVideoError(monitor) {
        if (!monitor) {
            videoErrors = {};
            return;
        }
        if (!(monitor in videoErrors)) return;
        const e = Object.assign({}, videoErrors);
        delete e[monitor];
        videoErrors = e;
    }

    function load(text) {
        const parsed = WallLib.parseState(text);
        if (parsed === null) {
            readOnly = true;
            state = WallLib.normalizeState(null);
        } else {
            readOnly = false;
            state = parsed;
        }
        revision++;
    }

    FolderListModel {
        id: folderModel
        folder: Paths.fileUrl(root.folder)
        nameFilters: WallLib.nameFilters()
        showDirs: false
        showDotAndDotDot: false
        showHidden: false
        sortField: FolderListModel.Name
        caseSensitive: false
    }

    FileView {
        id: file
        path: Paths.wallpaperFile
        blockLoading: true
        printErrors: false
        onLoadFailed: root.load("")
        onSaveFailed: console.warn("hyprdesk: не удалось сохранить wallpaper.json")
    }

    // gpu.conf читается только для выбора декодера (amd -> vaapi, nvidia -> nvdec).
    FileView {
        id: gpuFile
        property string loadedText: ""
        path: Paths.gpuConf
        watchChanges: true
        printErrors: false
        onLoaded: loadedText = text()
        onFileChanged: reload()
        onLoadFailed: loadedText = ""
    }

    Process {
        running: true
        command: ["pkill", "-f", "--", "title=hyprdesk-wallpaper"]
        onExited: root.videoCleanupDone = true
    }

    // Если pkill не запустился (нет команды), не блокируем видео навсегда.
    Timer {
        interval: 2000
        running: true
        onTriggered: root.videoCleanupDone = true
    }

    Component.onCompleted: load(file.text())
}
