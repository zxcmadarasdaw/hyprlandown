"""Определение окружения: KDE, обычный Hyprland, сессия HyprlandOwn, вложенный Preview, нет графики.

Название процесса ничему не доказывает, поэтому решение строится на данных сессии:
  * переменные WAYLAND_DISPLAY / DISPLAY / XDG_CURRENT_DESKTOP / HYPRLAND_INSTANCE_SIGNATURE;
  * каталог IPC $XDG_RUNTIME_DIR/hypr/<сигнатура>/: файл блокировки (pid и имя Wayland-сокета
    композитора), сокет управления, владелец каталога (должен совпадать с пользователем);
  * сам процесс: жив ли (/proc/<pid>), чей он, с каким конфигом запущен (-c в командной строке);
  * отпечаток конфига ЗАПУЩЕННОЙ сессии (ConfigManager.uses_our_config).

IPC считается принадлежащим текущей сессии, только если сигнатура из окружения найдена среди
живых экземпляров пользователя И Wayland-сокет этого экземпляра совпадает с WAYLAND_DISPLAY
терминала. Иначе (устаревшая переменная, чужой экземпляр) мы туда не пишем.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .config import ConfigManager
from .context import Ctx

KINDS = {
    "hyprland": "обычная сессия Hyprland (конфиг не HyprlandOwn)",
    "hyprlandown": "сессия HyprlandOwn",
    "preview": "вложенный Hyprland Preview",
    "kde": "Fedora KDE Plasma",
    "other": "другая графическая сессия",
    "none": "нет графической сессии",
}


# ---------------------------------------------------------------- процессы (через ctx.fs: тестируется без Linux)
def pid_alive(ctx: Ctx, pid: int) -> bool:
    return pid > 0 and ctx.fs(f"/proc/{pid}").exists()


def read_cmdline(ctx: Ctx, pid: int) -> list[str] | None:
    """Аргументы процесса или None, если прочитать нельзя (не Linux, нет прав, процесс исчез)."""
    try:
        raw = ctx.fs(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    return [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]


def my_uid() -> int | None:
    return os.getuid() if hasattr(os, "getuid") else None


def pid_uid(ctx: Ctx, pid: int) -> int | None:
    try:
        for line in ctx.fs(f"/proc/{pid}/status").read_text(errors="replace").splitlines():
            if line.startswith("Uid:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


def parse_config_arg(argv: list[str] | None) -> str | None:
    """Значение -c / --config из командной строки Hyprland (None: запущен без явного конфига)."""
    if not argv:
        return None
    for i, a in enumerate(argv):
        if a in ("-c", "--config") and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--config="):
            return a.split("=", 1)[1]
    return None


# ---------------------------------------------------------------- экземпляры Hyprland
@dataclass
class Instance:
    sig: str
    pid: int | None
    wl_socket: str
    dir: Path
    alive: bool | None      # None: pid неизвестен (старый Hyprland без lock-файла)
    owned: bool | None      # принадлежит текущему пользователю; None: проверить нельзя
    config_arg: str | None = None
    mtime: float = 0.0

    def to_dict(self):
        return {"sig": self.sig, "pid": self.pid, "wayland_display": self.wl_socket,
                "alive": self.alive, "owned": self.owned, "config": self.config_arg}


def scan_instances(ctx: Ctx, env: dict | None = None) -> list[Instance]:
    env = env if env is not None else ctx.env
    rt = env.get("XDG_RUNTIME_DIR", "")
    base = Path(rt) / "hypr" if rt else None
    out: list[Instance] = []
    if not base or not base.is_dir():
        return out
    uid = my_uid()
    for d in sorted(base.iterdir()):
        try:
            if not d.is_dir() or not (d / ".socket.sock").exists():
                continue
            pid, wl = None, ""
            lock = d / "hyprland.lock"
            if lock.is_file():
                parts = lock.read_text(errors="replace").split()
                if parts and parts[0].isdigit():
                    pid = int(parts[0])
                if len(parts) > 1:
                    wl = parts[1]
            alive = pid_alive(ctx, pid) if pid else None
            owned = None
            if uid is not None and hasattr(d.stat(), "st_uid"):
                owned = d.stat().st_uid == uid
            cfg = parse_config_arg(read_cmdline(ctx, pid)) if pid and alive else None
            out.append(Instance(d.name, pid, wl, d, alive, owned, cfg, d.stat().st_mtime))
        except OSError:
            continue
    return out


def usable(i: Instance) -> bool:
    return i.alive is not False and i.owned is not False


# ---------------------------------------------------------------- итог
@dataclass
class Environment:
    kind: str
    instance: Instance | None = None
    others: list = field(default_factory=list)       # другие живые экземпляры пользователя
    reasons: list = field(default_factory=list)      # как пришли к выводу
    can_attach: bool = False
    attach_block: str = ""
    ours: bool | None = None
    desktop: str = ""
    wayland_display: str = ""

    @property
    def title(self) -> str:
        return KINDS[self.kind]

    @property
    def in_hyprland(self) -> bool:
        return self.instance is not None

    def target_env(self, base: dict) -> dict:
        """Окружение для hyprctl / qs: строго тот экземпляр, к которому подключаемся."""
        env = dict(base)
        if self.instance:
            env["HYPRLAND_INSTANCE_SIGNATURE"] = self.instance.sig
            if self.instance.wl_socket:
                env["WAYLAND_DISPLAY"] = self.instance.wl_socket
        return env

    def to_dict(self):
        return {"kind": self.kind, "title": self.title, "desktop": self.desktop,
                "wayland_display": self.wayland_display,
                "instance": self.instance.to_dict() if self.instance else None,
                "other_instances": [i.to_dict() for i in self.others], "ours": self.ours,
                "can_attach": self.can_attach, "attach_block": self.attach_block, "reasons": self.reasons}


KDE_BLOCK = ("Вы внутри KDE Plasma: Attach подключает HyprlandOwn к УЖЕ запущенной сессии Hyprland, а второй "
             "композитор внутри KDE запускать нельзя. Войдите в сессию Hyprland (экран входа SDDM) и повторите, "
             "либо используйте `hyprown preview` (окно Hyprland внутри KDE).")


def detect_environment(ctx: Ctx, instance_sig: str | None = None) -> Environment:
    env = ctx.env
    desktop = env.get("XDG_CURRENT_DESKTOP", "")
    wl, x11 = env.get("WAYLAND_DISPLAY", ""), env.get("DISPLAY", "")
    sig = env.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    reasons: list[str] = []
    live = [i for i in scan_instances(ctx, env) if usable(i)]
    current: Instance | None = None
    low = desktop.lower()
    if instance_sig and ("kde" in low or "plasma" in low) and not sig:
        reasons.append("--instance игнорируется: терминал внутри KDE Plasma, подключать нужно из самого Hyprland")
        instance_sig = None

    if instance_sig:
        current = next((i for i in live if i.sig == instance_sig), None)
        reasons.append(f"экземпляр {instance_sig} указан явно: " + ("найден" if current else "не найден среди ваших живых"))
    elif sig:
        found = next((i for i in live if i.sig == sig), None)
        if not found:
            reasons.append(f"HYPRLAND_INSTANCE_SIGNATURE={sig} не найдена среди живых экземпляров пользователя: "
                           "переменная устарела или чужая, IPC игнорируем")
        elif wl and found.wl_socket and found.wl_socket != wl:
            reasons.append(f"экземпляр {sig} работает на Wayland-сокете {found.wl_socket}, а терминал на {wl}: "
                           "это не текущая сессия, IPC игнорируем")
        else:
            current = found
            reasons.append(f"сигнатура {sig} из окружения совпала с живым экземпляром (pid {found.pid})")
    elif wl:
        current = next((i for i in live if i.wl_socket == wl), None)
        if current:
            reasons.append(f"Wayland-сокет {wl} принадлежит экземпляру {current.sig}")

    if current:
        kind, ours = _classify_instance(ctx, current, env)
        env_obj = Environment(kind, current, [i for i in live if i.sig != current.sig], reasons, True, "",
                              ours, desktop, wl)
        if env_obj.others:
            env_obj.reasons.append(f"найдено ещё {len(env_obj.others)} экземпляр(ов) Hyprland: "
                                   "затрагивается только текущий")
        return env_obj

    if wl or x11:
        kind = "kde" if ("kde" in low or "plasma" in low) else "other"
        reasons.append(f"графическая сессия {desktop or '?'} без привязки к экземпляру Hyprland")
        res = Environment(kind, None, live, reasons, False, KDE_BLOCK if kind == "kde" else
                          f"Сессия {desktop or '?'} не Hyprland: Attach подключает окружение только к работающему Hyprland.",
                          None, desktop, wl)
        if live:
            res.reasons.append(f"в системе работает Hyprland (экземпляров: {len(live)}), но этот терминал не внутри него")
        return res
    reasons.append("нет WAYLAND_DISPLAY и DISPLAY: графической сессии у терминала нет")
    return Environment("none", None, live, reasons, False,
                       "Нет графической сессии. Запустите установщик из терминала внутри Hyprland "
                       "или укажите экземпляр явно: hyprown attach --instance СИГНАТУРА"
                       + (f" (доступны: {', '.join(i.sig for i in live)})" if live else ""),
                       None, desktop, wl)


def _classify_instance(ctx: Ctx, inst: Instance, env: dict) -> tuple[str, bool | None]:
    pdir = ctx.runtime_dir / "preview"
    cfg = inst.config_arg
    nested = bool(cfg) and Path(cfg).parent == pdir
    if not nested:
        try:
            nested = inst.pid is not None and int((ctx.runtime_dir / "preview.pid").read_text().strip()) == inst.pid
        except (OSError, ValueError):
            pass
    if nested:
        return "preview", True
    probe = dict(env)
    probe["HYPRLAND_INSTANCE_SIGNATURE"] = inst.sig
    if inst.wl_socket:
        probe["WAYLAND_DISPLAY"] = inst.wl_socket
    if not ctx.runner.which("hyprctl"):
        return "hyprland", None
    ours, _ = ConfigManager(ctx).uses_our_config(probe)
    return ("hyprlandown" if ours else "hyprland"), ours
