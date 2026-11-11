.pragma library

// Тема оболочки (этап 4): разбор tokens.json и переопределения на виджетах.
// tokens.json пишет `hyprown theme` (hyprown/theme.py); здесь только чтение и слияние.
// Чистая логика без QML: проверяется scripts/test-qs-logic.js.

var SCHEMA = 1;
var ROLES = ["bg", "surface", "surface_alt", "primary", "secondary", "accent",
             "text", "text_muted", "border", "success", "warning", "error"];
var OVERRIDABLE = ["palette", "material", "motion", "shape"];
var COLOR_RE = /^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;

// Встроенные значения (Aurora Glass, themes/aurora-glass.json): если файла нет или он битый.
function defaults() {
    return {
        id: "aurora-glass", name: "Aurora Glass", mode: "preset",
        palette: {
            source: "preset", bg: "#0B1020", surface: "#141B2E", surface_alt: "#1B2440",
            primary: "#7AA2F7", secondary: "#BB9AF7", accent: "#7DCFFF", text: "#E6ECFF",
            text_muted: "#9AA6C7", border: "#2A3558", success: "#9ECE6A", warning: "#E0AF68", error: "#F7768E"
        },
        material: { opacity: 0.62, blur_radius: 24, tint_strength: 0.35, highlight_strength: 0.5,
                    glow_strength: 0.4, border_width: 1 },
        motion: { duration_fast_ms: 120, duration_normal_ms: 220, duration_slow_ms: 420, easing: "ease-out",
                  spring: { stiffness: 180, damping: 22, mass: 1 } },
        shape: { radius_small: 8, radius_medium: 14, radius_large: 22, spacing_unit: 8 },
        typography: { font_family: "Inter", font_family_mono: "JetBrains Mono",
                      size_small: 12, size_body: 14, size_title: 20 },
        effects: { quality: "balanced", liquid_glass: true, spring_physics: true },
        widget_overrides: {}
    };
}

function isObj(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }

// Слияние: значения extra поверх base, только известные поля и совпадающие типы.
// Неверный тип (строка вместо числа, «red» вместо #RRGGBB) пропускается: оболочка не падает.
function mergeKnown(base, extra) {
    var out = {};
    for (var k in base) {
        var b = base[k], e = isObj(extra) ? extra[k] : undefined;
        if (isObj(b)) out[k] = mergeKnown(b, e);
        else if (e === undefined) out[k] = b;
        else if (typeof b === "number" && typeof e === "number" && isFinite(e)) out[k] = e;
        else if (typeof b === "boolean" && typeof e === "boolean") out[k] = e;
        else if (typeof b === "string" && typeof e === "string" && e.length > 0)
            out[k] = (COLOR_RE.test(b) && !COLOR_RE.test(e)) ? b : e;
        else out[k] = b;
    }
    return out;
}

// { tokens, status }: status "ok" | "default" (нет файла или битый) | "newer" (схема новее известной).
function parse(text) {
    var d = defaults();
    if (!text) return { tokens: d, status: "default" };
    var raw;
    try { raw = JSON.parse(text); } catch (e) { return { tokens: d, status: "default" }; }
    if (!isObj(raw)) return { tokens: d, status: "default" };
    if (raw.schema_version !== SCHEMA)
        return { tokens: d, status: (typeof raw.schema_version === "number" && raw.schema_version > SCHEMA) ? "newer" : "default" };
    var t = mergeKnown(d, raw);
    t.id = typeof raw.id === "string" ? raw.id : d.id;
    t.name = typeof raw.name === "string" ? raw.name : t.id;
    t.mode = raw.mode === "wallpaper" ? "wallpaper" : "preset";
    t.widget_overrides = isObj(raw.widget_overrides) ? raw.widget_overrides : {};
    return { tokens: t, status: "ok" };
}

// Значение переопределения для виджета или undefined. Сначала id виджета ("clock-1"),
// затем его тип ("clock"): id точнее. section: palette|material|motion|shape; field: "spring.damping".
function override(tokens, wid, wtype, section, field) {
    if (OVERRIDABLE.indexOf(section) < 0 || !tokens || !isObj(tokens.widget_overrides)) return undefined;
    var keys = [wid, wtype];
    for (var i = 0; i < keys.length; i++) {
        var o = keys[i] ? tokens.widget_overrides[keys[i]] : undefined;
        if (!isObj(o) || !isObj(o[section])) continue;
        var parts = field.split("."), v = o[section];
        for (var j = 0; j < parts.length && isObj(v); j++) v = v[parts[j]];
        if (v === undefined || isObj(v)) continue;
        if (section === "palette" && !(typeof v === "string" && COLOR_RE.test(v))) continue;
        if (section !== "palette" && typeof v !== "number" && typeof v !== "string") continue;
        return v;
    }
    return undefined;
}

// Полный набор токенов виджета: тема + переопределения (тип, затем id).
function forWidget(tokens, wid, wtype) {
    var t = mergeKnown(defaults(), tokens);
    var ov = tokens && isObj(tokens.widget_overrides) ? tokens.widget_overrides : {};
    var chain = [wtype, wid];
    for (var i = 0; i < chain.length; i++) {
        var o = chain[i] ? ov[chain[i]] : undefined;
        if (!isObj(o)) continue;
        for (var s = 0; s < OVERRIDABLE.length; s++) {
            var sec = OVERRIDABLE[s];
            if (isObj(o[sec])) t[sec] = mergeKnown(t[sec], o[sec]);
        }
    }
    return t;
}

// "#RRGGBB" / "#RRGGBBAA" (как в CSS и tokens.json) -> "#AARRGGBB" (как ждёт Qt color).
function qtColor(hex) {
    if (typeof hex !== "string" || !COLOR_RE.test(hex)) return "#000000";
    return hex.length === 9 ? "#" + hex.substr(7, 2) + hex.substr(1, 6) : hex;
}

// Экспорт для node-тестов; в QML (.pragma library) module не определён.
if (typeof module !== "undefined") {
    module.exports = {
        SCHEMA: SCHEMA, ROLES: ROLES, defaults: defaults, parse: parse, override: override,
        forWidget: forWidget, qtColor: qtColor, mergeKnown: mergeKnown
    };
}
