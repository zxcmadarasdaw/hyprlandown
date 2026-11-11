"""Dependency Resolver: выбор компонентов -> порядок -> список нужных пакетов.

Ничего не устанавливает: только считает план. План показывается пользователю
до любых изменений.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

from .manifest import Component, PackageDef
from .pkg import version_ge
from .registry import Registry
from .system import SystemInfo, fedora_major


class ResolveError(ValueError):
    pass


@dataclass
class PkgPlan:
    id: str
    rpm: list
    description: str
    required: bool
    components: list
    state: str  # installed | available | needs-copr | missing
    copr: list = field(default_factory=list)  # кандидаты COPR (только для needs-copr)
    version: str = ""
    min_version: str = ""
    note: str = ""

    @property
    def to_install(self) -> bool:
        return self.state in ("available", "needs-copr")

    def to_dict(self):
        return asdict(self)


def order(reg: Registry, selected: list[str]) -> list[str]:
    """Замыкание по requires + топологический порядок. Ошибка при цикле/неизвестном/неодобренном."""
    result: list[str] = []
    visiting: set[str] = set()

    def visit(cid: str, chain: tuple):
        if cid in result:
            return
        if cid in visiting:
            raise ResolveError("цикл зависимостей: " + " -> ".join(chain + (cid,)))
        if cid not in reg.components:
            raise ResolveError(f"неизвестный компонент {cid!r}" + (f" (нужен для {chain[-1]})" if chain else ""))
        comp = reg.components[cid]
        if not comp.approved:
            raise ResolveError(f"компонент {cid} из недоверенного каталога: сначала `hyprown trust {cid}`")
        visiting.add(cid)
        for dep in comp.requires:
            visit(dep, chain + (cid,))
        visiting.discard(cid)
        result.append(cid)

    for cid in selected:
        visit(cid, ())
    return result


def compat_problems(comp: Component, info: SystemInfo, hyprland_version: str) -> list[str]:
    out = []
    if comp.fedora_min and info.is_fedora and fedora_major(info) and fedora_major(info) < comp.fedora_min:
        out.append(f"{comp.id}: нужна Fedora {comp.fedora_min} или новее, у вас {info.version_id}")
    if comp.hyprland_min and hyprland_version and not version_ge(hyprland_version, comp.hyprland_min):
        out.append(f"{comp.id}: нужен Hyprland {comp.hyprland_min}+, у вас {hyprland_version}")
    return out


def plan_packages(reg: Registry, pm, ids: list[str], info: SystemInfo,
                  with_recommended: bool = True) -> list[PkgPlan]:
    wanted: dict[str, tuple[bool, list]] = {}
    for cid in ids:
        comp = reg.components[cid]
        names = [(p, True) for p in comp.pkg_required]
        if with_recommended:
            names += [(p, False) for p in comp.pkg_recommended]
            names += [(p, False) for p in comp.pkg_gpu.get(info.gpu, [])]
        for pid, req in names:
            was_req, comps = wanted.get(pid, (False, []))
            wanted[pid] = (was_req or req, comps + [cid])
    plans = []
    for pid, (req, comps) in wanted.items():
        pkg: PackageDef = reg.packages[pid]
        if pm.present(pkg):
            state, copr = "installed", []
        elif pm.available(pkg):
            state, copr = "available", []
        elif pkg.sources:
            state, copr = "needs-copr", [s for s in pkg.sources if s["type"] == "copr"]
        else:
            state, copr = "missing", []
        plans.append(PkgPlan(id=pid, rpm=pkg.rpm, description=pkg.description, required=req,
                             components=comps, state=state, copr=copr,
                             version=pm.version(pkg) if state == "installed" else "",
                             min_version=pkg.min_version, note=pkg.note))
    return plans
