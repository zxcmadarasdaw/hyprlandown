#!/usr/bin/env node
// Тесты чистой логики Quickshell (этапы 2 и 3): node scripts/test-qs-logic.js
// Проверяет quickshell/hyprdesk/lib/*.js без Quickshell и без Hyprland.
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

function load(rel, app) {
    const file = path.join(__dirname, "..", "quickshell", app || "hyprdesk", "lib", rel);
    // Строка ".pragma library" - директива QML, для node её убираем.
    const src = fs.readFileSync(file, "utf8").replace(/^\.pragma library\s*$/m, "");
    const mod = { exports: {} };
    vm.runInNewContext(src, { module: mod, Math, JSON, Object, Array, isFinite, RegExp }, { filename: file });
    return mod.exports;
}

let pass = 0, fail = 0;
function check(name, cond, extra) {
    if (cond) { pass++; console.log("PASS " + name); }
    else { fail++; console.log("FAIL " + name + (extra !== undefined ? "  -> " + JSON.stringify(extra) : "")); }
}
const near = (a, b) => Math.abs(a - b) < 1e-6;

// ---------- canvas.js ----------
const C = load("canvas.js");
const VW = 1920, VH = 1080;

{
    const cam = C.centeredCamera(VW, VH);
    const center = C.screenToWorld(cam, VW / 2, VH / 2);
    check("камера по умолчанию смотрит в центр мира",
        near(center.x, C.WORLD.width / 2) && near(center.y, C.WORLD.height / 2), center);
}
{
    const cam = C.centeredCamera(VW, VH);
    const before = C.screenToWorld(cam, 700, 300);
    const z = C.zoomAt(cam, 700, 300, 1.5, VW, VH);
    const after = C.screenToWorld(z, 700, 300);
    check("масштаб колесом сохраняет точку под курсором",
        near(before.x, after.x) && near(before.y, after.y) && near(z.zoom, 1.5), { before, after });
}
{
    let cam = C.centeredCamera(VW, VH);
    for (let i = 0; i < 100; i++) cam = C.zoomAt(cam, 0, 0, 2, VW, VH);
    check("масштаб не выше максимума", cam.zoom === C.ZOOM_MAX, cam.zoom);
    for (let i = 0; i < 100; i++) cam = C.zoomAt(cam, 0, 0, 0.5, VW, VH);
    check("масштаб не ниже минимума", cam.zoom === C.ZOOM_MIN, cam.zoom);
}
{
    let cam = C.centeredCamera(VW, VH);
    cam = C.pan(cam, 1e6, 1e6, VW, VH);
    check("панорамирование не уводит за левый/верхний край мира", cam.x === 0 && cam.y === 0, cam);
    cam = C.pan(cam, -1e7, -1e7, VW, VH);
    check("панорамирование не уводит за правый/нижний край мира",
        near(cam.x, VW - C.WORLD.width) && near(cam.y, VH - C.WORLD.height), cam);
}
{
    // Виджет в мировых координатах стоит на месте относительно мира при сдвиге камеры.
    const cam0 = C.centeredCamera(VW, VH);
    const cam1 = C.pan(cam0, -137, 59, VW, VH);
    const s0 = C.worldToScreen(cam0, 4000, 2500), s1 = C.worldToScreen(cam1, 4000, 2500);
    check("при панорамировании виджет сдвигается ровно на сдвиг камеры",
        near(s1.x - s0.x, -137) && near(s1.y - s0.y, 59), { s0, s1 });
}
{
    const r = C.fitRect({ x: -50, y: 99999, w: 10, h: "x" });
    check("прямоугольник виджета: минимум размера и границы мира",
        r.x === 0 && r.w === 80 && r.h === 120 && r.y === C.WORLD.height - 120, r);
    const s = C.fitRect({ x: 101, y: 203, w: 333, h: 151 });
    check("привязка к сетке 8px", s.x === 104 && s.y === 200 && s.w === 336 && s.h === 152, s);
}
{
    check("битый JSON -> пустое состояние", JSON.stringify(C.parseState("{oops")) ===
        JSON.stringify({ schema_version: 1, monitors: {} }));
    check("пустой файл -> пустое состояние", Object.keys(C.parseState("").monitors).length === 0);
    check("более новая схема -> null (файл не трогаем)",
        C.parseState('{"schema_version": 99, "monitors": {}}') === null);
    const st = C.parseState(JSON.stringify({
        schema_version: 1,
        monitors: {
            "DP-1": {
                camera: { x: -100, y: -50, zoom: 9 },
                widgets: [
                    { id: "a", type: "clock", x: 10, y: 10, w: 200, h: 100 },
                    { id: "a", type: "note", x: 0, y: 0, w: 200, h: 100, props: [1] },
                    { type: "rocket" }, null, "str"
                ]
            },
            "HDMI-A-1": { widgets: "nope" }
        }
    }));
    const m = st.monitors["DP-1"];
    check("мусорные и неизвестные виджеты отброшены", m.widgets.length === 2, m.widgets);
    check("повторяющиеся id сделаны уникальными", m.widgets[0].id !== m.widgets[1].id, m.widgets);
    check("props-массив заменён на объект", !Array.isArray(m.widgets[1].props));
    check("zoom из файла ограничен", m.camera.zoom === C.ZOOM_MAX, m.camera);
    check("битая запись монитора отброшена", !("HDMI-A-1" in st.monitors));
    check("у монитора без записи - раскладка по умолчанию",
        C.monitorLayout(st, "eDP-1").widgets.length === 2 && C.monitorLayout(st, "eDP-1").camera === null);
    const round = C.parseState(C.serialize(st));
    check("сохранение и загрузка дают то же самое", JSON.stringify(round) === JSON.stringify(st));
}

