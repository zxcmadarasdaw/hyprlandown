"""Recovery Manager: снимки состояния, откат установок, принудительный safe-режим.

Что считается «состоянием»: components.json, canvas.json, wallpaper.json,
performance.conf, shell.json, trust.json, theme.json из ~/.local/state/hyprdesk.
Производные файлы темы (tokens.json, theme.conf) не хранятся: их пересобирает ThemeEngine.
Пользовательские конфиги вне репозитория не копируются: их защищают резервные
копии ссылок (ConfigManager.apply_links) и откат транзакции установки.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from .config import ConfigManager
from .context import Ctx
from .manifest import Component
from .registry import Registry, atomic_write

STATE_FILES = ("components.json", "canvas.json", "wallpaper.json", "performance.conf",
               "shell.json", "trust.json", "theme.json")
KEEP_SNAPSHOTS = 10


class RecoveryManager:
    def __init__(self, ctx: Ctx, reg: Registry):
        self.ctx, self.reg = ctx, reg
        self.cfg = ConfigManager(ctx)

    # ---------- снимки ----------
    def snapshot(self, label: str = "manual") -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = self.ctx.snapshot_dir / f"{stamp}-{label}"
        n = 0
        while base.exists():
            n += 1
            base = self.ctx.snapshot_dir / f"{stamp}-{label}-{n}"
        base.mkdir(parents=True)
        saved = []
        for name in STATE_FILES:
            f = self.ctx.state_dir / name
            if f.is_file():
                shutil.copy2(f, base / name)
                saved.append(name)
        atomic_write(base / "meta.json", json.dumps({"label": label, "files": saved, "time": stamp}))
        self._prune()
        return base

    def _prune(self):
        snaps = sorted(p for p in self.ctx.snapshot_dir.glob("*") if p.is_dir())
        for old in snaps[:-KEEP_SNAPSHOTS]:
            shutil.rmtree(old, ignore_errors=True)

    def snapshots(self) -> list[dict]:
        out = []
        for p in sorted(self.ctx.snapshot_dir.glob("*"), reverse=True):
            if p.is_dir():
                try:
                    meta = json.loads((p / "meta.json").read_text())
                except (OSError, ValueError):
                    meta = {}
                out.append({"id": p.name, "label": meta.get("label", ""), "files": meta.get("files", [])})
        return out

    def restore_snapshot(self, sid: str) -> list[str]:
        base = self.ctx.snapshot_dir / sid
        if not base.is_dir() or "/" in sid or "\\" in sid or ".." in sid:
            raise FileNotFoundError(f"снимок не найден: {sid}")
        self.snapshot("before-restore")
        restored = []
        for name in STATE_FILES:
            f = base / name
            if f.is_file():
                atomic_write(self.ctx.state_dir / name, f.read_text(encoding="utf-8"))
                restored.append(name)
        if "theme.json" in restored:
            from .theme import ThemeEngine  # поздний импорт: theme не нужен остальному recovery
            ThemeEngine(self.ctx).write()
        return restored

    # ---------- транзакции установки ----------
    def new_journal(self, kind: str) -> dict:
        return {"id": time.strftime("%Y%m%d-%H%M%S"), "kind": kind, "ops": [], "ok": None,
                "components": []}

    def save_journal(self, j: dict) -> Path:
        f = self.ctx.journal_dir / f"{j['id']}.json"
        atomic_write(f, json.dumps(j, indent=2, ensure_ascii=False))
        return f

    def journals(self) -> list[dict]:
        out = []
        for f in sorted(self.ctx.journal_dir.glob("*.json"), reverse=True):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return out

    def rollback(self, jid: str | None = None) -> list[str]:
        """Откатывает ссылки последней (или указанной) установки. Пакеты не удаляет."""
        js = self.journals()
        if not js:
            raise FileNotFoundError("нет записей об установках: откатывать нечего")
        j = next((x for x in js if x["id"] == jid), None) if jid else js[0]
        if j is None:
            raise FileNotFoundError(f"запись {jid} не найдена")
        self.snapshot("before-rollback")
        msgs = []
        for op in reversed(j["ops"]):
            if op["op"] == "link":
                msgs.append(self.cfg.rollback_link(op["name"], Path(op["dst"])))
            elif op["op"] == "mark":
                self.reg.forget(op["component"])
                msgs.append(f"[{op['component']}] отметка об установке снята")
            elif op["op"] == "copr":
                msgs.append(f"COPR {op['id']} остаётся включённым: отключить можно командой "
                            f"`sudo dnf copr disable {op['id']}`")
            elif op["op"] == "packages":
                msgs.append("Пакеты не удаляются автоматически: " + ", ".join(op["rpms"]))
        j["rolled_back"] = True
        self.save_journal(j)
        return msgs

    # ---------- safe-режим ----------
    def safe_flag(self) -> Path:
        return self.ctx.state_dir / "force-safe"

    def set_safe_mode(self, on: bool) -> None:
        f = self.safe_flag()
        if on:
            atomic_write(f, f"{int(time.time())}\n")
        else:
            f.unlink(missing_ok=True)

    def safe_mode(self) -> bool:
        return self.safe_flag().exists()

    def reset_shell_state(self) -> list[str]:
        """Убирает canvas.json и wallpaper.json (в снимок), если оболочка не стартует из-за них."""
        snap = self.snapshot("before-reset-shell")
        gone = []
        for name in ("canvas.json", "wallpaper.json"):
            f = self.ctx.state_dir / name
            if f.exists():
                f.unlink()
                gone.append(name)
        return gone + [f"копия в {snap}"]
