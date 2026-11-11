"""Diagnostics Engine: проверки состояния окружения. Только чтение, ничего не меняет.

Каждая проверка возвращает {id, title, status, detail, fix}. status: ok | warn | fail | skip.
Те же данные видит терминал (`hyprown doctor`), Manager (`--json`) и скрипт
scripts/fedora-diagnose.sh.
"""

from __future__ import annotations

from pathlib import Path

from . import TESTED_FEDORA, TESTED_HYPRLAND
from .config import ConfigManager
from .context import Ctx
from .pkg import DnfAdapter, version_ge
from .registry import Registry
from .session import SessionManager, SESSION_FILES, SESSIONS_DIR, WRAPPER
from .shell import ShellManager
from .system import SystemInfo, detect, fedora_major


def _c(cid, title, status, detail="", fix=""):
    return {"id": cid, "title": title, "status": status, "detail": detail, "fix": fix}


def run_all(ctx: Ctx, reg: Registry, info: SystemInfo | None = None) -> list[dict]:
    info = info or detect(ctx)
    pm, cfg, sess, sh = DnfAdapter(ctx), ConfigManager(ctx), SessionManager(ctx), ShellManager(ctx)
    out = []

    # --- система ---
    if not info.is_fedora:
        out.append(_c("os", "Операционная система", "warn", f"{info.pretty_name or info.os_id or 'не определена'}: проект рассчитан на Fedora"))
    elif fedora_major(info) != int(TESTED_FEDORA):
        out.append(_c("os", "Версия Fedora", "warn", f"{info.version_id} (проверялось на {TESTED_FEDORA})"))
    else:
        out.append(_c("os", "Fedora", "ok", info.pretty_name))
    if info.is_live:
        out.append(_c("live", "Live USB", "warn", "изменения пропадут после перезагрузки; место ограничено оперативной памятью"))
    out.append(_c("disk", "Свободное место", "ok" if info.free_home_mb >= 1500 else "warn",
                  f"домашний каталог: {info.free_home_mb} МБ" + ("" if info.free_home_mb >= 1500 else " (рекомендуется 1500+)")))
    out.append(_c("gpu", "Видеокарта", "ok" if info.gpus else "warn",
                  ", ".join(info.gpus) or "не определена (читаем /sys/class/drm)",
                  "NVIDIA: проприетарный драйвер ставится вручную, установщик его не трогает" if "nvidia" in info.gpus else ""))

    # --- пакеты ---
    for pid, pkg in reg.packages.items():
        needed = any(pid in c.pkg_required for c in reg.components.values() if reg.is_installed(c.id))
        if pm.present(pkg):
            ver = pm.version(pkg)
            if pkg.min_version and ver and not version_ge(ver, pkg.min_version):
                out.append(_c("pkg-" + pid, pkg.id, "fail", f"версия {ver}, нужна {pkg.min_version}+"))
            else:
                out.append(_c("pkg-" + pid, pkg.id, "ok", ver or "установлен"))
        elif needed:
            out.append(_c("pkg-" + pid, pkg.id, "fail", "не установлен, а нужен установленным компонентам", "bash install.sh"))
        else:
            out.append(_c("pkg-" + pid, pkg.id, "skip", "не установлен (не требуется текущим набором)"))
    hv = pm.version(reg.packages["hyprland"]) if "hyprland" in reg.packages else ""
    if hv and hv != TESTED_HYPRLAND:
        out.append(_c("hyprland-tested", "Версия Hyprland", "warn", f"{hv}: проект проверялся на {TESTED_HYPRLAND}"))

    # --- Quickshell ---
    caps = sh.probe()
    if caps.binary:
        out.append(_c("qs-cli", "CLI Quickshell", "ok" if caps.has_path or caps.has_config else "warn",
                      f"{caps.binary} {caps.version}; --path: {caps.has_path}, --config: {caps.has_config}, "
                      f"--no-duplicate: {caps.has_no_duplicate}"))
    try:
        out.append(_c("shell-qml", "shell.qml найден", "ok", str(sh.find_shell())))
    except FileNotFoundError as exc:
        out.append(_c("shell-qml", "shell.qml найден", "fail", str(exc)))
    st = sh.status()
    out.append(_c("shell-run", "Супервизор Quickshell", "ok" if st["supervisor_pid"] else "skip",
                  f"pid {st['supervisor_pid']}" if st["supervisor_pid"] else "не запущен (нормально вне сессии Hyprland)"))

    # --- ссылки конфигов ---
    for comp in reg.components.values():
        if not reg.is_installed(comp.id):
            continue
        for ls in cfg.link_states(comp):
            ok = ls.state == "ok"
            out.append(_c(f"link-{ls.name}", f"Ссылка {ls.name}", "ok" if ok else "fail",
                          f"{ls.dst} -> {ls.src}" if ok else f"{ls.dst}: {ls.state}. {ls.detail}",
                          "" if ok else "hyprown config link"))

    # --- конфиг: синтаксис и реальная загрузка ---
    ok, text = cfg.verify()
    out.append(_c("verify-config", "Синтаксис конфига (--verify-config)", "ok" if ok else ("skip" if "не установлен" in text else "fail"),
                  text.splitlines()[0] if text else "", "Это проверка файла, а не запущенной сессии"))
    for line in cfg.lint():
        out.append(_c("lint", "Устаревший параметр", "warn", line))
    if sess.in_hyprland():
        env = sess.hypr_env()
        ours, why = cfg.uses_our_config(env)
        out.append(_c("running-config", "Запущенная сессия использует конфиг проекта",
                      "skip" if ours is None else ("ok" if ours else "fail"), why,
                      "" if ours else "hyprown config link, затем перелогин; для проверки: hyprown preview"))
        if ctx.runner.which("hyprctl"):
            res = ctx.runner.run(["hyprctl", "configerrors"], mutates=False, env=env, timeout=10)
            errs = res.out.strip()
            out.append(_c("configerrors", "hyprctl configerrors", "ok" if not errs else "fail", errs[:300] or "пусто"))
    else:
        out.append(_c("running-config", "Запущенная сессия использует конфиг проекта", "skip",
                      "Hyprland не запущен (проверка выполняется внутри сессии или Preview)"))

    # --- вход в сессию ---
    for f in SESSION_FILES:
        out.append(_c("session-" + f, f"Запись входа {f}", "ok" if ctx.fs(f"{SESSIONS_DIR}/{f}").exists() else "warn",
                      "", "компонент login-session"))
    out.append(_c("wrapper", "Обёртка сессии", "ok" if ctx.fs(WRAPPER).exists() else "warn", WRAPPER))

    # --- хост-сессия ---
    out.append(_c("host-session", "Графическая сессия для Preview", "ok" if info.can_nest else "warn",
                  f"{info.session_type or '?'} / {info.desktop or '?'}"))
    return out


def summarize(checks: list[dict]) -> dict:
    n = {"ok": 0, "warn": 0, "fail": 0, "skip": 0}
    for c in checks:
        n[c["status"]] += 1
    return n
