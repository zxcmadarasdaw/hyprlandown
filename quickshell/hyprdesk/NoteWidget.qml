import QtQuick

// Заметка на холсте. Текст правится только в режиме редактирования
// и сохраняется в props.text (canvas.json). Пароли сюда не писать.
Rectangle {
    id: root

    property var props: ({})
    property bool editing: false

    signal changeProps(var props)

    radius: Theme.radiusLarge
    color: Theme.alpha(Theme.surface, Theme.surfaceOpacity)
    border.color: editing ? Theme.alpha(Theme.primary, 0.6) : Theme.alpha(Theme.border, 0.9)
    border.width: 1
    clip: true

    TextEdit {
        id: edit
        anchors.fill: parent
        anchors.margins: 16
        text: root.props.text || ""
        readOnly: !root.editing
        selectByMouse: root.editing
        wrapMode: TextEdit.Wrap
        color: Theme.text
        selectionColor: Theme.alpha(Theme.primary, 0.5)
        font.family: Theme.fontFamily
        font.pixelSize: Theme.sizeBody

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
