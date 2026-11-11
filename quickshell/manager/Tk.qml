pragma Singleton
import QtQuick
import Quickshell

// Токены Aurora Glass для Manager (те же значения, что quickshell/hyprdesk/Theme.qml
// и docs/tokens.default.json). Светлая тема: dark=false переключает набор цветов.
Singleton {
    property bool dark: true
    readonly property color bg: dark ? "#0B1020" : "#EEF2FF"
    readonly property color surface: dark ? "#141B2E" : "#FFFFFF"
    readonly property color surfaceAlt: dark ? "#1B2440" : "#E3E9FB"
    readonly property color primary: dark ? "#7AA2F7" : "#3D63D6"
    readonly property color secondary: "#BB9AF7"
    readonly property color accent: dark ? "#7DCFFF" : "#0E7FB8"
    readonly property color text: dark ? "#E6ECFF" : "#141B2E"
    readonly property color textMuted: dark ? "#9AA6C7" : "#55618A"
    readonly property color border: dark ? "#2A3558" : "#C5CEEA"
    readonly property color success: "#9ECE6A"
    readonly property color warning: "#E0AF68"
    readonly property color error: "#F7768E"
    readonly property int radius: 14
    readonly property int radiusSmall: 8
    readonly property int sizeSmall: 12
    readonly property int sizeBody: 14
    readonly property int sizeTitle: 22
    readonly property int durationFast: 120
    readonly property string fontFamily: "Inter"
    readonly property string fontMono: "JetBrains Mono"
    function alpha(c, a) { return Qt.rgba(c.r, c.g, c.b, a); }
}
