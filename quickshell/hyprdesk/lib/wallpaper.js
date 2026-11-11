.pragma library
// Чистая логика обоев (этап 3): типы файлов, состояние, выбор декодера.
// Тестируется в node (scripts/test-qs-logic.js).
//
// wallpaper.json:
// {
//   "schema_version": 1,
//   "folder": "",              пусто = ~/Pictures/Wallpapers
//   "hwdec": "auto",           auto = по gpu.conf; или явное значение mpv (vaapi, nvdec, no ...)
//   "all": { "path": "" },     обои для мониторов без своей записи; пусто = встроенные
//   "monitors": { "DP-1": { "path": "/home/user/Pictures/Wallpapers/a.jpg" } }
// }

var SCHEMA_VERSION = 1;

var IMAGE_EXT = ["jpg", "jpeg", "png", "webp", "bmp", "svg"];
var VIDEO_EXT = ["mp4", "webm", "mkv", "mov", "m4v"];
var HWDEC_ALLOWED = ["auto", "auto-safe", "vaapi", "vaapi-copy", "nvdec", "nvdec-copy", "no"];

function ext(path) {
    if (typeof path !== "string") return "";
    var base = path.split("/").pop();
    var i = base.lastIndexOf(".");
    return i > 0 ? base.slice(i + 1).toLowerCase() : "";
}

// "image" | "video" | "" (неизвестно или пусто).
function kindOf(path) {
    var e = ext(path);
    if (IMAGE_EXT.indexOf(e) >= 0) return "image";
    if (VIDEO_EXT.indexOf(e) >= 0) return "video";
    return "";
}

function nameFilters() {
    var all = IMAGE_EXT.concat(VIDEO_EXT);
    var out = [];
    for (var i = 0; i < all.length; i++) {
        out.push("*." + all[i]);
        out.push("*." + all[i].toUpperCase());
    }
    return out;
}

// Следующий файл по кругу. Если текущего нет в списке, берётся первый (или последний при step<0).
function nextIn(list, current, step) {
    if (!list || list.length === 0) return "";
    step = step || 1;
    var i = list.indexOf(current);
    if (i < 0) return step > 0 ? list[0] : list[list.length - 1];
    var n = list.length;
    return list[((i + step) % n + n) % n];
}

// Из текста hypr/gpu.conf: строка "$hyprdesk_gpu = amd|nvidia".
function parseGpu(confText) {
    if (typeof confText !== "string") return "unknown";
    var lines = confText.split("\n");
    for (var i = 0; i < lines.length; i++) {
        var m = /^\s*\$hyprdesk_gpu\s*=\s*([A-Za-z]+)\s*(#.*)?$/.exec(lines[i]);
        if (m) {
            var v = m[1].toLowerCase();
            return (v === "amd" || v === "nvidia") ? v : "unknown";
        }
    }
    return "unknown";
}

// Аппаратный декодер mpv: явная настройка важнее, иначе по GPU.
// auto-safe - безопасный вариант mpv, если GPU неизвестен.
function hwdecFor(gpu, override) {
    if (typeof override === "string" && override !== "auto" && HWDEC_ALLOWED.indexOf(override) >= 0)
        return override;
    if (gpu === "amd") return "vaapi";
    if (gpu === "nvidia") return "nvdec";
    return "auto-safe";
}

// Опции mpv для mpvpaper (-o): без звука, по кругу, аппаратное декодирование.
function mpvOptions(hwdec) {
    return "no-audio loop hwdec=" + hwdec + " panscan=1.0 no-osc no-osd-bar";
}

function cleanPath(p) {
    return (typeof p === "string" && p.length > 0 && p.charAt(0) === "/" && kindOf(p) !== "") ? p : "";
}

function normalizeState(raw) {
    var out = { schema_version: SCHEMA_VERSION, folder: "", hwdec: "auto", all: { path: "" }, monitors: {} };
    if (!raw || typeof raw !== "object") return out;
    if (typeof raw.schema_version === "number" && raw.schema_version > SCHEMA_VERSION) return null;
    if (typeof raw.folder === "string" && raw.folder.charAt(0) === "/") out.folder = raw.folder.replace(/\/+$/, "");
    if (typeof raw.hwdec === "string" && HWDEC_ALLOWED.indexOf(raw.hwdec) >= 0) out.hwdec = raw.hwdec;
    if (raw.all && typeof raw.all === "object") out.all.path = cleanPath(raw.all.path);
    if (raw.monitors && typeof raw.monitors === "object") {
        for (var name in raw.monitors) {
            if (!Object.prototype.hasOwnProperty.call(raw.monitors, name)) continue;
            var m = raw.monitors[name];
            var p = (m && typeof m === "object") ? cleanPath(m.path) : "";
            if (p) out.monitors[name] = { path: p };
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

// Путь обоев для монитора: своя запись, иначе общая, иначе "" (встроенные по умолчанию).
function pathFor(state, monitor) {
    if (!state) return "";
    if (state.monitors && state.monitors[monitor]) return state.monitors[monitor].path;
    return (state.all && state.all.path) || "";
}

// Новое состояние (исходное не меняется). monitor = "" - для всех мониторов.
function withPath(state, monitor, path) {
    var s = JSON.parse(JSON.stringify(state || normalizeState(null)));
    path = cleanPath(path);
    if (!monitor) {
        s.all = { path: path };
        s.monitors = {};
    } else if (path) {
        s.monitors[monitor] = { path: path };
    } else {
        delete s.monitors[monitor];
    }
    return s;
}

function serialize(state) {
    return JSON.stringify(state, null, 2) + "\n";
}

if (typeof module !== "undefined") {
    module.exports = {
        SCHEMA_VERSION: SCHEMA_VERSION, kindOf: kindOf, nameFilters: nameFilters, nextIn: nextIn,
        parseGpu: parseGpu, hwdecFor: hwdecFor, mpvOptions: mpvOptions,
        normalizeState: normalizeState, parseState: parseState, pathFor: pathFor,
        withPath: withPath, serialize: serialize
    };
}
