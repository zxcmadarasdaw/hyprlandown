import QtQuick
import QtQuick.Layouts

// Страница «кнопки + вывод». actions: [{label, args, tint?, confirm?}].
// Опасные действия (confirm) просят второй клик: Manager не выполняет их неожиданно.
Item {
    id: page
    property string title: ""
    property string hint: ""
    property var actions: []
    property string autoRun: ""   // JSON-массив аргументов, выполняется при открытии
    property string output: "Нажмите кнопку."
    property int armed: -1

    Cli {
        id: cli
        onDone: (data, text, code) => {
            page.output = (data ? JSON.stringify(data, null, 2) : text.trim()) + (code === 0 ? "" : "\n[код выхода " + code + "]");
        }
    }
    function runArgs(a) { cli.args = a; cli.run(); }
    Component.onCompleted: if (autoRun !== "") runArgs(JSON.parse(autoRun))

    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Text { text: page.title; color: Tk.text; font.pixelSize: Tk.sizeTitle; font.family: Tk.fontFamily; font.bold: true }
        Text {
            visible: page.hint !== ""
            text: page.hint; color: Tk.textMuted; font.pixelSize: Tk.sizeBody; font.family: Tk.fontFamily
            wrapMode: Text.WordWrap; Layout.fillWidth: true
        }
        Flow {
            Layout.fillWidth: true
            spacing: 8
            Repeater {
                model: page.actions
                delegate: Btn {
                    required property var modelData
                    required property int index
                    label: page.armed === index ? "Подтвердить: " + modelData.label : modelData.label
                    tint: modelData.tint === "danger" ? Tk.error : Tk.primary
                    enabled: !cli.busy
                    onClicked: {
                        if (modelData.confirm && page.armed !== index) { page.armed = index; return; }
                        page.armed = -1;
                        page.runArgs(modelData.args);
                    }
                }
            }
        }
        Rectangle {
            Layout.fillWidth: true; Layout.fillHeight: true
            radius: Tk.radiusSmall
            color: Tk.alpha(Tk.surface, 0.8); border.color: Tk.border; border.width: 1
            Flickable {
                anchors.fill: parent; anchors.margins: 10
                contentHeight: out.implicitHeight; clip: true
                Text {
                    id: out
                    width: parent.width
                    text: cli.busy ? "Выполняется…" : page.output
                    color: Tk.text; font.family: Tk.fontMono; font.pixelSize: Tk.sizeSmall
                    wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText
                }
            }
        }
    }
}
