import QtQuick
import "lib/theme.js" as ThemeLib

// Тема конкретного виджета (этап 4): токены Theme + его переопределения из tokens.json
// (widget_overrides: сначала id виджета, потом его тип). Переопределения хранит
// `hyprown theme override` / Manager -> Themes; смена обоев их не сбрасывает.
// Не переопределённые значения берутся у Theme и поэтому плавно меняются вместе с темой.
QtObject {
    id: wt

    property string wid: ""
    property string wtype: ""

    function _ov(section, field) {
        return ThemeLib.override(Theme.tokens, wid, wtype, section, field);
    }
    function _c(field, fallback) {
        const v = _ov("palette", field);
        return v === undefined ? fallback : ThemeLib.qtColor(v);
    }
    function _n(section, field, fallback) {
        const v = _ov(section, field);
        return typeof v === "number" ? v : fallback;
    }

    readonly property bool overridden: Theme.tokens.widget_overrides[wid] !== undefined
                                       || Theme.tokens.widget_overrides[wtype] !== undefined

    readonly property color bg: _c("bg", Theme.bg)
    readonly property color surface: _c("surface", Theme.surface)
    readonly property color surfaceAlt: _c("surface_alt", Theme.surfaceAlt)
    readonly property color primary: _c("primary", Theme.primary)
    readonly property color secondary: _c("secondary", Theme.secondary)
    readonly property color accent: _c("accent", Theme.accent)
    readonly property color text: _c("text", Theme.text)
    readonly property color textMuted: _c("text_muted", Theme.textMuted)
    readonly property color border: _c("border", Theme.border)
    readonly property color success: _c("success", Theme.success)
    readonly property color warning: _c("warning", Theme.warning)
    readonly property color error: _c("error", Theme.error)

    readonly property real surfaceOpacity: _n("material", "opacity", Theme.surfaceOpacity)
    readonly property real borderWidth: _n("material", "border_width", Theme.borderWidth)
    readonly property real glowStrength: Theme.quality === "simple" ? 0 : _n("material", "glow_strength", Theme.glowStrength)

    readonly property int radiusSmall: _n("shape", "radius_small", Theme.radiusSmall)
    readonly property int radiusMedium: _n("shape", "radius_medium", Theme.radiusMedium)
    readonly property int radiusLarge: _n("shape", "radius_large", Theme.radiusLarge)
    readonly property int spacing: _n("shape", "spacing_unit", Theme.spacing)

    readonly property int durationFast: _n("motion", "duration_fast_ms", Theme.durationFast)
    readonly property int durationNormal: _n("motion", "duration_normal_ms", Theme.durationNormal)
    readonly property int durationSlow: _n("motion", "duration_slow_ms", Theme.durationSlow)

    // Шрифты не переопределяются на виджете (схема docs/TOKENS.md, раздел 3).
    readonly property string fontFamily: Theme.fontFamily
    readonly property string fontMono: Theme.fontMono
    readonly property int sizeSmall: Theme.sizeSmall
    readonly property int sizeBody: Theme.sizeBody
    readonly property int sizeTitle: Theme.sizeTitle

    function alpha(c, a) {
        return Qt.rgba(c.r, c.g, c.b, a);
    }
}
