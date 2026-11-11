pragma Singleton
import QtQuick
import Quickshell

// Адрес CLI проекта. Менеджер работает от обычного пользователя и ничего не
// устанавливает сам: все действия идут через `hyprown` (общий backend).
Singleton {
    readonly property string home: Quickshell.env("HOME") || "/tmp"
    readonly property string cli: Quickshell.env("HYPROWN_CLI") || (home + "/.local/bin/hyprown")
}
