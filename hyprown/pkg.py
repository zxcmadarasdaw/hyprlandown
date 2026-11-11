"""Package Manager Adapter: единственное место, знающее про dnf/rpm.

Другие модули спрашивают «установлен ли пакет», «доступен ли он», «какая версия»
и просят «поставить». Чтобы поддержать другой менеджер пакетов, достаточно
написать ещё один класс с теми же методами.
"""

from __future__ import annotations

import re

from .context import Ctx
from .manifest import PackageDef
from .runner import Result


def parse_version(text: str, regex: str) -> str:
    m = re.search(regex or r"(\d+\.\d+(?:\.\d+)?)", text or "")
    return m.group(1) if m else ""


def version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4])


def version_ge(have: str, need: str) -> bool:
    if not need:
        return True
    if not have:
        return False
    a, b = version_tuple(have), version_tuple(need)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) >= b + (0,) * (n - len(b))


class DnfAdapter:
    name = "dnf"

    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self.r = ctx.runner

    # --- чтение (безопасно и в dry-run) ---
    def present(self, pkg: PackageDef) -> bool:
        """Установлено: программа в PATH, нужный файл или все rpm-пакеты."""
        if pkg.check_bin and self.r.which(pkg.check_bin):
            return True
        if any(self.ctx.fs(p).exists() for p in pkg.check_paths):
            return True
        if not self.r.which("rpm"):
            return False
        return all(self.r.run(["rpm", "-q", n], mutates=False).ok for n in pkg.rpm)

    def available(self, pkg: PackageDef) -> bool:
        """Есть ли пакет в УЖЕ подключённых репозиториях."""
        if not self.r.which("dnf"):
            return False
        for name in pkg.rpm:
            res = self.r.run(["dnf", "-q", "repoquery", "--available", "--latest-limit", "1", name],
                             mutates=False, timeout=120)
            if not res.ok or not res.out.strip():
                return False
        return True

    def version(self, pkg: PackageDef) -> str:
        if not pkg.version_cmd or not self.r.which(pkg.version_cmd[0]):
            return ""
        res = self.r.run(pkg.version_cmd, mutates=False, timeout=15)
        return parse_version(res.out + res.err, pkg.version_re) if res.ok or res.out else ""

    def copr_enabled(self, copr_id: str) -> bool:
        res = self.r.run(["dnf", "copr", "list"], mutates=False, timeout=60)
        return res.ok and copr_id in res.out

    # --- изменения (нужен root, только после подтверждения) ---
    def enable_copr(self, copr_id: str) -> Result:
        return self.r.run(["dnf", "-y", "copr", "enable", copr_id], privileged=True,
                          stream=True, interactive=self.ctx.ui.interactive)

    def disable_copr(self, copr_id: str) -> Result:
        return self.r.run(["dnf", "-y", "copr", "disable", copr_id], privileged=True,
                          stream=True, interactive=self.ctx.ui.interactive)

    def install(self, rpms: list[str]) -> Result:
        return self.r.run(["dnf", "-y", "install", *rpms], privileged=True,
                          stream=self.ctx.ui.interactive, interactive=self.ctx.ui.interactive)

    def remove(self, rpms: list[str]) -> Result:
        return self.r.run(["dnf", "-y", "remove", *rpms], privileged=True,
                          stream=self.ctx.ui.interactive, interactive=self.ctx.ui.interactive)
