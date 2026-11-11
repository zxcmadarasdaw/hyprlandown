"""Quickshell: надёжный запуск, супервизор, IPC.

Что было не так (этап 2-3, тесты на Fedora):
  - `qs -c hyprdesk` ищет ~/.config/quickshell/hyprdesk. Без ссылки: «Could not find
    hyprdesk config directory»;
  - `qs -p <каталог>`: опция -p ждёт ПУТЬ К ФАЙЛУ shell.qml, а не каталог:
    «Could not open config file»;
  - процесс, запущенный из терминала, умирал вместе с ним;
  - дубликаты панелей при повторном запуске.

Решение: один супервизор `hyprown shell run` (его запускает exec-once). Он
  1. находит shell.qml и берёт realpath (символические ссылки больше не мешают);
  2. читает `qs --help` установленной версии и строит команды из реально
     существующих опций, пробуя стратегии по очереди (-p файл, -p каталог, -c имя);
  3. держит ровно один экземпляр на сессию Hyprland (pid-файл);
  4. перезапускает qs после сбоя, но с защитой от цикла падений;
  5. пишет лог в ~/.local/state/hyprdesk/logs/quickshell.log;
  6. сам завершается, когда исчез Wayland-сокет (закрыта сессия или Preview).
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .context import Ctx
from .registry import atomic_write
from .sessenv import pid_alive, read_cmdline

QS_BINS = ("qs", "quickshell")
FAST_FAIL_SEC = 3.0       # процесс умер быстрее: стратегия не работает
MAX_RESTARTS = 5          # сколько перезапусков за окно
RESTART_WINDOW_SEC = 60.0


@dataclass
class Caps:
    binary: str = ""
    version: str = ""
    has_path: bool = False
    has_config: bool = False
    has_no_duplicate: bool = False
    help_text: str = ""

    def to_dict(self):
        d = dict(self.__dict__)
        d["help_text"] = self.help_text[:4000]
        return d


def is_supervisor_cmd(argv: list[str]) -> bool:
    """Командная строка нашего супервизора: ... hyprown shell run."""
    return any("hyprown" in a for a in argv) and "shell" in argv and "run" in argv


def parse_caps(help_text: str, binary: str, version: str = "") -> Caps:
    t = help_text or ""
    return Caps(
        binary=binary, version=version,
        has_path=bool(re.search(r"(^|\s)(-p,\s*)?--path\b|(^|\s)-p\b", t, re.M)),
        has_config=bool(re.search(r"--config\b|(^|\s)-c\b", t)),
        has_no_duplicate=bool(re.search(r"--no-duplicate\b|(^|\s)-n\b", t)),
        help_text=t)


class ShellManager:
    def __init__(self, ctx: Ctx, popen=subprocess.Popen, sleep=time.sleep, clock=time.monotonic):
        self.ctx, self.popen, self.sleep, self.clock = ctx, popen, sleep, clock

    # ---------- поиск ----------
    def find_shell(self) -> Path:
        """shell.qml по приоритету: HYPRDESK_SHELL_DIR, ссылка в ~/.config, репозиторий."""
        c = self.ctx
        cands = []
        if c.env.get("HYPRDESK_SHELL_DIR"):
            cands.append(Path(c.env["HYPRDESK_SHELL_DIR"]))
        cands += [c.config_dir / "quickshell" / "hyprdesk", c.shell_dir]
        for d in cands:
            f = d / "shell.qml"
            if f.is_file():
                return f.resolve()
        raise FileNotFoundError("shell.qml не найден: проверено " + ", ".join(str(x) for x in cands))

    def binary(self) -> str | None:
        for b in QS_BINS:
            if self.ctx.runner.which(b):
                return b
        return None

    def probe(self) -> Caps:
        b = self.binary()
        if not b:
            return Caps()
        r = self.ctx.runner
        help_text = (lambda x: x.out + x.err)(r.run([b, "--help"], mutates=False, timeout=15))
        ver = (lambda x: x.out + x.err)(r.run([b, "--version"], mutates=False, timeout=15))
        m = re.search(r"(\d+\.\d+(?:\.\d+)?)", ver)
        return parse_caps(help_text, b, m.group(1) if m else "")

    def strategies(self, caps: Caps, shell_qml: Path, dir_name: str = "hyprdesk") -> list[list[str]]:
        """Селекторы конфига в порядке надёжности. Возвращает аргументы ПОСЛЕ имени программы."""
        out = []
        if caps.has_path:
            out.append(["-p", str(shell_qml)])
            out.append(["-p", str(shell_qml.parent)])
        if caps.has_config:
            out.append(["-c", dir_name])
        if not out:  # help не разобрался: пробуем всё подряд, лог покажет, что сработало
            out = [["-p", str(shell_qml)], ["-c", dir_name]]
        return out

    # ---------- окружение ----------
    def compositor_alive(self, env: dict) -> bool:
        disp = env.get("WAYLAND_DISPLAY", "")
        rt = env.get("XDG_RUNTIME_DIR", "")
        if not disp:
            return False
        sock = Path(disp) if os.path.isabs(disp) else Path(rt) / disp
        return sock.exists()

    def lock_path(self, env: dict) -> Path:
        sig = env.get("HYPRLAND_INSTANCE_SIGNATURE") or env.get("WAYLAND_DISPLAY") or "default"
        return self.ctx.runtime_dir / f"shell.{re.sub(r'[^A-Za-z0-9_.-]', '_', sig)[:60]}.pid"

    def running_pid(self, env: dict) -> int | None:
        f = self.lock_path(env)
        try:
            pid = int(f.read_text().strip())
        except (OSError, ValueError):
            return None
        try:
            os.kill(pid, 0)
        except (OSError, SystemError):
            return None
        # Номер процесса мог достаться постороннему после сбоя: сверяем командную строку.
        # Где прочитать нельзя (не Linux), доверяем pid-файлу.
        argv = read_cmdline(self.ctx, pid)
        if argv is not None and not is_supervisor_cmd(argv):
            return None
        return pid

    def child_path(self, env: dict) -> Path:
        return self.lock_path(env).with_suffix(".child")

    def child_pid(self, env: dict) -> int | None:
        """qs, запущенный нашим супервизором (для остановки без pkill по имени)."""
        try:
            pid = int(self.child_path(env).read_text().strip())
        except (OSError, ValueError):
            return None
        argv = read_cmdline(self.ctx, pid)
        if not pid_alive(self.ctx, pid) or argv is None or not argv or Path(argv[0]).name not in QS_BINS:
            return None
        return pid

    def log_file(self) -> Path:
        d = self.ctx.log_dir
        d.mkdir(parents=True, exist_ok=True)
        f = d / "quickshell.log"
        if f.exists() and f.stat().st_size > 1_000_000:
            os.replace(f, f.with_suffix(".log.1"))
        return f

    # ---------- супервизор ----------
    def run(self, env: dict | None = None) -> int:
        """Блокирующий цикл. Вызывается из exec-once. Возвращает код выхода."""
        env = dict(env or self.ctx.env)
        c = self.ctx
        if not self.compositor_alive(env):
            c.ui.error("Нет Wayland-сессии (WAYLAND_DISPLAY не указывает на сокет). Запустите внутри Hyprland.")
            return 3
        if self.running_pid(env):
            c.ui.info("Quickshell уже управляется другим супервизором: второй не нужен.")
            return 0
        caps = self.probe()
        if not caps.binary:
            c.ui.error("Quickshell не найден (ни qs, ни quickshell). Установите: hyprown install")
            return 4
        try:
            shell = self.find_shell()
        except FileNotFoundError as exc:
            c.ui.error(str(exc))
            return 5

        lock = self.lock_path(env)
        atomic_write(lock, f"{os.getpid()}\n")
        log = self.log_file()
        stop = {"flag": False, "child": None}

        def on_term(signum, frame):
            stop["flag"] = True
            ch = stop["child"]
            if ch is not None:
                try:
                    ch.terminate()
                except OSError:
                    pass

        for s in (signal.SIGTERM, signal.SIGINT, getattr(signal, "SIGHUP", signal.SIGTERM)):
            try:
                signal.signal(s, on_term)
            except (ValueError, OSError):
                pass  # не главный поток (тесты)

        code = self._loop(caps, shell, env, log, stop)
        try:
            lock.unlink()
        except OSError:
            pass
        return code

    def _loop(self, caps: Caps, shell: Path, env: dict, log: Path, stop: dict) -> int:
        strategies = self.strategies(caps, shell)
        idx, restarts = 0, []
        with open(log, "ab") as lf:
            lf.write(f"\n=== {time.strftime('%F %T')} супервизор: {caps.binary} {caps.version} shell={shell} ===\n".encode())
            while not stop["flag"]:
                if not self.compositor_alive(env):
                    lf.write(b"compositor gone: supervisor exits\n")
                    return 0
                args = [caps.binary, *strategies[idx]]
                if caps.has_no_duplicate:
                    args.append("--no-duplicate")
                lf.write((" ".join(args) + "\n").encode())
                lf.flush()
                t0 = self.clock()
                child = self.popen(args, env=env, stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT)
                stop["child"] = child
                try:
                    atomic_write(self.child_path(env), f"{child.pid}\n")
                except (OSError, AttributeError, TypeError):
                    pass
                self._save_active(strategies[idx], caps)
                rc = child.wait()
                stop["child"] = None
                lived = self.clock() - t0
                if stop["flag"]:
                    return 0
                if rc == 0 and lived >= FAST_FAIL_SEC:
                    return 0  # штатное завершение (qs kill): не воскрешаем
                if lived < FAST_FAIL_SEC:
                    idx += 1
                    lf.write(f"стратегия {args} умерла за {lived:.1f} с (код {rc}), пробуем следующую\n".encode())
                    if idx >= len(strategies):
                        self.ctx.ui.error(f"Quickshell не стартует ни одним способом. Лог: {log}")
                        self._notify(env, "Quickshell не запустился. Лог: " + str(log))
                        return 1
                    continue
                now = self.clock()
                restarts = [t for t in restarts if now - t < RESTART_WINDOW_SEC] + [now]
                if len(restarts) > MAX_RESTARTS:
                    lf.write(b"too many crashes: supervisor gives up\n")
                    self._notify(env, "Quickshell падает слишком часто. Лог: " + str(log))
                    return 1
                lf.write(f"qs завершился (код {rc}) спустя {lived:.0f} с, перезапуск\n".encode())
                self.sleep(1.0)
        return 0

    def _save_active(self, selector: list, caps: Caps):
        atomic_write(self.ctx.state_dir / "shell.json",
                     json.dumps({"selector": selector, "binary": caps.binary, "version": caps.version}))

    def _notify(self, env: dict, msg: str):
        if self.ctx.runner.which("hyprctl"):
            self.ctx.runner.run(["hyprctl", "notify", "0", "15000", "rgb(f7768e)", msg], env=env, timeout=5)

    # ---------- управление снаружи ----------
    def start_detached(self, env: dict | None = None) -> int:
        """Запуск супервизора вне терминала: новая сессия процессов, без stdin/stdout."""
        env = dict(env or self.ctx.env)
        if self.running_pid(env):
            self.ctx.ui.info("Quickshell уже запущен.")
            return 0
        cmd = [str(self.ctx.repo / "bin" / "hyprown"), "shell", "run"]
        self.popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, start_new_session=True)
        return 0

    def stop(self, env: dict | None = None) -> bool:
        env = dict(env or self.ctx.env)
        pid = self.running_pid(env)
        if not pid:
            return False
        os.kill(pid, signal.SIGTERM)
        for _ in range(50):
            if not self.running_pid(env):
                break
            self.sleep(0.1)
        left = self.child_pid(env)  # дочерний qs пережил супервизор (редко): гасим только проверенный
        if left:
            try:
                os.kill(left, signal.SIGTERM)
            except OSError:
                pass
        self.child_path(env).unlink(missing_ok=True)
        return True

    def restart(self, env: dict | None = None) -> int:
        self.stop(env)
        return self.start_detached(env)

    def status(self, env: dict | None = None) -> dict:
        env = dict(env or self.ctx.env)
        active = {}
        try:
            active = json.loads((self.ctx.state_dir / "shell.json").read_text())
        except (OSError, ValueError):
            pass
        return {"supervisor_pid": self.running_pid(env), "active": active,
                "binary": self.binary() or "", "log": str(self.ctx.log_dir / "quickshell.log")}

    def ipc(self, args: list[str], env: dict | None = None) -> int:
        """qs ipc <тот же селектор, что запустил оболочку> call ..."""
        env = dict(env or self.ctx.env)
        b = self.binary()
        if not b:
            self.ctx.ui.error("Quickshell не установлен.")
            return 4
        try:
            sel = json.loads((self.ctx.state_dir / "shell.json").read_text()).get("selector")
        except (OSError, ValueError):
            sel = None
        if not sel:
            sel = ["-p", str(self.find_shell())]
        res = self.ctx.runner.run([b, "ipc", *sel, *args], env=env, timeout=15)
        if res.out:
            print(res.out, end="")
        if res.err:
            self.ctx.ui.error(res.err.strip())
        return res.code

    # ---------- Manager ----------
    def open_manager(self, env: dict | None = None) -> int:
        env = dict(env or self.ctx.env)
        b = self.binary()
        qml = self.ctx.manager_dir / "shell.qml"
        if not b:
            self.ctx.ui.error("Quickshell не установлен: Manager недоступен. Установка: bash install.sh")
            return 4
        if not qml.is_file():
            self.ctx.ui.error(f"Нет {qml}")
            return 5
        args = [b, "-p", str(qml.resolve())]
        caps = self.probe()
        if caps.has_no_duplicate:
            args.append("--no-duplicate")
        lf = open(self.log_file().with_name("manager.log"), "ab")
        self.popen(args, env=env, stdin=subprocess.DEVNULL, stdout=lf, stderr=subprocess.STDOUT,
                   start_new_session=True)
        return 0