// ---------- wallpaper.js ----------
const W = load("wallpaper.js");
check("тип: картинка", W.kindOf("/a/b/Photo.JPG") === "image");
check("тип: видео", W.kindOf("/a/b/clip.webm") === "video");
check("тип: неизвестный и без расширения", W.kindOf("/a/b/readme.txt") === "" && W.kindOf("/a/.mp4") === "");
check("фильтры имён включают верхний регистр", W.nameFilters().indexOf("*.MP4") >= 0);
check("следующие обои по кругу", W.nextIn(["a", "b", "c"], "c", 1) === "a" && W.nextIn(["a", "b", "c"], "a", -1) === "c");
check("текущих нет в списке -> первые", W.nextIn(["a", "b"], "zzz", 1) === "a");
check("пустой список -> пусто", W.nextIn([], "a", 1) === "");

const gpuConf = "# comment\n$hyprdesk_gpu = nvidia  # выбрано install.sh\nenv = X,1\n";
check("GPU из gpu.conf: nvidia", W.parseGpu(gpuConf) === "nvidia");
check("GPU из gpu.conf: amd", W.parseGpu("$hyprdesk_gpu=AMD") === "amd");
check("GPU из gpu.conf: нет строки -> unknown", W.parseGpu("env = A,1") === "unknown");
check("GPU из gpu.conf: закомментировано -> unknown", W.parseGpu("# $hyprdesk_gpu = amd") === "unknown");
check("декодер: AMD -> vaapi", W.hwdecFor("amd", "auto") === "vaapi");
check("декодер: NVIDIA -> nvdec", W.hwdecFor("nvidia", "auto") === "nvdec");
check("декодер: неизвестный GPU -> auto-safe", W.hwdecFor("unknown", "auto") === "auto-safe");
check("декодер: явная настройка важнее GPU", W.hwdecFor("amd", "no") === "no");
check("декодер: мусор в настройке игнорируется", W.hwdecFor("amd", "rm -rf") === "vaapi");
check("опции mpv без звука и с hwdec", /no-audio/.test(W.mpvOptions("vaapi")) && /hwdec=vaapi/.test(W.mpvOptions("vaapi")));

