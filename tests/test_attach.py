"""Live Session Attach: определение окружения, Attach/Detach, процессы сессии, меню, CLI.

Всё на подменах: поддельный Hyprland (tests/hypr_fake.py), поддельный запуск супервизора и os.kill.
Настоящую графику (Quickshell, Wayland-сокеты) проверяет Fedora: docs/FEDORA_VERIFY.md.
"""

import contextlib
import io
import json
import os
import unittest
from dataclasses import replace
from pathlib import Path

from hyprown.attach import AttachEngine, classify_settings, EXIT_UNAVAILABLE
from hyprown.cli import build_parser, cmd_attach, cmd_detach, cmd_keys, cmd_session
from hyprown.menu import applicable
from hyprown.procman import ProcessManager, RESTART_LIMIT
from hyprown.registry import Registry
from hyprown.sessenv import detect_environment, parse_config_arg
from hyprown.shell import ShellManager
from hyprown.ui import UI
from tests.helpers import Env, REPO, dnf_responses, needs_symlink, no_links, ok
from tests.hypr_fake import FakeHypr, FakePopen, fake_kill, make_instance, write_cmdline

HELP = "Usage: qs\n  -p, --path PATH\n  -c, --config NAME\n  -n, --no-duplicate\n"
HYPR_PID, SHELL_PID = 4242, 7777


class Scene:
    """Готовая сцена: Env + поддельный Hyprland + поддельный супервизор."""

    def __init__(self, test, ours=False, bins=None, yes=True, start=True, instance=True,
                 extra_responses=(), **inst_kw):
        if bins is None:  # по умолчанию все пакеты проекта «установлены»
            packs = Registry(Env().ctx).packages.values()
            bins = {"hyprctl", "qs", "rpm"} | {p.check_bin for p in packs if p.check_bin}
        self.e = Env(bins=set(bins), yes=yes, env_extra={"XDG_SESSION_TYPE": "wayland"})
        test.addCleanup(self.e.__exit__)
        self.ctx = self.e.ctx
        if instance:
            make_instance(self.e, pid=HYPR_PID, **inst_kw)
        self.fh = FakeHypr(self.ctx, ours=ours)
        self.e.runner.responses[:] = (list(extra_responses) + self.fh.responses() +
                                      [(("qs", "--help"), ok(HELP)), (("qs", "--version"), ok("0.2.1"))])
        self.alive = {HYPR_PID}
        base = ShellManager(self.ctx)
        self.popen = FakePopen(self.e, base, self.ctx.env, pid=SHELL_PID, alive=self.alive, start=start)
        self.shell = ShellManager(self.ctx, popen=self.popen, sleep=lambda s: None)
        self.proc = ProcessManager(self.ctx, self.shell, sleep=lambda s: None)
        self.engine = AttachEngine(self.ctx, Registry(self.ctx), self.proc)

    @property
    def calls(self):
        return self.e.runner.calls

    def called_with(self, *parts) -> bool:
        return any(all(p in c for p in parts) for c in self.calls)


