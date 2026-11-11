import json
import unittest
from pathlib import Path

from hyprown.installer import Installer, Options
from hyprown.registry import Registry
from tests.helpers import Env, bad, dnf_responses, no_links, ok

BINS = {"dnf", "rpm"}
ALL_AVAILABLE = {"hyprland", "kitty", "fuzzel", "quickshell", "qt6-qtdeclarative", "mpv", "mpvpaper",
                 "ffmpeg-free", "mesa-va-drivers", "libva-utils", "hyprpaper", "hyprlock"}


def make(available=ALL_AVAILABLE, installed=(), **kw):
    state, resp = dnf_responses(available=available, installed_rpms=installed, **kw)
    e = Env(bins=BINS, responses=resp)
    return e, state


def installs(e):
    return [c for c in e.runner.calls if "install" in c and "dnf" in c and "copr" not in c]


class PlanTests(unittest.TestCase):
    def test_plan_for_clean_fedora_lists_packages_and_needs_root(self):
        e, _ = make()
        with e, no_links():
            plan = Installer(e.ctx, Registry(e.ctx)).build_plan(Options(components=["desktop-core"]))
            self.assertEqual(plan.problems, [])
            self.assertTrue(plan.need_root)
            self.assertEqual({p.id for p in plan.pkgs}, {"hyprland", "kitty", "fuzzel"})
            self.assertTrue(all(p.state == "available" for p in plan.pkgs))

    def test_hyprland_missing_from_repos_requires_copr(self):
        e, _ = make(available=ALL_AVAILABLE - {"hyprland"})
        with e, no_links():
            plan = Installer(e.ctx, Registry(e.ctx)).build_plan(Options(components=["desktop-core"]))
            hp = next(p for p in plan.pkgs if p.id == "hyprland")
            self.assertEqual(hp.state, "needs-copr")
            self.assertEqual(hp.copr[0]["id"], "sdegler/hyprland")

    def test_no_copr_blocks_component_and_dependants(self):
        e, _ = make(available=ALL_AVAILABLE - {"hyprland"})
        with e, no_links():
            plan = Installer(e.ctx, Registry(e.ctx)).build_plan(Options(components=["manager"], no_copr=True))
            self.assertIn("desktop-core", plan.blocked)
            self.assertIn("manager", plan.blocked)

    def test_unavailable_required_package_without_source_blocks(self):
        e, _ = make(available=ALL_AVAILABLE - {"kitty"})
        with e, no_links():
            plan = Installer(e.ctx, Registry(e.ctx)).build_plan(Options(components=["desktop-core"]))
            self.assertIn("desktop-core", plan.blocked)

    def test_missing_optional_package_only_warns(self):
        e, _ = make(available=ALL_AVAILABLE - {"mpvpaper"})
        with e, no_links():
            plan = Installer(e.ctx, Registry(e.ctx)).build_plan(Options(components=["wallpaper-engine"]))
            self.assertEqual(plan.blocked, {})
            self.assertTrue(any("mpvpaper" in w for w in plan.warnings))

    def test_not_fedora_is_a_problem(self):
        state, resp = dnf_responses()
        with Env(bins=BINS, responses=resp, os_release="ID=ubuntu\nVERSION_ID=24.04\n") as e, no_links():
            plan = Installer(e.ctx, Registry(e.ctx)).build_plan(Options(components=["desktop-core"]))
            self.assertTrue(plan.problems)

    def test_other_fedora_version_warns(self):
        state, resp = dnf_responses(available=ALL_AVAILABLE)
        with Env(bins=BINS, responses=resp, os_release="ID=fedora\nVERSION_ID=43\n") as e, no_links():
            plan = Installer(e.ctx, Registry(e.ctx)).build_plan(Options(components=["desktop-core"]))
            self.assertTrue(any("проверялся" in w for w in plan.warnings))

    def test_low_disk_is_a_problem(self):
        e, _ = make()
        with e, no_links():
            inst = Installer(e.ctx, Registry(e.ctx))
            inst.info.free_home_mb = 100
            self.assertTrue(any("Мало места" in p for p in inst.build_plan(Options(components=["desktop-core"])).problems))

    def test_default_selection_skips_login_session_on_live(self):
        e, _ = make()
        with e:
            e.ctx.fsroot  # noqa
        state, resp = dnf_responses()
        with Env(bins=BINS, responses=resp, live=True) as e:
            sel = Installer(e.ctx, Registry(e.ctx)).default_selection()
            self.assertNotIn("login-session", sel)
            self.assertIn("desktop-core", sel)
            self.assertNotIn("hyprlock", sel)  # не нужные пакеты не ставятся по умолчанию


