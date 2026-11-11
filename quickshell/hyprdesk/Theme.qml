pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import "lib/theme.js" as ThemeLib

// Тема оболочки (этап 4). Источник: ~/.local/state/hyprdesk/tokens.json, его пишет
// `hyprown theme` (готовые темы, палитра из обоев, переопределения виджетов).
// Файла нет или он битый -> встроенные значения Aurora Glass; оболочка не падает.
// Виджеты берут цвета отсюда или из WidgetTheme (если у виджета есть свои цвета).
Singleton {
    id: root

    property var tokens: ThemeLib.defaults()
    // ok | default (файла нет или битый) | newer (создан более новой версией)
    property string status: "default"
    property string _lastText: ""

    readonly property string themeId: tokens.id
    readonly property string themeName: tokens.name
    readonly property string mode: tokens.mode
    readonly property string paletteSource: tokens.palette.source

    // Цвета: смена темы или обоев перетекает плавно, а не мигает.
    property color bg: ThemeLib.qtColor(tokens.palette.bg)
    property color surface: ThemeLib.qtColor(tokens.palette.surface)
    property color surfaceAlt: ThemeLib.qtColor(tokens.palette.surface_alt)
    property color primary: ThemeLib.qtColor(tokens.palette.primary)
    property color secondary: ThemeLib.qtColor(tokens.palette.secondary)
    property color accent: ThemeLib.qtColor(tokens.palette.accent)
    property color text: ThemeLib.qtColor(tokens.palette.text)
    property color textMuted: ThemeLib.qtColor(tokens.palette.text_muted)
    property color border: ThemeLib.qtColor(tokens.palette.border)
    property color success: ThemeLib.qtColor(tokens.palette.success)
    property color warning: ThemeLib.qtColor(tokens.palette.warning)
    property color error: ThemeLib.qtColor(tokens.palette.error)
    Behavior on bg { ColorAnimation { duration: root.durationSlow } }
    Behavior on surface { ColorAnimation { duration: root.durationSlow } }
    Behavior on surfaceAlt { ColorAnimation { duration: root.durationSlow } }
    Behavior on primary { ColorAnimation { duration: root.durationSlow } }
    Behavior on secondary { ColorAnimation { duration: root.durationSlow } }
    Behavior on accent { ColorAnimation { duration: root.durationSlow } }
    Behavior on text { ColorAnimation { duration: root.durationSlow } }
    Behavior on textMuted { ColorAnimation { duration: root.durationSlow } }
    Behavior on border { ColorAnimation { duration: root.durationSlow } }

    // Материал (Liquid Glass; этап 7 использует остальные поля)
    readonly property real surfaceOpacity: tokens.material.opacity
    readonly property real blurRadius: tokens.material.blur_radius
    readonly property real tintStrength: tokens.material.tint_strength
    readonly property real highlightStrength: tokens.material.highlight_strength
    readonly property real glowStrength: tokens.effects.quality === "simple" ? 0 : tokens.material.glow_strength
    readonly property real borderWidth: tokens.material.border_width

    readonly property int radiusSmall: tokens.shape.radius_small
    readonly property int radiusMedium: tokens.shape.radius_medium
    readonly property int radiusLarge: tokens.shape.radius_large
    readonly property int spacing: tokens.shape.spacing_unit

    readonly property string fontFamily: tokens.typography.font_family
    readonly property string fontMono: tokens.typography.font_family_mono
    readonly property int sizeSmall: tokens.typography.size_small
    readonly property int sizeBody: tokens.typography.size_body
    readonly property int sizeTitle: tokens.typography.size_title

    readonly property int durationFast: tokens.motion.duration_fast_ms
    readonly property int durationNormal: tokens.motion.duration_normal_ms
    readonly property int durationSlow: tokens.motion.duration_slow_ms
    readonly property real springStiffness: tokens.motion.spring.stiffness
    readonly property real springDamping: tokens.motion.spring.damping
    readonly property real springMass: tokens.motion.spring.mass

    readonly property string quality: tokens.effects.quality
    readonly property bool liquidGlass: tokens.effects.liquid_glass
    readonly property bool springPhysics: tokens.effects.spring_physics

    readonly property string cli: Quickshell.env("HYPROWN_CLI") || (Paths.home + "/.local/bin/hyprown")

    function alpha(c, a) {
        return Qt.rgba(c.r, c.g, c.b, a);
    }

    function reloadFile() {
        file.reload();
    }

    function load(text) {
        if (text === _lastText) return;
        _lastText = text;
        const r = ThemeLib.parse(text);
        if (r.status === "newer")
            console.warn("hyprdesk: tokens.json создан более новой версией, встроенная тема");
        else if (r.status === "default" && text)
            console.warn("hyprdesk: tokens.json не читается, встроенная тема");
        status = r.status;
        tokens = r.tokens;
    }

    // ---- окно выбора темы (Ctrl+Alt+F) ----
    property bool pickerOpen: false
    property string pickerMonitor: ""

    function openPicker(monitor) {
        pickerMonitor = monitor;
        pickerOpen = true;
    }
    function closePicker() {
        pickerOpen = false;
    }

    // Готовая тема: палитра из неё.
    function setPreset(id) {
        run(["theme", "set", id]);
    }
    // Режим «из обоев»: палитра строится по текущим обоям монитора; нет обоев - только режим.
    function useWallpaper(path) {
        if (path) run(["theme", "from-wallpaper", "--switch", "--path", path]);
        else run(["theme", "mode", "wallpaper"]);
    }

    // ---- вызовы CLI (по одному, без параллельных запусков) ----
    property var _queue: []

    function run(args) {
        if (cliProc.running) {
            _queue = _queue.concat([args]);
            return;
        }
        cliProc.command = [cli, "--plain"].concat(args);
        cliProc.running = true;
    }

    // ---- палитра из обоев ----
    // Обои сменились: если включён режим «из обоев», CLI строит палитру и пишет tokens.json,
    // этот синглтон подхватывает файл. Частые нажатия Super+W схлопываются в один запуск.
    property string _pendingWallpaper: ""

    function wallpaperChanged(path) {
        if (!path || mode !== "wallpaper") return;
        _pendingWallpaper = path;
        paletteDebounce.restart();
    }

    Timer {
        id: paletteDebounce
        interval: 350
        onTriggered: root.run(["theme", "from-wallpaper", "--if-wallpaper-mode", "--path", root._pendingWallpaper])
    }

    Process {
        id: cliProc
        stderr: SplitParser { onRead: data => console.warn("hyprdesk theme: " + data) }
        onExited: (code, st) => {
            if (code !== 0) console.warn("hyprdesk theme: " + cliProc.command.slice(2).join(" ") + " -> код " + code);
            file.reload();
            if (root._queue.length > 0) {
                const next = root._queue[0];
                root._queue = root._queue.slice(1);
                root.run(next);
            }
        }
    }

    FileView {
        id: file
        path: Paths.tokensFile
        watchChanges: true
        printErrors: false
        onLoaded: root.load(text())
        onFileChanged: reload()
        onLoadFailed: root.load("")
    }

    // Запасной путь: атомарная запись (временный файл + переименование) может сорвать
    // слежение за файлом. Раз в 3 секунды перечитываем; тот же текст ничего не меняет.
    Timer {
        interval: 3000
        running: true
        repeat: true
        onTriggered: file.reload()
    }
}
