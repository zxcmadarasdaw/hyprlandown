import QtQuick
import QtQuick.Layouts

// Диагностика: hyprown doctor --json. Только чтение.
Item {
    id: page
    property var checks: []
    property string summary: ""
    Cli {
        id: cli
        args: ["doctor", "--json"]
        onDone: (data, text, code) => {
            if (data) { page.checks = data.checks; const s = data.summary; page.summary = "ок " + s.ok + " · предупреждений " + s.warn + " · ошибок " + s.fail; }
            else page.summary = text;
        }
    }
    Component.onCompleted: cli.run()
    ColumnLayout {
        anchors.fill: parent; spacing: 10
        RowLayout {
            Text { text: "Diagnostics"; color: Tk.text; font.pixelSize: Tk.sizeTitle; font.bold: true; font.family: Tk.fontFamily }
            Item { Layout.fillWidth: true }
            Text { text: cli.busy ? "проверка…" : page.summary; color: Tk.textMuted; font.family: Tk.fontFamily; font.pixelSize: Tk.sizeBody }
            Btn { label: "Проверить снова"; enabled: !cli.busy; onClicked: cli.run() }
        }
        ListView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 4
            model: page.checks
            delegate: Rectangle {
                required property var modelData
                width: ListView.view.width; height: col.implicitHeight + 12
                radius: Tk.radiusSmall; color: Tk.alpha(Tk.surface, 0.8)
                RowLayout {
                    anchors.fill: parent; anchors.margins: 6; spacing: 8
                    Text {
                        text: modelData.status === "ok" ? "✓" : modelData.status === "warn" ? "⚠" : modelData.status === "fail" ? "✗" : "·"
                        color: modelData.status === "ok" ? Tk.success : modelData.status === "warn" ? Tk.warning : modelData.status === "fail" ? Tk.error : Tk.textMuted
                        font.pixelSize: Tk.sizeBody; font.family: Tk.fontFamily
                    }
                    ColumnLayout {
                        id: col; Layout.fillWidth: true; spacing: 0
                        Text { text: modelData.title; color: Tk.text; font.pixelSize: Tk.sizeBody; font.family: Tk.fontFamily }
                        Text { visible: modelData.detail !== ""; text: modelData.detail; color: Tk.textMuted; font.pixelSize: Tk.sizeSmall; font.family: Tk.fontFamily; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
                        Text { visible: modelData.fix !== "" && modelData.status !== "ok"; text: "Что делать: " + modelData.fix; color: Tk.accent; font.pixelSize: Tk.sizeSmall; font.family: Tk.fontFamily; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                    }
                }
            }
        }
    }
}
