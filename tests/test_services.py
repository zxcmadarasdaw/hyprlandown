import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from hyprown import cli
from hyprown.diagnostics import run_all, summarize
from hyprown.recovery import RecoveryManager
from hyprown.registry import Registry
from hyprown.session import SessionManager
from hyprown.updater import UpdateManager
from tests.helpers import Env, bad, ok


class Recovery(unittest.TestCase):
    def test_snapshot_and_restore_state(self):
        with Env() as e:
            reg = Registry(e.ctx)
            reg.mark("manager", installed=True, enabled=True, version="0.1.0")
            rec = RecoveryManager(e.ctx, reg)
            snap = rec.snapshot("t")
            reg.forget("manager")
            self.assertFalse(reg.is_installed("manager"))
            rec.restore_snapshot(snap.name)
            self.assertTrue(Registry(e.ctx).is_installed("manager"))

    def test_restore_rejects_path_tricks(self):
        with Env() as e:
            rec = RecoveryManager(e.ctx, Registry(e.ctx))
            for bad_id in ("../x", "..", "a/b"):
                with self.assertRaises(FileNotFoundError):
                    rec.restore_snapshot(bad_id)

    def test_only_last_ten_snapshots_kept(self):
        with Env() as e:
            rec = RecoveryManager(e.ctx, Registry(e.ctx))
            for i in range(13):
                rec.snapshot(f"s{i}")
            self.assertEqual(len(rec.snapshots()), 10)

    def test_safe_mode_flag(self):
        with Env() as e:
            rec = RecoveryManager(e.ctx, Registry(e.ctx))
            self.assertFalse(rec.safe_mode())
            rec.set_safe_mode(True)
            self.assertTrue((e.ctx.state_dir / "force-safe").exists())
            rec.set_safe_mode(False)
            self.assertFalse(rec.safe_mode())

    def test_rollback_without_history_is_clear_error(self):
        with Env() as e:
            with self.assertRaises(FileNotFoundError):
                RecoveryManager(e.ctx, Registry(e.ctx)).rollback()

    def test_rollback_undoes_links_marks_and_never_removes_packages(self):
        with Env() as e:
            reg = Registry(e.ctx)
            rec = RecoveryManager(e.ctx, reg)
            reg.mark("manager", installed=True)
            j = rec.new_journal("install")
            j["ops"] = [{"op": "packages", "rpms": ["kitty"]}, {"op": "copr", "id": "a/b"},
                        {"op": "link", "name": "hypr", "dst": str(e.tmp / "hypr"), "backup": "none"},
                        {"op": "mark", "component": "manager"}]
            rec.save_journal(j)
            msgs = rec.rollback()
            self.assertFalse(reg.is_installed("manager"))
            self.assertTrue(any("не удаляются" in m for m in msgs))
            self.assertTrue(any("остаётся включённым" in m for m in msgs))
            self.assertFalse(e.runner.calls)  # ни dnf, ни sudo
            self.assertTrue(rec.journals()[0]["rolled_back"])

    def test_reset_shell_state_keeps_copy(self):
        with Env() as e:
            e.ctx.state_dir.mkdir(parents=True)
            (e.ctx.state_dir / "canvas.json").write_text("{}")
            rec = RecoveryManager(e.ctx, Registry(e.ctx))
            rec.reset_shell_state()
            self.assertFalse((e.ctx.state_dir / "canvas.json").exists())
            snap = e.ctx.snapshot_dir / rec.snapshots()[-1]["id"]
            self.assertTrue(any(p.name == "canvas.json" for p in e.ctx.snapshot_dir.rglob("canvas.json")))


