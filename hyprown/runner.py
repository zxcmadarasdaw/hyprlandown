"""Запуск внешних команд. Единственное место, где вызывается subprocess.

Раннер умеет: сухой прогон (dry-run), повышение прав только для явно помеченных
команд, потоковый вывод (настоящий вывод dnf вместо выдуманных процентов).
Тесты подставляют FakeRunner, поэтому на Windows ничего реального не выполняется.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Sequence


@dataclass
class Result:
    cmd: list
    code: int
    out: str = ""
    err: str = ""

    @property
    def ok(self) -> bool:
        return self.code == 0


class Runner:
    def __init__(self, dry_run: bool = False, log: Callable[[str], None] | None = None):
        self.dry_run = dry_run
        self.log = log or (lambda msg: None)

    # --- поиск программ ---
    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def is_root(self) -> bool:
        return hasattr(os, "geteuid") and os.geteuid() == 0

    def escalation_prefix(self, interactive: bool) -> list[str] | None:
        """Как получить root. None: способа нет.

        Правило: сначала sudo (в терминале), иначе pkexec (графический запрос
        пароля у polkit). Сам менеджер работает от обычного пользователя.
        """
        if self.is_root():
            return []
        if interactive and self.which("sudo"):
            return ["sudo"]
        if self.which("pkexec"):
            return ["pkexec"]
        if self.which("sudo"):
            return ["sudo", "-n"]  # без tty пароль не спросить: сработает только NOPASSWD
        return None

    def run(self, cmd: Sequence[str], *, privileged: bool = False, stream: bool = False,
            timeout: float | None = None, env: dict | None = None, mutates: bool = True,
            interactive: bool = False) -> Result:
        """mutates=False: безопасное чтение, выполняется даже в dry-run."""
        cmd = [str(c) for c in cmd]
        if privileged:
            prefix = self.escalation_prefix(interactive)
            if prefix is None:
                return Result(cmd, 126, err="нет способа получить права root (нужен sudo или pkexec)")
            cmd = prefix + cmd
        if self.dry_run and mutates:
            self.log("[dry-run] " + " ".join(cmd))
            return Result(cmd, 0, out="[dry-run]")
        self.log("$ " + " ".join(cmd))
        try:
            if stream:
                p = subprocess.run(cmd, env=env, timeout=timeout)
                return Result(cmd, p.returncode)
            p = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                               env=env, timeout=timeout)
            return Result(cmd, p.returncode, p.stdout, p.stderr)
        except FileNotFoundError:
            return Result(cmd, 127, err=f"команда не найдена: {cmd[0]}")
        except subprocess.TimeoutExpired:
            return Result(cmd, 124, err=f"таймаут {timeout} с: {' '.join(cmd)}")


@dataclass
class FakeRunner(Runner):
    """Раннер для тестов: ничего не запускает, отвечает по заготовкам.

    responses: список (префикс команды, Result|callable). Берётся первое совпадение.
    bins: какие программы «есть в системе».
    """

    responses: list = field(default_factory=list)
    bins: set = field(default_factory=set)
    root: bool = False
    escalation: tuple = ("sudo",)
    calls: list = field(default_factory=list)

    def __post_init__(self):
        super().__init__()
        self.bins = set(self.bins)

    def which(self, name):
        return f"/usr/bin/{name}" if name in self.bins else None

    def is_root(self):
        return self.root

    def escalation_prefix(self, interactive):
        if self.root:
            return []
        return list(self.escalation) if self.escalation else None

    def run(self, cmd, *, privileged=False, stream=False, timeout=None, env=None,
            mutates=True, interactive=False):
        cmd = [str(c) for c in cmd]
        full = cmd
        if privileged:
            prefix = self.escalation_prefix(interactive)
            if prefix is None:
                return Result(cmd, 126, err="нет способа получить права root")
            full = prefix + cmd
        self.calls.append(full)
        for prefix, resp in self.responses:
            p = list(prefix)
            if cmd[:len(p)] == p:
                r = resp(full) if callable(resp) else resp
                return Result(full, r.code, r.out, r.err)
        return Result(full, 0)

    def called(self, *prefix) -> bool:
        """Был ли вызов с таким началом (с учётом префикса sudo/pkexec)."""
        p = list(prefix)
        return any(c[:len(p)] == p or c[1:1 + len(p)] == p for c in self.calls)
