import json
import os
import unittest
from pathlib import Path

from hyprown.config import ConfigManager, PERF_PROFILES
from hyprown.pkg import version_ge, parse_version
from hyprown.registry import Registry
from hyprown.system import detect, parse_os_release
from tests.helpers import Env, needs_symlink, ok, bad


class SystemDetection(unittest.TestCase):
    def test_fedora_detected(self):
        with Env() as e:
            i = detect(e.ctx)
            self.assertTrue(i.is_fedora)
            self.assertEqual(i.version_id, "45")
            self.assertFalse(i.is_live)
            self.assertEqual(i.gpu, "amd")

    def test_live_usb_detected(self):
        with Env(live=True) as e:
            self.assertTrue(detect(e.ctx).is_live)

    def test_not_fedora(self):
        with Env(os_release='ID=ubuntu\nVERSION_ID="24.04"\n') as e:
            self.assertFalse(detect(e.ctx).is_fedora)

    def test_nvidia_has_priority(self):
        with Env(gpu="0x10de") as e:
            self.assertEqual(detect(e.ctx).gpu, "nvidia")

    def test_can_nest_needs_display(self):
        with Env(env_extra={"WAYLAND_DISPLAY": "wayland-0"}) as e:
            self.assertTrue(detect(e.ctx).can_nest)
        with Env() as e:
            self.assertFalse(detect(e.ctx).can_nest)

    def test_os_release_parser(self):
        self.assertEqual(parse_os_release('ID=fedora\nPRETTY_NAME="Fedora 45"\n')["PRETTY_NAME"], "Fedora 45")

    def test_versions(self):
        self.assertTrue(version_ge("0.57.1", "0.50.0"))
        self.assertFalse(version_ge("0.49.9", "0.50.0"))
        self.assertTrue(version_ge("0.2", "0.2.0"))
        self.assertEqual(parse_version("Hyprland 0.57.1 built from branch main", r"(\d+\.\d+\.\d+)"), "0.57.1")


class Render(unittest.TestCase):
    def test_desktop_render_has_only_absolute_sources(self):
        with Env() as e:
            out = ConfigManager(e.ctx).render("desktop", e.tmp / "r")
            text = out.read_text(encoding="utf-8")
            sources = [l.split("=", 1)[1].strip() for l in text.splitlines() if l.strip().startswith("source")]
            self.assertGreaterEqual(len(sources), 6)
            for s in sources:
                self.assertTrue(Path(s).is_absolute(), s)
                self.assertTrue(Path(s).exists(), s)
            self.assertNotIn("~/.config/hypr", text)
            self.assertIn("hyprown shell run", text)
            self.assertNotIn("~/.local/bin/hyprown", text)

    def test_preview_uses_alt_not_super(self):
        with Env() as e:
            ConfigManager(e.ctx).render("preview", e.tmp / "r")
            kb = (e.tmp / "r" / "keybinds.conf").read_text(encoding="utf-8")
            self.assertIn("$mainMod = ALT", kb)
            self.assertNotIn("$mainMod = SUPER", kb)
            self.assertIn("kb_options =", (e.tmp / "r" / "hyprland.conf").read_text(encoding="utf-8"))

    def test_desktop_render_keeps_super(self):
        with Env() as e:
            ConfigManager(e.ctx).render("desktop", e.tmp / "r")
            self.assertIn("$mainMod = SUPER", (e.tmp / "r" / "keybinds.conf").read_text(encoding="utf-8"))

    def test_render_creates_performance_file_so_source_never_dangles(self):
        with Env() as e:
            ConfigManager(e.ctx).render("desktop", e.tmp / "r")
            self.assertTrue((e.ctx.state_dir / "performance.conf").exists())

    def test_all_sourced_files_exist_in_repo(self):
        text = (Path(__file__).resolve().parent.parent / "hypr/hyprland.conf").read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("source"):
                name = line.split("=", 1)[1].strip().rsplit("/", 1)[-1]
                if name == "performance.conf":
                    continue  # создаётся установщиком
                self.assertTrue((Path(__file__).resolve().parent.parent / "hypr" / name).exists(), name)