class ApplyTests(unittest.TestCase):
    def apply(self, e, ids, **opt):
        reg = Registry(e.ctx)
        inst = Installer(e.ctx, reg)
        o = Options(components=ids, live_ok=True, **opt)
        return inst, reg, inst.apply(inst.build_plan(o), o)

    def test_install_marks_components_and_writes_journal(self):
        e, state = make()
        with e, no_links():
            inst, reg, rep = self.apply(e, ["quickshell-shell"])
            self.assertTrue(rep.ok, rep.failed)
            self.assertEqual(rep.installed, ["desktop-core", "quickshell-shell"])
            self.assertTrue(reg.is_installed("quickshell-shell"))
            self.assertTrue(rep.journal)
            self.assertTrue(e.runner.called("dnf", "-y", "install"))

    def test_assume_yes_never_enables_copr(self):
        e, state = make(available=ALL_AVAILABLE - {"hyprland"})
        with e, no_links():
            inst, reg, rep = self.apply(e, ["desktop-core"])
            self.assertFalse(e.runner.called("dnf", "-y", "copr", "enable"))
            self.assertIn("desktop-core", rep.failed)
            self.assertFalse(reg.is_installed("desktop-core"))

    def test_copr_enabled_after_explicit_confirmation(self):
        e, state = make(available=ALL_AVAILABLE - {"hyprland"})
        with e, no_links():
            asked = []
            e.ui.confirm = lambda q, default=True: asked.append(q) or True
            inst, reg, rep = self.apply(e, ["desktop-core"])
            self.assertTrue(any("sdegler/hyprland" in q for q in asked))
            self.assertTrue(e.runner.called("dnf", "-y", "copr", "enable", "sdegler/hyprland"))
            self.assertTrue(rep.ok, rep.failed)
            ops = json.loads(Path(rep.journal).read_text(encoding="utf-8"))["ops"]
            self.assertIn("sdegler/hyprland", [o["id"] for o in ops if o["op"] == "copr"])

    def test_copr_failure_is_reported_not_crash(self):
        e, state = make(available=ALL_AVAILABLE - {"hyprland"}, copr_ok=False)
        with e, no_links():
            e.ui.confirm = lambda q, default=True: True
            inst, reg, rep = self.apply(e, ["desktop-core"])
            self.assertIn("desktop-core", rep.failed)

    def test_one_failed_component_does_not_break_others(self):
        e, state = make()
        orig = e.runner.responses[:]

        def install(cmd):
            if "hyprpaper" in cmd:
                return bad(1, "boom")
            state["installed"].update(x for x in cmd if not x.startswith("-") and x not in ("sudo", "dnf", "install"))
            return ok()
        e.runner.responses = [r for r in orig if r[0] != ("dnf", "-y", "install")] + [(("dnf", "-y", "install"), install)]
        with e, no_links():
            inst, reg, rep = self.apply(e, ["desktop-core", "hyprpaper"])
            self.assertIn("desktop-core", rep.installed)
            self.assertIn("hyprpaper", rep.failed)
            self.assertTrue(reg.is_installed("desktop-core"))
            self.assertFalse(reg.is_installed("hyprpaper"))
            self.assertTrue(reg.record("hyprpaper").get("failed"))

    def test_failed_recommended_packages_do_not_fail_component(self):
        e, state = make()
        orig = e.runner.responses[:]

        def install(cmd):
            if "mpv" in cmd:
                return bad(1, "mpv boom")
            state["installed"].update(x for x in cmd if not x.startswith("-") and x not in ("sudo", "dnf", "install"))
            return ok()
        e.runner.responses = [r for r in orig if r[0] != ("dnf", "-y", "install")] + [(("dnf", "-y", "install"), install)]
        with e, no_links():
            inst, reg, rep = self.apply(e, ["wallpaper-engine"])
            self.assertIn("wallpaper-engine", rep.installed)
            self.assertTrue(any("рекомендуемые" in w for w in rep.warnings))

    def test_reinstall_is_idempotent_no_second_dnf_install(self):
        e, state = make()
        with e, no_links():
            self.apply(e, ["quickshell-shell"])
            before = len(installs(e))
            inst, reg, rep = self.apply(e, ["quickshell-shell"])
            self.assertTrue(rep.ok)
            self.assertEqual(len(installs(e)), before)

    def test_live_usb_declined_changes_nothing(self):
        state, resp = dnf_responses(available=ALL_AVAILABLE)
        with Env(bins=BINS, responses=resp, live=True) as e, no_links():
            e.ui.confirm = lambda q, default=True: False
            reg = Registry(e.ctx)
            inst = Installer(e.ctx, reg)
            o = Options(components=["desktop-core"])
            rep = inst.apply(inst.build_plan(o), o)
            self.assertFalse(e.runner.called("dnf", "-y", "install"))
            self.assertIn("desktop-core", rep.skipped)

    def test_plan_with_problems_is_never_applied(self):
        state, resp = dnf_responses(available=ALL_AVAILABLE)
        with Env(bins=BINS, responses=resp, os_release="ID=arch\n") as e, no_links():
            inst, reg, rep = self.apply(e, ["desktop-core"])
            self.assertFalse(rep.ok)
            self.assertFalse(e.runner.called("dnf", "-y", "install"))

    def test_login_session_runs_privileged_vetted_script_only_after_confirm(self):
        e, state = make()
        with e, no_links():
            e.ui.confirm = lambda q, default=True: "root" not in q
            inst, reg, rep = self.apply(e, ["login-session"])
            self.assertFalse(any("install-session.sh" in " ".join(c) for c in e.runner.calls))
        e, state = make()
        with e, no_links():
            inst, reg, rep = self.apply(e, ["login-session"])
            call = next(c for c in e.runner.calls if any("install-session.sh" in x for x in c))
            self.assertEqual(call[0], "sudo")
            self.assertEqual(call[-1], "--apply")