class Environments(unittest.TestCase):
    def test_regular_hyprland(self):
        s = Scene(self)
        env = detect_environment(s.ctx)
        self.assertEqual(env.kind, "hyprland")
        self.assertTrue(env.can_attach)
        self.assertEqual(env.instance.sig, "sigA")
        self.assertFalse(env.ours)

    def test_hyprlandown_session(self):
        s = Scene(self, ours=True)
        env = detect_environment(s.ctx)
        self.assertEqual(env.kind, "hyprlandown")
        self.assertTrue(env.ours)

    def test_nested_preview(self):
        e = Env(bins={"hyprctl"})
        self.addCleanup(e.__exit__)
        conf = e.ctx.runtime_dir / "preview" / "hyprland.conf"
        make_instance(e, pid=HYPR_PID, cmdline=("Hyprland", "-c", str(conf)))
        e.runner.responses[:] = FakeHypr(e.ctx, ours=True).responses()
        env = detect_environment(e.ctx)
        self.assertEqual(env.kind, "preview")
        self.assertTrue(env.can_attach)

    def test_kde_blocks_attach_even_when_preview_runs(self):
        e = Env(bins={"hyprctl"}, env_extra={"XDG_CURRENT_DESKTOP": "KDE", "WAYLAND_DISPLAY": "wayland-0"})
        self.addCleanup(e.__exit__)
        (e.tmp / "run").mkdir(exist_ok=True)
        (e.tmp / "run" / "wayland-0").write_text("")
        make_instance(e, sig="prev", pid=HYPR_PID, wl="wayland-9", set_env=False)  # Preview другого терминала
        env = detect_environment(e.ctx)
        self.assertEqual(env.kind, "kde")
        self.assertFalse(env.can_attach)
        self.assertIn("KDE", env.attach_block)
        self.assertIsNone(env.instance, "IPC чужого Preview нельзя принимать за текущую сессию")
        self.assertEqual(len(env.others), 1)

    def test_kde_ignores_explicit_instance(self):
        e = Env(bins={"hyprctl"}, env_extra={"XDG_CURRENT_DESKTOP": "KDE", "WAYLAND_DISPLAY": "wayland-0"})
        self.addCleanup(e.__exit__)
        make_instance(e, sig="prev", pid=HYPR_PID, wl="wayland-9", set_env=False)
        env = detect_environment(e.ctx, "prev")
        self.assertEqual(env.kind, "kde")
        self.assertFalse(env.can_attach)

    def test_no_graphical_session(self):
        e = Env(bins={"hyprctl"})
        self.addCleanup(e.__exit__)
        env = detect_environment(e.ctx)
        self.assertEqual(env.kind, "none")
        self.assertFalse(env.can_attach)

    def test_tty_can_attach_with_explicit_instance(self):
        e = Env(bins={"hyprctl"})
        self.addCleanup(e.__exit__)
        make_instance(e, sig="sigB", pid=HYPR_PID, set_env=False)
        e.runner.responses[:] = FakeHypr(e.ctx).responses()
        self.assertFalse(detect_environment(e.ctx).can_attach)
        env = detect_environment(e.ctx, "sigB")
        self.assertTrue(env.can_attach)
        self.assertEqual(env.target_env({})["HYPRLAND_INSTANCE_SIGNATURE"], "sigB")
        self.assertEqual(env.target_env({})["WAYLAND_DISPLAY"], "wayland-1")

    def test_stale_signature_is_ignored(self):
        e = Env(bins={"hyprctl"}, env_extra={"HYPRLAND_INSTANCE_SIGNATURE": "gone", "WAYLAND_DISPLAY": "wayland-1",
                                              "XDG_CURRENT_DESKTOP": "Hyprland"})
        self.addCleanup(e.__exit__)
        make_instance(e, sig="live", pid=HYPR_PID, set_env=False)
        env = detect_environment(e.ctx)
        self.assertIsNone(env.instance)
        self.assertFalse(env.can_attach)
        self.assertTrue(any("gone" in r for r in env.reasons))

    def test_signature_on_other_wayland_socket_is_not_current_session(self):
        e = Env(bins={"hyprctl"}, env_extra={"HYPRLAND_INSTANCE_SIGNATURE": "sigA", "WAYLAND_DISPLAY": "wayland-0"})
        self.addCleanup(e.__exit__)
        make_instance(e, sig="sigA", pid=HYPR_PID, wl="wayland-1", set_env=False)
        env = detect_environment(e.ctx)
        self.assertIsNone(env.instance)
        self.assertTrue(any("не текущая сессия" in r for r in env.reasons))

    def test_dead_instance_is_ignored(self):
        e = Env(bins={"hyprctl"})
        self.addCleanup(e.__exit__)
        make_instance(e, sig="dead", pid=HYPR_PID, alive=False)  # lock-файл есть, процесса нет
        env = detect_environment(e.ctx)
        self.assertIsNone(env.instance)

    def test_multiple_instances_pick_the_current_one_only(self):
        e = Env(bins={"hyprctl"})
        self.addCleanup(e.__exit__)
        make_instance(e, sig="other", pid=5001, wl="wayland-2", set_env=False)
        make_instance(e, sig="mine", pid=HYPR_PID, wl="wayland-1")
        e.runner.responses[:] = FakeHypr(e.ctx).responses()
        env = detect_environment(e.ctx)
        self.assertEqual(env.instance.sig, "mine")
        self.assertEqual([i.sig for i in env.others], ["other"])
        self.assertEqual(env.target_env({})["HYPRLAND_INSTANCE_SIGNATURE"], "mine")

    def test_parse_config_arg(self):
        self.assertEqual(parse_config_arg(["Hyprland", "-c", "/x/a.conf"]), "/x/a.conf")
        self.assertEqual(parse_config_arg(["Hyprland", "--config=/y"]), "/y")
        self.assertIsNone(parse_config_arg(["Hyprland"]))


