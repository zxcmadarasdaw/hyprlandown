import itertools
import unittest
from pathlib import Path

from hyprown.shell import ShellManager, parse_caps, Caps
from tests.helpers import Env, ok

HELP_NEW = """Usage: qs [options]
  -p, --path PATH   Path to shell.qml
  -c, --config NAME Name of config in ~/.config/quickshell
  -n, --no-duplicate Exit if another instance is running
"""


class FakeProc:
    def __init__(self, code, tick, lived):
        self.code, self.tick, self.lived = code, tick, lived

    def wait(self):
        self.tick.advance(self.lived)
        return self.code

    def terminate(self):
        pass


class Tick:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class Caps_(unittest.TestCase):
    def test_parse_new_cli(self):
        c = parse_caps(HELP_NEW, "qs", "0.2.1")
        self.assertTrue(c.has_path and c.has_config and c.has_no_duplicate)

    def test_parse_only_config(self):
        c = parse_caps("Usage: qs -c NAME", "qs")
        self.assertFalse(c.has_path)
        self.assertTrue(c.has_config)

    def test_strategies_prefer_file_path_then_dir_then_name(self):
        with Env() as e:
            sm = ShellManager(e.ctx)
            s = sm.strategies(parse_caps(HELP_NEW, "qs"), Path("/x/shell.qml"))
            self.assertEqual(s[0], ["-p", str(Path("/x/shell.qml"))])
            self.assertEqual(s[1][0], "-p")
            self.assertEqual(s[-1], ["-c", "hyprdesk"])

    def test_probe_runs_real_help(self):
        with Env(bins={"qs"}, responses=[(("qs", "--help"), ok(HELP_NEW)), (("qs", "--version"), ok("quickshell 0.2.1"))]) as e:
            c = ShellManager(e.ctx).probe()
            self.assertEqual((c.binary, c.version, c.has_path), ("qs", "0.2.1", True))


class FindShell(unittest.TestCase):
    def test_find_repo_shell_qml_is_absolute_and_real(self):
        with Env() as e:
            f = ShellManager(e.ctx).find_shell()
            self.assertTrue(f.is_absolute())
            self.assertEqual(f.name, "shell.qml")

    def test_env_override_wins(self):
        with Env() as e:
            d = e.tmp / "custom"
            d.mkdir()
            (d / "shell.qml").write_text("")
            e.ctx.env["HYPRDESK_SHELL_DIR"] = str(d)
            self.assertEqual(ShellManager(e.ctx).find_shell(), (d / "shell.qml").resolve())


class Supervisor(unittest.TestCase):
    def setUp(self):
        self.e = Env(bins={"qs"}, responses=[(("qs", "--help"), ok(HELP_NEW)), (("qs", "--version"), ok("0.2.1"))])
        self.ctx = self.e.ctx
        sock = self.e.tmp / "run"
        sock.mkdir(parents=True, exist_ok=True)
        (sock / "wayland-9").write_text("")
        self.ctx.env.update({"WAYLAND_DISPLAY": "wayland-9", "HYPRLAND_INSTANCE_SIGNATURE": "sigA"})
        self.tick = Tick()
        self.launched = []

    def tearDown(self):
        self.e.__exit__()

    def mgr(self, plan):
        """plan: [(код выхода, сколько прожил)] по порядку запусков."""
        it = iter(plan)

        def popen(args, **kw):
            self.launched.append(args)
            code, lived = next(it)
            return FakeProc(code, self.tick, lived)

        return ShellManager(self.ctx, popen=popen, sleep=lambda s: self.tick.advance(s), clock=self.tick)

    def run_loop(self, sm):
        caps = parse_caps(HELP_NEW, "qs", "0.2.1")
        return sm._loop(caps, Path("/x/shell.qml"), self.ctx.env, self.e.tmp / "q.log", {"flag": False, "child": None})

    def test_falls_back_to_next_strategy_when_first_dies_fast(self):
        sm = self.mgr([(1, 0.2), (0, 20)])
        self.assertEqual(self.run_loop(sm), 0)
        self.assertEqual(self.launched[0][1:3], ["-p", str(Path("/x/shell.qml"))])
        self.assertEqual(self.launched[1][1:3], ["-p", str(Path("/x"))])

    def test_gives_up_when_every_strategy_fails(self):
        sm = self.mgr([(1, 0.1)] * 5)
        self.assertEqual(self.run_loop(sm), 1)
        self.assertEqual(len(self.launched), 3)

    def test_clean_exit_is_not_restarted(self):
        sm = self.mgr([(0, 60)])
        self.assertEqual(self.run_loop(sm), 0)
        self.assertEqual(len(self.launched), 1)

    def test_restarts_after_crash_then_stops_on_clean_exit(self):
        sm = self.mgr([(139, 30), (0, 30)])
        self.assertEqual(self.run_loop(sm), 0)
        self.assertEqual(len(self.launched), 2)
        self.assertEqual(self.launched[0], self.launched[1])  # та же рабочая стратегия

    def test_crash_loop_protection(self):
        sm = self.mgr([(139, 10)] * 10)
        self.assertEqual(self.run_loop(sm), 1)
        self.assertLessEqual(len(self.launched), 7)

    def test_exits_when_compositor_socket_disappears(self):
        sm = self.mgr([(139, 10), (0, 10)])
        (self.e.tmp / "run" / "wayland-9").unlink()
        self.assertEqual(self.run_loop(sm), 0)
        self.assertEqual(self.launched, [])

    def test_no_duplicate_flag_added_when_supported(self):
        sm = self.mgr([(0, 20)])
        self.run_loop(sm)
        self.assertIn("--no-duplicate", self.launched[0])

    def test_run_refuses_without_wayland(self):
        self.ctx.env["WAYLAND_DISPLAY"] = ""
        self.assertEqual(self.mgr([]).run(self.ctx.env), 3)

    def test_second_supervisor_does_not_start(self):
        import os
        sm = self.mgr([])
        lock = sm.lock_path(self.ctx.env)
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(str(os.getpid()))  # «живой» процесс: текущий
        self.assertEqual(sm.run(self.ctx.env), 0)
        self.assertEqual(self.launched, [])

    def test_stale_lock_is_ignored(self):
        sm = self.mgr([])
        lock = sm.lock_path(self.ctx.env)
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("999999999")
        self.assertIsNone(sm.running_pid(self.ctx.env))

    def test_ipc_uses_the_same_selector_that_started_the_shell(self):
        sm = self.mgr([(0, 20)])
        self.run_loop(sm)
        sm.ctx.runner.calls.clear()
        sm.ipc(["canvas", "toggleEdit"], self.ctx.env)
        call = sm.ctx.runner.calls[-1]
        self.assertEqual(call[:3], ["qs", "ipc", "-p"])
        self.assertEqual(call[-2:], ["canvas", "toggleEdit"])


class Detached(unittest.TestCase):
    def test_start_detached_uses_new_session_and_no_stdio(self):
        import subprocess
        with Env(bins={"qs"}) as e:
            calls = []
            sm = ShellManager(e.ctx, popen=lambda a, **kw: calls.append((a, kw)))
            sm.start_detached({"XDG_RUNTIME_DIR": str(e.tmp)})
            args, kw = calls[0]
            self.assertTrue(kw["start_new_session"])
            self.assertEqual(kw["stdin"], subprocess.DEVNULL)
            self.assertEqual(args[1:], ["shell", "run"])


if __name__ == "__main__":
    unittest.main()
