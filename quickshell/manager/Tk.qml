pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Токены Manager. Тёмная тема берёт палитру активной темы HyprlandOwn
// (~/.local/state/hyprdesk/tokens.json, пишет `hyprown theme`), поэтому Manager
// меняет цвета вместе с оболочкой. Светлая тема (dark=false) - отдельный фиксированный
// набор для читаемости днём. Нет файла или он битый -> значения Aurora Glass.
Singleton {
    id: tk
    property bool dark: true
    property var pal: ({})
    readonly property string stateDir: (Quickshell.env("XDG_STATE_HOME") || ((Quickshell.env("HOME") || "/tmp") + "/.local/state")) + "/hyprdesk"

    function _p(role, fallback) {
        const v = pal[role];
        return (typeof v === "string" && /^#[0-9a-fA-F]{6}$/.test(v.substr(0, 7))) ? v.substr(0, 7) : fallback;
    }

    readonly property color bg: dark ? _p("bg", "#0B1020") : "#EEF2FF"
    readonly property color surface: dark ? _p("surface", "#141B2E") : "#FFFFFF"
    readonly property color surfaceAlt: dark ? _p("surface_alt", "#1B2440") : "#E3E9FB"
    readonly property color primary: dark ? _p("primary", "#7AA2F7") : "#3D63D6"
    readonly property color secondary: dark ? _p("secondary", "#BB9AF7") : "#7A4FD6"
    readonly property color accent: dark ? _p("accent", "#7DCFFF") : "#0E7FB8"
    readonly property color text: dark ? _p("text", "#E6ECFF") : "#141B2E"
    readonly property color textMuted: dark ? _p("text_muted", "#9AA6C7") : "#55618A"
    readonly property color border: dark ? _p("border", "#2A3558") : "#C5CEEA"
    readonly property color success: dark ? _p("success", "#9ECE6A") : "#2F7D32"
    readonly property color warning: dark ? _p("warning", "#E0AF68") : "#A15C00"
    readonly property color error: dark ? _p("error", "#F7768E") : "#C62828"
    readonly property int radius: 14
    readonly property int radiusSmall: 8
    readonly property int sizeSmall: 12
    readonly property int sizeBody: 14
    readonly property int sizeTitle: 22
    readonly property int durationFast: 120
    readonly property string fontFamily: "Inter"
    readonly property string fontMono: "JetBrains Mono"
    function alpha(c, a) { return Qt.rgba(c.r, c.g, c.b, a); }

    function reload() { tokensFile.reload(); }

    FileView {
        id: tokensFile
        path: tk.stateDir + "/tokens.json"
        watchChanges: true
        printErrors: false
        onLoaded: {
            try {
                const t = JSON.parse(text());
                tk.pal = (t && t.schema_version === 1 && t.palette) ? t.palette : ({});
            } catch (e) {
                tk.pal = ({});
            }
        }
        onFileChanged: reload()
        onLoadFailed: tk.pal = ({})
    }
}
