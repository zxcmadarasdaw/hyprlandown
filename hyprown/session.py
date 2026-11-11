"""Session Manager: Preview Mode (вложенная сессия) и готовность Desktop Mode.

Preview: Hyprland запускается ОКНОМ внутри текущей Wayland/X11-сессии (KDE Plasma)
с явным `-c` на отрендеренный конфиг проекта. KDE остаётся основной сессией,
закрытие окна ничего в ней не нарушает. Маркер аварийного выхода реальной
сессии (hypr/session/hyprland-session) Preview не трогает.

Desktop Mode: полноценная сессия запускается ТОЛЬКО через экран входа (SDDM) и
записи wayland-sessions, установленные компонентом login-session. Подмена
работающей сессии KDE здесь не реализуется и не планируется.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from .config import ConfigManager
from .context import Ctx
from .registry import atomic_write
from .sessenv import scan_instances, usable
from .system import detect

SESSIONS_DIR = "/usr/share/wayland-sessions"
SESSION_FILES = ("hyprland-managed.desktop", "hyprland-safe.desktop")
WRAPPER = "/usr/local/bin/hyprland-session"


class SessionManager:
    def __init__(self, ctx: Ctx, popen=subprocess.Popen):
        self.ctx, self.popen = ctx, popen
        self.cfg = ConfigManager(ctx)

    # ---------- связь с запущенным Hyprland ----------
    def hypr_env(self) -> dict:
        """Окружение для hyprctl, если команду запустили не из Hyprland (терминал KDE, Manager).

        Экземпляр угадывается ТОЛЬКО если живой пользовательский экземпляр ровно один: при нескольких
        (например, обычная сессия и Preview) выбирать наугад нельзя, чужой IPC не трогаем.
        Точный выбор: HYPRLAND_INSTANCE_SIGNATURE или `hyprown attach --instance`.
        """
        env = dict(self.ctx.env)
        live = [i for i in scan_instances(self.ctx, env) if usable(i)]
        sig = env.get("HYPRLAND_INSTANCE_SIGNATURE")
        if sig and (not live or any(i.sig == sig for i in live)):
            return env
        env.pop("HYPRLAND_INSTANCE_SIGNATURE", None)  # устаревшая сигнатура: не доверяем
        if len(live) == 1:
            env["HYPRLAND_INSTANCE_SIGNATURE"] = live[0].sig
        return env

    def in_hyprland(self) -> bool:
        return bool(self.hypr_env().get("HYPRLAND_INSTANCE_SIGNATURE"))

    # ---------- Preview ----------
    def preview_pid_file(self) -> Path:
        return self.ctx.runtime_dir / "preview.pid"

    def preview_running(self) -> int | None:
        try:
            pid = int(self.preview_pid_file().read_text().strip())
            os.kill(pid, 0)
            return pid
        except (OSError, ValueError, SystemError):
            return None

    def preview(self, wait: bool = True) -> int:
        ui, c = self.ctx.ui, self.ctx
        info = detect(c)
        if not c.runner.which("Hyprland"):
            ui.error("Hyprland не установлен. Выполните: bash install.sh")
            return 2
        if not info.can_nest:
            ui.error("Preview открывается окном внутри графической сессии (KDE Plasma), а такой не найдено "
                     "(нет WAYLAND_DISPLAY и DISPLAY). Запустите команду из терминала в KDE.")
            return 3
        if self.in_hyprland() and c.env.get("HYPRLAND_INSTANCE_SIGNATURE"):
            ui.warn("Вы уже внутри Hyprland: Preview запустится вложенным окном поверх него.")
        if self.preview_running():
            ui.error("Preview уже запущен (см. окно Hyprland в KDE).")
            return 4
        conf = self.cfg.render("preview", c.runtime_dir / "preview")
        ok, text = self.cfg.verify()
        if not ok and "не установлен" not in text:
            ui.warn("Проверка конфига сообщила о проблемах (Preview всё равно запустится): " + text.splitlines()[0])
        env = dict(c.env)
        env["HYPRDESK_SESSION_MODE"] = "preview"
        log = c.log_dir / "preview.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        ui.info(f"Запуск Hyprland во вложенном окне. Конфиг: {conf}. Лог: {log}")
        ui.info("Закрыть: Alt+M внутри окна Preview или закрыть окно. KDE это не затронет.")
        lf = open(log, "ab")
        lf.write(f"\n=== {time.strftime('%F %T')} preview conf={conf} ===\n".encode())
        proc = self.popen(["Hyprland", "-c", str(conf)], env=env, stdin=subprocess.DEVNULL,
                          stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
        atomic_write(self.preview_pid_file(), f"{proc.pid}\n")
        if not wait:
            return 0
        try:
            code = proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            code = proc.wait()
        finally:
            self.preview_pid_file().unlink(missing_ok=True)
        if code != 0:
            ui.error(f"Hyprland завершился с кодом {code}. Смотрите {log}")
        else:
            ui.ok("Preview закрыт.")
        return code

    # ---------- Desktop Mode ----------
    def desktop_readiness(self) -> list[dict]:
        """Что нужно для входа в полноценную сессию. Ничего не меняет."""
        c = self.ctx
        out = []

        def chk(cid, title, ok, detail="", fix=""):
            out.append({"id": cid, "title": title, "ok": bool(ok), "detail": detail, "fix": fix})

        chk("hyprland", "Hyprland установлен", c.runner.which("Hyprland"),
            fix="bash install.sh")
        for f in SESSION_FILES:
            chk("session-" + f, f"Запись входа {f}", c.fs(f"{SESSIONS_DIR}/{f}").exists(),
                fix="bash install.sh (компонент login-session, нужен root)")
        chk("wrapper", "Обёртка " + WRAPPER, c.fs(WRAPPER).exists(),
            fix="bash install.sh (компонент login-session)")
        conf = c.config_dir / "hypr" / "hyprland.conf"
        chk("hypr-config", "~/.config/hypr/hyprland.conf доступен", conf.exists(),
            fix="hyprown config link")
        return out

    def desktop_instructions(self) -> list[str]:
        return [
            "Полноценная сессия запускается только с экрана входа, без подмены работающего KDE:",
            "  1. Сохраните работу и выйдите из KDE (меню запуска -> Выйти).",
            "  2. На экране входа SDDM выберите сессию «Hyprland» (рабочий стол) или «Hyprland (safe)» (восстановление).",
            "  3. Если сессия не поднялась, следующий вход автоматически откроется в safe-режиме.",
        ]

    def logout_prompt(self) -> int:
        """Открывает штатный диалог выхода KDE. Пользователь подтверждает сам."""
        for q in ("qdbus6", "qdbus-qt6", "qdbus"):
            if self.ctx.runner.which(q):
                r = self.ctx.runner.run([q, "org.kde.LogoutPrompt", "/LogoutPrompt",
                                         "org.kde.LogoutPrompt.promptLogout"])
                return r.code
        self.ctx.ui.error("qdbus не найден: выйдите из KDE через меню вручную.")
        return 1
