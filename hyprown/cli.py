"""Командная строка hyprown. Все команды работают поверх общих модулей пакета.

Правила для вызывающих (люди, Manager, другие ИИ):
  --json         итоговый результат одним JSON-документом (команды чтения);
  --json-stream  события построчно (JSONL) для длинных операций (install);
  --yes          заранее данное подтверждение: без него команды, меняющие систему,
                 спрашивают в терминале или отказывают, если терминала нет;
  --dry-run      только показать план, ничего не менять.
Коды выхода: 0 успех, 1 ошибка выполнения, 2 план содержит проблемы/неверные аргументы,
3-5 окружение не готово (нет сессии, нет Quickshell, нет shell.qml), 6 Attach недоступен
(терминал в KDE или другой не-Hyprland сессии).
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time

from . import __version__, TESTED_FEDORA, TESTED_HYPRLAND
from .attach import AttachEngine, EXIT_UNAVAILABLE
from .config import ConfigManager, PERF_PROFILES
from .context import Ctx
from .diagnostics import run_all, summarize
from .installer import Installer, Options
from .keybinds import KeyManager, combo_text, render_default, validate_registry
from .manifest import approve
from .menu import run_menu
from .procman import ProcessManager
from .recovery import RecoveryManager
from .registry import Registry
from .runner import Runner
from .session import SessionManager
from .sessenv import detect_environment
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
    def make_common(sub: bool) -> argparse.ArgumentParser:
        """Общие флаги. У подкоманд значение по умолчанию SUPPRESS: иначе `--yes install` затирал бы
        `--yes`, заданный ДО имени команды (argparse копирует значения подпарсера поверх основных)."""
        c = argparse.ArgumentParser(add_help=False)
        d = {"default": argparse.SUPPRESS} if sub else {}
        c.add_argument("-y", "--yes", action="store_true", help="подтвердить действия заранее", **d)
        c.add_argument("--dry-run", action="store_true", help="ничего не менять, показать план", **d)
        c.add_argument("--plain", action="store_true", help="без цвета и анимации", **d)
        c.add_argument("--json", action="store_true", help="результат в JSON", **d)
        c.add_argument("--json-stream", action="store_true", help="события JSON построчно", **d)
        return c

    common, sub_common = make_common(False), make_common(True)

    p = argparse.ArgumentParser(prog="hyprown", description="HyprlandOwn: установщик и менеджер компонентов",
                                parents=[common])
    sub = p.add_subparsers(dest="cmd", metavar="команда")

    def add(name, help_, **kw):
        return sub.add_parser(name, help=help_, parents=[sub_common], **kw)

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
    at = add("attach", "подключить HyprlandOwn к текущей сессии Hyprland (без второго композитора)")
    at.add_argument("--instance", help="сигнатура экземпляра Hyprland (если терминал не внутри него)")
    at.add_argument("--no-config", action="store_true", help="не ставить пакеты и не менять ссылки конфигов")
    dt = add("detach", "отключить компоненты проекта, не закрывая Hyprland")
    dt.add_argument("--restore-config", action="store_true", help="вернуть конфиги из резервных копий Attach")
    dt.add_argument("--instance")
    se = add("session", "процессы HyprlandOwn в текущей сессии")
    se.add_argument("action", choices=["status", "start-all", "restart-all", "stop-all"])
    se.add_argument("--instance")
    ky = add("keys", "горячие клавиши: реестр, конфликты, переназначение")
    ky.add_argument("action", choices=["list", "check", "live", "set", "unbind", "reset", "render", "apply", "verify"])
    ky.add_argument("id", nargs="?", help="id привязки (keys list)")
    ky.add_argument("--mods", help='модификаторы, например "SUPER SHIFT"')
    ky.add_argument("--key", help="клавиша Hyprland, например X, RETURN, F5")
    ky.add_argument("--mode", default="desktop", choices=["desktop", "preview"])
    ky.add_argument("--force", action="store_true", help="назначить несмотря на предупреждения")
    ky.add_argument("--write", action="store_true", help="keys render: записать hypr/keybinds.conf")
    ky.add_argument("--apply", action="store_true", help="сразу применить к запущенной сессии")
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
    ctx.ui.banner()
    if not args.components and ctx.ui.interactive and not (args.json_stream or args.dry_run or args.yes):
        return run_menu(ctx, args, _install_flow)
    return _install_flow(ctx, args)


def _install_flow(ctx, args) -> int:
    ui = ctx.ui
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
            "preview_running": bool(sess.preview_running()),
            "environment": detect_environment(ctx).to_dict(),
            "session_units": ProcessManager(ctx, sh).status(sess.hypr_env())}
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
    pm = ProcessManager(ctx, sh)
    if args.action in ("start", "stop", "restart"):
        rows = {"start": pm.start_all, "stop": pm.stop_all, "restart": pm.restart_all}[args.action](env)
        return _report_rows(ctx, rows, args)
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
        env_info = detect_environment(ctx)
        env = env_info.target_env(ctx.env) if env_info.instance else SessionManager(ctx).hypr_env()
        ours, why = cfg.uses_our_config(env)
        inst = env.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        if args.json:
            emit({"ours": ours, "detail": why, "environment": env_info.kind, "instance": inst})
        else:
            (ctx.ui.ok if ours else ctx.ui.error)(why + (f" [экземпляр {inst}]" if inst else ""))
        return 0 if ours else (3 if ours is None else 1)
    for comp in comps:
        for ls in cfg.link_states(comp):
            ctx.ui.info(f"{ls.name}: {ls.state}  {ls.dst} -> {ls.src}")
    return 0


# ---------------------------------------------------------------- Attach, сессия, клавиши
def _quiet(ctx, args) -> None:
    """--json: результат единым документом, текстовые сообщения шагов не смешиваются с ним."""
    if args.json:
        ctx.ui = UI(assume_yes=args.yes, color=False, stream=io.StringIO(), interactive=False)


def _report_rows(ctx, rows: list[dict], args) -> int:
    if args.json:
        emit({"results": rows})
    else:
        for r in rows:
            (ctx.ui.ok if r["result"] in ("started", "already", "stopped", "absent") else ctx.ui.error)(
                f"{r['id']}: {r['detail']}")
    bad = [r for r in rows if r["result"] in ("failed", "throttled", "blocked")]
    if any(r["result"] == "blocked" and "Wayland" in r["detail"] for r in bad):
        return 3
    return 1 if bad else 0


def cmd_attach(ctx, args) -> int:
    _quiet(ctx, args)
    rep = AttachEngine(ctx, Registry(ctx)).attach(args.instance, args.no_config)
    if args.json:
        emit(rep.to_dict())
    return rep.code


def cmd_detach(ctx, args) -> int:
    _quiet(ctx, args)
    rep = AttachEngine(ctx, Registry(ctx)).detach(args.restore_config, args.instance)
    if args.json:
        emit(rep.to_dict())
    return rep.code


def cmd_session(ctx, args) -> int:
    _quiet(ctx, args)
    eng = AttachEngine(ctx, Registry(ctx))
    if args.action == "status":
        data = eng.session_status(args.instance)
        if args.json:
            emit(data)
        else:
            eng.show_status(data)
        return 0
    env_info = detect_environment(ctx, args.instance)
    if args.action != "stop-all" and not env_info.can_attach:
        ctx.ui.error(env_info.attach_block)
        if args.json:
            emit({"results": [], "error": env_info.attach_block})
        return EXIT_UNAVAILABLE if env_info.kind in ("kde", "other") else 3
    pm = eng.proc
    env = env_info.target_env(ctx.env)
    rows = {"start-all": pm.start_all, "restart-all": pm.restart_all, "stop-all": pm.stop_all}[args.action](env)
    return _report_rows(ctx, rows, args)


def _keys_env(ctx):
    """Окружение живой сессии для hyprctl и описание среды; env=None, если Hyprland не найден."""
    info = detect_environment(ctx)
    if info.instance:
        return info.target_env(ctx.env), info
    env = SessionManager(ctx).hypr_env()
    return (env, info) if env.get("HYPRLAND_INSTANCE_SIGNATURE") else (None, info)


def apply_keys(ctx, km: KeyManager) -> int:
    """Применяет сохранённые клавиши к запущенной сессии. Чужие привязки без разрешения не снимаются."""
    ui = ctx.ui
    env, info = _keys_env(ctx)
    if env is None:
        ui.info("Hyprland сейчас не запущен: клавиши применятся при его запуске (keybinds.user.conf).")
        return 0
    mode = "preview" if info.kind == "preview" else "desktop"
    if info.ours or info.kind == "preview":
        ctx.runner.run(["hyprctl", "reload"], env=env, timeout=15)
        ui.ok("hyprctl reload выполнен: сессия использует конфиг проекта, клавиши перечитаны.")
        return 0
    live = km.live(env, mode)
    clash = km.would_replace(live)
    if clash:
        ui.warn("Сессия запущена не на конфиге проекта. Эти комбинации сейчас делают другое:")
        for i in clash:
            ui.info(f"  {i['combo']}: {i['detail']}")
        if not ui.confirm("Заменить их нашими привязками через IPC (временно, до hyprctl reload)?", default=False, yes_ok=True):
            ui.info("Отменено: чужие привязки не тронуты.")
            return 0
    res = km.apply_live(env, mode)
    for e in res["errors"]:
        ui.error(e)
    (ui.ok if not res["errors"] else ui.warn)(f"Через IPC назначено привязок: {res['bound']}")
    return 1 if res["errors"] else 0


def cmd_keys(ctx, args) -> int:
    ui = ctx.ui
    km = KeyManager(ctx)
    act = args.action
    if act == "render":
        text = km.render_files(write=args.write)
        if args.write:
            ui.ok(f"Записан {km.default_conf_path()}")
        else:
            print(text, end="")
        return 0
    if act == "verify":
        problems = validate_registry(km.binds)
        gen = km.default_conf_path()
        if not gen.exists() or gen.read_text(encoding="utf-8") != render_default(km.binds):
            problems.append("hypr/keybinds.conf не совпадает с реестром: выполните `hyprown keys render --write`")
        if args.json:
            emit({"ok": not problems, "problems": problems})
        else:
            for p in problems:
                ui.error(p)
            if not problems:
                ui.ok(f"Реестр клавиш в порядке ({len(km.binds)} привязок, дублей и перехвата KDE нет).")
        return 2 if problems else 0
    if act == "list":
        rows = km.listing(args.mode)
        if args.json:
            emit({"mode": args.mode, "binds": rows, "registry_problems": validate_registry(km.binds),
                  "user_conf_hand_edited": km.user_conf_hand_edited()})
        else:
            ui.table([[r["id"], r["combo"] + (" *" if r["overridden"] else ""),
                       "отключена" if r["disabled"] else r["default"], r["title"]] for r in rows],
                     ["ID", "Сейчас", "По умолчанию", "Действие"])
            ui.info("* переназначено пользователем")
        return 0
    if act == "live":
        env, info = _keys_env(ctx)
        if env is None:
            ui.error("Запущенный Hyprland не найден (или экземпляров несколько): сверять нечего.")
            return 3
        rep = km.live(env, "preview" if info.kind == "preview" else "desktop")
        if args.json:
            emit(rep)
        elif rep["ok"] is None:
            ui.error(rep["error"])
        else:
            for i in rep["items"]:
                if i["status"] != "ok":
                    ui.error(f"{i['combo']}: {i['detail']}" + ("   <-- ВЫХОД ИЗ СЕССИИ" if i["danger"] else ""))
            for x in rep["extras"]:
                ui.info(f"чужая привязка {x['combo']}: {x['action']}" +
                        ("  (стандартная Hyprland)" if x["hyprland_default"] else ""))
            if rep["ok"]:
                ui.ok("Все привязки реестра действуют в запущенной сессии.")
        return 3 if rep["ok"] is None else (0 if rep["ok"] else 1)
    if act == "apply":
        return apply_keys(ctx, km)
    if act == "reset":
        for m in km.reset(args.id):
            ui.ok(m)
        return apply_keys(ctx, km) if args.apply else 0
    if not args.id:
        ui.error("Нужен id привязки (список: hyprown keys list)")
        return 2
    if act == "unbind":
        ok, msgs = km.disable(args.id, args.force)
        for m in msgs:
            (ui.ok if ok else ui.error)(m)
        return (apply_keys(ctx, km) if args.apply else 0) if ok else 2
    if args.mods is None or not args.key:
        ui.error('Нужны --mods "SUPER SHIFT" (можно пустые: "") и --key КЛАВИША')
        return 2
    if act == "check":
        cs = km.check(args.mods, args.key, args.id)
        if args.json:
            emit({"ok": not any(c.level == "error" for c in cs), "conflicts": [c.to_dict() for c in cs]})
        else:
            for c in cs:
                (ui.error if c.level == "error" else ui.warn)(c.message)
            if not cs:
                ui.ok(f"{combo_text(args.mods, args.key)}: конфликтов нет")
        return 2 if any(c.level == "error" for c in cs) else 0
    ok, msgs = km.set(args.id, args.mods, args.key, args.force)
    for m in msgs:
        (ui.ok if ok else ui.error)(m)
    if not ok:
        return 2
    return apply_keys(ctx, km) if args.apply else 0


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
    "ipc": cmd_ipc, "manager": cmd_manager, "attach": cmd_attach, "detach": cmd_detach,
    "session": cmd_session, "keys": cmd_keys, "config": cmd_config, "update": cmd_update,
    "recovery": cmd_recovery, "perf": cmd_perf, "trust": cmd_trust, "version": cmd_version,
}