class AttachFlow(unittest.TestCase):
    def test_attach_to_regular_hyprland(self):
        s = Scene(self)
        with no_links(), fake_kill(s.alive) as sent:
            rep = s.engine.attach()
        self.assertEqual(rep.code, 0, [x.to_dict() for x in rep.steps])
        # клавиши: всё действует, выход ровно один (Super+M)
        self.assertTrue(s.engine.keys.live(s.ctx.env)["ok"])
        self.assertEqual([b["key"].lower() for b in s.fh.binds if b["dispatcher"] == "exit"], ["m"])
        # процессы
        self.assertEqual(len(s.popen.calls), 1)
        # сессия не тронута: Hyprland не получал сигналов и команд завершения
        self.assertNotIn(HYPR_PID, [p for p, sig in sent if sig != 0])
        self.assertFalse(s.called_with("hyprctl", "dispatch"))
        self.assertFalse(any(c[0] in ("sudo", "pkexec", "systemctl", "loginctl", "dnf") for c in s.calls))
        st = json.loads((s.ctx.state_dir / "attach.json").read_text(encoding="utf-8"))
        self.assertTrue(st["attached"] and st["ipc_keys"])
        by = {x.id: x for x in rep.steps}
        self.assertEqual(by["config"].status, "deferred")   # reload не переключил чужой конфиг: честно сказано
        self.assertEqual(by["keys"].status, "ok")
        self.assertEqual(by["processes"].status, "ok")

    def test_attach_in_session_that_already_runs_hyprlandown(self):
        s = Scene(self, ours=True)
        with no_links(), fake_kill(s.alive):
            rep = s.engine.attach()
        self.assertEqual(rep.code, 0)
        self.assertEqual(s.fh.keywords, [], "наши клавиши уже на месте: IPC не нужен")
        self.assertEqual(s.fh.reloads, 0)
        self.assertEqual(len(s.popen.calls), 1)  # оболочка не работала: запущена один раз

    def test_repeated_attach_does_not_start_a_second_shell(self):
        s = Scene(self, ours=True)
        with no_links(), fake_kill(s.alive):
            first = s.engine.attach()
            second = s.engine.attach()
        self.assertEqual((first.code, second.code), (0, 0))
        self.assertEqual(len(s.popen.calls), 1)
        proc = next(x for x in second.steps if x.id == "processes")
        self.assertIn("уже работает", proc.detail)

    def test_repeated_attach_on_regular_hyprland_is_stable(self):
        s = Scene(self)
        with no_links(), fake_kill(s.alive):
            s.engine.attach()
            second = s.engine.attach()
        self.assertEqual(second.code, 0)
        self.assertEqual(len(s.popen.calls), 1)
        self.assertTrue(s.engine.keys.live(s.ctx.env)["ok"])

    def test_declined_confirmation_leaves_foreign_binds_alone(self):
        s = Scene(self, yes=False)  # без --yes и без терминала подтверждения нет
        with no_links(), fake_kill(s.alive):
            rep = s.engine.attach()
        self.assertEqual(s.fh.keywords, [])
        by = {x.id: x for x in rep.steps}
        self.assertEqual(by["keys"].status, "deferred")
        self.assertTrue(any(b["dispatcher"] == "exit" and b["key"] == "m" for b in s.fh.binds))

    def test_kde_is_refused_without_touching_anything(self):
        e = Env(bins={"hyprctl", "qs"}, env_extra={"XDG_CURRENT_DESKTOP": "KDE", "WAYLAND_DISPLAY": "wayland-0"})
        self.addCleanup(e.__exit__)
        eng = AttachEngine(e.ctx, Registry(e.ctx), ProcessManager(e.ctx))
        rep = eng.attach()
        self.assertEqual(rep.code, EXIT_UNAVAILABLE)
        self.assertEqual(e.runner.calls, [])
        self.assertIn("KDE", rep.steps[0].detail)
        self.assertFalse((e.ctx.state_dir / "attach.json").exists())

    def test_no_session_exit_code(self):
        e = Env(bins={"hyprctl"})
        self.addCleanup(e.__exit__)
        rep = AttachEngine(e.ctx, Registry(e.ctx)).attach()
        self.assertEqual(rep.code, 3)

    def test_missing_dependencies_declined(self):
        state, resp = dnf_responses(available={"hyprland", "kitty", "fuzzel", "quickshell", "qt6-qml"})
        s = Scene(self, yes=False, bins=("hyprctl", "qs", "dnf"), extra_responses=resp)
        with no_links(), fake_kill(s.alive):
            rep = s.engine.attach()
        by = {x.id: x for x in rep.steps}
        self.assertEqual(by["deps"].status, "warn")
        self.assertFalse(s.e.runner.called("dnf", "-y", "install"))
        self.assertEqual(state["installed"], set())

    def test_missing_dependencies_installed_after_consent(self):
        state, resp = dnf_responses(available={"hyprland", "kitty", "fuzzel", "quickshell", "qt6-qml"})
        s = Scene(self, yes=True, bins=("hyprctl", "qs", "dnf"), extra_responses=resp)
        with no_links(), fake_kill(s.alive):
            rep = s.engine.attach()
        self.assertTrue(s.e.runner.called("dnf", "-y", "install"))
        self.assertIn("kitty", state["installed"])
        self.assertFalse(any(("login-session" in " ".join(c)) or ("install-session" in " ".join(c)) for c in s.calls),
                         "Attach не ставит записи экрана входа (SDDM)")
        self.assertIn("deps", [x.id for x in rep.steps])

    def test_quickshell_is_not_installed_blocks_start_but_keeps_session(self):
        s = Scene(self, bins=("hyprctl",))
        with no_links(), fake_kill(s.alive):
            rep = s.engine.attach()
        by = {x.id: x for x in rep.steps}
        self.assertEqual(by["quickshell"].status, "warn")
        self.assertEqual(by["processes"].status, "fail")
        self.assertEqual(rep.code, 1)
        self.assertEqual(s.popen.calls, [])
        self.assertTrue(s.engine.keys.live(s.ctx.env)["ok"], "клавиши применены, сессия цела")

    def test_quickshell_fails_to_start(self):
        s = Scene(self, start=False)
        with no_links(), fake_kill(s.alive):
            rep = s.engine.attach()
        by = {x.id: x for x in rep.steps}
        self.assertEqual(by["processes"].status, "fail")
        self.assertIn("quickshell.log", by["processes"].detail)
        self.assertEqual(rep.code, 1)

    def test_shell_is_started_without_terminal_dependency(self):
        s = Scene(self, ours=True)
        with no_links(), fake_kill(s.alive):
            s.engine.attach()
        args, kw = s.popen.calls[0]
        self.assertTrue(kw["start_new_session"], "отдельная сессия процессов: закрытие терминала не гасит оболочку")
        self.assertEqual(kw["stdin"], __import__("subprocess").DEVNULL)
        self.assertEqual(kw["stdout"], __import__("subprocess").DEVNULL)
        self.assertEqual(args[1:], ["shell", "run"])
        self.assertEqual(kw["env"]["HYPRLAND_INSTANCE_SIGNATURE"], "sigA")

    def test_custom_main_config_is_not_replaced(self):
        s = Scene(self, cmdline=("Hyprland", "-c", "/home/u/custom.conf"))
        hypr_dir = s.ctx.config_dir / "hypr"
        hypr_dir.mkdir(parents=True)
        (hypr_dir / "mine.conf").write_text("# моё")
        with fake_kill(s.alive):
            rep = s.engine.attach()
        by = {x.id: x for x in rep.steps}
        self.assertEqual(by["config"].status, "deferred")
        self.assertIn("custom.conf", by["config"].detail)
        self.assertEqual(s.fh.reloads, 0)
        self.assertTrue((hypr_dir / "mine.conf").exists() and not hypr_dir.is_symlink())
        self.assertEqual(by["keys"].status, "ok", "клавиши применяются через IPC и без смены конфига")

    def test_dry_run_changes_nothing(self):
        s = Scene(self)
        s.e.runner.dry_run = True
        with fake_kill(s.alive):
            rep = s.engine.attach()
        self.assertEqual(s.fh.keywords, [])
        self.assertEqual(s.fh.reloads, 0)
        self.assertEqual(s.popen.calls, [])
        self.assertFalse((s.ctx.state_dir / "attach.json").exists())
        self.assertFalse((s.ctx.state_dir / "snapshots").exists())

    @needs_symlink
    def test_attach_links_config_with_backup_and_detach_restores_it(self):
        s = Scene(self)
        hypr = s.ctx.config_dir / "hypr"
        hypr.mkdir(parents=True)
        (hypr / "hyprland.conf").write_text("# автосгенерированный\n", encoding="utf-8")
        with fake_kill(s.alive):
            rep = s.engine.attach()
            self.assertTrue(hypr.is_symlink(), [x.to_dict() for x in rep.steps])
            self.assertGreaterEqual(s.fh.reloads, 1)
            backups = [p for p in s.ctx.backup_dir.glob("hypr.*")]
            self.assertEqual(len(backups), 1)
            self.assertIn("автосгенерированный", (backups[0] / "hyprland.conf").read_text(encoding="utf-8"))
            dr = s.engine.detach(restore_config=True)
        self.assertEqual(dr.code, 0, [x.to_dict() for x in dr.steps])
        self.assertFalse(hypr.is_symlink())
        self.assertIn("автосгенерированный", (hypr / "hyprland.conf").read_text(encoding="utf-8"))


