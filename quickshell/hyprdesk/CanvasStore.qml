pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import "lib/canvas.js" as CanvasLib

// Хранилище холста: раскладка виджетов и камера по каждому монитору.
// Файл: ~/.local/state/hyprdesk/canvas.json (схема в lib/canvas.js).
// Запись атомарная (FileView пишет во временный файл и переименовывает),
// с задержкой 400 мс после изменения, чтобы позиции пережили аварийный выход.
Singleton {
    id: root

    property bool editMode: false
    // true, если файл создан более новой версией: читаем значения по умолчанию,
    // файл не перезаписываем.
    property bool readOnly: false
    property var state: CanvasLib.normalizeState(null)

    // Текущий масштаб камеры по мониторам (для панели), не сохраняется отдельно.
    property var zooms: ({})

    signal cameraResetRequested(string monitor)

    function reportZoom(monitor, zoom) {
        const z = Object.assign({}, zooms);
        z[monitor] = zoom;
        zooms = z;
    }

    function layoutFor(monitor) {
        return CanvasLib.monitorLayout(state, monitor);
    }

    function commit(monitor, layout) {
        if (readOnly) return;
        state.monitors[monitor] = layout;
        saveTimer.restart();
    }

    function flush() {
        if (saveTimer.running) {
            saveTimer.stop();
            write();
        }
    }

    function write() {
        if (readOnly) return;
        file.setText(CanvasLib.serialize(state));
    }

    function setEditMode(on) {
        if (editMode === on) return;
        editMode = on;
        if (!on) flush();
    }

    function load(text) {
        const parsed = CanvasLib.parseState(text);
        if (parsed === null) {
            console.warn("hyprdesk: canvas.json создан более новой версией, работаем без записи");
            readOnly = true;
            state = CanvasLib.normalizeState(null);
        } else {
            readOnly = false;
            state = parsed;
        }
    }

    Timer {
        id: saveTimer
        interval: 400
        onTriggered: root.write()
    }

    FileView {
        id: file
        path: Paths.canvasFile
        blockLoading: true
        printErrors: false
        // Файла ещё нет (первый запуск) - это не ошибка: берём раскладку по умолчанию.
        onLoadFailed: root.load("")
        onSaveFailed: console.warn("hyprdesk: не удалось сохранить canvas.json")
    }

    Component.onCompleted: {
        // blockLoading: текст доступен сразу; пустая строка, если файла нет.
        load(file.text());
    }
}
