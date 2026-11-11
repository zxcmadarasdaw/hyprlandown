"""Component Registry: каталог компонентов и их состояние (установлен, включён).

Каталог читается из доверенной папки проекта (components/). Состояние
пользователя лежит в ~/.local/state/hyprdesk/components.json и пишется атомарно.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from .context import Ctx
from .manifest import Component, PackageDef, discover, load_packages


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Registry:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self.packages: dict[str, PackageDef] = load_packages(ctx.packages_file)
        self.components, self.errors = discover(ctx, self.packages)

    # --- состояние ---
    def state(self) -> dict:
        try:
            data = json.loads(self.ctx.state_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"components": {}}
        except (OSError, ValueError):
            return {"components": {}}

    def _save(self, st: dict) -> None:
        atomic_write(self.ctx.state_file, json.dumps(st, indent=2, ensure_ascii=False))

    def record(self, cid: str) -> dict:
        return self.state().get("components", {}).get(cid, {})

    def is_installed(self, cid: str) -> bool:
        return bool(self.record(cid).get("installed"))

    def is_enabled(self, cid: str) -> bool:
        r = self.record(cid)
        return bool(r.get("installed") and r.get("enabled", True))

    def mark(self, cid: str, **fields) -> None:
        st = self.state()
        rec = st.setdefault("components", {}).setdefault(cid, {})
        rec.update(fields)
        rec["updated_at"] = int(time.time())
        self._save(st)

    def forget(self, cid: str) -> None:
        st = self.state()
        st.get("components", {}).pop(cid, None)
        self._save(st)

    # --- запросы ---
    def get(self, cid: str) -> Component:
        if cid not in self.components:
            raise KeyError(f"неизвестный компонент: {cid}")
        return self.components[cid]

    def dependants(self, cid: str) -> list[str]:
        """Установленные компоненты, которым нужен cid."""
        return [c.id for c in self.components.values()
                if cid in c.requires and self.is_installed(c.id)]

    def listing(self) -> list[dict]:
        out = []
        for c in self.components.values():
            d = c.to_dict()
            rec = self.record(c.id)
            d.update(installed=bool(rec.get("installed")), enabled=self.is_enabled(c.id),
                     installed_version=rec.get("version", ""), failed=bool(rec.get("failed")),
                     failure=rec.get("failure", ""))
            out.append(d)
        return out
