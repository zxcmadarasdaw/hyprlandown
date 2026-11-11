import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland

// hyprdesk: оболочка рабочего стола на Quickshell (этапы 2 и 3).
// Запуск: qs -c hyprdesk   (конфиг лежит в ~/.config/quickshell/hyprdesk)
//
// Слои снизу вверх на каждом мониторе:
//   Background  WallpaperWindow  - обои (картинка или mpvpaper для видео)
//   Bottom      CanvasWindow     - холст виджетов (под окнами)
//   (окна приложений)
//   Top         Bar              - панель
//   Overlay     WallpaperPicker  - сетка обоев, только когда открыта
//
// Управление снаружи (хоткеи Hyprland в hypr/keybinds.conf):
//   qs ipc -c hyprdesk call canvas toggleEdit
//   qs ipc -c hyprdesk call canvas resetCamera
//   qs ipc -c hyprdesk call wallpaper next | prev | picker | reset
//   qs ipc -c hyprdesk call wallpaper set /путь/к/файлу
//   qs ipc -c hyprdesk call wallpaper setAll /путь/к/файлу
ShellRoot {
    Variants {
        model: Quickshell.screens
        WallpaperWindow {}
    }

    Variants {
        model: Quickshell.screens
        CanvasWindow {}
    }

    Variants {
        model: Quickshell.screens
        Bar {}
    }

    LazyLoader {
        active: WallpaperStore.pickerOpen
        WallpaperPicker {}
    }

    IpcHandler {
        target: "canvas"

        function toggleEdit(): void {
            CanvasStore.setEditMode(!CanvasStore.editMode);
        }

        function setEdit(on: bool): void {
            CanvasStore.setEditMode(on);
        }

        // Камера фокусного монитора: центр мира, масштаб 100%.
        function resetCamera(): void {
            CanvasStore.cameraResetRequested(WallpaperStore.focusedMonitor());
        }
    }

    IpcHandler {
        target: "wallpaper"

        function next(): void {
            WallpaperStore.step(WallpaperStore.focusedMonitor(), 1);
        }

        function prev(): void {
            WallpaperStore.step(WallpaperStore.focusedMonitor(), -1);
        }

        function picker(): void {
            if (WallpaperStore.pickerOpen)
                WallpaperStore.closePicker();
            else
                WallpaperStore.openPicker(WallpaperStore.focusedMonitor());
        }

        function set(path: string): void {
            WallpaperStore.setPath(WallpaperStore.focusedMonitor(), path);
        }

        function setAll(path: string): void {
            WallpaperStore.setPath("", path);
        }

        // Откат этапа 3: встроенные обои по умолчанию на всех мониторах.
        function reset(): void {
            WallpaperStore.setPath("", "");
        }

        function status(): string {
            return "gpu=" + WallpaperStore.gpu + " hwdec=" + WallpaperStore.hwdec
                + " folder=" + WallpaperStore.folder
                + " files=" + WallpaperStore.files.count
                + " current=" + (WallpaperStore.pathFor(WallpaperStore.focusedMonitor()) || "(по умолчанию)");
        }
    }
}
