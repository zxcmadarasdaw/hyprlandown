"""Манифесты: пакеты (manifests/packages.toml) и компоненты (components/*/component.toml).

Манифест только ОПИСЫВАЕТ. Исполняемых полей в нём нет: нельзя указать команду,
скрипт или произвольный пакет. Допустимые действия (ссылки, системные файлы
сессии, автозапуск, активация) фиксированы в коде. Поэтому даже подставной
манифест не может выполнить произвольный код.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .context import Ctx

SCHEMA = 1
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
KINDS = {"core", "widget", "theme", "plugin", "tool"}
ACTIVATION = {"none", "quickshell-restart", "hyprland-reload", "relogin"}
DST_ROOTS = {"@config": "config_dir", "@data": "data_dir", "@bin": "bin_dir"}
PERMISSIONS = {"packages", "copr", "user-config", "session-files", "autostart"}


class ManifestError(ValueError):
    pass


@dataclass
class PackageDef:
    id: str
    description: str
    rpm: list
    check_bin: str = ""
    check_paths: list = field(default_factory=list)
    version_cmd: list = field(default_factory=list)
    version_re: str = ""
    min_version: str = ""
    note: str = ""
    sources: list = field(default_factory=list)


@dataclass
class Link:
    name: str
    src: str
    dst: str


@dataclass
class Component:
    id: str
    name: str
    version: str
    summary: str
    kind: str
    default: bool
    experimental: bool
    requires: list
    pkg_required: list
    pkg_recommended: list
    pkg_gpu: dict
    permissions: list
    links: list
    system_session: bool
    activation: str
    hyprland_min: str
    fedora_min: int
    path: Path
    trusted: bool = True
    sha256: str = ""
    approved: bool = True  # недоверенный манифест ставится только после trust

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "version": self.version, "summary": self.summary,
            "kind": self.kind, "default": self.default, "experimental": self.experimental,
            "requires": self.requires, "packages_required": self.pkg_required,
            "packages_recommended": self.pkg_recommended, "permissions": self.permissions,
            "activation": self.activation, "trusted": self.trusted, "approved": self.approved,
            "system_session": self.system_session,
        }


def load_packages(path: Path) -> dict[str, PackageDef]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ManifestError(f"{path}: {exc}") from exc
    out = {}
    for pid, p in data.get("package", {}).items():
        if not ID_RE.match(pid):
            raise ManifestError(f"{path}: недопустимый id пакета {pid!r}")
        if not p.get("rpm"):
            raise ManifestError(f"{path}: у пакета {pid} нет поля rpm")
        for s in p.get("sources", []):
            if s.get("type") != "copr" or not re.match(r"^[\w.-]+/[\w.-]+$", s.get("id", "")):
                raise ManifestError(f"{path}: пакет {pid}: неверный источник {s!r}")
        out[pid] = PackageDef(
            id=pid, description=p.get("description", ""), rpm=list(p["rpm"]),
            check_bin=p.get("check_bin", ""), check_paths=list(p.get("check_paths", [])),
            version_cmd=list(p.get("version_cmd", [])), version_re=p.get("version_re", ""),
            min_version=p.get("min_version", ""), note=p.get("note", ""),
            sources=list(p.get("sources", [])))
    return out


def _safe_rel(rel: str, what: str) -> str:
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts or not rel:
        raise ManifestError(f"{what}: путь должен быть относительным и без '..': {rel!r}")
    return rel


def parse_component(path: Path, packages: dict, trusted: bool, approved: bool) -> Component:
    raw = path.read_bytes()
    try:
        d = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ManifestError(f"{path}: {exc}") from exc
    cid = d.get("id", "")
    if not ID_RE.match(cid):
        raise ManifestError(f"{path}: недопустимый id {cid!r}")
    if d.get("schema") != SCHEMA:
        raise ManifestError(f"{cid}: schema должна быть {SCHEMA}")
    for req in ("name", "version", "summary", "kind"):
        if not d.get(req):
            raise ManifestError(f"{cid}: нет поля {req}")
    if d["kind"] not in KINDS:
        raise ManifestError(f"{cid}: kind должен быть одним из {sorted(KINDS)}")
    pk = d.get("packages", {})
    required, recommended = list(pk.get("required", [])), list(pk.get("recommended", []))
    gpu = {k: list(v) for k, v in pk.get("gpu", {}).items()}
    for pid in required + recommended + [x for v in gpu.values() for x in v]:
        if pid not in packages:
            raise ManifestError(f"{cid}: неизвестный пакет {pid!r} (его нет в manifests/packages.toml)")
    perms = list(d.get("permissions", []))
    bad = [p for p in perms if p not in PERMISSIONS]
    if bad:
        raise ManifestError(f"{cid}: неизвестные разрешения {bad}")
    links = []
    for ln in d.get("links", []):
        _safe_rel(ln.get("src", ""), f"{cid}: links.src")
        dst = ln.get("dst", "")
        root, _, rest = dst.partition("/")
        if root not in DST_ROOTS or not rest:
            raise ManifestError(f"{cid}: links.dst должен начинаться с одного из {sorted(DST_ROOTS)}/: {dst!r}")
        _safe_rel(rest, f"{cid}: links.dst")
        if not ln.get("name"):
            raise ManifestError(f"{cid}: у ссылки нужно поле name")
        links.append(Link(ln["name"], ln["src"], dst))
    act = d.get("activation", {}).get("mode", "none")
    if act not in ACTIVATION:
        raise ManifestError(f"{cid}: activation.mode должен быть одним из {sorted(ACTIVATION)}")
    sysf = bool(d.get("session", {}).get("system_files", False))
    if not trusted and (sysf or "session-files" in perms or "copr" in perms):
        raise ManifestError(f"{cid}: недоверенный манифест не может просить системные файлы или COPR")
    compat = d.get("compat", {})
    return Component(
        id=cid, name=d["name"], version=str(d["version"]), summary=d["summary"], kind=d["kind"],
        default=bool(d.get("default", False)), experimental=bool(d.get("experimental", False)),
        requires=list(d.get("requires", [])), pkg_required=required, pkg_recommended=recommended,
        pkg_gpu=gpu, permissions=perms, links=links, system_session=sysf, activation=act,
        hyprland_min=compat.get("hyprland_min", ""), fedora_min=int(compat.get("fedora_min", 0)),
        path=path, trusted=trusted, sha256=hashlib.sha256(raw).hexdigest(), approved=approved)


def load_trust(ctx: Ctx) -> dict:
    f = ctx.state_dir / "trust.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def discover(ctx: Ctx, packages: dict) -> tuple[dict[str, Component], list[str]]:
    """Находит компоненты. Доверенные: каталог проекта. Остальные: каталог пользователя.

    Возвращает (компоненты, ошибки). Ошибка одного манифеста не мешает остальным.
    """
    found, errors = {}, []
    trust = load_trust(ctx)
    sources = [(ctx.components_dir, True)]
    if ctx.user_catalog_dir.is_dir():
        sources.append((ctx.user_catalog_dir, False))
    for base, trusted in sources:
        if not base.is_dir():
            continue
        for mf in sorted(base.glob("*/component.toml")):
            try:
                raw_hash = hashlib.sha256(mf.read_bytes()).hexdigest()
                approved = trusted or trust.get(mf.parent.name) == raw_hash
                comp = parse_component(mf, packages, trusted, approved)
            except ManifestError as exc:
                errors.append(str(exc))
                continue
            if comp.id in found:
                errors.append(f"{mf}: id {comp.id} уже занят доверенным компонентом")
                continue
            found[comp.id] = comp
    return found, errors


def approve(ctx: Ctx, comp: Component) -> None:
    """Запоминает хэш просмотренного пользователем недоверенного манифеста."""
    trust = load_trust(ctx)
    trust[comp.path.parent.name] = comp.sha256
    ctx.state_dir.mkdir(parents=True, exist_ok=True)
    (ctx.state_dir / "trust.json").write_text(json.dumps(trust, indent=2), encoding="utf-8")