class DetachFlow(unittest.TestCase):
    def test_detach_stops_only_project_processes_and_never_hyprland(self):
        s = Scene(self)
        with no_links(), fake_kill(s.alive) as sent:
            s.engine.attach()
            self.assertIn(SHELL_PID, s.alive)
            rep = s.engine.detach()
        self.assertEqual(rep.code, 0)
        self.assertIn((SHELL_PID, 15), sent)
        self.assertEqual([p for p, sig in sent if p == HYPR_PID and sig != 0], [], "Hyprland не получает сигналов")
        self.assertIn(HYPR_PID, s.alive)
        self.assertFalse(s.called_with("hyprctl", "dispatch"))
        self.assertFalse(s.called_with("exit"))
        # IPC-привязки сняты: вернулся конфиг сессии
        self.assertTrue(any(b["dispatcher"] == "exit" and b["key"] == "m" for b in s.fh.binds))
        st = json.loads((s.ctx.state_dir / "attach.json").read_text(encoding="utf-8"))
        self.assertFalse(st["attached"])

    def test_detach_without_attach_is_harmless(self):
        s = Scene(self, ours=True)
        with fake_kill(s.alive) as sent:
            rep = s.engine.detach()
        self.assertEqual(rep.code, 0)
        self.assertEqual([p for p, sig in sent if sig != 0], [])
        self.assertEqual(s.fh.reloads, 0)

    def test_restore_without_changes_says_nothing_to_restore(self):
        s = Scene(self)
        with fake_kill(s.alive):
            rep = s.engine.detach(restore_config=True)
        self.assertTrue(any("восстанавливать нечего" in x.detail for x in rep.steps))


