"""Командная строка hyprown. Все команды работают поверх общих модулей пакета.

Правила для вызывающих (люди, Manager, другие ИИ):
  --json         итоговый результат одним JSON-документом (команды чтения);
  --json-stream  события построчно (JSONL) для длинных операций (install);
  --yes          заранее данное подтверждение: без него команды, меняющие систему,
                 спрашивают в терминале или отказывают, если терминала нет;
  --dry-run      только показать план, ничего не менять.
Коды выхода: 0 успех, 1 ошибка выполнения, 2 план содержит проблемы/неверные аргументы,
3-5 окружение не готово (нет сессии, нет Quickshell, нет shell.qml).
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__, TESTED_FEDORA, TESTED_HYPRLAND
from .config import ConfigManager, PERF_PROFILES
from .context import Ctx
from .diagnostics import run_all, summarize
from .installer import Installer, Options
from .manifest import approve
from .recovery import RecoveryManager
from .registry import Registry
from .runner import Runner
from .session import SessionManager
from .shell import ShellManager
from .system import detect
from .ui import JsonUI, UI
from .updater import UpdateManager


def emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def make_logger(ctx: Ctx):
    def log(msg: str):
        try:
            ctx.log_dir.mkdir(parents=True, exist_ok=True)
            with open(ctx.log_dir / "hyprown.log", "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%F %T')} {msg}\n")
        except OSError:
            pass
    return log


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-y", "--yes", action="store_true", help="подтвердить действия заранее")
    common.add_argument("--dry-run", action="store_true", help="ничего не менять, показать план")
    common.add_argument("--plain", action="store_true", help="без цвета и анимации")
    common.add_argument("--json", action="store_true", help="результат в JSON")
    common.add_argument("--json-stream", action="store_true", help="события JSON построчно")

    p = argparse.ArgumentParser(prog="hyprown", description="HyprlandOwn: установщик и менеджер компонентов",
                                parents=[common])
    sub = p.add_subparsers(dest="cmd", metavar="команда")

    def add(name, help_, **kw):
        return sub.add_parser(name, help=help_, parents=[common], **kw)

    s = add("install", "установка окружения (интерактивное меню)")
    s.add_argument("--components", help="id через запятую (по умолчанию: меню)")
    s.add_argument("--minimal", action="store_true", help="только обязательные пакеты")
    s.add_argument("--no-copr", action="store_true", help="не подключать сторонние репозитории")
    s.add_argument("--live-ok", action="store_true", help="согласен с ограничениями Live USB")
    s.add_argument("--no-launch", action="store_true", help="не предлагать запуск после установки")
    add("plan", "показать план установки, ничего не меняя").add_argument("--components")
    add("status", "сводка для Dashboard")
    add("doctor", "диагностика окружения")
    add("deps", "зависимости и недостающие пакеты")
    c = add("component", "управление компонентами")
    c.add_argument("action", choices=["list", "info", "plan", "install", "remove", "enable", "disable"])
    c.add_argument("id", nargs="?")
    add("preview", "Preview Mode: Hyprland окном внутри KDE")
    d = add("desktop", "готовность и запуск Desktop Mode")
    d.add_argument("--logout-prompt", action="store_true", help="открыть штатный диалог выхода KDE")
    sh = add("shell", "супервизор Quickshell")
    sh.add_argument("action", choices=["run", "start", "stop", "restart", "status", "probe"])
    ip = add("ipc", "вызов IPC оболочки: ipc canvas toggleEdit")
    ip.add_argument("args", nargs=argparse.REMAINDER)
    add("manager", "открыть HyprlandOwn Manager")
    cf = add("config", "конфигурации")
    cf.add_argument("action", choices=["link", "unlink", "rollback", "render", "verify", "status", "fingerprint"])
    cf.add_argument("--mode", default="desktop", choices=["desktop", "preview"])
    u = add("update", "обновление проекта")
    u.add_argument("action", choices=["check", "apply", "reload"])
    r = add("recovery", "восстановление")
    r.add_argument("action", choices=["list", "snapshot", "restore", "rollback", "safe-mode", "reset-shell"])
    r.add_argument("arg", nargs="?")
    pf = add("perf", "профиль производительности")
    pf.add_argument("action", choices=["get", "set"])
    pf.add_argument("profile", nargs="?", choices=sorted(PERF_PROFILES))
    add("trust", "одобрить недоверенный манифест после просмотра").add_argument("id")
    add("version", "версия")
    return p


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:  # консоль Windows (cp1251) не знает галочек: вывод всегда UTF-8
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 2
    if args.json_stream:
        ui = JsonUI(assume_yes=args.yes)
    else:
        ui = UI(assume_yes=args.yes, color=False if args.plain else None)
    ctx = Ctx.from_env(runner=Runner(dry_run=args.dry_run), ui=ui)
    ctx.runner.log = make_logger(ctx)
    try:
        handler = HANDLERS[args.cmd]
        return handler(ctx, args)
    except KeyboardInterrupt:
        ctx.ui.error("Прервано пользователем.")
        return 130
    except (FileNotFoundError, RuntimeError, KeyError, ValueError, FileExistsError) as exc:
        ctx.ui.error(str(exc.args[0] if isinstance(exc, KeyError) and exc.args else exc))
        return 1


def _registry(ctx: Ctx) -> Registry:
    reg = Registry(ctx)
    for e in reg.errors:
        ctx.ui.warn("Манифест пропущен: " + e)
    return reg


# ---------------------------------------------------------------- install
def _show_system(ctx, info):
    ui = ctx.ui
    ui.title("Ваша система")
    ui.info(f"ОС:            {info.pretty_name or info.os_id or 'не определена'} ({info.arch})")
    ui.info(f"Режим:         {'Live USB (изменения временные)' if info.is_live else 'установленная система'}")
    ui.info(f"Сессия:        {info.session_type or '?'} / {info.desktop or '?'}")
    ui.info(f"Видеокарта:    {', '.join(info.gpus) or 'не определена'}")
    ui.info(f"Свободно:      {info.free_home_mb} МБ" + (f"   (виртуальная машина: {info.in_vm})" if info.in_vm else ""))


def cmd_install(ctx, args) -> int:
    ui = ctx.ui
    ui.banner()
    info = detect(ctx)
    _show_system(ctx, info)
    reg = _registry(ctx)
    inst = Installer(ctx, reg, info)
    if args.components:
        ids = [x.strip() for x in args.components.split(",") if x.strip()]
    else:
        items = [(c.id, f"{c.name}: {c.summary}", c.id in inst.default_selection())
                 for c in reg.components.values() if c.approved]
        ids = ui.choose_many("Что установить?", items)
        if not ids:
            ui.info("Ничего не выбрано.")
            return 0
    opts = Options(components=ids, minimal=args.minimal, no_copr=args.no_copr, live_ok=args.live_ok)
    plan = inst.build_plan(opts)
    inst.show_plan(plan)
    if args.json_stream:
        ui.event("plan", plan=plan.to_dict())
    if plan.problems:
        return 2
    if args.dry_run:
        ui.info("")
        ui.ok("dry-run: ничего не изменено.")
        return 0
    if not ui.confirm("Применить этот план?", default=True):
        ui.info("Отменено. Ничего не изменено.")
        return 0
    rep = inst.apply(plan, opts)
    return _finish_install(ctx, args, reg, rep)


def _finish_install(ctx, args, reg, rep) -> int:
    ui = ctx.ui
    ui.title("Результат")
    for cid in rep.installed:
        ui.ok(f"{reg.components[cid].name}: установлен")
    for cid, why in rep.failed.items():
        ui.error(f"{reg.components[cid].name}: {why}")
    for cid, why in rep.skipped.items():
        ui.warn(f"{cid}: пропущен ({why})")
    for w in rep.warnings:
        ui.warn(w)
    if rep.installed:
        ui.title("Проверка")
        problems = [c for c in run_all(ctx, reg) if c["status"] in ("fail",) and
                    not c["id"].startswith("pkg-") or (c["id"].startswith("link-") and c["status"] != "ok")]
        if problems:
            for c in problems:
                ui.error(f"{c['title']}: {c['detail']}")
        else:
            ui.ok("Ссылки на конфиги, shell.qml и синтаксис конфига в порядке.")
        ui.info("Журнал отката: " + (rep.journal or "-") + "  (откат: hyprown recovery rollback)")
        if ctx.bin_dir.as_posix() not in ctx.env.get("PATH", ""):
            ui.warn(f"{ctx.bin_dir} нет в PATH: используйте {ctx.repo / 'bin' / 'hyprown'} либо добавьте каталог в PATH.")
    if args.json_stream:
        ui.event("result", **rep.to_dict())
    if rep.installed and not getattr(args, "no_launch", False) and not args.json_stream:
        ui.title("Что дальше")
        ui.info("Предпросмотр: bin/hyprown preview   (окно Hyprland внутри KDE)")
        ui.info("Полный рабочий стол: bin/hyprown desktop   (вход через экран SDDM)")
        ui.info("Менеджер компонентов: bin/hyprown manager")
        if ui.interactive and ui.confirm("Запустить Preview сейчас?", default=True):
            return SessionManager(ctx).preview()
    return 0 if rep.ok else 1


def cmd_plan(ctx, args) -> int:
    reg = _registry(ctx)
    inst = Installer(ctx, reg)
    ids = [x for x in (args.components or "").split(",") if x] or None
    plan = inst.build_plan(Options(components=ids))
    if args.json:
        emit(plan.to_dict())
    else:
        inst.show_plan(plan)
    return 2 if plan.problems else 0


# ---------------------------------------------------------------- чтение
def cmd_status(ctx, args) -> int:
    reg = _registry(ctx)
    info = detect(ctx)
    cfg, sh, rec, sess = ConfigManager(ctx), ShellManager(ctx), RecoveryManager(ctx, reg), SessionManager(ctx)
    data = {"version": __version__, "tested": {"fedora": TESTED_FEDORA, "hyprland": TESTED_HYPRLAND},
            "system": info.to_dict(), "components": reg.listing(), "manifest_errors": reg.errors,
            "performance": cfg.perf_profile(), "safe_mode_forced": rec.safe_mode(),
            "shell": sh.status(), "in_hyprland": sess.in_hyprland(),
            "preview_running": bool(sess.preview_running())}
    if args.json:
        emit(data)
    else:
        ui = ctx.ui
        ui.title(f"HyprlandOwn {__version__}")
        ui.table([[c["id"], c["version"], "установлен" if c["installed"] else "нет",
                   "включён" if c["enabled"] else "выключен"] for c in data["components"]],
                 ["Компонент", "Версия", "Состояние", "Активность"])
    return 0


def cmd_doctor(ctx, args) -> int:
    reg = _registry(ctx)
    checks = run_all(ctx, reg)
    if args.json:
        emit({"checks": checks, "summary": summarize(checks)})
    else:
        ui = ctx.ui
        ui.title("Диагностика")
        for c in checks:
            line = f"{c['title']}: {c['detail']}" if c["detail"] else c["title"]
            {"ok": ui.ok, "warn": ui.warn, "fail": ui.error, "skip": lambda t: ui.info("· " + t)}[c["status"]](line)
            if c["fix"] and c["status"] in ("warn", "fail"):
                ui.info("    что делать: " + c["fix"])
        s = summarize(checks)
        ui.info("")
        ui.info(f"Итого: ок {s['ok']}, предупреждений {s['warn']}, ошибок {s['fail']}, пропущено {s['skip']}")
    return 1 if summarize(checks)["fail"] else 0


def cmd_deps(ctx, args) -> int:
    from .pkg import DnfAdapter
    reg = _registry(ctx)
    pm = DnfAdapter(ctx)
    rows = []
    for pid, pkg in reg.packages.items():
        users = [c.id for c in reg.components.values()
                 if pid in c.pkg_required + c.pkg_recommended + [x for v in c.pkg_gpu.values() for x in v]]
        present = pm.present(pkg)
        rows.append({"id": pid, "rpm": pkg.rpm, "description": pkg.description, "installed": bool(present),
                     "version": pm.version(pkg) if present else "", "used_by": users,
                     "copr": [s["id"] for s in pkg.sources]})
    if args.json:
        emit({"packages": rows})
    else:
        ctx.ui.title("Зависимости")
        ctx.ui.table([[r["id"], "есть" if r["installed"] else "НЕТ", r["version"] or "-", ", ".join(r["used_by"]) or "-"]
                      for r in rows], ["Пакет", "Состояние", "Версия", "Нужен компонентам"])
    return 0


# ---------------------------------------------------------------- компоненты
def cmd_component(ctx, args) -> int:
    reg = _registry(ctx)
    inst = Installer(ctx, reg)
    act = args.action
    if act == "list":
        data = reg.listing()
        if args.json:
            emit({"components": data})
        else:
            ctx.ui.table([[d["id"], d["kind"], d["version"], "установлен" if d["installed"] else "-",
                           "вкл" if d["enabled"] else "выкл", "" if d["trusted"] else "недоверенный"] for d in data],
                         ["ID", "Тип", "Версия", "Состояние", "Активность", "Доверие"])
        return 0
    if not args.id:
        ctx.ui.error("Нужен id компонента")
        return 2
    comp = reg.get(args.id)
    if act == "info":
        d = next(x for x in reg.listing() if x["id"] == args.id)
        emit(d) if args.json else [ctx.ui.info(f"{k}: {v}") for k, v in d.items()]
        return 0
    if act == "plan":
        plan = inst.build_plan(Options(components=[args.id]))
        emit(plan.to_dict()) if args.json else inst.show_plan(plan)
        return 2 if plan.problems else 0
    if act == "install":
        opts = Options(components=[args.id], live_ok=args.yes)
        plan = inst.build_plan(opts)
        inst.show_plan(plan)
        if plan.problems:
            return 2
        if args.dry_run:
            return 0
        if not ctx.ui.confirm(f"Установить {comp.name}?", default=True):
            return 0
        rep = inst.apply(plan, opts)
        code = _finish_install(ctx, args, reg, rep)
        if rep.ok and rep.installed:
            ctx.ui.info("Активация: hyprown component enable " + args.id)
        return code
    if act == "remove":
        if not ctx.ui.confirm(f"Удалить {comp.name}? (пакеты останутся)", default=False):
            return 0
        for m in inst.remove(args.id):
            ctx.ui.info(m)
        return 0
    res = inst.activate(args.id) if act == "enable" else inst.deactivate(args.id)
    emit(res) if args.json else ctx.ui.info(res["message"])
    return 0


# ---------------------------------------------------------------- сессии и shell
def cmd_preview(ctx, args) -> int:
    return SessionManager(ctx).preview()


def cmd_desktop(ctx, args) -> int:
    sess = SessionManager(ctx)
    checks = sess.desktop_readiness()
    if args.json:
        emit({"ready": all(c["ok"] for c in checks), "checks": checks, "steps": sess.desktop_instructions()})
        return 0
    ui = ctx.ui
    ui.title("Desktop Mode")
    for c in checks:
        (ui.ok if c["ok"] else ui.error)(c["title"] + ("" if c["ok"] else f": нужно `{c['fix']}`"))
    for line in sess.desktop_instructions():
        ui.info(line)
    if args.logout_prompt and ui.confirm("Открыть диалог выхода KDE?", default=False):
        return sess.logout_prompt()
    return 0 if all(c["ok"] for c in checks) else 1


def cmd_shell(ctx, args) -> int:
    sh = ShellManager(ctx)
    sess = SessionManager(ctx)
    env = sess.hypr_env()
    if args.action == "run":
        return sh.run(env)
    if args.action == "start":
        return sh.start_detached(env)
    if args.action == "stop":
        ctx.ui.info("остановлен" if sh.stop(env) else "не был запущен")
        return 0
    if args.action == "restart":
        return sh.restart(env)
    if args.action == "status":
        st = sh.status(env)
        emit(st) if args.json else [ctx.ui.info(f"{k}: {v}") for k, v in st.items()]
        return 0
    caps = sh.probe()
    emit(caps.to_dict())
    return 0 if caps.binary else 4


def cmd_ipc(ctx, args) -> int:
    return ShellManager(ctx).ipc(args.args, SessionManager(ctx).hypr_env())


def cmd_manager(ctx, args) -> int:
    return ShellManager(ctx).open_manager()


# ---------------------------------------------------------------- конфиги и сервис
def cmd_config(ctx, args) -> int:
    reg = _registry(ctx)
    cfg = ConfigManager(ctx)
    act = args.action
    comps = [c for c in reg.components.values() if c.links and c.approved]
    if act == "link":
        rec = RecoveryManager(ctx, reg)
        j = rec.new_journal("link")
        for comp in comps:
            if comp.id in ("hyprpaper", "hyprlock"):
                continue
            if args.dry_run:
                for ls in cfg.link_states(comp):
                    ctx.ui.info(f"[dry-run] {ls.dst} -> {ls.src}: {ls.state}")
            else:
                for ls in cfg.apply_links(comp, j["ops"]):
                    ctx.ui.ok(f"{ls.dst}: {ls.detail or 'уже настроено'}")
        if j["ops"] and not args.dry_run:
            rec.save_journal(j)
        return 0
    if act == "unlink":
        for comp in comps:
            for m in cfg.unlink_component(comp):
                ctx.ui.info(m)
        return 0
    if act == "rollback":
        for m in RecoveryManager(ctx, reg).rollback():
            ctx.ui.info(m)
        return 0
    if act == "render":
        out = cfg.render(args.mode, ctx.state_dir / "rendered" if args.mode == "desktop" else ctx.runtime_dir / "preview")
        print(out)
        return 0
    if act == "verify":
        ok, text = cfg.verify()
        (ctx.ui.ok if ok else ctx.ui.error)(text)
        for line in cfg.lint():
            ctx.ui.warn(line)
        return 0 if ok else 1
    if act == "fingerprint":
        ours, why = cfg.uses_our_config(SessionManager(ctx).hypr_env())
        emit({"ours": ours, "detail": why}) if args.json else (ctx.ui.ok if ours else ctx.ui.error)(why)
        return 0 if ours else (3 if ours is None else 1)
    for comp in comps:
        for ls in cfg.link_states(comp):
            ctx.ui.info(f"{ls.name}: {ls.state}  {ls.dst} -> {ls.src}")
    return 0


def cmd_update(ctx, args) -> int:
    reg = _registry(ctx)
    um = UpdateManager(ctx, reg)
    if args.action == "reload":
        for m in um.hot_reload():
            ctx.ui.ok(m)
        return 0
    if args.action == "apply" and not ctx.ui.confirm("Обновить проект из Git (fast-forward)?", default=True):
        return 0
    res = um.check() if args.action == "check" else um.apply()
    emit(res) if args.json else [ctx.ui.info(f"{k}: {v}") for k, v in res.items() if v not in ("", [], None)]
    return 0 if res.get("ok", True) else 1


def cmd_recovery(ctx, args) -> int:
    reg = _registry(ctx)
    rec = RecoveryManager(ctx, reg)
    act = args.action
    if act == "list":
        data = {"snapshots": rec.snapshots(), "installs": [{"id": j["id"], "ok": j.get("ok"), "components": j.get("components"),
                                                           "rolled_back": j.get("rolled_back", False)} for j in rec.journals()],
                "safe_mode_forced": rec.safe_mode()}
        emit(data) if args.json else emit(data)
    elif act == "snapshot":
        ctx.ui.ok("Снимок: " + str(rec.snapshot(args.arg or "manual")))
    elif act == "restore":
        if not args.arg:
            ctx.ui.error("Нужен id снимка (recovery list)")
            return 2
        for f in rec.restore_snapshot(args.arg):
            ctx.ui.ok("восстановлено: " + f)
    elif act == "rollback":
        if not ctx.ui.confirm("Откатить последнюю установку (ссылки конфигов вернутся к сохранённым копиям)?", default=False):
            return 0
        for m in rec.rollback(args.arg):
            ctx.ui.info(m)
    elif act == "safe-mode":
        if args.arg not in ("on", "off"):
            ctx.ui.info("Принудительный safe-режим: " + ("включён" if rec.safe_mode() else "выключен") + ". Команда: safe-mode on|off")
        else:
            rec.set_safe_mode(args.arg == "on")
            ctx.ui.ok("Следующий вход в Hyprland будет в safe-режиме." if args.arg == "on" else "Принудительный safe-режим выключен.")
    elif act == "reset-shell":
        for m in rec.reset_shell_state():
            ctx.ui.info(m)
    return 0


def cmd_perf(ctx, args) -> int:
    cfg = ConfigManager(ctx)
    if args.action == "get" or not args.profile:
        emit({"profile": cfg.perf_profile(), "available": sorted(PERF_PROFILES)}) if args.json else ctx.ui.info(cfg.perf_profile())
        return 0
    RecoveryManager(ctx, Registry(ctx)).snapshot("before-perf")
    cfg.set_perf_profile(args.profile)
    msgs = UpdateManager(ctx, Registry(ctx)).hot_reload() if ctx.env.get("HYPRLAND_INSTANCE_SIGNATURE") else []
    ctx.ui.ok(f"Профиль {args.profile} записан." + (" Применено без перезапуска сессии." if msgs else " Применится при запуске Hyprland или hyprctl reload."))
    return 0


def cmd_trust(ctx, args) -> int:
    reg = _registry(ctx)
    comp = reg.get(args.id)
    if comp.trusted:
        ctx.ui.info("Компонент из доверенного каталога проекта: одобрение не нужно.")
        return 0
    ctx.ui.info(f"Манифест: {comp.path}\nsha256: {comp.sha256}\nОн описывает: {comp.summary}\nРазрешения: {', '.join(comp.permissions) or '-'}")
    if ctx.ui.confirm("Вы прочитали манифест и доверяете ему?", default=False):
        approve(ctx, comp)
        ctx.ui.ok("Одобрено для текущего содержимого. Изменение файла снимет одобрение.")
    return 0


def cmd_version(ctx, args) -> int:
    print(f"hyprown {__version__} (проверялось: Fedora {TESTED_FEDORA}, Hyprland {TESTED_HYPRLAND})")
    return 0


HANDLERS = {
    "install": cmd_install, "plan": cmd_plan, "status": cmd_status, "doctor": cmd_doctor, "deps": cmd_deps,
    "component": cmd_component, "preview": cmd_preview, "desktop": cmd_desktop, "shell": cmd_shell,
    "ipc": cmd_ipc, "manager": cmd_manager, "config": cmd_config, "update": cmd_update,
    "recovery": cmd_recovery, "perf": cmd_perf, "trust": cmd_trust, "version": cmd_version,
}
