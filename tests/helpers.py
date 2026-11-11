"""Общие помощники тестов: временный контекст и поддельная «система».

Тесты не трогают реальный ~/.config, /etc и dnf: контекст целиком во временном
каталоге, команды выполняет FakeRunner. Тесты, которым нужны настоящие
симлинки, пропускаются там, где их создать нельзя (Windows без прав).
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from hyprown.config import ConfigManager
from hyprown.context import Ctx
from hyprown.runner import FakeRunner, Result
from hyprown.ui import UI

REPO = Path(__file__).resolve().parent.parent


def _can_symlink() -> bool:
    d = Path(tempfile.mkdtemp())
    try:
        (d / "a").mkdir()
        os.symlink(d / "a", d / "l", target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        return False
    finally:
        shutil.rmtree(d, ignore_errors=True)


HAS_SYMLINK = _can_symlink()
needs_symlink = unittest.skipUnless(HAS_SYMLINK, "в этой системе нельзя создавать симлинки (Windows без прав)")

FEDORA_OS_RELEASE = ('NAME="Fedora Linux"\nID=fedora\nVERSION_ID=45\n'
                     'PRETTY_NAME="Fedora Linux 45 (KDE Plasma Desktop Edition)"\nVARIANT_ID=kde\n')


class Env:
    """Временный контекст. Использование: with Env(bins={"dnf"}) as e: e.ctx ..."""

    def __init__(self, bins=(), responses=None, live=False, os_release=FEDORA_OS_RELEASE, gpu="0x1002",
                 yes=True, root=False, env_extra=None, interactive=False):
        self.tmp = Path(tempfile.mkdtemp(prefix="hyprown-test-"))
        self.fake_root = self.tmp / "root"
        (self.fake_root / "etc").mkdir(parents=True)
        (self.fake_root / "etc/os-release").write_text(os_release)
        (self.fake_root / "proc").mkdir()
        (self.fake_root / "proc/cmdline").write_text("BOOT_IMAGE=x rd.live.image quiet" if live else "BOOT_IMAGE=x quiet")
        if gpu:
            card = self.fake_root / "sys/class/drm/card0/device"
            card.mkdir(parents=True)
            (card / "vendor").write_text(gpu + "\n")
        home = self.tmp / "home"
        home.mkdir()
        self.out = io.StringIO()
        self.ui = UI(assume_yes=yes, color=False, stream=self.out, interactive=interactive)
        self.runner = FakeRunner(responses=responses or [], bins=set(bins), root=root)
        env = {"HOME": str(home), "PATH": "/usr/bin", "XDG_RUNTIME_DIR": str(self.tmp / "run")}
        env.update(env_extra or {})
        self.ctx = Ctx(repo=REPO, home=home, config_dir=home / ".config", state_dir=home / ".local/state/hyprdesk",
                       data_dir=home / ".local/share", bin_dir=home / ".local/bin",
                       runtime_dir=self.tmp / "run" / "hyprown", runner=self.runner, ui=self.ui,
                       env=env, fsroot=self.fake_root)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @property
    def output(self) -> str:
        return self.out.getvalue()


def ok(out="", err=""):
    return Result([], 0, out, err)


def bad(code=1, err="ошибка"):
    return Result([], code, "", err)


@contextmanager
def no_links():
    """Отключает создание симлинков (для тестов, где важна логика, а не ссылки)."""
    with mock.patch.object(ConfigManager, "apply_links", lambda self, comp, journal=None: []), \
         mock.patch.object(ConfigManager, "link_states", lambda self, comp: []):
        yield


def dnf_responses(available=(), installed_rpms=(), enabled_copr=(), install_ok=True, copr_ok=True):
    """Типовые ответы dnf/rpm. available: rpm, которые видны в репозиториях сейчас."""
    state = {"available": set(available), "installed": set(installed_rpms), "copr": set(enabled_copr)}

    def repoquery(cmd):
        name = cmd[-1]
        return ok(name + "-1.0\n") if name in state["available"] else ok("")

    def rpm_q(cmd):
        return ok(cmd[-1]) if cmd[-1] in state["installed"] else bad(1)

    def install(cmd):
        if not install_ok:
            return bad(1, "install failed")
        state["installed"].update(x for x in cmd if not x.startswith("-") and x not in ("sudo", "dnf", "install"))
        return ok()

    def copr_enable(cmd):
        if not copr_ok:
            return bad(1, "copr failed")
        state["copr"].add(cmd[-1])
        state["available"].update({"hyprland", "quickshell", "hyprpaper", "hyprlock"})
        return ok()

    return state, [
        (("dnf", "-q", "repoquery"), repoquery),
        (("rpm", "-q"), rpm_q),
        (("dnf", "copr", "list"), lambda c: ok("\n".join(state["copr"]))),
        (("dnf", "-y", "copr", "enable"), copr_enable),
        (("dnf", "-y", "install"), install),
    ]