class Processes(unittest.TestCase):
    def test_foreign_process_with_similar_name_is_never_killed(self):
        s = Scene(self, ours=True)
        lock = s.shell.lock_path(s.ctx.env)
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("9999\n")
        write_cmdline(s.e, 9999, "firefox", "--hyprown-docs")  # «hyprown» в имени, но это не наш супервизор
        s.alive.add(9999)
        with fake_kill(s.alive) as sent:
            rows = s.proc.stop_all(s.ctx.env)
            self.assertIsNone(s.shell.running_pid(s.ctx.env))
        self.assertEqual(rows[0]["result"], "absent")
        self.assertEqual([p for p, sig in sent if sig == 15], [])
        self.assertIn(9999, s.alive)

    def test_pid_reuse_by_foreign_process_does_not_block_start(self):
        s = Scene(self, ours=True)
        lock = s.shell.lock_path(s.ctx.env)
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("9999\n")
        write_cmdline(s.e, 9999, "/usr/bin/some-daemon")
        s.alive.add(9999)
        with fake_kill(s.alive):
            rows = s.proc.start_all(s.ctx.env)
        self.assertEqual(rows[0]["result"], "started")

    def test_start_all_is_idempotent(self):
        s = Scene(self, ours=True)
        with fake_kill(s.alive):
            a = s.proc.start_all(s.ctx.env)
            b = s.proc.start_all(s.ctx.env)
        self.assertEqual((a[0]["result"], b[0]["result"]), ("started", "already"))
        self.assertEqual(len(s.popen.calls), 1)

    def test_restart_all_replaces_the_process(self):
        s = Scene(self, ours=True)
        with fake_kill(s.alive) as sent:
            s.proc.start_all(s.ctx.env)
            rows = s.proc.restart_all(s.ctx.env)
        self.assertEqual([r["result"] for r in rows], ["stopped", "started"])
        self.assertEqual(len(s.popen.calls), 2)
        self.assertIn((SHELL_PID, 15), sent)

    def test_restart_rate_limit(self):
        s = Scene(self, ours=True, start=False)
        with fake_kill(s.alive):
            results = [s.proc.start_all(s.ctx.env)[0]["result"] for _ in range(RESTART_LIMIT + 2)]
        self.assertEqual(results[:RESTART_LIMIT], ["failed"] * RESTART_LIMIT)
        self.assertEqual(results[RESTART_LIMIT:], ["throttled"] * 2)
        self.assertEqual(len(s.popen.calls), RESTART_LIMIT)

    def test_no_wayland_blocks_start(self):
        s = Scene(self, ours=True)
        env = dict(s.ctx.env, WAYLAND_DISPLAY="")
        rows = s.proc.start_all(env)
        self.assertEqual(rows[0]["result"], "blocked")
        self.assertIn("Wayland", rows[0]["detail"])

    def test_status_reports_modules_of_the_shell(self):
        s = Scene(self, ours=True)
        with fake_kill(s.alive):
            before = s.proc.status(s.ctx.env)
            s.proc.start_all(s.ctx.env)
            after = s.proc.status(s.ctx.env)
        self.assertEqual(before[0]["state"], "stopped")
        self.assertEqual(after[0]["state"], "running")
        self.assertEqual([r["id"] for r in after[1:]], ["wallpaper", "widgets", "ipc", "theme"])
        self.assertTrue(all(r["state"] == "running" for r in after[1:]))
        self.assertEqual(ProcessManager.summary(after)["running"], 1)

    def test_actions_are_logged(self):
        s = Scene(self, ours=True)
        with fake_kill(s.alive):
            s.proc.start_all(s.ctx.env)
        self.assertIn("start-all", (s.ctx.log_dir / "session.log").read_text(encoding="utf-8"))

    def test_leftover_child_is_stopped_only_if_it_is_quickshell(self):
        s = Scene(self, ours=True)
        sh = s.shell
        child = sh.child_path(s.ctx.env)
        child.parent.mkdir(parents=True, exist_ok=True)
        child.write_text("8888\n")
        write_cmdline(s.e, 8888, "/usr/bin/vim")
        s.alive.add(8888)
        self.assertIsNone(sh.child_pid(s.ctx.env))
        write_cmdline(s.e, 8888, "/usr/bin/qs", "-p", "/x/shell.qml")
        self.assertEqual(sh.child_pid(s.ctx.env), 8888)


