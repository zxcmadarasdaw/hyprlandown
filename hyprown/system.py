"""Определение системы: ОС, Live USB, сессия, GPU, место на диске.

Читает только файлы и вызывает безопасные команды чтения. Корень «системы»
берётся из ctx.fsroot, поэтому тесты подставляют поддельные /etc и /proc.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field, asdict

from .context import Ctx

GPU_VENDORS = {"0x1002": "amd", "0x10de": "nvidia", "0x8086": "intel"}


@dataclass
class SystemInfo:
    os_id: str = ""
    version_id: str = ""
    pretty_name: str = ""
    variant: str = ""
    arch: str = ""
    is_fedora: bool = False
    is_live: bool = False
    is_root: bool = False
    in_vm: str = ""
    session_type: str = ""
    desktop: str = ""
    wayland_display: str = ""
    x11_display: str = ""
    gpus: list = field(default_factory=list)
    free_root_mb: int = 0
    free_home_mb: int = 0
    tty: bool = False

    def to_dict(self):
        return asdict(self)

    @property
    def gpu(self) -> str:
        """Основная видеокарта для выбора декодера: nvidia > amd > intel > ''. """
        for v in ("nvidia", "amd", "intel"):
            if v in self.gpus:
                return v
        return ""

    @property
    def can_nest(self) -> bool:
        return bool(self.wayland_display or self.x11_display)


def parse_os_release(text: str) -> dict:
    data = {}
    for line in text.splitlines():
        m = re.match(r'^([A-Z_]+)=(.*)$', line.strip())
        if m:
            data[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return data


def detect_live(ctx: Ctx) -> bool:
    """Fedora Live: dracut помечает загрузку параметром rd.live.image / root=live:."""
    cmdline = ""
    p = ctx.fs("/proc/cmdline")
    if p.exists():
        cmdline = p.read_text(errors="replace")
    if "rd.live.image" in cmdline or "root=live:" in cmdline or "rd.live.overlay" in cmdline:
        return True
    return ctx.fs("/run/initramfs/live").exists()


def detect_gpus(ctx: Ctx) -> list:
    found = []
    drm = ctx.fs("/sys/class/drm")
    if drm.exists():
        for card in sorted(drm.glob("card[0-9]")):
            vf = card / "device" / "vendor"
            if vf.exists():
                v = GPU_VENDORS.get(vf.read_text().strip().lower())
                if v and v not in found:
                    found.append(v)
    return found


def free_mb(path) -> int:
    try:
        return int(shutil.disk_usage(path).free / (1024 * 1024))
    except OSError:
        return 0


def detect(ctx: Ctx) -> SystemInfo:
    info = SystemInfo()
    osr = ctx.fs("/etc/os-release")
    data = parse_os_release(osr.read_text(errors="replace")) if osr.exists() else {}
    info.os_id = data.get("ID", "")
    info.version_id = data.get("VERSION_ID", "")
    info.pretty_name = data.get("PRETTY_NAME", "")
    info.variant = data.get("VARIANT_ID", "")
    info.is_fedora = info.os_id == "fedora"
    info.arch = ctx.env.get("HYPROWN_ARCH") or _arch()
    info.is_live = detect_live(ctx)
    info.is_root = ctx.runner.is_root()
    info.session_type = ctx.env.get("XDG_SESSION_TYPE", "")
    info.desktop = ctx.env.get("XDG_CURRENT_DESKTOP", "")
    info.wayland_display = ctx.env.get("WAYLAND_DISPLAY", "")
    info.x11_display = ctx.env.get("DISPLAY", "")
    info.gpus = detect_gpus(ctx)
    root = ctx.fs("/")
    info.free_root_mb = free_mb(root) if root.exists() else 0
    info.free_home_mb = free_mb(ctx.home) if ctx.home.exists() else info.free_root_mb
    info.tty = ctx.ui.interactive
    if ctx.runner.which("systemd-detect-virt"):
        r = ctx.runner.run(["systemd-detect-virt"], mutates=False)
        if r.ok and r.out.strip() != "none":
            info.in_vm = r.out.strip()
    return info


def _arch() -> str:
    import platform
    return platform.machine()


def fedora_major(info: SystemInfo) -> int:
    try:
        return int(info.version_id.split(".")[0])
    except ValueError:
        return 0
