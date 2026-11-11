"""Установка, удаление и активация компонентов. Общий механизм для install.sh и Manager.

Порядок: план -> показ плана -> подтверждения -> применение -> проверка -> журнал.
Ни один шаг не выполняется до подтверждения. Сбой компонента не отменяет
остальные: рабочие функции сохраняются, итог перечисляет, что не удалось.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import TESTED_FEDORA
from .config import ConfigManager
from .context import Ctx
from .keybinds import KeyManager
from .theme import ThemeEngine
from .pkg import DnfAdapter
from .recovery import RecoveryManager
from .registry import Registry
from .resolver import PkgPlan, ResolveError, compat_problems, order, plan_packages
from .shell import ShellManager
from .system import SystemInfo, detect, fedora_major

# Грубая оценка скачиваемого и распаковываемого объёма для проверки места, МБ.
EST_MB_PER_PACKAGE = 120
MIN_FREE_MB = 800


@dataclass
class Options:
    components: list | None = None
    minimal: bool = False       # без рекомендуемых пакетов
    no_copr: bool = False       # не подключать сторонние репозитории
    live_ok: bool = False       # заранее согласен с ограничениями Live USB
    with_session: bool | None = None  # login-session: None = по умолчанию


@dataclass
class Plan:
    ids: list
    pkgs: list
    links: list
    blocked: dict
    warnings: list
    problems: list
    live: bool
    need_root: bool
    est_mb: int

    def to_dict(self):
        return {"components": self.ids, "packages": [p.to_dict() for p in self.pkgs],
                "links": [{"component": c, **ls.to_dict()} for c, ls in self.links],
                "blocked": self.blocked, "warnings": self.warnings, "problems": self.problems,
                "live": self.live, "need_root": self.need_root, "est_mb": self.est_mb}


@dataclass
class Report:
    installed: list = field(default_factory=list)
    failed: dict = field(default_factory=dict)
    skipped: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    journal: str = ""

    @property
    def ok(self) -> bool:
        return not self.failed

    def to_dict(self):
        return {"ok": self.ok, **self.__dict__}


class Installer:
    def __init__(self, ctx: Ctx, reg: Registry, info: SystemInfo | None = None):
        self.ctx, self.reg = ctx, reg
        self.info = info or detect(ctx)
        self.pm = DnfAdapter(ctx)
        self.cfg = ConfigManager(ctx)
        self.rec = RecoveryManager(ctx, reg)
        self.dry = bool(getattr(ctx.runner, "dry_run", False))

    # ---------- выбор по умолчанию ----------
    def default_selection(self) -> list[str]:
        out = []
        for c in self.reg.components.values():
            if not (c.default and c.approved):
                continue
            if c.id == "login-session" and self.info.is_live:
                continue  # на Live экран входа обычно не используется: включается явно
            out.append(c.id)
        return out

    # ---------- план ----------
    def build_plan(self, opts: Options) -> Plan:
        selected = opts.components if opts.components is not None else self.default_selection()
        warnings, problems, blocked = [], [], {}
        try:
            ids = order(self.reg, selected)
        except ResolveError as exc:
            return Plan([], [], [], {}, [], [str(exc)], self.info.is_live, False, 0)
        if self.info.is_fedora and fedora_major(self.info) and fedora_major(self.info) != int(TESTED_FEDORA):
            warnings.append(f"Fedora {self.info.version_id}: проект проверялся на Fedora {TESTED_FEDORA}")
        if not self.info.is_fedora:
            problems.append(f"Система {self.info.pretty_name or self.info.os_id or '?'} не Fedora: "
                            "установщик рассчитан на Fedora (dnf)")
        pkgs = plan_packages(self.reg, self.pm, ids, self.info, with_recommended=not opts.minimal)
        for p in pkgs:
            if p.state == "missing" and p.required:
                for cid in p.components:
                    blocked[cid] = f"пакет {p.id} недоступен ни в одном репозитории"
            if p.state == "needs-copr" and opts.no_copr and p.required:
                for cid in p.components:
                    blocked[cid] = f"пакет {p.id} есть только в стороннем COPR, а он запрещён (--no-copr)"
            if p.state == "missing" and not p.required:
                warnings.append(f"Необязательный пакет {p.id} недоступен: {p.description}")
        # блокировка распространяется на зависящие компоненты
        changed = True
        while changed:
            changed = False
            for cid in ids:
                dep = next((d for d in self.reg.components[cid].requires if d in blocked), None)
                if dep and cid not in blocked:
                    blocked[cid] = f"зависит от заблокированного компонента {dep}"
                    changed = True
        links = []
        for cid in ids:
            for ls in self.cfg.link_states(self.reg.components[cid]):
                links.append((cid, ls))
        hv = next((p.version for p in pkgs if p.id == "hyprland" and p.state == "installed"), "")
        for cid in ids:
            warnings += compat_problems(self.reg.components[cid], self.info, hv)
        need_root = any(p.to_install for p in pkgs) or any(
            self.reg.components[c].system_session for c in ids)
        est = sum(EST_MB_PER_PACKAGE for p in pkgs if p.to_install)
        free = self.info.free_root_mb if self.info.is_live else self.info.free_home_mb
        if est and free and free < est + MIN_FREE_MB:
            problems.append(f"Мало места: свободно {free} МБ, нужно примерно {est + MIN_FREE_MB} МБ")
        return Plan(ids, pkgs, links, blocked, warnings, problems, self.info.is_live, need_root, est)

    def show_plan(self, plan: Plan) -> None:
        ui = self.ctx.ui
        ui.title("План установки")
        if plan.problems:
            for p in plan.problems:
                ui.error(p)
        if not plan.ids:
            return
        ui.info("Компоненты (в порядке установки):")
        for cid in plan.ids:
            c = self.reg.components[cid]
            mark = "уже установлен" if self.reg.is_installed(cid) else "будет установлен"
            if cid in plan.blocked:
                mark = "ЗАБЛОКИРОВАН: " + plan.blocked[cid]
            ui.info(f"  - {c.name} [{cid}] {c.version}: {mark}")
        names = {"installed": "уже есть", "available": "из репозиториев Fedora",
                 "needs-copr": "ТРЕБУЕТ стороннего COPR", "missing": "недоступен"}
        rows = [[p.id, ("обяз." if p.required else "реком."), names[p.state], p.version or "-"] for p in plan.pkgs]
        if rows:
            ui.info("")
            ui.table(rows, ["Пакет", "Тип", "Состояние", "Версия"])
        changes = [(c, ls) for c, ls in plan.links if ls.state != "ok"]
        if changes:
            ui.info("")
            ui.info("Конфигурации (ссылки на репозиторий):")
            for c, ls in changes:
                extra = f" ({ls.detail})" if ls.detail else ""
                ui.info(f"  - {ls.dst} -> {ls.src}{extra}")
        for w in plan.warnings:
            ui.warn(w)
        if plan.need_root:
            ui.info("Права root понадобятся только для dnf и записей экрана входа; запрос будет отдельным.")

    # ---------- применение ----------
    def apply(self, plan: Plan, opts: Options) -> Report:
        ui, rep = self.ctx.ui, Report()
        if plan.problems:
            for cid in plan.ids:
                rep.failed[cid] = "; ".join(plan.problems)
            return rep
        todo = [c for c in plan.ids if c not in plan.blocked]
        for cid, why in plan.blocked.items():
            rep.failed[cid] = why
        if plan.live and not opts.live_ok:
            ui.warn("Fedora Live: всё, что вы установите, ПРОПАДЁТ после перезагрузки. Место ограничено памятью.")
            if not ui.confirm("Продолжить установку во временную Live-систему?", default=True):
                rep.skipped = {c: "отказ пользователя (Live USB)" for c in todo}
                return rep
        journal = self.rec.new_journal("install")
        journal["components"] = todo
        if not self.dry:
            self.rec.snapshot("before-install")
        pkg_by_id = {p.id: p for p in plan.pkgs}

        # 1. COPR (отдельное подтверждение на каждый источник)
        coprs = {}
        for p in plan.pkgs:
            if p.state == "needs-copr" and any(c in todo for c in p.components):
                for s in p.copr:
                    coprs.setdefault(s["id"], (s, []))[1].append(p.id)
        denied = set()
        for copr_id, (src, pids) in coprs.items():
            if opts.no_copr or self.pm.copr_enabled(copr_id):
                continue
            ui.warn(f"Пакеты {', '.join(pids)} нет в репозиториях Fedora. Источник: COPR {copr_id}.")
            ui.info(f"  {src.get('note', 'Сторонний репозиторий')}")
            ui.info(f"  Проверялся: {src.get('verified') or 'НЕ проверялся'}. COPR может исчезнуть или измениться без предупреждения.")
            if not ui.confirm(f"Подключить сторонний COPR {copr_id}?", default=False):
                denied.add(copr_id)
                continue
            with ui.step(f"Подключение COPR {copr_id}") as s:
                s.pause()
                r = self.pm.enable_copr(copr_id)
                if not r.ok:
                    s.fail((r.err or "ошибка dnf copr enable").strip().splitlines()[-1] if (r.err or "").strip() else "ошибка")
                    denied.add(copr_id)
                else:
                    journal["ops"].append({"op": "copr", "id": copr_id})
        for p in plan.pkgs:
            if p.state == "needs-copr":
                if all(s["id"] in denied for s in p.copr):
                    p.state = "missing"
                elif not self.dry and not self.pm.available(self.reg.packages[p.id]):
                    p.state = "missing"
                    rep.warnings.append(f"Пакета {p.id} нет и после подключения COPR")
                else:
                    p.state = "available"

        # 2. Пакеты и конфиги по компонентам
        for cid in todo:
            comp = self.reg.components[cid]
            bad = next((d for d in comp.requires if d in rep.failed), None)
            if bad:
                rep.failed[cid] = f"зависит от {bad}, который не установлен"
                continue
            try:
                self._install_component(comp, pkg_by_id, journal, rep)
            except Exception as exc:  # сбой одного компонента не ломает остальные
                rep.failed[cid] = str(exc) or exc.__class__.__name__
                self.reg.mark(cid, failed=True, failure=rep.failed[cid]) if not self.dry else None

        journal["ok"] = rep.ok
        if not self.dry:
            rep.journal = str(self.rec.save_journal(journal))
        return rep

    def _install_component(self, comp, pkg_by_id, journal, rep):
        ui = self.ctx.ui
        req = [pkg_by_id[p] for p in comp.pkg_required if p in pkg_by_id]
        rec = [pkg_by_id[p] for p in comp.pkg_recommended + comp.pkg_gpu.get(self.info.gpu, []) if p in pkg_by_id]
        miss = [p.id for p in req if p.state == "missing"]
        if miss:
            raise RuntimeError("недоступны обязательные пакеты: " + ", ".join(miss))
        need_req = [p for p in req if p.state == "available"]
        need_rec = [p for p in rec if p.state == "available"]
        for p in rec:
            if p.state == "missing":
                rep.warnings.append(f"{comp.id}: пакет {p.id} пропущен (недоступен)")
        if need_req or need_rec:
            rpms = [r for p in need_req + need_rec for r in p.rpm]
            with ui.step(f"Установка пакетов для {comp.name}: {', '.join(rpms)}") as s:
                s.pause()
                r = self.pm.install(rpms)
                if not r.ok and need_rec and need_req:
                    ui.warn("Общая установка не удалась, пробуем только обязательные пакеты.")
                    r = self.pm.install([x for p in need_req for r_ in [p.rpm] for x in r_])
                    rep.warnings.append(f"{comp.id}: рекомендуемые пакеты не установлены")
                elif not r.ok and need_rec and not need_req:
                    rep.warnings.append(f"{comp.id}: рекомендуемые пакеты не установлены")
                    r = type(r)(r.cmd, 0)
                if not r.ok:
                    s.fail("dnf завершился с кодом " + str(r.code))
                    raise RuntimeError("не удалось установить пакеты: " + ", ".join(rpms))
            journal["ops"].append({"op": "packages", "rpms": rpms})
            if not self.dry:
                for p in need_req:
                    if not self.pm.present(self.reg.packages[p.id]):
                        raise RuntimeError(f"после установки пакет {p.id} не обнаружен")
        if self.dry:
            for ln in comp.links:
                ui.info(f"[dry-run] ссылка {self.cfg.resolve_dst(ln.dst)} -> {self.ctx.repo / ln.src}")
            if comp.system_session:
                ui.info("[dry-run] scripts/install-session.sh --apply (root)")
            rep.installed.append(comp.id)
            return
        if comp.links:
            with ui.step(f"Подключение конфигураций: {comp.name}") as s:
                for ls in self.cfg.apply_links(comp, journal["ops"]):
                    ui.info(f"  {ls.dst}: {ls.detail or 'уже настроено'}")
        if comp.system_session:
            self._install_session_files(comp, journal, rep)
        self.cfg.ensure_performance_file()
        KeyManager(self.ctx).ensure_user_conf()  # source в hyprland.conf не должен висеть в пустоту
        ThemeEngine(self.ctx).ensure_files()     # theme.conf и tokens.json (этап 4)
        self.reg.mark(comp.id, installed=True, enabled=True, version=comp.version, failed=False, failure="")
        journal["ops"].append({"op": "mark", "component": comp.id})
        rep.installed.append(comp.id)

    def _install_session_files(self, comp, journal, rep):
        ui = self.ctx.ui
        script = self.ctx.repo / "scripts" / "install-session.sh"
        ui.info("Записи экрана входа: /usr/local/bin/hyprland-session и два файла в /usr/share/wayland-sessions.")
        ui.info("Существующие файлы системы не перезаписываются. PAM и SDDM-конфиг не меняются.")
        if self.info.is_live and not ui.confirm("Это Live USB: записи пропадут после перезагрузки. Всё равно установить?", default=False):
            rep.warnings.append("login-session пропущен на Live USB")
            return
        if not ui.confirm("Установить записи экрана входа (потребуется root)?", default=True):
            rep.warnings.append("login-session: пользователь отказался")
            return
        with ui.step("Запись сессий для экрана входа") as s:
            s.pause()
            r = self.ctx.runner.run(["bash", str(script), "--apply"], privileged=True, stream=ui.interactive,
                                    interactive=ui.interactive)
            if not r.ok:
                s.fail((r.err or "ошибка").strip()[:200])
                raise RuntimeError("не удалось установить записи сессии: " + (r.err or "").strip()[:200])
        journal["ops"].append({"op": "session"})

    # ---------- удаление, включение, активация ----------
    def remove(self, cid: str) -> list[str]:
        comp = self.reg.get(cid)
        deps = self.reg.dependants(cid)
        if deps:
            raise RuntimeError(f"нельзя удалить {cid}: от него зависят {', '.join(deps)}")
        if not self.reg.is_installed(cid):
            raise RuntimeError(f"{cid} не установлен")
        msgs = []
        self.rec.snapshot(f"before-remove-{cid}")
        if comp.system_session:
            script = self.ctx.repo / "scripts" / "install-session.sh"
            r = self.ctx.runner.run(["bash", str(script), "--remove"], privileged=True,
                                    stream=self.ctx.ui.interactive, interactive=self.ctx.ui.interactive)
            msgs.append("записи экрана входа удалены" if r.ok else "записи входа не удалены: " + (r.err or "").strip())
        msgs += self.cfg.unlink_component(comp)
        self.reg.forget(cid)
        msgs.append("Пакеты не удалены: они могут быть нужны другим программам (dnf remove вручную).")
        return msgs

    def activate(self, cid: str) -> dict:
        """Включает компонент и применяет его способом из манифеста. Не перезапускает рабочий стол."""
        comp = self.reg.get(cid)
        if not self.reg.is_installed(cid):
            raise RuntimeError(f"{cid} не установлен")
        self.reg.mark(cid, enabled=True)
        return self._apply_activation(comp)

    def deactivate(self, cid: str) -> dict:
        comp = self.reg.get(cid)
        if not self.reg.is_installed(cid):
            raise RuntimeError(f"{cid} не установлен")
        self.reg.mark(cid, enabled=False)
        return self._apply_activation(comp)

    def _apply_activation(self, comp) -> dict:
        mode = comp.activation
        env = self.ctx.env
        if mode == "quickshell-restart":
            sh = ShellManager(self.ctx)
            if sh.running_pid(env):
                sh.restart()
                return {"hot": True, "message": "Quickshell перезапущен, изменения применены без перезапуска сессии."}
            return {"hot": False, "message": "Оболочка сейчас не запущена: изменения применятся при её запуске."}
        if mode == "hyprland-reload":
            if env.get("HYPRLAND_INSTANCE_SIGNATURE") and self.ctx.runner.which("hyprctl"):
                self.ctx.runner.run(["hyprctl", "reload"], env=env, timeout=10)
                return {"hot": True, "message": "Выполнен hyprctl reload."}
            return {"hot": False, "message": "Hyprland сейчас не запущен: изменения применятся при следующем запуске."}
        if mode == "relogin":
            return {"hot": False, "message": "Нужен перезапуск сессии (выход и вход). Автоматически не выполняется."}
        return {"hot": False, "message": "Дополнительных действий не требуется."}
