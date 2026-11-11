"""Session Process Manager: какие процессы принадлежат HyprlandOwn и как ими управлять.

Что в проекте реально является процессом, а что модулем:
  * процесс один: супервизор `hyprown shell run`, он держит Quickshell (qs) с перезапуском
    после сбоев (hyprown/shell.py);
  * обои (Wallpaper Engine), холст виджетов (Widget Services), IPC и тема (Theme Engine)
    это модули ВНУТРИ этого Quickshell (quickshell/hyprdesk). Отдельных процессов у них нет,
    поэтому в статусе они показаны как модули оболочки и зависят от её состояния.

Правила:
  * мы управляем только теми PID, которые записал наш супервизор, и перед сигналом сверяем
    командную строку процесса (ShellManager.running_pid/child_pid). Процессы по имени
    не убиваются никогда;
  * повторный запуск уже работающего не создаёт дубль;
  * запуск идёт отдельной сессией процессов без терминала: закрытие терминала окружение не гасит;
  * частые запуски ограничены (RESTART_LIMIT за RESTART_WINDOW секунд): зацикливание невозможно;
  * каждое действие пишется в logs/session.log.
"""

from __future__ import annotations

import json
import time

from .context import Ctx
from .registry import atomic_write
from .shell import ShellManager

RESTART_LIMIT = 4
RESTART_WINDOW_SEC = 120.0
START_WAIT_SEC = 6.0

# Модули внутри Quickshell: (id, название, что делает)
SHELL_MODULES = (
    ("wallpaper", "Wallpaper Engine", "обои: картинки и видео (WallpaperWindow, mpvpaper при наличии)"),
    ("widgets", "Widget Services", "холст виджетов и панель (CanvasWindow, Bar)"),
    ("ipc", "IPC Services", "вызовы `hyprown ipc ...` и горячие клавиши холста и обоев"),
    ("theme", "Theme Engine", "токены Aurora Glass (Theme.qml)"),
)


