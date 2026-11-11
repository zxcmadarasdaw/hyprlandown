"""Live Session Attach Engine: подключает HyprlandOwn к УЖЕ работающей сессии Hyprland.

Принципы (все проверены тестами с подменой системы, графику проверяет Fedora):
  * второй композитор не запускается, сессия не завершается, выход из системы не вызывается;
  * SDDM, загрузчик, драйверы, диски и KDE не затрагиваются; запись сессий для экрана входа
    (компонент login-session) в Attach никогда не ставится;
  * любое изменение пользовательских файлов идёт через резервную копию и записывается в журнал,
    поэтому `detach --restore-config` возвращает прежнее состояние;
  * настройки делятся по способу применения (см. classify_settings):
      ipc          `hyprctl keyword` / запуск процессов: действуют сразу;
      reload       `hyprctl reload`: перечитывает ТОТ ЖЕ главный конфиг. Он не переключает сессию на
                   другой файл, поэтому результат проверяется отпечатком (config fingerprint);
      new-session  читается только при старте Hyprland (переменные env, обёртка сессии): откладывается
                   с предупреждением;
  * все изменения лежат в домашнем каталоге и в $XDG_RUNTIME_DIR: на Fedora Live они временные.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import ConfigManager
from .context import Ctx
from .installer import Installer, Options
from .keybinds import KeyManager, validate_registry
from .procman import ProcessManager
from .recovery import RecoveryManager
from .registry import Registry, atomic_write
from .sessenv import Environment, detect_environment
from .system import detect
from .theme import ThemeEngine

ATTACH_COMPONENTS = ("desktop-core", "quickshell-shell", "wallpaper-engine")  # login-session не входит намеренно
EXIT_UNAVAILABLE = 6


@dataclass
class Step:
    id: str
    title: str
    status: str   # ok | warn | fail | skip | deferred
    detail: str = ""

    def to_dict(self):
        return self.__dict__.copy()


@dataclass
class Report:
    env: dict = field(default_factory=dict)
    steps: list = field(default_factory=list)
    settings: dict = field(default_factory=dict)
    units: list = field(default_factory=list)
    code: int = 0

    def add(self, sid, title, status, detail="") -> Step:
        s = Step(sid, title, status, detail)
        self.steps.append(s)
        return s

    @property
    def failed(self) -> bool:
        return any(s.status == "fail" for s in self.steps)

    def to_dict(self):
        return {"ok": self.code == 0, "code": self.code, "environment": self.env,
                "steps": [s.to_dict() for s in self.steps], "settings": self.settings, "units": self.units}


def classify_settings(ctx: Ctx) -> dict:
    """Что применяется сразу (ipc), через reload и только в новой сессии. Читает реальные файлы hypr/."""
    new_session = []
    for f in sorted((ctx.repo / "hypr").glob("*.conf")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if re.match(r"^\s*env\s*=", line):
                new_session.append(f"{f.name}: «{line.strip()}»: переменные окружения читаются только при старте Hyprland")
    new_session.append("hypr/session/hyprland-session: маркер аварии и safe-режим работают только при входе через SDDM")
    return {
        "ipc": ["горячие клавиши (hyprctl keyword unbind/bind)", "запуск и перезапуск Quickshell, обоев и виджетов",
                "вызовы hyprown ipc (холст, обои)",
                "тема: цвета оболочки и Manager (tokens.json), цвета рамок окон и скругление (hyprctl keyword)"],
        "reload": ["appearance.conf: скругления, отступы, блюр, тени, анимации", "input.conf: раскладки и мышь",
                   "performance.conf: профиль производительности", "theme.conf: цвета рамок активной темы", "keybinds.conf и keybinds.user.conf",
                   "ВАЖНО: reload перечитывает тот же главный файл, а не переключает на другой"],
        "new_session": new_session,
    }


class AttachEngine:
    def __init__(self, ctx: Ctx, reg: Registry, procman: ProcessManager | None = None):
        self.ctx, self.reg = ctx, reg
        self.ui = ctx.ui
        self.cfg = ConfigManager(ctx)
        self.keys = KeyManager(ctx)
        self.proc = procman or ProcessManager(ctx)
        self.rec = RecoveryManager(ctx, reg)

    @property
    def dry(self) -> bool:
        return bool(getattr(self.ctx.runner, "dry_run", False))

    def state_file(self) -> Path:
        return self.ctx.state_dir / "attach.json"

    def load_state(self) -> dict:
        try:
            return json.loads(self.state_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self, st: dict) -> None:
        if not self.dry:
            atomic_write(self.state_file(), json.dumps(st, indent=2, ensure_ascii=False))

    # ---------------------------------------------------------------- attach
    def attach(self, instance_sig: str | None = None, no_config: bool = False) -> Report:
        ui, rep = self.ui, Report()
        env_info = detect_environment(self.ctx, instance_sig)
        rep.env = env_info.to_dict()
        ui.title("Подключение HyprlandOwn к текущей сессии")
        ui.info(f"Окружение: {env_info.title}")
        for r in env_info.reasons:
            ui.info("  · " + r)
        if not env_info.can_attach:
            ui.error(env_info.attach_block)
            rep.add("environment", "Окружение", "fail", env_info.attach_block)
            rep.code = EXIT_UNAVAILABLE if env_info.kind in ("kde", "other") else 3
            return rep
        inst = env_info.instance
        env = env_info.target_env(self.ctx.env)
        info = detect(self.ctx)
        rep.add("environment", "Окружение", "ok", f"{env_info.title}, экземпляр {inst.sig} (pid {inst.pid})")
        ui.ok(f"Экземпляр Hyprland {inst.sig} (pid {inst.pid}) принадлежит текущей сессии: IPC проверен.")
        if info.is_live:
            ui.info("Fedora Live: все изменения лежат в домашнем каталоге и пропадут после перезагрузки. Диски не затрагиваются.")
        if self.dry:
            ui.info("dry-run: показываю шаги, ничего не меняю.")

        st = self.load_state()
        st.setdefault("journals", [])
        self._project(rep)
        if rep.failed:
            rep.code = 1
            return rep
        self._configs(rep)
        snap = None if self.dry else self.rec.snapshot("before-attach")
        if snap:
            ui.ok(f"Резервная копия состояния: {snap}")
        rep.add("backup", "Резервные копии", "ok" if snap else "skip", str(snap or "dry-run"))
        quickshell_ok = self._quickshell(rep)
        if not no_config:
            self._deps(rep, st, quickshell_ok)
        else:
            rep.add("deps", "Зависимости", "skip", "--no-config: пакеты и ссылки не трогаем")
        ours = env_info.ours
        if not no_config:
            ours = self._config_switch(rep, st, inst, env, env_info)
        else:
            rep.add("config", "Конфигурация", "skip", "--no-config")
        self._keys(rep, st, env, env_info, ours)
        self._theme(rep, env, ours)
        self._start(rep, env)
        rep.settings = classify_settings(self.ctx)
        self._show_settings(rep, ours)
        rep.units = self.proc.status(env)
        self._show_units(rep.units)
        st.update({"attached": True, "time": time.strftime("%F %T"), "instance": inst.sig, "kind": env_info.kind})
        self._save_state(st)
        rep.code = 1 if rep.failed else 0
        return rep

    # ---- шаги ----
    def _project(self, rep: Report) -> None:
        c = self.ctx
        need = [c.repo / "bin" / "hyprown", c.repo / "hypr" / "hyprland.conf", c.shell_dir / "shell.qml"]
        miss = [str(p) for p in need if not p.exists()]
        if miss:
            self.ui.error("Каталог проекта неполный: нет " + ", ".join(miss))
            rep.add("project", "Каталог проекта", "fail", "нет " + ", ".join(miss))
        else:
            self.ui.ok(f"Проект: {c.repo}")
            rep.add("project", "Каталог проекта", "ok", str(c.repo))

    def _configs(self, rep: Report) -> None:
        for line in self.cfg.lint():
            self.ui.warn(line)
        problems = self.keys_problems()
        for p in problems:
            self.ui.warn("Реестр клавиш: " + p)
        ok, text = self.cfg.verify()
        skipped = "не установлен" in text
        status = "skip" if skipped else ("ok" if ok else "warn")
        (self.ui.info if skipped else (self.ui.ok if ok else self.ui.warn))(
            "Синтаксис конфига: " + (text.splitlines()[0] if text else "ok"))
        rep.add("verify", "Проверка конфигураций", status, text.splitlines()[0] if text else "ok")

    def keys_problems(self) -> list[str]:
        return validate_registry(self.keys.binds)

    def _quickshell(self, rep: Report) -> bool:
        b = self.proc.shell.binary()
        if b:
            self.ui.ok(f"Quickshell найден: {b}")
            rep.add("quickshell", "Quickshell", "ok", b)
            return True
        self.ui.warn("Quickshell не найден: панель, обои и виджеты не запустятся, пока он не установлен.")
        rep.add("quickshell", "Quickshell", "warn", "не установлен")
        return False

    def _deps(self, rep: Report, st: dict, quickshell_ok: bool) -> None:
        ui = self.ui
        ids = [i for i in ATTACH_COMPONENTS if i in self.reg.components and self.reg.components[i].approved]
        info = detect(self.ctx)
        inst = Installer(self.ctx, self.reg, info)
        opts = Options(components=ids, live_ok=True)
        plan = inst.build_plan(opts)
        missing = [p for p in plan.pkgs if p.to_install]
        unavailable = [p for p in plan.pkgs if p.state == "missing" and p.required]
        if not missing and not unavailable and not plan.problems:
            ui.ok("Зависимости готовых модулей на месте.")
            rep.add("deps", "Зависимости", "ok", "все пакеты установлены")
            return
        if plan.problems:
            ui.warn("Автоустановка пакетов невозможна: " + "; ".join(plan.problems))
            rep.add("deps", "Зависимости", "warn", "; ".join(plan.problems))
            return
        if not missing:
            names = ", ".join(p.id for p in unavailable)
            ui.warn(f"Нужные пакеты не найдены ни в одном подключённом репозитории: {names}")
            rep.add("deps", "Зависимости", "warn", "недоступны в репозиториях: " + names)
            return
        ui.warn("Не хватает пакетов: " + ", ".join(p.id for p in missing))
        inst.show_plan(plan)
        if self.dry:
            rep.add("deps", "Зависимости", "skip", "dry-run: не хватает " + ", ".join(p.id for p in missing))
            return
        if not ui.confirm("Установить недостающие пакеты сейчас (dnf, потребуются права)?", default=True):
            rep.add("deps", "Зависимости", "warn", "пользователь отказался: " + ", ".join(p.id for p in missing))
            return
        r = inst.apply(plan, opts)
        if r.journal:
            st["journals"].append(r.journal)
        if r.ok:
            rep.add("deps", "Зависимости", "ok", "установлено: " + ", ".join(r.installed))
        else:
            rep.add("deps", "Зависимости", "fail", "; ".join(f"{k}: {v}" for k, v in r.failed.items()))
            ui.error("Установка завершилась с ошибкой: " + "; ".join(f"{k}: {v}" for k, v in r.failed.items()))

    def default_main_config(self) -> Path:
        return self.ctx.config_dir / "hypr" / "hyprland.conf"

    def _config_switch(self, rep: Report, st: dict, inst, env: dict, env_info: Environment) -> bool | None:
        """Приводит запущенную сессию к конфигу проекта безопасным путём. Возвращает ours."""
        ui = self.ui
        ours, why = self.cfg.uses_our_config(env)
        if ours:
            ui.ok("Сессия уже использует конфиг HyprlandOwn: " + why)
            rep.add("config", "Конфигурация сессии", "ok", why)
            return True
        if ours is None:
            ui.warn("Не удалось проверить конфиг запущенной сессии: " + why)
            rep.add("config", "Конфигурация сессии", "warn", why)
            return None
        ui.warn(why)
        main = Path(inst.config_arg).expanduser() if inst.config_arg else self.default_main_config()
        if inst.config_arg and main != self.default_main_config():
            msg = (f"Hyprland запущен с явным конфигом -c {main}: его мы не подменяем и reload не переключит сессию на "
                   "другой файл. Клавиши и процессы применяются через IPC, полный переход на конфиг проекта "
                   "возможен только при новом входе.")
            ui.warn(msg)
            rep.add("config", "Конфигурация сессии", "deferred", msg)
            return False
        comps = [self.reg.components[i] for i in ("desktop-core", "quickshell-shell")
                 if i in self.reg.components and self.reg.components[i].approved and self.reg.components[i].links]
        plan = [ls for c in comps for ls in self.cfg.link_states(c) if ls.state != "ok"]
        if not plan:
            ui.info("Ссылки на конфиги уже созданы, перечитываю конфиг (hyprctl reload).")
        else:
            ui.info("Чтобы сессия перешла на конфиг проекта, будут подключены ссылки (существующее переносится в резервную копию):")
            for ls in plan:
                ui.info(f"  {ls.dst} -> {ls.src}   [{ls.state}: {ls.detail or 'новая ссылка'}]")
        if self.dry:
            rep.add("config", "Конфигурация сессии", "skip", "dry-run: " + (f"{len(plan)} ссылок и reload" if plan else "reload"))
            return False
        if not ui.confirm("Подключить конфиг HyprlandOwn к этой сессии (с резервной копией)?", default=True):
            rep.add("config", "Конфигурация сессии", "deferred",
                    "отказ пользователя: конфиг не менялся, клавиши применятся через IPC")
            return False
        journal = self.rec.new_journal("attach")
        journal["id"] += "-attach"  # не затирает журнал установщика, созданный в ту же секунду
        try:
            for c in comps:
                self.cfg.apply_links(c, journal["ops"])
        except (FileNotFoundError, OSError) as exc:
            ui.error(f"Ссылки не созданы: {exc}")
            rep.add("config", "Конфигурация сессии", "fail", str(exc))
            return False
        finally:
            if journal["ops"]:
                self.rec.save_journal(journal)
                st["journals"].append(journal["id"])
        self.keys.ensure_user_conf()
        self.ctx.runner.run(["hyprctl", "reload"], env=env, timeout=15)
        ours, why = self.cfg.uses_our_config(env)
        if ours:
            ui.ok("hyprctl reload переключил сессию на конфиг проекта.")
            rep.add("config", "Конфигурация сессии", "ok", "ссылки подключены, reload выполнен, отпечаток совпал")
            return True
        done = "Ссылки созданы и reload выполнен" if plan else "reload выполнен"
        msg = (done + ", но сессия всё ещё не на нашем конфиге: " + why +
               " Клавиши и процессы применяются через IPC, полный переход при новом входе.")
        ui.warn(msg)
        rep.add("config", "Конфигурация сессии", "deferred", msg)
        return False

    def _keys(self, rep: Report, st: dict, env: dict, env_info: Environment, ours) -> None:
        ui = self.ui
        mode = "preview" if env_info.kind == "preview" else "desktop"
        live = self.keys.live(env, mode)
        if live["ok"] is None:
            ui.warn("Клавиши не проверены: " + live["error"])
            rep.add("keys", "Горячие клавиши", "warn", live["error"])
            return
        if live["ok"]:
            ui.ok("Горячие клавиши в сессии совпадают с реестром.")
            rep.add("keys", "Горячие клавиши", "ok", "совпадают с реестром")
            return
        bad = [i for i in live["items"] if i["status"] != "ok"]
        ui.warn(f"Клавиши сессии расходятся с реестром ({len(bad)}):")
        for i in bad:
            ui.info(f"  {i['combo']}: {i['detail']}" + ("   <-- ВЫХОД ИЗ СЕССИИ" if i.get("danger") else ""))
        if self.dry:
            rep.add("keys", "Горячие клавиши", "skip", f"dry-run: расхождений {len(bad)}")
            return
        if not ui.confirm("Назначить клавиши HyprlandOwn через IPC (временно, до hyprctl reload или нового входа)?",
                          default=True):
            rep.add("keys", "Горячие клавиши", "deferred", f"отказ пользователя, расхождений {len(bad)}")
            return
        res = self.keys.apply_live(env, mode)
        again = self.keys.live(env, mode)
        if res["errors"] or not again["ok"]:
            detail = "; ".join(res["errors"][:3]) or f"расхождений осталось: {sum(1 for i in again['items'] if i['status'] != 'ok')}"
            ui.warn("Клавиши применены не полностью: " + detail)
            rep.add("keys", "Горячие клавиши", "warn", detail)
        else:
            ui.ok(f"Клавиши применены через IPC: {res['bound']} привязок.")
            rep.add("keys", "Горячие клавиши", "ok", f"IPC: {res['bound']} привязок")
            st["ipc_keys"] = True

    def _theme(self, rep: Report, env: dict, ours) -> None:
        """Токены темы для оболочки и цвета рамок окон: через IPC, без reload и без выхода.

        Сессия на нашем конфиге уже читает theme.conf: IPC не нужен. Чужой сессии рамки
        перекрашиваются только с согласия (до hyprctl reload или нового входа)."""
        if self.dry:
            rep.add("theme", "Тема", "skip", "dry-run")
            return
        eng = ThemeEngine(self.ctx)
        try:
            tokens = eng.write()
        except (OSError, RuntimeError) as exc:
            self.ui.warn(f"Тема не записана: {exc}. Оболочка возьмёт встроенные цвета.")
            rep.add("theme", "Тема", "warn", str(exc))
            return
        name = tokens.get("name", tokens["id"]) + (" (палитра из обоев)" if tokens["mode"] == "wallpaper" else "")
        if ours:
            errors = []
        elif self.ui.confirm("Перекрасить рамки окон в цвета темы HyprlandOwn (до hyprctl reload или нового входа)?",
                             default=True):
            errors = eng.apply_live(tokens, env)
        else:
            self.ui.info(f"Тема {name}: только оболочка; рамки окон Hyprland не тронуты.")
            rep.add("theme", "Тема", "deferred", f"{name}: рамки окон не перекрашены (отказ)")
            return
        if errors:
            self.ui.warn("Цвета рамок не применены: " + "; ".join(errors[:2]))
            rep.add("theme", "Тема", "warn", f"{name}; рамки: {errors[0]}")
        else:
            self.ui.ok(f"Тема: {name}.")
            rep.add("theme", "Тема", "ok", name)

    def _start(self, rep: Report, env: dict) -> None:
        ui = self.ui
        if self.dry:
            rep.add("processes", "Процессы", "skip", "dry-run")
            return
        out = self.proc.start_all(env)
        for r in out:
            line = f"{r['id']}: {r['detail']}"
            if r["result"] in ("started", "already"):
                ui.ok(line)
            elif r["result"] == "failed" or r["result"] == "blocked":
                ui.error(line)
            else:
                ui.warn(line)
        bad = [r for r in out if r["result"] in ("failed", "blocked", "throttled")]
        rep.add("processes", "Процессы", "fail" if bad else "ok", "; ".join(f"{r['id']}: {r['detail']}" for r in out))

    def _show_settings(self, rep: Report, ours) -> None:
        ui = self.ui
        ui.title("Как применены настройки")
        s = rep.settings
        ui.info("Сразу (IPC): " + "; ".join(s["ipc"]))
        ui.info("Через reload: " + "; ".join(s["reload"]) + ("" if ours else "  [сессия не на нашем конфиге: действует только то, что применено через IPC]"))
        for line in s["new_session"]:
            ui.warn("Нужна новая сессия (отложено): " + line)

    def _show_units(self, units: list) -> None:
        ui = self.ui
        ui.title("Состояние компонентов")
        mark = {"running": ui.ok, "stopped": ui.warn, "blocked": ui.error}
        for u in units:
            mark.get(u["state"], ui.info)(f"{u['title']}: {u['state']}. {u['detail']}")

    # ---------------------------------------------------------------- detach
    def detach(self, restore_config: bool = False, instance_sig: str | None = None) -> Report:
        """Останавливает процессы проекта. Hyprland не закрывается ни при каких условиях."""
        ui, rep = self.ui, Report()
        env_info = detect_environment(self.ctx, instance_sig)
        rep.env = env_info.to_dict()
        env = env_info.target_env(self.ctx.env)
        ui.title("Отключение HyprlandOwn (Hyprland продолжает работать)")
        out = self.proc.stop_all(env) if not self.dry else []
        for r in out:
            (ui.ok if r["result"] in ("stopped", "absent") else ui.error)(f"{r['id']}: {r['detail']}")
        rep.add("processes", "Процессы проекта", "fail" if any(r["result"] == "failed" for r in out) else "ok",
                "; ".join(r["detail"] for r in out) or "dry-run")
        st = self.load_state()
        reload_needed = bool(st.get("ipc_keys"))
        if restore_config:
            for msg, ok in self._restore_links(st):
                (ui.ok if ok else ui.error)(msg)
                rep.add("restore", "Восстановление конфигурации", "ok" if ok else "fail", msg)
            reload_needed = True
        if reload_needed and env_info.instance and not self.dry:
            self.ctx.runner.run(["hyprctl", "reload"], env=env, timeout=15)
            ui.ok("hyprctl reload: возвращены привязки и настройки, описанные в конфиге сессии (IPC-изменения сняты).")
            st["ipc_keys"] = False
        if not self.dry:
            st.update({"attached": False, "detached": time.strftime("%F %T")})
            if restore_config:
                st["journals"] = []
            self._save_state(st)
        rep.units = self.proc.status(env)
        rep.code = 1 if rep.failed else 0
        return rep

    def _restore_links(self, st: dict) -> list[tuple[str, bool]]:
        msgs = []
        ids = list(st.get("journals", []))
        if not ids:
            return [("Attach не менял ссылки конфигов: восстанавливать нечего.", True)]
        for jid in reversed(ids):
            j = next((x for x in self.rec.journals() if x["id"] == jid), None)
            if not j:
                msgs.append((f"запись {jid} не найдена", False))
                continue
            for op in reversed(j["ops"]):
                if op.get("op") != "link":
                    continue
                try:
                    if self.dry:
                        msgs.append((f"[dry-run] откат {op['name']}", True))
                    else:
                        msgs.append((self.cfg.rollback_link(op["name"], Path(op["dst"])), True))
                except (FileNotFoundError, FileExistsError, OSError) as exc:
                    msgs.append((f"{op['name']}: {exc}", False))
        return msgs

    # ---------------------------------------------------------------- состояние
    def session_status(self, instance_sig: str | None = None) -> dict:
        env_info = detect_environment(self.ctx, instance_sig)
        env = env_info.target_env(self.ctx.env)
        st = self.load_state()
        data = {"environment": env_info.to_dict(), "units": self.proc.status(env), "attach": {
            "attached": bool(st.get("attached")), "since": st.get("time", ""), "ipc_keys": bool(st.get("ipc_keys"))}}
        if env_info.instance:
            ours, why = self.cfg.uses_our_config(env)
            data["config"] = {"ours": ours, "detail": why}
            mode = "preview" if env_info.kind == "preview" else "desktop"
            live = self.keys.live(env, mode)
            data["keys"] = {"ok": live["ok"], "summary": live["summary"], "error": live["error"],
                            "problems": [f"{i['combo']}: {i['detail']}" for i in live["items"] if i["status"] != "ok"]}
        return data

    def show_status(self, data: dict) -> None:
        ui = self.ui
        e = data["environment"]
        ui.title("Состояние сессии")
        ui.info(f"Окружение: {e['title']}")
        if e["instance"]:
            ui.info(f"Экземпляр Hyprland: {e['instance']['sig']} (pid {e['instance']['pid']})")
        if "config" in data:
            (ui.ok if data["config"]["ours"] else ui.warn)("Конфиг сессии: " + data["config"]["detail"])
        if "keys" in data:
            k = data["keys"]
            if k["ok"] is None:
                ui.warn("Клавиши: не проверены: " + k["error"])
            elif k["ok"]:
                ui.ok("Горячие клавиши совпадают с реестром.")
            else:
                for p in k["problems"]:
                    ui.warn("Клавиша: " + p)
        self._show_units(data["units"])
        if not e["can_attach"]:
            ui.info("Attach: " + e["attach_block"])