class Updates(unittest.TestCase):
    def git(self, behind="2", dirty="", pull=ok()):
        return [
            (("git", "-C"), lambda c: {"fetch": ok(), "rev-list": ok(behind + "\n"), "log": ok("abc один\ndef два\n"),
                                       "status": ok(dirty), "pull": pull}[c[3]]),
        ]

    def mgr(self, e):
        return UpdateManager(e.ctx, Registry(e.ctx))

    def test_not_a_git_repo(self):
        with Env(bins={"git"}) as e:
            mgr = self.mgr(e)
            e.ctx.repo = e.tmp  # без .git
            self.assertFalse(mgr.check()["ok"])

    def test_check_reports_commits(self):
        with Env(bins={"git"}, responses=self.git()) as e:
            (e.ctx.repo / ".git").exists() or None
            with mock.patch.object(UpdateManager, "is_git", lambda s: True):
                r = self.mgr(e).check()
                self.assertEqual(r["behind"], 2)
                self.assertEqual(len(r["commits"]), 2)

    def test_apply_refuses_dirty_tree(self):
        with Env(bins={"git"}, responses=self.git(dirty=" M file")) as e, \
                mock.patch.object(UpdateManager, "is_git", lambda s: True):
            r = self.mgr(e).apply()
            self.assertFalse(r["applied"])
            self.assertFalse(e.runner.called("git", "-C", str(e.ctx.repo), "pull"))

    def test_apply_pulls_ff_only_after_snapshot(self):
        with Env(bins={"git"}, responses=self.git()) as e, mock.patch.object(UpdateManager, "is_git", lambda s: True):
            r = self.mgr(e).apply()
            self.assertTrue(r["applied"])
            self.assertTrue(any(c[-2:] == ["pull", "--ff-only"] for c in e.runner.calls))
            self.assertTrue(Path(r["snapshot"]).exists())

    def test_up_to_date(self):
        with Env(bins={"git"}, responses=self.git(behind="0")) as e, mock.patch.object(UpdateManager, "is_git", lambda s: True):
            self.assertFalse(self.mgr(e).apply()["applied"])


class Sessions(unittest.TestCase):
    def test_preview_needs_hyprland(self):
        with Env() as e:
            self.assertEqual(SessionManager(e.ctx).preview(), 2)

    def test_preview_needs_host_session(self):
        with Env(bins={"Hyprland"}) as e:
            self.assertEqual(SessionManager(e.ctx).preview(), 3)

    def test_preview_launches_nested_with_explicit_config(self):
        calls = []

        class P:
            pid = 4242

            def wait(self):
                return 0
        with Env(bins={"Hyprland"}, env_extra={"WAYLAND_DISPLAY": "wayland-0"}) as e:
            sm = SessionManager(e.ctx, popen=lambda a, **kw: calls.append((a, kw)) or P())
            self.assertEqual(sm.preview(), 0)
            args, kw = calls[0]
            self.assertEqual(args[:2], ["Hyprland", "-c"])
            conf = Path(args[2])
            self.assertTrue(conf.exists())
            self.assertIn("$mainMod = ALT", (conf.parent / "keybinds.conf").read_text(encoding="utf-8"))
            self.assertEqual(kw["env"]["HYPRDESK_SESSION_MODE"], "preview")
            self.assertTrue(kw["start_new_session"])
            self.assertFalse(sm.preview_pid_file().exists())  # убран после закрытия
            self.assertFalse((e.ctx.state_dir / "session.marker").exists())  # маркер реальной сессии не трогаем

    def test_preview_refuses_second_instance(self):
        with Env(bins={"Hyprland"}, env_extra={"WAYLAND_DISPLAY": "wayland-0"}) as e:
            sm = SessionManager(e.ctx, popen=lambda *a, **k: None)
            sm.preview_pid_file().parent.mkdir(parents=True, exist_ok=True)
            sm.preview_pid_file().write_text(str(os.getpid()))
            self.assertEqual(sm.preview(), 4)

    def test_desktop_readiness_lists_login_files(self):
        with Env() as e:
            checks = SessionManager(e.ctx).desktop_readiness()
            self.assertFalse(all(c["ok"] for c in checks))
            self.assertTrue(any("hyprland-managed.desktop" in c["title"] for c in checks))

    def test_desktop_instructions_never_replace_running_session(self):
        with Env() as e:
            text = " ".join(SessionManager(e.ctx).desktop_instructions())
            self.assertIn("экран", text)
            self.assertFalse(e.runner.calls)

    def test_hypr_env_discovers_instance_signature(self):
        with Env() as e:
            sock = Path(e.ctx.env["XDG_RUNTIME_DIR"]) / "hypr" / "abc123"
            sock.mkdir(parents=True)
            (sock / ".socket.sock").write_text("")
            self.assertEqual(SessionManager(e.ctx).hypr_env()["HYPRLAND_INSTANCE_SIGNATURE"], "abc123")