{
    const s = W.parseState(JSON.stringify({
        schema_version: 1, folder: "/home/u/Walls/", hwdec: "evil",
        all: { path: "relative.jpg" },
        monitors: { "DP-1": { path: "/w/a.png" }, "X": { path: "/w/a.txt" }, "Y": 5 }
    }));
    check("состояние обоев: папка без хвостового /", s.folder === "/home/u/Walls");
    check("состояние обоев: плохой hwdec -> auto", s.hwdec === "auto");
    check("состояние обоев: относительный путь отброшен", s.all.path === "");
    check("состояние обоев: плохие записи мониторов отброшены",
        Object.keys(s.monitors).length === 1 && s.monitors["DP-1"].path === "/w/a.png");
    check("путь для монитора со своей записью", W.pathFor(s, "DP-1") === "/w/a.png");
    check("путь для монитора без записи -> общий (пусто)", W.pathFor(s, "HDMI-A-1") === "");
    const s2 = W.withPath(s, "HDMI-A-1", "/w/b.mp4");
    check("смена обоев одного монитора не трогает другой",
        W.pathFor(s2, "DP-1") === "/w/a.png" && W.pathFor(s2, "HDMI-A-1") === "/w/b.mp4");
    check("исходное состояние не изменено", W.pathFor(s, "HDMI-A-1") === "");
    const s3 = W.withPath(s2, "", "/w/c.jpg");
    check("обои на все мониторы сбрасывают личные записи",
        W.pathFor(s3, "DP-1") === "/w/c.jpg" && Object.keys(s3.monitors).length === 0);
    const s4 = W.withPath(s2, "DP-1", "");
    check("сброс монитора к общим обоям", W.pathFor(s4, "DP-1") === "");
    check("более новая схема обоев -> null", W.parseState('{"schema_version":2}') === null);
    check("сохранение и загрузка обоев дают то же самое",
        JSON.stringify(W.parseState(W.serialize(s2))) === JSON.stringify(s2));
}

// ---------- hyprdesk/lib/theme.js (этап 4: токены темы) ----------
{
    const T = load("theme.js");
    const d = T.defaults();
    check("тема: нет файла -> встроенная Aurora Glass", T.parse("").status === "default" && T.parse("").tokens.palette.primary === "#7AA2F7");
    check("тема: битый JSON -> встроенная", T.parse("{нет").status === "default");
    check("тема: более новая схема -> newer, встроенная", T.parse('{"schema_version":9}').status === "newer");
    const fileText = require("fs").readFileSync(require("path").join(__dirname, "..", "themes", "cyber-terminal.json"), "utf8");
    const ct = T.parse(fileText);
    check("тема: готовая тема из themes/ читается", ct.status === "ok" && ct.tokens.palette.primary === "#39FF88" && ct.tokens.shape.radius_large === 10);
    const bad = T.parse(JSON.stringify({schema_version: 1, id: "x", palette: {primary: "red", bg: "#000000"}, material: {opacity: "0.5"}}));
    check("тема: неверные значения пропускаются, верные берутся",
        bad.tokens.palette.primary === d.palette.primary && bad.tokens.palette.bg === "#000000" && bad.tokens.material.opacity === d.material.opacity);
    check("тема: режим из обоев", T.parse(JSON.stringify({schema_version: 1, id: "x", mode: "wallpaper"})).tokens.mode === "wallpaper");
    const tk = T.parse(JSON.stringify({schema_version: 1, id: "x", widget_overrides: {
        "clock": {palette: {primary: "#111111"}, material: {opacity: 0.3}},
        "clock-1": {palette: {primary: "#FFB86C"}},
        "note-1": {palette: {text: "nope"}, motion: {spring: {damping: 30}}}}})).tokens;
    check("override: id виджета точнее типа", T.override(tk, "clock-1", "clock", "palette", "primary") === "#FFB86C");
    check("override: тип применяется ко всем виджетам типа", T.override(tk, "clock-2", "clock", "palette", "primary") === "#111111");
    check("override: материал от типа", T.override(tk, "clock-1", "clock", "material", "opacity") === 0.3);
    check("override: нет записи -> undefined", T.override(tk, "note-1", "note", "palette", "primary") === undefined);
    check("override: неверный цвет игнорируется", T.override(tk, "note-1", "note", "palette", "text") === undefined);
    check("override: вложенное поле", T.override(tk, "note-1", "note", "motion", "spring.damping") === 30);
    check("override: шрифты не переопределяются", T.override(tk, "clock-1", "clock", "typography", "size_body") === undefined);
    const fw = T.forWidget(tk, "clock-1", "clock");
    check("forWidget: слияние тип + id + тема", fw.palette.primary === "#FFB86C" && fw.material.opacity === 0.3 && fw.palette.bg === d.palette.bg);
    check("qtColor: #RRGGBBAA -> #AARRGGBB", T.qtColor("#11223344") === "#44112233" && T.qtColor("#112233") === "#112233");
    check("qtColor: мусор -> чёрный", T.qtColor("red") === "#000000");
}

