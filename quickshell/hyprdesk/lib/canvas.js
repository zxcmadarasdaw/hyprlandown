.pragma library
// Чистая логика холста (этап 2): камера, координаты, схема раскладки.
// Без зависимостей от QML: файл тестируется в node (scripts/test-qs-logic.js).
//
// Модель камеры: экранная точка = мировая точка * zoom + (x, y).
// То есть camera.x/y - сдвиг мира на экране в пикселях экрана.

var SCHEMA_VERSION = 1;

var WORLD = { width: 8000, height: 5000 };
var ZOOM_MIN = 0.25;
var ZOOM_MAX = 3.0;
var GRID = 8;
var MIN_WIDGET = { w: 80, h: 60 };

function clamp(v, lo, hi) {
    return Math.min(hi, Math.max(lo, v));
}

function num(v, fallback) {
    return (typeof v === "number" && isFinite(v)) ? v : fallback;
}

function screenToWorld(cam, sx, sy) {
    return { x: (sx - cam.x) / cam.zoom, y: (sy - cam.y) / cam.zoom };
}

function worldToScreen(cam, wx, wy) {
    return { x: wx * cam.zoom + cam.x, y: wy * cam.zoom + cam.y };
}

// Ограничивает камеру так, чтобы экран не уходил за пределы мира.
// Если мир при текущем масштабе меньше экрана, мир центрируется.
function clampCamera(cam, viewW, viewH, world) {
    world = world || WORLD;
    var z = clamp(num(cam.zoom, 1), ZOOM_MIN, ZOOM_MAX);
    var ww = world.width * z, wh = world.height * z;
    var x = num(cam.x, 0), y = num(cam.y, 0);
    x = ww <= viewW ? (viewW - ww) / 2 : clamp(x, viewW - ww, 0);
    y = wh <= viewH ? (viewH - wh) / 2 : clamp(y, viewH - wh, 0);
    return { x: x, y: y, zoom: z };
}

function pan(cam, dx, dy, viewW, viewH, world) {
    return clampCamera({ x: cam.x + dx, y: cam.y + dy, zoom: cam.zoom }, viewW, viewH, world);
}

// Масштаб вокруг точки экрана (mx, my): мировая точка под курсором остаётся на месте
// (если не упёрлись в границу мира).
function zoomAt(cam, mx, my, factor, viewW, viewH, world) {
    var z = clamp(cam.zoom * factor, ZOOM_MIN, ZOOM_MAX);
    var w = screenToWorld(cam, mx, my);
    return clampCamera({ x: mx - w.x * z, y: my - w.y * z, zoom: z }, viewW, viewH, world);
}

// Камера по умолчанию: масштаб 1, центр мира в центре экрана.
function centeredCamera(viewW, viewH, world) {
    world = world || WORLD;
    return clampCamera({
        x: viewW / 2 - world.width / 2,
        y: viewH / 2 - world.height / 2,
        zoom: 1
    }, viewW, viewH, world);
}

function snap(v, grid) {
    grid = grid || GRID;
    return Math.round(v / grid) * grid;
}

// Прямоугольник виджета в мировых координатах, привязанный к сетке и миру.
function fitRect(r, world) {
    world = world || WORLD;
    var w = clamp(snap(num(r.w, 200)), MIN_WIDGET.w, world.width);
    var h = clamp(snap(num(r.h, 120)), MIN_WIDGET.h, world.height);
    var x = clamp(snap(num(r.x, 0)), 0, world.width - w);
    var y = clamp(snap(num(r.y, 0)), 0, world.height - h);
    return { x: x, y: y, w: w, h: h };
}

var KNOWN_TYPES = ["clock", "note"];

// Стартовые виджеты вокруг центра мира. Камера null = центрировать при первом показе.
function defaultMonitorLayout() {
    var cx = WORLD.width / 2, cy = WORLD.height / 2;
    return {
        camera: null,
        widgets: [
            { id: "clock-1", type: "clock", x: cx - 400, y: cy - 240, w: 320, h: 160, props: {} },
            { id: "note-1", type: "note", x: cx + 80, y: cy - 240, w: 320, h: 200,
              props: { text: "Super+Shift+C: режим редактирования.\nПустое место: тянуть мышью.\nКолесо: масштаб." } }
        ]
    };
}

function normalizeWidget(w, idx, usedIds) {
    if (!w || typeof w !== "object") return null;
    if (KNOWN_TYPES.indexOf(w.type) < 0) return null;
    var id = (typeof w.id === "string" && w.id.length > 0) ? w.id : (w.type + "-" + (idx + 1));
    while (usedIds[id]) id = id + "_";
    usedIds[id] = true;
    var r = fitRect(w);
    var props = (w.props && typeof w.props === "object" && !Array.isArray(w.props)) ? w.props : {};
    return { id: id, type: w.type, x: r.x, y: r.y, w: r.w, h: r.h, props: props };
}

function normalizeCamera(c) {
    if (!c || typeof c !== "object") return null;
    if (typeof c.x !== "number" || typeof c.y !== "number" || typeof c.zoom !== "number") return null;
    if (!isFinite(c.x) || !isFinite(c.y) || !isFinite(c.zoom)) return null;
    return { x: c.x, y: c.y, zoom: clamp(c.zoom, ZOOM_MIN, ZOOM_MAX) };
}

function normalizeMonitor(m) {
    if (!m || typeof m !== "object" || !Array.isArray(m.widgets)) return null;
    var used = {};
    var widgets = [];
    for (var i = 0; i < m.widgets.length; i++) {
        var w = normalizeWidget(m.widgets[i], i, used);
        if (w) widgets.push(w);
    }
    return { camera: normalizeCamera(m.camera), widgets: widgets };
}

// Приводит содержимое canvas.json к схеме. Мусор отбрасывается, а не падает.
// Более новая версия схемы: возвращается null, такой файл не перезаписываем.
function normalizeState(raw) {
    var out = { schema_version: SCHEMA_VERSION, monitors: {} };
    if (!raw || typeof raw !== "object") return out;
    if (typeof raw.schema_version === "number" && raw.schema_version > SCHEMA_VERSION) return null;
    var mons = raw.monitors;
    if (mons && typeof mons === "object") {
        for (var name in mons) {
            if (!Object.prototype.hasOwnProperty.call(mons, name)) continue;
            var m = normalizeMonitor(mons[name]);
            if (m) out.monitors[name] = m;
        }
    }
    return out;
}

function parseState(text) {
    if (typeof text !== "string" || text.trim() === "") return normalizeState(null);
    try {
        return normalizeState(JSON.parse(text));
    } catch (e) {
        return normalizeState(null);
    }
}

function monitorLayout(state, name) {
    if (state && state.monitors && state.monitors[name]) return state.monitors[name];
    return defaultMonitorLayout();
}

function serialize(state) {
    return JSON.stringify(state, null, 2) + "\n";
}

// Экспорт для node-тестов; в QML (.pragma library) module не определён.
if (typeof module !== "undefined") {
    module.exports = {
        SCHEMA_VERSION: SCHEMA_VERSION, WORLD: WORLD, ZOOM_MIN: ZOOM_MIN, ZOOM_MAX: ZOOM_MAX,
        clamp: clamp, screenToWorld: screenToWorld, worldToScreen: worldToScreen,
        clampCamera: clampCamera, pan: pan, zoomAt: zoomAt, centeredCamera: centeredCamera,
        snap: snap, fitRect: fitRect, defaultMonitorLayout: defaultMonitorLayout,
        normalizeState: normalizeState, parseState: parseState, monitorLayout: monitorLayout,
        serialize: serialize
    };
}
