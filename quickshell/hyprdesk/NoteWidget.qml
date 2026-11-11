import QtQuick

// Заметка на холсте. Текст правится только в режиме редактирования
// и сохраняется в props.text (canvas.json). Пароли сюда не писать.
Rectangle {
    id: root

    property var props: ({})
    // Тема виджета: WidgetTheme с его переопределениями (WidgetFrame) или общая root.tk.
    property var tk: Theme
    property bool editing: false

    signal changeProps(var props)

    radius: root.tk.radiusLarge
    color: root.tk.alpha(root.tk.surface, root.tk.surfaceOpacity)
    border.color: editing ? root.tk.alpha(root.tk.primary, 0.6) : root.tk.alpha(root.tk.border, 0.9)
    border.width: root.tk.borderWidth
    clip: true

    TextEdit {
        id: edit
        anchors.fill: parent
        anchors.margins: 16
        text: root.props.text || ""
        readOnly: !root.editing
        selectByMouse: root.editing
        wrapMode: TextEdit.Wrap
        color: root.tk.text
        selectionColor: root.tk.alpha(root.tk.primary, 0.5)
        font.family: root.tk.fontFamily
        font.pixelSize: root.tk.sizeBody

        // Сохраняем с задержкой, чтобы не писать файл на каждую букву.
        onTextChanged: if (root.editing) saveTimer.restart()
    }

    Timer {
        id: saveTimer
        interval: 600
        onTriggered: {
            const p = Object.assign({}, root.props);
            p.text = edit.text;
            root.changeProps(p);
        }
    }

    // Выход из редактирования: несохранённый текст сохраняется сразу.
    onEditingChanged: if (!editing && saveTimer.running) {
        saveTimer.stop();
        saveTimer.triggered();
    }
}