// ---------- manager/lib/keymap.js (редактор клавиш) ----------
{
    const K = load("keymap.js", "manager");
    const META = 0x10000000, CTRL = 0x04000000, ALT = 0x08000000, SHIFT = 0x02000000;
    check("буква Q -> Q", K.keyName(0x51) === "Q");
    check("цифра 5 -> 5", K.keyName(0x35) === "5");
    check("F5 -> F5", K.keyName(0x01000034) === "F5");
    check("Enter -> RETURN", K.keyName(0x01000005) === "RETURN" && K.keyName(0x01000004) === "RETURN");
    check("пробел -> SPACE", K.keyName(0x20) === "SPACE");
    check("стрелка влево -> left", K.keyName(0x01000012) === "left");
    check("одиночный модификатор не комбинация", K.keyName(0x01000022) === "" && K.keyName(0x01000020) === "");
    check("неизвестная клавиша -> пусто", K.keyName(0x01ffffff) === "");
    check("Meta+Shift -> SUPER SHIFT", K.modsName(META | SHIFT) === "SUPER SHIFT");
    check("порядок модификаторов канонический", K.modsName(ALT | CTRL | META) === "SUPER CTRL ALT");
    check("без модификаторов -> пусто", K.modsName(0) === "");
    check("comboText Super+M", K.comboText("SUPER", "M") === "Super+M");
    check("comboText Ctrl+Alt+Return", K.comboText("CTRL ALT", "RETURN") === "Ctrl+Alt+Return");
    check("comboText без модификатора", K.comboText("", "F5") === "F5");
    check("verdict: чисто", K.verdict([]).clean && !K.verdict([]).blocked);
    check("verdict: error блокирует", K.verdict([{level: "error"}, {level: "warn"}]).blocked
        && !K.verdict([{level: "error"}]).needsForce);
    check("verdict: warn требует --force", K.verdict([{level: "warn"}]).needsForce
        && !K.verdict([{level: "warn"}]).blocked);
    const g = K.groupByCategory([{id: "a", category: "X"}, {id: "b", category: "Y"}, {id: "c", category: "X"}, {id: "d"}]);
    check("группы сохраняют порядок реестра", g.map(x => x.category).join() === "X,Y,Прочее"
        && g[0].items.length === 2);
    const a = K.setArgs("launcher", "SUPER", "SPACE", false);
    check("setArgs без force", a.join(" ") === "keys set launcher --mods SUPER --key SPACE --apply --yes");
    check("setArgs с force", K.setArgs("x", "", "F5", true).slice(-1)[0] === "--force");
}

console.log("Итог: PASS=" + pass + " FAIL=" + fail);
process.exit(fail === 0 ? 0 : 1);
