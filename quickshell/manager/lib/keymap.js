.pragma library

// Перевод нажатия Qt в имена Hyprland для редактора клавиш Manager (hyprown keys set).
// Чистая логика без QML: проверяется scripts/test-qs-logic.js.

// Qt.Key_* (значения из qnamespace.h)
const NAMED = {
    0x20: "SPACE", 0x01000000: "ESCAPE", 0x01000001: "TAB", 0x01000003: "BACKSPACE", 0x01000004: "RETURN",
    0x01000005: "RETURN", 0x01000006: "INSERT", 0x01000007: "DELETE", 0x01000009: "PRINT",
    0x01000010: "HOME", 0x01000011: "END", 0x01000012: "left", 0x01000013: "up", 0x01000014: "right",
    0x01000015: "down", 0x01000016: "PRIOR", 0x01000017: "NEXT",
    0x2d: "MINUS", 0x3d: "EQUAL", 0x2c: "COMMA", 0x2e: "PERIOD", 0x2f: "SLASH", 0x5c: "BACKSLASH",
    0x3b: "SEMICOLON", 0x27: "APOSTROPHE", 0x60: "GRAVE", 0x5b: "BRACKETLEFT", 0x5d: "BRACKETRIGHT"
};
// Клавиши-модификаторы сами по себе комбинацией не являются
const MODIFIER_KEYS = [0x01000020, 0x01000021, 0x01000022, 0x01000023, 0x01000024, 0x01000025,
                       0x01000026, 0x01000027, 0x01000053, 0x01000054, 0x01001103];
const SHIFT = 0x02000000, CTRL = 0x04000000, ALT = 0x08000000, META = 0x10000000;

// Имя клавиши Hyprland или "" (нажат только модификатор или неизвестная клавиша).
function keyName(qtKey) {
    if (MODIFIER_KEYS.indexOf(qtKey) >= 0) return "";
    if (qtKey >= 0x41 && qtKey <= 0x5a) return String.fromCharCode(qtKey);          // A-Z
    if (qtKey >= 0x30 && qtKey <= 0x39) return String.fromCharCode(qtKey);          // 0-9
    if (qtKey >= 0x01000030 && qtKey <= 0x01000047) return "F" + (qtKey - 0x01000030 + 1);
    return NAMED[qtKey] || "";
}

// "SUPER CTRL ALT SHIFT" в каноническом порядке (Win = Meta в Qt).
function modsName(qtMods) {
    const out = [];
    if (qtMods & META) out.push("SUPER");
    if (qtMods & CTRL) out.push("CTRL");
    if (qtMods & ALT) out.push("ALT");
    if (qtMods & SHIFT) out.push("SHIFT");
    return out.join(" ");
}

function comboText(mods, key) {
    const names = (mods ? mods.split(" ") : []).map(function (m) { return m === "CTRL" ? "Ctrl" : m.charAt(0) + m.slice(1).toLowerCase(); });
    const k = key.length > 1 ? key.charAt(0).toUpperCase() + key.slice(1).toLowerCase() : key.toUpperCase();
    return names.concat([k]).join("+");
}

// Итог проверки конфликтов (ответ `keys check --json`): error блокирует, warn требует --force.
function verdict(conflicts) {
    let errors = 0, warns = 0;
    for (let i = 0; i < conflicts.length; i++) {
        if (conflicts[i].level === "error") errors++;
        else warns++;
    }
    return { blocked: errors > 0, needsForce: errors === 0 && warns > 0, clean: errors + warns === 0 };
}

// Группы для списка: [{category, items: []}] с сохранением порядка реестра.
function groupByCategory(binds) {
    const order = [], map = {};
    for (let i = 0; i < binds.length; i++) {
        const c = binds[i].category || "Прочее";
        if (!map[c]) { map[c] = { category: c, items: [] }; order.push(c); }
        map[c].items.push(binds[i]);
    }
    return order.map(function (c) { return map[c]; });
}

// Аргументы hyprown для назначения. Разрешения пользователя передаются явно флагами.
function setArgs(id, mods, key, force) {
    const a = ["keys", "set", id, "--mods", mods, "--key", key, "--apply", "--yes"];
    if (force) a.push("--force");
    return a;
}

// Экспорт для node-тестов; в QML (.pragma library) module не определён.
if (typeof module !== "undefined") {
    module.exports = {
        keyName: keyName, modsName: modsName, comboText: comboText,
        verdict: verdict, groupByCategory: groupByCategory, setArgs: setArgs
    };
}
