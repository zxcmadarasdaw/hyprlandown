import QtQuick
import QtQuick.Layouts

// Список компонентов. filter: all | widget | experimental.
// Установка: план (component plan --json) -> окно подтверждения -> install --yes.
Item {
    id: page
    property string title: "Компоненты"
    property string filter: "all"
    property var items: []
    property var plan: null
    property string planId: ""
    property string log: ""
    property bool working: false

    function visibleItems() {
        return items.filter(c => filter === "all" || (filter === "widget" && c.kind === "widget")
            || (filter === "experimental" && (c.experimental || c.kind === "plugin")));
    }
    function refresh() { list.args = ["component", "list", "--json"]; list.run(); }
    Component.onCompleted: refresh()

    Cli { id: list; onDone: (data, text, code) => { if (data) page.items = data.components; } }
    Cli {
        id: planCli
        onDone: (data, text, code) => { if (data) page.plan = data; else page.log = text; }
    }
    Cli {
        id: act
        onLine: ev => {
            if (ev.event === "step_start") page.log += "→ " + ev.title + "\n";
            else if (ev.event === "step_end") page.log += (ev.status === "ok" ? "✓ " : ev.status === "warn" ? "⚠ " : "✗ ") + ev.title + (ev.note ? ": " + ev.note : "") + "\n";
            else if (ev.text) page.log += ev.text + "\n";
        }
        onDone: (data, text, code) => { page.working = false; page.log += code === 0 ? "\nГотово.\n" : "\nЗавершено с ошибкой (код " + code + ").\n"; page.refresh(); }
    }
    function startPlan(id) { planId = id; plan = null; log = ""; planCli.args = ["component", "plan", id, "--json"]; planCli.run(); }
    function runAct(a) { working = true; log = ""; act.args = a; act.run(); }

    ColumnLayout {
        anchors.fill: parent
        spacing: 10
        Text { text: page.title; color: Tk.text; font.pixelSize: Tk.sizeTitle; font.family: Tk.fontFamily; font.bold: true }
        Text {
            visible: page.visibleItems().length === 0
            text: page.filter === "widget" ? "Виджетов-модулей пока нет. Они появятся как компоненты kind = widget (docs/MODULES.md)." : "Здесь пока пусто."
            color: Tk.textMuted; font.pixelSize: Tk.sizeBody; font.family: Tk.fontFamily
        }
        ListView {
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: 8
            model: page.visibleItems()
            delegate: Rectangle {
                required property var modelData
                width: ListView.view.width
                height: 84
                radius: Tk.radius
                color: Tk.alpha(Tk.surface, 0.85); border.color: Tk.border; border.width: 1
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 12; spacing: 2
                    RowLayout {
                        Text { text: modelData.name; color: Tk.text; font.pixelSize: Tk.sizeBody + 1; font.bold: true; font.family: Tk.fontFamily }
                        Text { text: modelData.version; color: Tk.textMuted; font.pixelSize: Tk.sizeSmall; font.family: Tk.fontFamily }
                        Text {
                            text: modelData.failed ? "ошибка установки" : modelData.installed ? (modelData.enabled ? "включён" : "выключен") : "не установлен"
                            color: modelData.failed ? Tk.error : modelData.installed ? (modelData.enabled ? Tk.success : Tk.warning) : Tk.textMuted
                            font.pixelSize: Tk.sizeSmall; font.family: Tk.fontFamily
                        }
                        Text { visible: modelData.experimental; text: "экспериментальный"; color: Tk.warning; font.pixelSize: Tk.sizeSmall; font.family: Tk.fontFamily }
                        Item { Layout.fillWidth: true }
                        Btn { visible: !modelData.installed; label: "Установить"; enabled: !page.working && modelData.approved; onClicked: page.startPlan(modelData.id) }
                        Btn { visible: modelData.installed && !modelData.enabled; label: "Активировать"; enabled: !page.working; onClicked: page.runAct(["--json-stream", "component", "enable", modelData.id]) }
                        Btn { visible: modelData.installed && modelData.enabled; label: "Отключить"; tint: Tk.warning; enabled: !page.working; onClicked: page.runAct(["--json-stream", "component", "disable", modelData.id]) }
                        Btn { visible: modelData.installed; label: "Удалить"; tint: Tk.error; enabled: !page.working; onClicked: page.runAct(["--json-stream", "--yes", "component", "remove", modelData.id]) }
                    }
                    Text { text: modelData.summary; color: Tk.textMuted; font.pixelSize: Tk.sizeSmall; font.family: Tk.fontFamily; wrapMode: Text.WordWrap; Layout.fillWidth: true; maximumLineCount: 2; elide: Text.ElideRight }
                    Text { visible: modelData.failure !== ""; text: modelData.failure; color: Tk.error; font.pixelSize: Tk.sizeSmall; font.family: Tk.fontFamily }
                }
            }
        }
        Rectangle {
            visible: page.log !== ""
            Layout.fillWidth: true; Layout.preferredHeight: 150
            radius: Tk.radiusSmall; color: Tk.alpha(Tk.surface, 0.9); border.color: Tk.border
            Flickable {
                anchors.fill: parent; anchors.margins: 8; clip: true; contentHeight: lt.implicitHeight
                Text { id: lt; width: parent.width; text: page.log; color: Tk.text; font.family: Tk.fontMono; font.pixelSize: Tk.sizeSmall; wrapMode: Text.WrapAnywhere }
            }
        }
    }

    // Окно подтверждения: показывает изменения ДО установки.
    Rectangle {
        anchors.fill: parent
        visible: page.plan !== null
        color: Tk.alpha(Tk.bg, 0.7)
        MouseArea { anchors.fill: parent }
        Rectangle {
            width: Math.min(parent.width - 40, 620); height: Math.min(parent.height - 40, 460)
            anchors.centerIn: parent
            radius: Tk.radius; color: Tk.surfaceAlt; border.color: Tk.primary; border.width: 1
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 16; spacing: 8
                Text { text: "Установить: " + page.planId; color: Tk.text; font.pixelSize: Tk.sizeTitle - 2; font.bold: true; font.family: Tk.fontFamily }
                Flickable {
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true; contentHeight: pt.implicitHeight
                    Text {
                        id: pt; width: parent.width; color: Tk.text; font.family: Tk.fontMono; font.pixelSize: Tk.sizeSmall; wrapMode: Text.WrapAnywhere
                        text: {
                            if (!page.plan) return "";
                            let s = "";
                            for (const p of page.plan.packages) s += (p.state === "installed" ? "уже есть     " : p.state === "available" ? "установить    " : p.state === "needs-copr" ? "СТОРОННИЙ COPR " : "недоступен    ") + p.id + "\n";
                            s += "\nСсылки на конфиги:\n";
                            for (const l of page.plan.links) if (l.state !== "ok") s += "  " + l.dst + " -> " + l.src + "\n";
                            for (const w of page.plan.warnings) s += "\n⚠ " + w;
                            for (const p of page.plan.problems) s += "\n✗ " + p;
                            for (const k in page.plan.blocked) s += "\n✗ " + k + ": " + page.plan.blocked[k];
                            if (page.plan.need_root) s += "\n\nДля dnf появится системный запрос пароля (polkit). Manager пароль не видит.";
                            if (page.plan.live) s += "\n\nLive USB: после перезагрузки установленное пропадёт.";
                            return s;
                        }
                    }
                }
                RowLayout {
                    Item { Layout.fillWidth: true }
                    Btn { label: "Отмена"; tint: Tk.textMuted; onClicked: page.plan = null }
                    Btn {
                        label: "Установить"
                        enabled: page.plan !== null && page.plan.problems.length === 0 && Object.keys(page.plan.blocked).length === 0
                        onClicked: { const id = page.planId; page.plan = null; page.runAct(["--json-stream", "--yes", "component", "install", id]); }
                    }
                }
            }
        }
    }
}
