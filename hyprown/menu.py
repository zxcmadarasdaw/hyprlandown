"""Главное меню установщика. Показывает только действия, применимые к ТЕКУЩЕМУ окружению.

Внутри Hyprland первым предлагается «Подключить HyprlandOwn к текущей сессии Hyprland».
В KDE этого пункта нет, а вместо него выводится объяснение, почему подключение недоступно.
"""

from __future__ import annotations

from .attach import AttachEngine
from .context import Ctx
from .procman import ProcessManager
from .registry import Registry
from .sessenv import Environment, detect_environment
from .shell import ShellManager

LABELS = {
    "attach": "Подключить HyprlandOwn к текущей сессии Hyprland",
    "install": "Установить недостающие компоненты",
    "start": "Запустить отсутствующие процессы",
    "restart": "Перезапустить компоненты HyprlandOwn",
    "manager": "Открыть HyprlandOwn Manager",
    "status": "Проверить состояние",
    "restore": "Восстановить стандартный Hyprland",
    "preview": "Запустить Preview (окно Hyprland внутри KDE)",
    "exit": "Выйти",
}


def applicable(ctx: Ctx, env: Environment, units: list, attach_state: dict) -> list[str]:
    """Идентификаторы пунктов меню в порядке показа."""
    ids = []
    procs = [u for u in units if u["kind"] == "process"]
    if env.can_attach:
        ids.append("attach")
    ids.append("install")
    if env.can_attach and any(u["state"] == "stopped" for u in procs):
        ids.append("start")
    if env.can_attach and any(u["state"] == "running" for u in procs):
        ids.append("restart")
    if env.kind != "none" and (ctx.runner.which("qs") or ctx.runner.which("quickshell")):
        ids.append("manager")
    ids.append("status")
    if env.can_attach and (attach_state.get("attached") or attach_state.get("journals")):
        ids.append("restore")
    if env.kind in ("kde", "other"):
        ids.append("preview")
    ids.append("exit")
    return ids


def run_menu(ctx: Ctx, args, install_flow) -> int:
    """Цикл меню. install_flow(ctx, args): прежний мастер выбора компонентов и установки."""
    ui = ctx.ui
    reg = Registry(ctx)
    procman = ProcessManager(ctx)
    engine = AttachEngine(ctx, reg, procman)
    while True:
        env = detect_environment(ctx)
        units = procman.status(env.target_env(ctx.env))
        state = engine.load_state()
        ui.title("Меню HyprlandOwn")
        ui.info(f"Окружение: {env.title}" + (f" (экземпляр {env.instance.sig})" if env.instance else ""))
        if not env.can_attach:
            ui.info("Подключение к текущей сессии недоступно: " + env.attach_block)
        items = [(i, LABELS[i]) for i in applicable(ctx, env, units, state)]
        choice = ui.choose_one("Что сделать?", items)
        if choice in (None, "exit"):
            return 0
        target = env.target_env(ctx.env)
        if choice == "install":
            return install_flow(ctx, args)
        if choice == "attach":
            engine.attach()
        elif choice == "start":
            _show(ui, procman.start_all(target))
        elif choice == "restart":
            _show(ui, procman.restart_all(target))
        elif choice == "manager":
            ShellManager(ctx).open_manager(target)
            ui.ok("Manager запущен отдельным окном.")
        elif choice == "status":
            engine.show_status(engine.session_status())
        elif choice == "restore":
            if ui.confirm("Остановить процессы HyprlandOwn и вернуть прежние конфиги из резервных копий "
                          "(Hyprland продолжит работать)?", default=False):
                engine.detach(restore_config=True)
        elif choice == "preview":
            from .session import SessionManager
            return SessionManager(ctx).preview()


def _show(ui, rows: list[dict]) -> None:
    for r in rows:
        (ui.ok if r["result"] in ("started", "already", "stopped", "absent") else ui.error)(f"{r['id']}: {r['detail']}")
