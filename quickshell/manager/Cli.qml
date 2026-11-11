import QtQuick
import Quickshell.Io

// Один вызов hyprown. Использование:
//   Cli { id: c; args: ["status", "--json"]; onDone: (data, text, code) => ... }  c.run()
// data: разобранный JSON (если вывод был JSON), text: сырой вывод.
Item {
    id: root
    property var args: []
    property bool busy: false
    property string text: ""
    property int code: -1
    property bool _gotText: false
    property bool _gotExit: false
    signal done(var data, string text, int code)
    signal line(var event)   // для --json-stream: каждое событие

    function run() {
        if (busy) return;
        busy = true; _gotText = false; _gotExit = false; text = "";
        proc.command = [Backend.cli, "--plain"].concat(args);
        proc.running = true;
    }
    function _finish() {
        if (!(_gotText && _gotExit)) return;
        busy = false;
        let data = null;
        try { data = JSON.parse(text); } catch (e) { data = null; }
        done(data, text, code);
    }
    Process {
        id: proc
        stdout: SplitParser {
            onRead: data => {
                root.text += data + "\n";
                try { root.line(JSON.parse(data)); } catch (e) {}
            }
        }
        stderr: SplitParser { onRead: data => root.text += data + "\n" }
        onExited: (c, s) => { root.code = c; root._gotExit = true; root._gotText = true; root._finish(); }
    }
}