class ProcessManager:
    def __init__(self, ctx: Ctx, shell: ShellManager | None = None, sleep=time.sleep, clock=time.time):
        self.ctx = ctx
        self.shell = shell or ShellManager(ctx)
        self.sleep, self.clock = sleep, clock

    # ---------- журнал и ограничение частоты ----------
    def log(self, msg: str) -> None:
        try:
            self.ctx.log_dir.mkdir(parents=True, exist_ok=True)
            with open(self.ctx.log_dir / "session.log", "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%F %T')} {msg}\n")
        except OSError:
            pass

    def _state_file(self):
        return self.ctx.state_dir / "session-units.json"

    def _starts(self, unit: str) -> list[float]:
        try:
            data = json.loads(self._state_file().read_text())
        except (OSError, ValueError):
            return []
        now = self.clock()
        return [t for t in data.get(unit, []) if now - t < RESTART_WINDOW_SEC]

    def _note_start(self, unit: str) -> None:
        try:
            data = json.loads(self._state_file().read_text())
        except (OSError, ValueError):
            data = {}
        data[unit] = self._starts(unit) + [self.clock()]
        atomic_write(self._state_file(), json.dumps(data))

    def throttled(self, unit: str) -> float:
        """Сколько секунд ждать до следующего разрешённого запуска (0: можно сейчас)."""
        starts = self._starts(unit)
        if len(starts) < RESTART_LIMIT:
            return 0.0
        return max(0.0, RESTART_WINDOW_SEC - (self.clock() - min(starts)))

    def _throttled_row(self, wait: float) -> dict:
        msg = (f"слишком частые запуски ({RESTART_LIMIT} за {int(RESTART_WINDOW_SEC)} с): "
               f"подождите {int(wait) + 1} с и изучите лог {self.ctx.log_dir / 'quickshell.log'}")
        self.log("ограничение частоты: " + msg)
        return {"id": "shell", "result": "throttled", "detail": msg}

    # ---------- состояние ----------
    def blockers(self, env: dict) -> list[str]:
        """Почему запуск сейчас невозможен (пусто: можно)."""
        out = []
        if not self.shell.compositor_alive(env):
            out.append("нет Wayland-сокета композитора (WAYLAND_DISPLAY): сессия Hyprland не найдена")
        if not self.shell.binary():
            out.append("Quickshell не установлен (нет qs/quickshell): установите компонент quickshell-shell")
        try:
            self.shell.find_shell()
        except FileNotFoundError as exc:
            out.append(str(exc))
        return out

    def status(self, env: dict | None = None) -> list[dict]:
        env = dict(env or self.ctx.env)
        pid = self.shell.running_pid(env)
        child = self.shell.child_pid(env)
        blockers = [] if pid else self.blockers(env)
        if pid:
            state, detail = "running", f"супервизор pid {pid}" + (f", qs pid {child}" if child else "")
        elif blockers:
            state, detail = "blocked", "; ".join(blockers)
        else:
            state, detail = "stopped", "не запущен"
        rows = [{"id": "shell", "title": "Quickshell (супервизор)", "kind": "process", "state": state,
                 "pid": pid, "detail": detail, "log": str(self.ctx.log_dir / "quickshell.log")}]
        for mid, title, what in SHELL_MODULES:
            extra = ""
            if mid == "wallpaper":
                extra = "; видео-обои доступны" if self.ctx.runner.which("mpvpaper") else "; mpvpaper нет: только картинки"
            if mid == "theme" and not (self.ctx.shell_dir / "Theme.qml").exists():
                rows.append({"id": mid, "title": title, "kind": "module", "state": "blocked", "pid": None,
                             "detail": "нет Theme.qml в quickshell/hyprdesk"})
                continue
            rows.append({"id": mid, "title": title, "kind": "module", "pid": pid,
                         "state": "running" if pid else "stopped",
                         "detail": what + extra + ("" if pid else " (появится вместе с Quickshell)")})
        return rows

    # ---------- действия ----------
    def start_all(self, env: dict | None = None) -> list[dict]:
        env = dict(env or self.ctx.env)
        res = []
        if self.shell.running_pid(env):
            self.log("start-all: shell уже работает, второй не запускаем")
            return [{"id": "shell", "result": "already", "detail": "уже работает: повторный запуск не нужен"}]
        blockers = self.blockers(env)
        if blockers:
            self.log("start-all: отказ: " + "; ".join(blockers))
            return [{"id": "shell", "result": "blocked", "detail": "; ".join(blockers)}]
        wait = self.throttled("shell")
        if wait:
            return [self._throttled_row(wait)]
        self._note_start("shell")
        self.log(f"start-all: запуск супервизора (WAYLAND_DISPLAY={env.get('WAYLAND_DISPLAY', '')})")
        self.shell.start_detached(env)
        waited = 0.0
        while waited < START_WAIT_SEC:
            if self.shell.running_pid(env):
                break
            self.sleep(0.25)
            waited += 0.25
        pid = self.shell.running_pid(env)
        if pid:
            self.log(f"start-all: shell запущен, pid {pid}")
            res.append({"id": "shell", "result": "started", "detail": f"запущен, pid {pid}"})
        else:
            log = self.ctx.log_dir / "quickshell.log"
            self.log("start-all: супервизор не поднялся за %.0f с" % START_WAIT_SEC)
            res.append({"id": "shell", "result": "failed",
                        "detail": f"супервизор не запустился за {int(START_WAIT_SEC)} с. Смотрите {log}"})
        return res

    def stop_all(self, env: dict | None = None) -> list[dict]:
        env = dict(env or self.ctx.env)
        if not self.shell.running_pid(env):
            self.log("stop-all: нечего останавливать")
            return [{"id": "shell", "result": "absent", "detail": "не был запущен"}]
        self.shell.stop(env)
        gone = not self.shell.running_pid(env)
        self.log("stop-all: shell " + ("остановлен" if gone else "НЕ остановился"))
        return [{"id": "shell", "result": "stopped" if gone else "failed",
                 "detail": "остановлен (посторонние процессы не затронуты)" if gone else "не остановился за 5 с"}]

    def restart_all(self, env: dict | None = None) -> list[dict]:
        env = dict(env or self.ctx.env)
        wait = self.throttled("shell")
        if wait:
            return [self._throttled_row(wait)]  # работающую оболочку не трогаем
        out = self.stop_all(env)
        return out + self.start_all(env)

    @staticmethod
    def summary(rows: list[dict]) -> dict:
        procs = [r for r in rows if r.get("kind") == "process"]
        return {"running": sum(1 for r in procs if r["state"] == "running"),
                "stopped": sum(1 for r in procs if r["state"] == "stopped"),
                "blocked": sum(1 for r in procs if r["state"] == "blocked")}
