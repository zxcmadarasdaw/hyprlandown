"""Update Manager: обновление проекта из Git без перезапуска рабочего стола.

Обновляется только сам репозиторий (git pull --ff-only), потому что ссылки
конфигов указывают в него. Перед обновлением делается снимок состояния.
Сетевые запросы выполняются только по явной команде пользователя. Системные
пакеты обновляет сам пользователь (dnf upgrade), мы их не трогаем.
"""

from __future__ import annotations

from .context import Ctx
from .recovery import RecoveryManager
from .registry import Registry
from .shell import ShellManager


class UpdateManager:
    def __init__(self, ctx: Ctx, reg: Registry):
        self.ctx, self.reg = ctx, reg

    def _git(self, *args, **kw):
        return self.ctx.runner.run(["git", "-C", str(self.ctx.repo), *args], mutates=kw.pop("mutates", False),
                                   timeout=kw.pop("timeout", 60))

    def is_git(self) -> bool:
        return (self.ctx.repo / ".git").exists() and bool(self.ctx.runner.which("git"))

    def check(self) -> dict:
        if not self.is_git():
            return {"ok": False, "reason": "каталог проекта не является git-репозиторием", "behind": 0}
        fetch = self._git("fetch", "--quiet", timeout=90)
        if not fetch.ok:
            return {"ok": False, "reason": "не удалось получить обновления: " + (fetch.err or fetch.out).strip(),
                    "behind": 0}
        behind = self._git("rev-list", "--count", "HEAD..@{u}")
        if not behind.ok:
            return {"ok": False, "reason": "у ветки нет upstream: обновлять нечего", "behind": 0}
        n = int(behind.out.strip() or 0)
        log = self._git("log", "--oneline", "-n", "15", "HEAD..@{u}").out.strip().splitlines() if n else []
        dirty = bool(self._git("status", "--porcelain").out.strip())
        return {"ok": True, "behind": n, "commits": log, "dirty": dirty, "reason": ""}

    def apply(self) -> dict:
        info = self.check()
        if not info["ok"]:
            return info
        if info["behind"] == 0:
            return {**info, "applied": False, "message": "уже последняя версия"}
        if info["dirty"]:
            return {**info, "applied": False,
                    "message": "в проекте есть незакоммиченные изменения: обновление отменено, чтобы их не потерять"}
        snap = RecoveryManager(self.ctx, self.reg).snapshot("before-update")
        pull = self._git("pull", "--ff-only", mutates=True, timeout=180)
        if not pull.ok:
            return {**info, "applied": False, "message": "git pull не выполнен: " + (pull.err or pull.out).strip(),
                    "snapshot": str(snap)}
        return {**info, "applied": True, "snapshot": str(snap),
                "message": "обновлено. Горячая перезагрузка: Quickshell перечитывает QML сам; "
                           "изменения hypr/*.conf применит `hyprctl reload`. "
                           "Если менялись записи сессии: переустановите компонент login-session."}

    def hot_reload(self) -> list[str]:
        """Безопасные горячие действия: перезапуск оболочки и перечитывание конфига Hyprland."""
        done = []
        sh = ShellManager(self.ctx)
        if sh.running_pid(self.ctx.env):
            sh.restart()
            done.append("Quickshell перезапущен")
        if self.ctx.env.get("HYPRLAND_INSTANCE_SIGNATURE") and self.ctx.runner.which("hyprctl"):
            self.ctx.runner.run(["hyprctl", "reload"], env=self.ctx.env, timeout=10)
            done.append("hyprctl reload выполнен")
        return done