class SettingsClassification(unittest.TestCase):
    def test_real_repo_defers_session_wrapper(self):
        e = Env()
        self.addCleanup(e.__exit__)
        cls = classify_settings(e.ctx)
        self.assertTrue(any("hyprland-session" in x for x in cls["new_session"]))
        self.assertTrue(any("reload" in x or "тот же главный файл" in x for x in cls["reload"]))

    def test_env_variables_need_a_new_session(self):
        e = Env()
        self.addCleanup(e.__exit__)
        repo = e.tmp / "repo"
        (repo / "hypr").mkdir(parents=True)
        (repo / "hypr" / "gpu.conf").write_text("# env = X,Y\nenv = LIBVA_DRIVER_NAME,nvidia\n", encoding="utf-8")
        ctx = replace(e.ctx, repo=repo)
        cls = classify_settings(ctx)
        env_items = [x for x in cls["new_session"] if "LIBVA_DRIVER_NAME" in x]
        self.assertEqual(len(env_items), 1)  # закомментированная строка не считается
        self.assertIn("при старте Hyprland", env_items[0])


class MenuAndCli(unittest.TestCase):
    def ids(self, s):
        env = detect_environment(s.ctx)
        units = s.proc.status(env.target_env(s.ctx.env))
        return applicable(s.ctx, env, units, s.engine.load_state())

    def test_attach_is_first_inside_hyprland(self):
        s = Scene(self)
        ids = self.ids(s)
        self.assertEqual(ids[0], "attach")
        self.assertIn("start", ids)
        self.assertNotIn("restart", ids)
        self.assertNotIn("restore", ids)
        self.assertEqual(ids[-1], "exit")

    def test_menu_after_attach_offers_restart_and_restore(self):
        s = Scene(self)
        with no_links(), fake_kill(s.alive):
            s.engine.attach()
            ids = self.ids(s)
        self.assertIn("restart", ids)
        self.assertIn("restore", ids)
        self.assertNotIn("start", ids)

    def test_menu_in_kde_hides_attach_and_offers_preview(self):
        e = Env(bins={"qs"}, env_extra={"XDG_CURRENT_DESKTOP": "KDE", "WAYLAND_DISPLAY": "wayland-0"})
        self.addCleanup(e.__exit__)
        env = detect_environment(e.ctx)
        ids = applicable(e.ctx, env, [], {})
        self.assertNotIn("attach", ids)
        self.assertNotIn("start", ids)
        self.assertIn("preview", ids)
        self.assertEqual(ids[0], "install")

    def run_cmd(self, fn, s, argv):
        args = build_parser().parse_args(argv)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = fn(s.ctx, args)
        return code, buf.getvalue()

    def test_cli_attach_json(self):
        s = Scene(self, ours=True)
        with no_links(), fake_kill(s.alive):
            args = build_parser().parse_args(["attach", "--json", "--yes"])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                import hyprown.cli as cli
                orig = cli.AttachEngine
                cli.AttachEngine = lambda ctx, reg: AttachEngine(ctx, reg, s.proc)
                try:
                    code = cmd_attach(s.ctx, args)
                finally:
                    cli.AttachEngine = orig
        data = json.loads(buf.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(data["ok"])
        self.assertEqual(data["environment"]["kind"], "hyprlandown")
        self.assertEqual(data["units"][0]["state"], "running")

    def test_cli_attach_in_kde_returns_6(self):
        e = Env(env_extra={"XDG_CURRENT_DESKTOP": "KDE", "WAYLAND_DISPLAY": "wayland-0"})
        self.addCleanup(e.__exit__)
        s = type("S", (), {"ctx": e.ctx})()
        code, _ = self.run_cmd(cmd_attach, s, ["attach"])
        self.assertEqual(code, EXIT_UNAVAILABLE)

    def test_cli_session_status_json(self):
        s = Scene(self, ours=True)
        code, out = self.run_cmd(cmd_session, s, ["session", "status", "--json"])
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(data["environment"]["kind"], "hyprlandown")
        self.assertTrue(data["keys"]["ok"])
        self.assertEqual(data["units"][0]["state"], "stopped")

    def test_cli_session_start_all_refused_in_kde(self):
        e = Env(env_extra={"XDG_CURRENT_DESKTOP": "KDE", "WAYLAND_DISPLAY": "wayland-0"})
        self.addCleanup(e.__exit__)
        s = type("S", (), {"ctx": e.ctx})()
        code, _ = self.run_cmd(cmd_session, s, ["session", "start-all"])
        self.assertEqual(code, EXIT_UNAVAILABLE)

    def test_cli_keys_verify_and_check(self):
        s = Scene(self, ours=True)
        self.assertEqual(self.run_cmd(cmd_keys, s, ["keys", "verify"])[0], 0)
        code, out = self.run_cmd(cmd_keys, s, ["keys", "check", "manager", "--mods", "SUPER", "--key", "E", "--json"])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out)["ok"])
        code, _ = self.run_cmd(cmd_keys, s, ["keys", "check", "manager", "--mods", "SUPER SHIFT", "--key", "X"])
        self.assertEqual(code, 0)

    def test_cli_keys_live_reports_missing_keys_of_stock_config(self):
        s = Scene(self)
        code, out = self.run_cmd(cmd_keys, s, ["keys", "live", "--json"])
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(next(i for i in data["items"] if i["id"] == "manager")["status"], "missing")
        self.assertEqual(next(i for i in data["items"] if i["id"] == "terminal")["status"], "ok")

    def test_cli_keys_set_applies_through_ipc_only_after_consent(self):
        s = Scene(self, yes=False)
        code, _ = self.run_cmd(cmd_keys, s, ["keys", "set", "manager", "--mods", "SUPER", "--key", "S", "--apply", "--force"])
        self.assertEqual(s.fh.keywords, [], "без разрешения чужие привязки (Super+S magic) не снимаются")
        self.assertEqual(s.engine.keys.user()["overrides"]["manager"]["key"], "S", "само назначение сохранено")

    def test_cli_keys_set_with_yes_applies(self):
        s = Scene(self, yes=True)
        code, _ = self.run_cmd(cmd_keys, s, ["keys", "set", "manager", "--mods", "SUPER SHIFT", "--key", "X", "--apply", "--yes"])
        self.assertEqual(code, 0)
        self.assertTrue(any(b["key"] == "x" and b["modmask"] == 65 for b in s.fh.binds))

    def test_cli_keys_set_rejects_conflict(self):
        s = Scene(self)
        code, _ = self.run_cmd(cmd_keys, s, ["keys", "set", "manager", "--mods", "SUPER", "--key", "E"])
        self.assertEqual(code, 2)
        self.assertEqual(s.engine.keys.user()["overrides"], {})

    def test_global_flags_before_subcommand_are_kept(self):
        """Регрессия: `--plain --yes install` раньше терял флаги из-за перезаписи в подпарсере."""
        p = build_parser()
        a = p.parse_args(["--plain", "--yes", "--json", "install"])
        self.assertTrue(a.yes and a.plain and a.json)
        b = p.parse_args(["install", "--yes"])
        self.assertTrue(b.yes)
        c = p.parse_args(["install"])
        self.assertFalse(c.yes)
        d = p.parse_args(["--yes", "detach", "--restore-config"])
        self.assertTrue(d.yes and d.restore_config)


if __name__ == "__main__":
    unittest.main()
