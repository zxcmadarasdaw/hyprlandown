import QtQuick
import QtQuick.Layouts

// Themes & Wallpapers (этап 4): готовые темы, палитра из обоев, свои цвета виджетов.
// Всё меняется через `hyprown theme ...`; оболочка и Manager подхватывают tokens.json сами.
Item {
    id: page
    property var info: null
    property string output: ""
    property int armed: -1
    // редактор цветов виджета
    property string wid: ""
    property string role: "primary"
    property string hex: ""
    readonly property var roles: [
        {id: "primary", label: "Акцент"}, {id: "accent", label: "Подсветка"}, {id: "text", label: "Текст"},
        {id: "text_muted", label: "Второй текст"}, {id: "surface", label: "Фон"}, {id: "border", label: "Рамка"}
    ]
    readonly property bool hexOk: /^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/.test(hex)

    function refresh() { statusCli.run(); }
    function act(args) { actCli.args = args; actCli.run(); }
    function ovFor(w) { return info && info.widget_overrides ? (info.widget_overrides[w] || null) : null; }
    function ovText(w) {
        const o = ovFor(w);
        if (!o) return "цвета темы";
        const parts = [];
        for (const sec in o) for (const k in o[sec]) parts.push(k + "=" + JSON.stringify(o[sec][k]));
        return parts.join(", ");
    }

    Cli {
        id: statusCli
        args: ["theme", "status", "--json"]
        onDone: (data, text, code) => {
            if (data) {
                page.info = data;
                if (page.wid === "" && data.widgets.length > 0) page.wid = data.widgets[0].id;
            } else page.output = text.trim();
        }
    }
    Cli {
        id: actCli
        onDone: (data, text, code) => {
            page.output = text.trim() + (code === 0 ? "" : "\n[код выхода " + code + "]");
            page.refresh();
            Tk.reload();
        }
    }
    Component.onCompleted: refresh()

    Flickable {
        anchors.fill: parent
        contentHeight: col.implicitHeight
        clip: true

        ColumnLayout {
            id: col
            width: parent.width
            spacing: 14

            Text { text: "Themes & Wallpapers"; color: Tk.text; font.pixelSize: Tk.sizeTitle; font.family: Tk.fontFamily; font.bold: true }
            Text {
                Layout.fillWidth: true; wrapMode: Text.WordWrap
                color: Tk.textMuted; font.pixelSize: Tk.sizeBody; font.family: Tk.fontFamily
                text: page.info === null ? "Загрузка…"
                      : "Сейчас: " + (page.info.mode === "wallpaper" ? "палитра из обоев (форма и материал темы " + page.info.preset + ")"
                                                                     : "тема " + page.info.preset)
                        + ". Ctrl+Alt+F открывает выбор темы прямо на рабочем столе."
                        + (page.info.readable ? "" : "\nВнимание: " + page.info.problems.join("; "))
            }

            // ---- готовые темы ----
            Flow {
                Layout.fillWidth: true
                spacing: 10
                Repeater {
                    model: page.info ? page.info.presets : []
                    delegate: Rectangle {
                        id: card
                        required property var modelData
                        readonly property bool active: page.info.mode === "preset" && page.info.preset === modelData.id
                        width: 210; height: 104; radius: Tk.radiusSmall + 4
                        color: modelData.palette.bg
                        border.width: active ? 3 : 1
                        border.color: active ? Tk.primary : Tk.border
                        Column {
                            anchors.fill: parent; anchors.margins: 10; spacing: 8
                            Text { text: (card.active ? "● " : "") + card.modelData.name; color: card.modelData.palette.text; font.pixelSize: Tk.sizeBody; font.bold: true; font.family: Tk.fontFamily }
                            Row {
                                spacing: 5
                                Repeater {
                                    model: ["surface", "primary", "secondary", "accent", "text"]
                                    delegate: Rectangle {
                                        required property string modelData
                                        width: 22; height: 22; radius: 11
                                        color: card.modelData.palette[modelData]
                                        border.color: Tk.alpha(Tk.text, 0.25); border.width: 1
                                    }
                                }
                            }
                            Text { width: parent.width; elide: Text.ElideRight; text: card.modelData.description; color: card.modelData.palette.text; opacity: 0.75; font.pixelSize: Tk.sizeSmall; font.family: Tk.fontFamily }
                        }
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; enabled: !actCli.busy; onClicked: page.act(["theme", "set", card.modelData.id]) }
                    }
                }
            }

            Flow {
                Layout.fillWidth: true
                spacing: 8
                Btn {
                    label: page.info && page.info.mode === "wallpaper" ? "✓ Палитра из обоев" : "Палитра из обоев"
                    enabled: !actCli.busy
                    onClicked: page.act(["theme", "mode", "wallpaper"])
                }
                Btn { label: "Пересчитать из текущих обоев"; enabled: !actCli.busy && page.info !== null && page.info.current_wallpaper !== ""; onClicked: page.act(["theme", "from-wallpaper", "--switch"]) }
                Btn { label: "Следующие обои"; enabled: !actCli.busy; onClicked: page.act(["ipc", "wallpaper", "next"]) }
                Btn { label: "Сетка превью"; enabled: !actCli.busy; onClicked: page.act(["ipc", "wallpaper", "picker"]) }
                Btn {
                    label: page.armed === 1 ? "Подтвердить: стандартная палитра" : "Стандартная палитра"
                    tint: Tk.error; enabled: !actCli.busy
                    onClicked: { if (page.armed !== 1) { page.armed = 1; return; } page.armed = -1; page.act(["theme", "reset"]); }
                }
            }

            // ---- цвета виджетов ----
            Text { text: "Свои цвета виджета"; color: Tk.text; font.pixelSize: Tk.sizeBody + 2; font.bold: true; font.family: Tk.fontFamily; Layout.topMargin: 6 }
            Text {
                Layout.fillWidth: true; wrapMode: Text.WordWrap
                text: "Хранятся отдельно от темы: смена обоев и темы их не сбрасывает. Цвет для типа (например, clock) действует на все такие виджеты, для id - только на один."
                color: Tk.textMuted; font.pixelSize: Tk.sizeSmall; font.family: Tk.fontFamily
            }
            Flow {
                Layout.fillWidth: true
                spacing: 8
                Repeater {
                    model: {
                        if (!page.info) return [];
                        const out = [], types = {};
                        for (const w of page.info.widgets) { out.push({key: w.id, label: w.id}); types[w.type] = true; }
                        for (const t in types) out.push({key: t, label: "все " + t});
                        return out;
                    }
                    delegate: Btn {
                        required property var modelData
                        label: (page.wid === modelData.key ? "✓ " : "") + modelData.label + (page.ovFor(modelData.key) ? " *" : "")
                        tint: page.wid === modelData.key ? Tk.accent : Tk.textMuted
                        onClicked: page.wid = modelData.key
                    }
                }
            }
            Text {
                visible: page.wid !== ""
                Layout.fillWidth: true; wrapMode: Text.WrapAnywhere
                text: page.wid + ": " + page.ovText(page.wid)
                color: Tk.textMuted; font.pixelSize: Tk.sizeSmall; font.family: Tk.fontMono
            }
            Flow {
                visible: page.wid !== ""
                Layout.fillWidth: true
                spacing: 8
                Repeater {
                    model: page.roles
                    delegate: Btn {
                        required property var modelData
                        label: (page.role === modelData.id ? "✓ " : "") + modelData.label
                        tint: page.role === modelData.id ? Tk.primary : Tk.textMuted
                        onClicked: page.role = modelData.id
                    }
                }
            }
            RowLayout {
                visible: page.wid !== ""
                spacing: 8
                // быстрый выбор из текущей палитры
                Repeater {
                    model: page.info ? ["primary", "secondary", "accent", "success", "warning", "error", "text", "surface_alt"] : []
                    delegate: Rectangle {
                        required property string modelData
                        width: 28; height: 28; radius: 14
                        color: page.info.palette[modelData]
                        border.color: page.hex === page.info.palette[modelData] ? Tk.text : Tk.alpha(Tk.text, 0.25)
                        border.width: page.hex === page.info.palette[modelData] ? 3 : 1
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: page.hex = page.info.palette[modelData] }
                    }
                }
                Rectangle {
                    width: 120; height: 32; radius: 8; color: Tk.alpha(Tk.surface, 0.9)
                    border.color: page.hex === "" || page.hexOk ? Tk.border : Tk.error; border.width: 1
                    TextInput {
                        id: hexInput
                        anchors.fill: parent; anchors.margins: 7
                        color: Tk.text; font.family: Tk.fontMono; font.pixelSize: Tk.sizeBody
                        text: page.hex
                        onTextEdited: page.hex = text.trim()
                        maximumLength: 9
                        selectByMouse: true
                    }
                    Text { visible: hexInput.text === ""; anchors.centerIn: parent; text: "#RRGGBB"; color: Tk.textMuted; font.pixelSize: Tk.sizeSmall; font.family: Tk.fontMono }
                }
                Rectangle { width: 32; height: 32; radius: 16; color: page.hexOk ? page.hex.substr(0, 7) : "transparent"; border.color: Tk.border; border.width: 1 }
                Btn {
                    label: "Сохранить"
                    enabled: !actCli.busy && page.hexOk
                    onClicked: page.act(["theme", "override", page.wid, "palette." + page.role + "=" + page.hex])
                }
                Btn {
                    label: "Убрать этот цвет"; tint: Tk.textMuted
                    enabled: !actCli.busy && page.ovFor(page.wid) !== null
                    onClicked: page.act(["theme", "override", page.wid, "--clear", "palette." + page.role])
                }
                Btn {
                    label: "Сбросить виджет"; tint: Tk.error
                    enabled: !actCli.busy && page.ovFor(page.wid) !== null
                    onClicked: page.act(["theme", "override", page.wid, "--clear"])
                }
            }

            Rectangle {
                visible: page.output !== "" || actCli.busy
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(160, outText.implicitHeight + 20)
                radius: Tk.radiusSmall
                color: Tk.alpha(Tk.surface, 0.8); border.color: Tk.border; border.width: 1
                Text {
                    id: outText
                    anchors.fill: parent; anchors.margins: 10
                    text: actCli.busy ? "Выполняется…" : page.output
                    color: Tk.text; font.family: Tk.fontMono; font.pixelSize: Tk.sizeSmall
                    wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText
                }
            }
        }
    }
}