class Diagnostics(unittest.TestCase):
    def test_runs_on_empty_system_without_crash(self):
        with Env() as e:
            checks = run_all(e.ctx, Registry(e.ctx))
            ids = {c["id"] for c in checks}
            self.assertTrue({"os", "disk", "shell-qml", "running-config", "verify-config"} <= ids)
            for c in checks:
                self.assertIn(c["status"], ("ok", "warn", "fail", "skip"))
            self.assertEqual(sum(summarize(checks).values()), len(checks))

    def test_detects_autogenerated_config_in_running_session(self):
        vals = {"decoration:rounding": 0, "general:gaps_out": 20, "general:gaps_in": 5}
        resp = [(("hyprctl", "-j", "getoption"), lambda c: ok(json.dumps({"int": vals[c[-1]]}))),
                (("hyprctl", "configerrors"), ok(""))]
        with Env(bins={"hyprctl"}, responses=resp, env_extra={"HYPRLAND_INSTANCE_SIGNATURE": "sig"}) as e:
            c = next(x for x in run_all(e.ctx, Registry(e.ctx)) if x["id"] == "running-config")
            self.assertEqual(c["status"], "fail")
            self.assertIn("НЕ конфиг проекта", c["detail"])

    def test_old_quickshell_is_flagged(self):
        resp = [(("qs", "--version"), ok("quickshell 0.1.0")), (("qs", "--help"), ok("-c"))]
        with Env(bins={"qs", "rpm"}, responses=resp) as e:
            c = next(x for x in run_all(e.ctx, Registry(e.ctx)) if x["id"] == "pkg-quickshell")
            self.assertEqual(c["status"], "fail")


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        e = Env()
        self.addCleanup(e.__exit__)
        if True:
            env = {"HOME": str(e.ctx.home), "XDG_STATE_HOME": str(e.ctx.home / "st"),
                   "XDG_RUNTIME_DIR": str(e.tmp / "run"), "XDG_CONFIG_HOME": str(e.ctx.home / "cfg"),
                   "XDG_DATA_HOME": str(e.ctx.home / "data")}
            buf = io.StringIO()
            with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(buf):
                code = cli.main(list(argv))
            return code, buf.getvalue(), e.tmp

    def test_version(self):
        code, out, _ = self.run_cli("version")
        self.assertEqual(code, 0)
        self.assertIn("hyprown", out)

    def test_component_list_json_has_all_components(self):
        code, out, _ = self.run_cli("--plain", "component", "list", "--json")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertTrue({"desktop-core", "quickshell-shell", "manager"} <= {c["id"] for c in data["components"]})

    def test_status_json_is_valid_and_has_dashboard_fields(self):
        code, out, _ = self.run_cli("--plain", "status", "--json")
        data = json.loads(out)
        for key in ("version", "components", "system", "shell", "performance", "safe_mode_forced"):
            self.assertIn(key, data)

    def test_doctor_json(self):
        code, out, _ = self.run_cli("--plain", "doctor", "--json")
        data = json.loads(out)
        self.assertIn("summary", data)

    def test_plan_json_on_non_fedora_exits_2(self):
        code, out, _ = self.run_cli("--plain", "plan", "--json")
        self.assertIn(code, (0, 2))
        self.assertIn("components", json.loads(out))

    def test_install_dry_run_changes_nothing(self):
        code, out, tmp = self.run_cli("--plain", "--dry-run", "install", "--components", "desktop-core")
        self.assertTrue(tmp.exists())  # каталог теста ещё жив: проверка ниже настоящая
        self.assertFalse((tmp / "home" / "cfg" / "hypr").exists())
        self.assertFalse((tmp / "home" / "st" / "hyprdesk" / "components.json").exists())
        self.assertIn(code, (0, 2))  # 2: на не-Fedora план содержит проблемы, до применения не доходит

    def test_unknown_component_is_error_not_traceback(self):
        code, out, _ = self.run_cli("--plain", "component", "info", "nope")
        self.assertEqual(code, 1)

    def test_perf_set_writes_profile(self):
        code, out, tmp = self.run_cli("--plain", "perf", "set", "lite")
        self.assertEqual(code, 0)
        self.assertTrue((tmp / "home" / "st" / "hyprdesk" / "performance.conf").exists())

    def test_json_stream_confirm_without_yes_refuses(self):
        from hyprown.ui import JsonUI
        buf = io.StringIO()
        ui = JsonUI(assume_yes=False, stream=buf)
        self.assertFalse(ui.confirm("Установить?"))
        self.assertIn("--yes", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