class Verify(unittest.TestCase):
    def test_verify_skipped_without_hyprland(self):
        with Env() as e:
            okk, text = ConfigManager(e.ctx).verify()
            self.assertFalse(okk)
            self.assertIn("не установлен", text)

    def test_verify_reports_error_text(self):
        with Env(bins={"Hyprland"}, responses=[(("Hyprland", "--verify-config"), ok("config error at line 3"))]) as e:
            okk, _ = ConfigManager(e.ctx).verify()
            self.assertFalse(okk)

    def test_verify_ok(self):
        with Env(bins={"Hyprland"}, responses=[(("Hyprland", "--verify-config"), ok("config ok"))]) as e:
            self.assertTrue(ConfigManager(e.ctx).verify()[0])

    def test_lint_flags_removed_options(self):
        with Env() as e:
            self.assertEqual(ConfigManager(e.ctx).lint(), [])  # наши конфиги чистые


class Fingerprint(unittest.TestCase):
    def responses(self, rounding, gaps_out, gaps_in):
        vals = {"decoration:rounding": rounding, "general:gaps_out": gaps_out, "general:gaps_in": gaps_in}
        return [(("hyprctl", "-j", "getoption"),
                 lambda c: ok(json.dumps({"option": c[-1], "int": vals[c[-1]]})))]

    def test_expected_values_come_from_repo(self):
        with Env() as e:
            fp = ConfigManager(e.ctx).expected_fingerprint()
            self.assertEqual(fp, {"decoration:rounding": 22, "general:gaps_out": 10, "general:gaps_in": 5})

    def test_our_config_is_recognised(self):
        with Env(bins={"hyprctl"}, responses=self.responses(22, 10, 5)) as e:
            ours, _ = ConfigManager(e.ctx).uses_our_config({})
            self.assertTrue(ours)

    def test_autogenerated_config_is_detected(self):
        # Стандартные значения Hyprland: rounding 0, gaps_in 5, gaps_out 20.
        with Env(bins={"hyprctl"}, responses=self.responses(0, 20, 5)) as e:
            ours, why = ConfigManager(e.ctx).uses_our_config({})
            self.assertFalse(ours)
            self.assertIn("НЕ конфиг проекта", why)

    def test_unknown_when_hyprctl_fails(self):
        with Env(bins={"hyprctl"}, responses=[(("hyprctl",), bad(1, "no instance"))]) as e:
            ours, why = ConfigManager(e.ctx).uses_our_config({})
            self.assertIsNone(ours)


class Performance(unittest.TestCase):
    def test_profiles_roundtrip(self):
        with Env() as e:
            cfg = ConfigManager(e.ctx)
            self.assertEqual(cfg.perf_profile(), "quality")
            for name in PERF_PROFILES:
                cfg.set_perf_profile(name)
                self.assertEqual(cfg.perf_profile(), name)
            with self.assertRaises(ValueError):
                cfg.set_perf_profile("turbo")


class Links(unittest.TestCase):
    @needs_symlink
    def test_apply_backup_idempotent_rollback(self):
        with Env() as e:
            reg = Registry(e.ctx)
            comp = reg.components["desktop-core"]
            cfg = ConfigManager(e.ctx)
            hypr = e.ctx.config_dir / "hypr"
            hypr.mkdir(parents=True)
            (hypr / "hyprland.conf").write_text("autogenerated")
            journal = []
            cfg.apply_links(comp, journal)
            self.assertTrue(hypr.is_symlink())
            self.assertEqual(Path(os.readlink(hypr)), (e.ctx.repo / "hypr").resolve())
            backup = [o for o in journal if o["name"] == "hypr"][0]["backup"]
            self.assertEqual((Path(backup) / "hyprland.conf").read_text(), "autogenerated")
            journal2 = []
            cfg.apply_links(comp, journal2)
            self.assertEqual(journal2, [])  # повторный запуск ничего не делает
            cfg.unlink_component(comp)
            self.assertFalse(hypr.is_symlink())
            self.assertEqual((hypr / "hyprland.conf").read_text(), "autogenerated")

    @needs_symlink
    def test_wrong_symlink_is_replaced_with_backup(self):
        with Env() as e:
            comp = Registry(e.ctx).components["desktop-core"]
            hypr = e.ctx.config_dir / "hypr"
            hypr.parent.mkdir(parents=True)
            os.symlink(e.tmp, hypr, target_is_directory=True)
            j = []
            ConfigManager(e.ctx).apply_links(comp, j)
            self.assertEqual(Path(os.readlink(hypr)), (e.ctx.repo / "hypr").resolve())
            self.assertTrue(any(o["backup"] != "none" for o in j))

    def test_link_states_report_create_for_clean_home(self):
        with Env() as e:
            states = ConfigManager(e.ctx).link_states(Registry(e.ctx).components["desktop-core"])
            self.assertEqual({s.state for s in states}, {"create"})


if __name__ == "__main__":
    unittest.main()
