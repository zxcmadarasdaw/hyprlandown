import QtQuick
import QtQuick.Layouts
import "lib/keymap.js" as Keymap

// Редактор горячих клавиш. Все изменения идут через `hyprown keys ...`: там реестр,
// проверка конфликтов и защита пользовательских файлов (это окно ничего не решает само).
//
// Важно: комбинацию, которую Hyprland уже занял (например, Super+Q), окно не получит, потому что
// композитор перехватывает её раньше. Для таких комбинаций есть ручной выбор модификаторов и клавиши.
Item {
    id: page
    property var binds: []
    property var rows: []
    property bool handEdited: false
    property string status: ""
    property var editing: null
    property string capMods: ""
    property string capKey: ""
    property var conflicts: []
    property bool conflictsFresh: false
    property bool allowHand: false
    property bool force: false
    readonly property var verdict: Keymap.verdict(conflicts)

    function rebuild() {
        const out = [];
        const groups = Keymap.groupByCategory(binds);
        for (let g = 0; g < groups.length; g++) {
            out.push({ header: true, text: groups[g].category });
            for (let i = 0; i < groups[g].items.length; i++) out.push({ header: false, bind: groups[g].items[i] });
        }
        rows = out;
    }
    function startEdit(b) {
        editing = b; capMods = b.mods; capKey = b.key; conflicts = []; conflictsFresh = false;
        allowHand = false; force = false;
        check();
    }
    function toggleMod(m) {
        const cur = capMods === "" ? [] : capMods.split(" ");
        const i = cur.indexOf(m);
        if (i >= 0) cur.splice(i, 1); else cur.push(m);
        const order = ["SUPER", "CTRL", "ALT", "SHIFT"];
        capMods = order.filter(function (x) { return cur.indexOf(x) >= 0; }).join(" ");
        check();
    }
    function check() {
        conflictsFresh = false; force = false;
        if (!editing || capKey === "") { conflicts = []; return; }
        checkCli.args = ["keys", "check", editing.id, "--mods", capMods, "--key", capKey, "--json"];
        checkCli.run();
    }

    Cli {
        id: listCli
        args: ["keys", "list", "--json"]
        onDone: (data, text, code) => {
            if (data) { page.binds = data.binds; page.handEdited = data.user_conf_hand_edited; page.rebuild(); }
            else page.status = text.trim();
        }
    }
    Cli {
        id: checkCli
        onDone: (data, text, code) => {
            page.conflicts = data ? data.conflicts : [{ level: "error", kind: "cli", message: text.trim() }];
            page.conflictsFresh = true;
        }
    }
    Cli {
        id: actCli
        onDone: (data, text, code) => {
            page.status = text.trim() + (code === 0 ? "" : "\n[код выхода " + code + "]");
            if (code === 0) { page.editing = null; listCli.run(); }
        }
    }
    Component.onCompleted: listCli.run()

    ColumnLayout {
        anchors.fill: parent; spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Text { text: "Keybinds"; color: Tk.text; font.pixelSize: Tk.sizeTitle; font.bold: true; font.family: Tk.fontFamily }
            Item { Layout.fillWidth: true }
            Btn { label: "Обновить"; enabled: !listCli.busy; onClicked: listCli.run() }
            Btn { label: "Применить к сессии"; enabled: !actCli.busy; onClicked: { actCli.args = ["keys", "apply", "--yes"]; actCli.run(); } }
            Btn { label: "Живая сверка"; enabled: !actCli.busy; onClicked: { actCli.args = ["keys", "live"]; actCli.run(); } }
            Btn { label: "Сбросить все"; tint: Tk.error; enabled: !actCli.busy; onClicked: { actCli.args = ["keys", "reset", "--apply", "--yes"]; actCli.run(); } }
        }
        Text {
            Layout.fillWidth: true; wrapMode: Text.WordWrap
            color: Tk.textMuted; font.pixelSize: Tk.sizeSmall; font.family: Tk.fontFamily
            text: "Единый реестр клавиш HyprlandOwn. Конфликты проверяются при назначении; чужие привязки сессии не снимаются без вашего согласия."
                  + (page.handEdited ? "\nВнимание: keybinds.user.conf правился вручную. Пересоздать его можно только с вашего явного разрешения (копия сохранится)." : "")
        }
        Text {
            visible: page.status !== ""; Layout.fillWidth: true; wrapMode: Text.WrapAnywhere
            color: Tk.accent; font.pixelSize: Tk.sizeSmall; font.family: Tk.fontMono; text: page.status
        }
        ListView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 4
            model: page.rows
            delegate: Rectangle {
                required property var modelData
                width: ListView.view.width
                height: modelData.header ? 30 : 44
                radius: Tk.radiusSmall
                color: modelData.header ? "transparent" : Tk.alpha(Tk.surface, 0.8)
                Text {
                    visible: modelData.header
                    anchors.verticalCenter: parent.verticalCenter; x: 4
                    text: modelData.header ? modelData.text : ""
                    color: Tk.primary; font.pixelSize: Tk.sizeBody; font.bold: true; font.family: Tk.fontFamily
                }
                RowLayout {
                    visible: !modelData.header
                    anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 8; spacing: 10
                    Text {
                        Layout.fillWidth: true; elide: Text.ElideRight
                        text: modelData.header ? "" : modelData.bind.title
                        color: Tk.text; font.pixelSize: Tk.sizeBody; font.family: Tk.fontFamily
                    }
                    Text {
                        text: modelData.header ? "" : (modelData.bind.disabled ? "отключена" : modelData.bind.combo)
                        color: modelData.header ? Tk.text : (modelData.bind.overridden ? Tk.warning : Tk.accent)
                        font.pixelSize: Tk.sizeBody; font.family: Tk.fontMono; font.bold: true
                    }
                    Text {
                        visible: !modelData.header && (modelData.bind.overridden || modelData.bind.disabled)
                        text: modelData.header ? "" : "(по умолчанию " + modelData.bind.default + ")"
                        color: Tk.textMuted; font.pixelSize: Tk.sizeSmall; font.family: Tk.fontFamily
                    }
                    Btn { visible: !modelData.header; label: "Изменить"; onClicked: page.startEdit(modelData.bind) }
                    Btn {
                        visible: !modelData.header && (modelData.bind.overridden || modelData.bind.disabled); label: "Сбросить"; tint: Tk.textMuted
                        onClicked: { actCli.args = ["keys", "reset", modelData.bind.id, "--apply", "--yes"]; actCli.run(); }
                    }
                }
            }
        }
    }

    // ---- окно назначения ----
    Rectangle {
        visible: page.editing !== null
        anchors.fill: parent; color: Tk.alpha(Tk.bg, 0.82)
        MouseArea { anchors.fill: parent }   // не пускать клики под окно
        Rectangle {
            id: card
            anchors.centerIn: parent
            width: Math.min(parent.width - 40, 640); height: cardCol.implicitHeight + 32
            radius: Tk.radius; color: Tk.surfaceAlt; border.color: Tk.border; border.width: 1
            ColumnLayout {
                id: cardCol
                anchors.fill: parent; anchors.margins: 16; spacing: 10
                Text {
                    text: page.editing ? "Новая комбинация: " + page.editing.title : ""
                    color: Tk.text; font.pixelSize: Tk.sizeBody + 2; font.bold: true; font.family: Tk.fontFamily
                    Layout.fillWidth: true; wrapMode: Text.WordWrap
                }
                // Захват нажатия. Занятые композитором комбинации сюда не дойдут: используйте выбор ниже.
                FocusScope {
                    id: capture
                    Layout.fillWidth: true; height: 54
                    focus: page.editing !== null
                    Keys.onPressed: event => {
                        const k = Keymap.keyName(event.key);
                        if (k === "") { event.accepted = true; return; }
                        page.capMods = Keymap.modsName(event.modifiers);
                        page.capKey = k;
                        page.check();
                        event.accepted = true;
                    }
                    Rectangle {
                        anchors.fill: parent; radius: Tk.radiusSmall; color: Tk.alpha(Tk.surface, 0.9)
                        border.color: capture.activeFocus ? Tk.primary : Tk.border; border.width: 2
                        Text {
                            anchors.centerIn: parent
                            text: page.capKey === "" ? "Нажмите комбинацию…" : Keymap.comboText(page.capMods, page.capKey)
                            color: page.capKey === "" ? Tk.textMuted : Tk.text
                            font.pixelSize: Tk.sizeTitle; font.family: Tk.fontMono; font.bold: true
                        }
                        MouseArea { anchors.fill: parent; onClicked: capture.forceActiveFocus() }
                    }
                }
                Text {
                    text: "Или выберите вручную (для комбинаций, которые уже занял Hyprland, например Super+Q):"
                    color: Tk.textMuted; font.pixelSize: Tk.sizeSmall; font.family: Tk.fontFamily
                    Layout.fillWidth: true; wrapMode: Text.WordWrap
                }
                RowLayout {
                    spacing: 8
                    Repeater {
                        model: ["SUPER", "CTRL", "ALT", "SHIFT"]
                        delegate: Btn {
                            required property string modelData
                            readonly property bool on: page.capMods.split(" ").indexOf(modelData) >= 0
                            label: (on ? "✓ " : "") + modelData
                            tint: on ? Tk.success : Tk.textMuted
                            onClicked: page.toggleMod(modelData)
                        }
                    }
                    Rectangle {
                        width: 150; height: 32; radius: 8; color: Tk.alpha(Tk.surface, 0.9); border.color: Tk.border; border.width: 1
                        TextInput {
                            id: keyInput
                            anchors.fill: parent; anchors.margins: 6
                            color: Tk.text; font.family: Tk.fontMono; font.pixelSize: Tk.sizeBody
                            text: page.capKey
                            onTextEdited: { page.capKey = text.trim(); page.check(); }
                            selectByMouse: true
                        }
                        Text { visible: keyInput.text === ""; anchors.centerIn: parent; text: "клавиша: X, RETURN, F5"; color: Tk.textMuted; font.pixelSize: Tk.sizeSmall; font.family: Tk.fontFamily }
                    }
                }
                Repeater {
                    model: page.conflicts
                    delegate: Text {
                        required property var modelData
                        Layout.fillWidth: true; wrapMode: Text.WordWrap
                        text: (modelData.level === "error" ? "✗ " : "⚠ ") + modelData.message
                        color: modelData.level === "error" ? Tk.error : Tk.warning
                        font.pixelSize: Tk.sizeSmall; font.family: Tk.fontFamily
                    }
                }
                Text {
                    visible: page.conflictsFresh && page.verdict.clean
                    text: "✓ Конфликтов нет"; color: Tk.success; font.pixelSize: Tk.sizeSmall; font.family: Tk.fontFamily
                }
                RowLayout {
                    visible: page.verdict.needsForce; spacing: 8
                    Btn { label: page.force ? "✓ Назначить, несмотря на предупреждения" : "Назначить, несмотря на предупреждения"; tint: Tk.warning; onClicked: page.force = !page.force }
                }
                RowLayout {
                    visible: page.handEdited; spacing: 8
                    Btn { label: page.allowHand ? "✓ Разрешаю пересоздать keybinds.user.conf (копия сохранится)" : "Разрешить пересоздать keybinds.user.conf (правился вручную)"; tint: Tk.warning; onClicked: page.allowHand = !page.allowHand }
                }
                RowLayout {
                    Layout.fillWidth: true; spacing: 8
                    Item { Layout.fillWidth: true }
                    Btn { label: "Отмена"; tint: Tk.textMuted; onClicked: page.editing = null }
                    Btn {
                        label: "Назначить"
                        enabled: !actCli.busy && page.conflictsFresh && page.capKey !== "" && !page.verdict.blocked
                                 && (!page.verdict.needsForce || page.force) && (!page.handEdited || page.allowHand)
                        onClicked: { actCli.args = Keymap.setArgs(page.editing.id, page.capMods, page.capKey, page.force); actCli.run(); }
                    }
                }
            }
        }
    }
}
