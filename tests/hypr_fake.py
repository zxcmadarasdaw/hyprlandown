"""Поддельный Hyprland для тестов: экземпляр в $XDG_RUNTIME_DIR/hypr, процесс в /proc, ответы hyprctl.

Ничего реального не запускается. FakeHypr хранит список привязок и меняет его так же, как настоящий
Hyprland: `keyword unbind/bind` правят таблицу, `reload` возвращает привязки из конфига сессии
(наши или стандартные автосгенерированные).
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest import mock

from hyprown.config import ConfigManager
from hyprown.keybinds import KeyManager, effective, expand_vars, norm_mods
from hyprown.runner import Result

MASK = {"SHIFT": 1, "CTRL": 4, "ALT": 8, "SUPER": 64}
# Что делает стандартный (автосгенерированный) конфиг Hyprland
STOCK = [("SUPER", "q", "exec", "kitty"), ("SUPER", "c", "killactive", ""), ("SUPER", "m", "exit", ""),
         ("SUPER", "e", "exec", "dolphin"), ("SUPER", "v", "togglefloating", ""),
         ("SUPER", "r", "exec", "wofi --show drun"), ("SUPER", "s", "togglespecialworkspace", "magic"), ("SUPER", "left", "movefocus", "l")]
HOME_BIN = "/home/u/.local/bin/hyprown"


def ok(out="", err=""):
    return Result([], 0, out, err)


def make_instance(e, sig="sigA", pid=4242, wl="wayland-1", cmdline=("Hyprland",), desktop="Hyprland",
                  set_env=True, alive=True):
    """Создаёт экземпляр Hyprland в fake-системе и (по умолчанию) настраивает окружение терминала внутри него."""
    run = e.tmp / "run"
    d = run / "hypr" / sig
    d.mkdir(parents=True, exist_ok=True)
    (d / ".socket.sock").write_text("")
    (d / "hyprland.lock").write_text(f"{pid}\n{wl}\n")
    (run / wl).write_text("")
    if alive:
        write_cmdline(e, pid, *cmdline)
    if set_env:
        e.ctx.env.update({"WAYLAND_DISPLAY": wl, "HYPRLAND_INSTANCE_SIGNATURE": sig,
                          "XDG_CURRENT_DESKTOP": desktop})
    return d


def write_cmdline(e, pid, *argv):
    d = e.fake_root / "proc" / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    return d


class FakeHypr:
    def __init__(self, ctx, ours=False):
        self.ctx, self.ours = ctx, ours
        self.cfg = ConfigManager(ctx)
        self.want = self.cfg.expected_fingerprint()
        self.keywords: list = []
        self.options: dict = {}
        self.reloads = 0
        self.binds = self.config_binds()

    @staticmethod
    def _row(mods, key, disp, arg, mouse=False):
        mask = sum(MASK[m] for m in norm_mods(mods))
        return {"modmask": mask, "key": key, "dispatcher": disp, "arg": arg, "submap": "", "mouse": mouse}

    def config_binds(self) -> list:
        if not self.ours:
            return [self._row(*b) for b in STOCK]
        km = KeyManager(self.ctx)
        v = km.variables()
        rows = []
        for e in effective(km.binds, km.user(), "desktop"):
            if e.disabled:
                continue
            b = e.bind
            arg = expand_vars(b.arg, v).replace("~/.local/bin/hyprown", HOME_BIN)
            rows.append(self._row(e.mods, e.key, b.dispatcher, arg, b.kind == "bindm"))
        return rows

    # ---- ответы hyprctl ----
    def _binds(self, cmd):
        return ok(json.dumps(self.binds))

    def _getoption(self, cmd):
        key = cmd[-1]
        stock = {"decoration:rounding": 0, "general:gaps_out": 20, "general:gaps_in": 5}
        return ok(json.dumps({"int": self.want.get(key) if self.ours else stock.get(key)}))

    def _keyword(self, cmd):
        self.keywords.append(cmd[2:])
        name, value = cmd[2], cmd[3]
        if name not in ("bind", "bindm", "unbind"):
            self.options[name] = value
            return ok("ok")
        parts = value.split(",")
        mods, key = norm_mods(parts[0]), parts[1].strip().lower()
        if name == "unbind":
            mask = sum(MASK[m] for m in mods)
            self.binds = [b for b in self.binds if not (b["modmask"] == mask and b["key"].lower() == key)]
        else:
            self.binds.append(self._row(mods, key, parts[2], ",".join(parts[3:]), name == "bindm"))
        return ok("ok")

    def _reload(self, cmd):
        self.reloads += 1
        self.binds = self.config_binds()
        return ok("ok")

    def responses(self):
        return [(("hyprctl", "-j", "binds"), self._binds), (("hyprctl", "-j", "getoption"), self._getoption),
                (("hyprctl", "keyword"), self._keyword), (("hyprctl", "reload"), self._reload),
                (("hyprctl", "configerrors"), ok(""))]


@contextmanager
def fake_kill(alive_pids: set):
    """Подменяет os.kill: сигнал получает только pid из alive_pids, SIGTERM убирает процесс; все вызовы пишутся."""
    sent = []

    def kill(pid, sig):
        sent.append((pid, int(sig)))
        if pid not in alive_pids:
            raise ProcessLookupError(pid)
        if int(sig) == 15:
            alive_pids.discard(pid)

    with mock.patch("hyprown.shell.os.kill", kill):
        yield sent


class FakePopen:
    """Заменяет запуск супервизора: «запускает» его, записывая pid-файл и командную строку."""

    def __init__(self, e, shell, env, pid=7777, alive=None, start=True):
        self.e, self.shell, self.env, self.pid = e, shell, env, pid
        self.alive, self.start, self.calls = alive if alive is not None else set(), start, []

    def __call__(self, args, **kw):
        self.calls.append((args, kw))
        if self.start:
            lock = self.shell.lock_path(self.env)
            lock.parent.mkdir(parents=True, exist_ok=True)
            lock.write_text(f"{self.pid}\n")
            write_cmdline(self.e, self.pid, "python3", "-m", "hyprown", "shell", "run")
            self.alive.add(self.pid)
        return mock.Mock(pid=self.pid)
