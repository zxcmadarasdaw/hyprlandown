pragma Singleton
import QtQuick
import Quickshell

// Временная тема: значения из docs/tokens.default.json (Aurora Glass).
// На этапе 4 токены будут читаться из файла и браться из обоев;
// виджеты уже сейчас берут цвета только отсюда.
Singleton {
    readonly property color bg: "#0B1020"
    readonly property color surface: "#141B2E"
    readonly property color surfaceAlt: "#1B2440"
    readonly property color primary: "#7AA2F7"
    readonly property color secondary: "#BB9AF7"
    readonly property color accent: "#7DCFFF"
    readonly property color text: "#E6ECFF"
    readonly property color textMuted: "#9AA6C7"
    readonly property color border: "#2A3558"
    readonly property color success: "#9ECE6A"
    readonly property color warning: "#E0AF68"
    readonly property color error: "#F7768E"

    readonly property real surfaceOpacity: 0.62

    readonly property int radiusSmall: 8
    readonly property int radiusMedium: 14
    readonly property int radiusLarge: 22
    readonly property int spacing: 8

    readonly property string fontFamily: "Inter"
    readonly property string fontMono: "JetBrains Mono"
    readonly property int sizeSmall: 12
    readonly property int sizeBody: 14
    readonly property int sizeTitle: 20

    readonly property int durationFast: 120
    readonly property int durationNormal: 220

    function alpha(c, a) {
        return Qt.rgba(c.r, c.g, c.b, a);
    }
}