class ManageTests(unittest.TestCase):
    def installed(self, e):
        reg = Registry(e.ctx)
        for cid in ("desktop-core", "quickshell-shell", "manager"):
            reg.mark(cid, installed=True, enabled=True, version="0.1.0")
        return reg, Installer(e.ctx, reg)

    def test_cannot_remove_component_with_dependants(self):
        e, _ = make()
        with e, no_links():
            reg, inst = self.installed(e)
            with self.assertRaises(RuntimeError):
                inst.remove("quickshell-shell")

    def test_remove_leaf_forgets_state_and_keeps_packages(self):
        e, _ = make()
        with e, no_links():
            reg, inst = self.installed(e)
            msgs = inst.remove("manager")
            self.assertFalse(reg.is_installed("manager"))
            self.assertTrue(any("Пакеты не удалены" in m for m in msgs))
            self.assertFalse(e.runner.called("dnf", "-y", "remove"))

    def test_enable_disable_and_honest_activation_messages(self):
        e, _ = make()
        with e, no_links():
            reg, inst = self.installed(e)
            r = inst.deactivate("quickshell-shell")
            self.assertFalse(reg.is_enabled("quickshell-shell"))
            self.assertFalse(r["hot"])  # оболочка не запущена: честно говорим, что применится позже
            self.assertIn("не запущена", r["message"])
            inst.activate("quickshell-shell")
            self.assertTrue(reg.is_enabled("quickshell-shell"))

    def test_relogin_activation_is_never_automatic(self):
        e, _ = make()
        with e, no_links():
            reg, inst = self.installed(e)
            reg.mark("login-session", installed=True, enabled=True)
            r = inst.activate("login-session")
            self.assertFalse(r["hot"])
            self.assertIn("перезапуск сессии", r["message"])
            self.assertEqual(e.runner.calls, [])

    def test_enable_uninstalled_fails(self):
        e, _ = make()
        with e, no_links():
            with self.assertRaises(RuntimeError):
                Installer(e.ctx, Registry(e.ctx)).activate("manager")


if __name__ == "__main__":
    unittest.main()
