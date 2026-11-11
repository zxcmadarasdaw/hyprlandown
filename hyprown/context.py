"""Контекст выполнения: пути, окружение, раннер команд, интерфейс.

Все модули получают Ctx и не читают глобальное состояние напрямую. Благодаря
этому тесты подставляют временные каталоги и поддельный раннер, а настоящая
система (в том числе Windows при разработке) не затрагивается.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .runner import Runner
from .ui import UI


@dataclass
class Ctx:
    repo: Path
    home: Path
    config_dir: Path
    state_dir: Path
    data_dir: Path
    bin_dir: Path
    runtime_dir: Path
    runner: Runner
    ui: UI
    env: dict = field(default_factory=dict)
    fsroot: Path = Path("/")  # корень «системы»: в тестах временный каталог

    @classmethod
    def from_env(cls, runner: Runner | None = None, ui: UI | None = None) -> "Ctx":
        env = dict(os.environ)
        home = Path(env.get("HOME") or os.path.expanduser("~"))
        repo = Path(env.get("HYPROWN_REPO") or Path(__file__).resolve().parent.parent)
        state = Path(env.get("HYPRDESK_STATE_DIR")
                     or Path(env.get("XDG_STATE_HOME") or home / ".local/state") / "hyprdesk")
        uid = os.getuid() if hasattr(os, "getuid") else 0
        runtime = Path(env.get("XDG_RUNTIME_DIR") or f"/tmp/hyprown-{uid}")
        return cls(
            repo=repo.resolve(),
            home=home,
            config_dir=Path(env.get("XDG_CONFIG_HOME") or home / ".config"),
            state_dir=state,
            data_dir=Path(env.get("XDG_DATA_HOME") or home / ".local/share"),
            bin_dir=home / ".local/bin",
            runtime_dir=runtime / "hyprown",
            runner=runner or Runner(),
            ui=ui or UI(),
            env=env,
        )

    # --- производные пути ---
    def fs(self, path: str) -> Path:
        """Путь внутри «системы» (для /etc/os-release, /proc, /run)."""
        return self.fsroot / path.lstrip("/")

    @property
    def components_dir(self) -> Path:
        return self.repo / "components"

    @property
    def packages_file(self) -> Path:
        return self.repo / "manifests" / "packages.toml"

    @property
    def state_file(self) -> Path:
        return self.state_dir / "components.json"

    @property
    def log_dir(self) -> Path:
        return self.state_dir / "logs"

    @property
    def backup_dir(self) -> Path:
        return self.state_dir / "backups"

    @property
    def journal_dir(self) -> Path:
        return self.state_dir / "installs"

    @property
    def snapshot_dir(self) -> Path:
        return self.state_dir / "snapshots"

    @property
    def shell_dir(self) -> Path:
        return self.repo / "quickshell" / "hyprdesk"

    @property
    def manager_dir(self) -> Path:
        return self.repo / "quickshell" / "manager"

    @property
    def user_catalog_dir(self) -> Path:
        """Каталог недоверенных модулей: виден в менеджере, но не ставится без trust."""
        return self.data_dir / "hyprown" / "catalog"
