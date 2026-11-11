"""Theme Engine (этап 4): схема токенов, готовые темы, палитра из обоев, переопределения виджетов."""
import contextlib
import io
import json
import unittest

from hyprown.cli import build_parser, cmd_theme
from hyprown.recovery import RecoveryManager
from hyprown.registry import Registry
from hyprown.theme import (DEFAULT_ID, MIN_HUE_GAP, ROLES, Swatch, ThemeEngine, contrast, hue_dist,
                           migrate, oklch_to_rgb, palette_from_swatches, palette_problems, parse_assignment,
                           rgb_to_oklch, validate_overrides, validate_tokens)
from tests.helpers import Env, REPO, ok


def sw(hex_color, weight):
    h = hex_color.lstrip("#")
    return Swatch(tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)), weight)


def lch(hex_color):
    return rgb_to_oklch(tuple(int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)))


VIVID = [sw("#0E1A2B", 0.55), sw("#E8462B", 0.10), sw("#2B8CE8", 0.15), sw("#3FC46A", 0.08), sw("#CDB79E", 0.12)]


class Schema(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.addCleanup(self.e.__exit__)
        self.eng = ThemeEngine(self.e.ctx)

    def test_five_presets_are_valid_and_readable(self):
        p = self.eng.presets()
        self.assertEqual(set(p), {"aurora-glass", "cyber-terminal", "developer-workspace", "gaming-mode", "cinema-music"})
        for pid, t in p.items():
            self.assertEqual(validate_tokens(t), [], pid)
            self.assertEqual(palette_problems(t["palette"]), [], pid)
        self.assertEqual(self.eng.warnings, [])

    def test_default_preset_matches_documented_example(self):
        doc = json.loads((REPO / "docs" / "tokens.default.json").read_text(encoding="utf-8"))
        aurora = dict(self.eng.preset(DEFAULT_ID))
        aurora.pop("description")
        self.assertEqual(aurora, doc)

    def test_gaming_mode_is_light_on_resources(self):
        g = self.eng.preset("gaming-mode")
        self.assertEqual(g["effects"]["quality"], "simple")
        self.assertFalse(g["effects"]["liquid_glass"])
        self.assertEqual(g["material"]["glow_strength"], 0)

    def test_validator_rejects_bad_values(self):
        base = self.eng.preset(DEFAULT_ID)

        def broken(path, value):
            t = json.loads(json.dumps(base))
            node = t
            for k in path[:-1]:
                node = node[k]
            node[path[-1]] = value
            return validate_tokens(t)

        self.assertTrue(broken(("palette", "primary"), "red"))
        self.assertTrue(broken(("palette", "primary"), "#12345"))
        self.assertTrue(broken(("material", "opacity"), 1.5))
        self.assertTrue(broken(("shape", "radius_small"), 3.5))
        self.assertTrue(broken(("effects", "quality"), "insane"))
        self.assertTrue(broken(("effects", "liquid_glass"), 1))
        self.assertTrue(broken(("typography", "font_family"), "ghp_abcdefghijklmnopqrstuvwxyz0123456789"))
        self.assertTrue(broken(("material", "extra_field"), 1))
        self.assertTrue(broken(("schema_version",), 2))
        self.assertEqual(broken(("palette", "primary"), "#FFB86CCC"), [])  # с альфой допустимо

    def test_missing_section_is_an_error(self):
        t = json.loads(json.dumps(self.eng.preset(DEFAULT_ID)))
        del t["motion"]
        self.assertTrue(any("motion" in p for p in validate_tokens(t)))

    def test_newer_schema_is_not_migrated(self):
        data, why = migrate({"schema_version": 99})
        self.assertIsNone(data)
        self.assertIn("более новой", why)
        self.assertEqual(migrate({"schema_version": 1})[0], {"schema_version": 1})

    def test_broken_preset_file_is_skipped_not_fatal(self):
        bad = REPO / "themes" / "zz-broken-test.json"
        bad.write_text('{"schema_version": 1, "id": "zz-broken-test"}', encoding="utf-8")
        try:
            eng = ThemeEngine(self.e.ctx)
            self.assertNotIn("zz-broken-test", eng.presets())
            self.assertTrue(any("zz-broken-test" in w for w in eng.warnings))
        finally:
            bad.unlink()

    def test_overrides_validation(self):
        self.assertEqual(validate_overrides({"clock": {"palette": {"primary": "#FFB86C"}, "material": {"opacity": 0.5}}}), [])
        self.assertTrue(validate_overrides({"clock": {"typography": {"size_body": 20}}}))
        self.assertTrue(validate_overrides({"clock": {"palette": {"source": "manual"}}}))
        self.assertTrue(validate_overrides({"../x": {"palette": {"primary": "#FFFFFF"}}}))
        self.assertTrue(validate_overrides({"clock": {"palette": {"primary": "blue"}}}))


class Colour(unittest.TestCase):
    def test_oklch_roundtrip(self):
        for h in ("#7AA2F7", "#0B1020", "#E6ECFF", "#FF0000", "#00FF00"):
            rgb = tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
            back = oklch_to_rgb(*rgb_to_oklch(rgb))
            for a, b in zip(rgb, back):
                self.assertAlmostEqual(a, b, places=3)

    def test_out_of_gamut_is_mapped_not_clipped_to_garbage(self):
        rgb = oklch_to_rgb(0.7, 0.5, 30)  # заведомо вне sRGB
        self.assertTrue(all(0 <= c <= 1 for c in rgb))
        self.assertLess(hue_dist(rgb_to_oklch(rgb)[2], 30), 6)  # оттенок сохранён

    def test_contrast_reference_values(self):
        self.assertAlmostEqual(contrast("#FFFFFF", "#000000"), 21.0, places=1)
        self.assertAlmostEqual(contrast("#777777", "#777777"), 1.0)


class WallpaperPalette(unittest.TestCase):
    def test_vivid_wallpaper(self):
        pal = palette_from_swatches(VIVID)
        self.assertEqual(set(pal), {"source", *ROLES})
        self.assertEqual(pal["source"], "wallpaper")
        self.assertEqual(palette_problems(pal), [])
        # фон тёмный и почти серый
        L, C, _ = lch(pal["bg"])
        self.assertLess(L, 0.25)
        self.assertLess(C, 0.04)
        # акценты взяты из картинки и различаются оттенком
        hues = [lch(pal[r])[2] for r in ("primary", "secondary", "accent")]
        for i in range(3):
            for j in range(i + 1, 3):
                self.assertGreaterEqual(hue_dist(hues[i], hues[j]), MIN_HUE_GAP - 3)
        src = [rgb_to_oklch(s.rgb)[2] for s in VIVID[1:4]]
        self.assertTrue(any(hue_dist(hues[0], h) < 12 for h in src), (hues[0], src))

    def test_hierarchy_of_surfaces(self):
        pal = palette_from_swatches(VIVID)
        L = {r: lch(pal[r])[0] for r in ("bg", "surface", "surface_alt", "border")}
        self.assertLess(L["bg"], L["surface"])
        self.assertLess(L["surface"], L["surface_alt"])
        self.assertLess(L["surface_alt"], L["border"])

    def test_status_colours_keep_their_meaning(self):
        pal = palette_from_swatches([sw("#FF00AA", 1.0)])
        for role, hue in (("success", 145), ("warning", 75), ("error", 18)):
            self.assertLess(hue_dist(lch(pal[role])[2], hue), 15, role)

    def test_grey_light_and_empty_inputs_stay_readable(self):
        for case in ([sw("#808080", 1.0)], [sw("#FFFFFF", 0.9), sw("#F0F0F0", 0.1)], [sw("#000000", 1.0)], []):
            self.assertEqual(palette_problems(palette_from_swatches(case)), [], case)

    def test_single_colour_derives_accents(self):
        pal = palette_from_swatches([sw("#1E3A8A", 0.7), sw("#2563EB", 0.3)])
        self.assertEqual(palette_problems(pal), [])
        self.assertEqual(len({pal["primary"], pal["secondary"], pal["accent"]}), 3)

    def test_deterministic(self):
        self.assertEqual(palette_from_swatches(VIVID), palette_from_swatches(list(VIVID)))

    def test_tiny_vivid_spot_does_not_beat_large_colour(self):
        pal = palette_from_swatches([sw("#101418", 0.5), sw("#3B82F6", 0.45), sw("#FF0000", 0.002)])
        blue = rgb_to_oklch(sw("#3B82F6", 1).rgb)[2]
        self.assertLess(hue_dist(lch(pal["primary"])[2], blue), 12)


class Engine(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.addCleanup(self.e.__exit__)
        self.eng = ThemeEngine(self.e.ctx)

    def tokens(self):
        return json.loads(self.eng.tokens_file.read_text(encoding="utf-8"))

    def test_first_run_writes_default_files(self):
        self.eng.ensure_files()
        t = self.tokens()
        self.assertEqual(t["id"], DEFAULT_ID)
        self.assertEqual(t["mode"], "preset")
        self.assertEqual(t["widget_overrides"], {})
        conf = self.eng.hypr_file.read_text(encoding="utf-8")
        self.assertIn("col.active_border = rgba(7aa2f7ee) rgba(bb9af7ee) 45deg", conf)
        self.assertIn("rounding = 22", conf)

    def test_set_preset(self):
        t = self.eng.set_preset("cyber-terminal")
        self.assertEqual(t["id"], "cyber-terminal")
        self.assertEqual(self.tokens()["palette"]["primary"], "#39FF88")
        self.assertIn("rounding = 10", self.eng.hypr_file.read_text(encoding="utf-8"))
        with self.assertRaises(KeyError):
            self.eng.set_preset("nope")

    def test_wallpaper_mode_without_palette_falls_back_to_theme_colours(self):
        t = self.eng.set_mode("wallpaper")
        self.assertEqual(t["palette"]["source"], "preset")
        self.assertTrue(any("ещё не построена" in w for w in self.eng.warnings))

    def test_wallpaper_palette_and_mode(self):
        self.eng.set_wallpaper_palette("/w/a.jpg", VIVID)
        self.assertEqual(self.tokens()["palette"]["source"], "preset", "режим не переключался")
        t = self.eng.set_wallpaper_palette("/w/a.jpg", VIVID, switch_mode=True)
        self.assertEqual(t["palette"]["source"], "wallpaper")
        self.assertEqual(t["mode"], "wallpaper")
        self.assertEqual(self.eng.state()["wallpaper"]["path"], "/w/a.jpg")
        self.assertEqual(t["shape"], self.eng.preset(DEFAULT_ID)["shape"])  # форма и материал от темы

    def test_new_wallpaper_changes_palette(self):
        """Критерий этапа 4: смена обоев меняет палитру."""
        a = self.eng.set_wallpaper_palette("/w/a.jpg", VIVID, switch_mode=True)["palette"]
        b = self.eng.set_wallpaper_palette("/w/b.jpg", [sw("#2A0F0A", 0.6), sw("#F59E0B", 0.4)])["palette"]
        self.assertNotEqual(a["primary"], b["primary"])
        self.assertNotEqual(a["bg"], b["bg"])

    def test_widget_override_survives_wallpaper_and_theme_changes(self):
        """Критерий этапа 4: override на виджете сохраняется."""
        self.eng.set_override("clock", {"palette.primary": "#FFB86C", "material.opacity": 0.5})
        self.eng.set_wallpaper_palette("/w/a.jpg", VIVID, switch_mode=True)
        self.eng.set_wallpaper_palette("/w/b.jpg", [sw("#00FF88", 1.0)])
        self.eng.set_preset("cinema-music")
        self.eng.set_mode("wallpaper")
        ov = self.tokens()["widget_overrides"]
        self.assertEqual(ov, {"clock": {"palette": {"primary": "#FFB86C"}, "material": {"opacity": 0.5}}})

    def test_override_rejects_bad_input_and_keeps_state(self):
        for assign in ({"palette.primary": "orange"}, {"typography.size_body": 20},
                       {"palette.source": "manual"}, {"material": 1}, {"material.opacity": 3}):
            with self.assertRaises(ValueError, msg=assign):
                self.eng.set_override("clock", assign)
        with self.assertRaises(ValueError):
            self.eng.set_override("../etc", {"palette.primary": "#FFFFFF"})
        self.assertEqual(self.eng.state()["widget_overrides"], {})

    def test_clear_override_field_and_whole(self):
        self.eng.set_override("clock", {"palette.primary": "#FFB86C", "motion.spring.damping": 30})
        self.eng.clear_override("clock", "motion.spring.damping")
        self.assertEqual(self.eng.state()["widget_overrides"], {"clock": {"palette": {"primary": "#FFB86C"}}})
        self.eng.clear_override("clock", "palette.primary")
        self.assertEqual(self.eng.state()["widget_overrides"], {})
        self.eng.set_override("note-1", {"palette.text": "#FFFFFF"})
        self.eng.clear_override("note-1")
        self.assertEqual(self.eng.state()["widget_overrides"], {})

    def test_reset_keeps_widget_colours_unless_asked(self):
        self.eng.set_preset("gaming-mode")
        self.eng.set_override("clock", {"palette.primary": "#FFB86C"})
        t = self.eng.reset()
        self.assertEqual((t["id"], t["mode"]), (DEFAULT_ID, "preset"))
        self.assertIn("clock", t["widget_overrides"])
        self.assertEqual(self.eng.reset(overrides=True)["widget_overrides"], {})

    def test_simple_quality_forces_no_glow(self):
        self.assertEqual(self.eng.set_preset("gaming-mode")["material"]["glow_strength"], 0)

    def test_corrupt_state_falls_back(self):
        self.eng.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.eng.state_file.write_text("{не json", encoding="utf-8")
        self.assertEqual(self.eng.write()["id"], DEFAULT_ID)
        self.assertTrue(self.eng.warnings)

    def test_bad_entries_in_state_are_dropped_individually(self):
        self.eng.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.eng.state_file.write_text(json.dumps({
            "schema_version": 1, "mode": "wallpaper", "preset": "cinema-music",
            "wallpaper": {"path": "/x", "palette": {"bg": "#000000"}},
            "widget_overrides": {"clock": {"palette": {"primary": "#FFB86C"}}, "bad": {"palette": {"primary": "x"}}},
        }), encoding="utf-8")
        st = self.eng.state()
        self.assertEqual(st["preset"], "cinema-music")
        self.assertIsNone(st["wallpaper"], "неполная палитра обоев отброшена")
        self.assertEqual(list(st["widget_overrides"]), ["clock"])

    def test_newer_state_is_never_overwritten(self):
        self.eng.state_file.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"schema_version": 7, "mode": "wallpaper"})
        self.eng.state_file.write_text(text, encoding="utf-8")
        self.assertEqual(self.eng.write()["id"], DEFAULT_ID)
        with self.assertRaises(RuntimeError):
            self.eng.set_preset("gaming-mode")
        self.assertEqual(self.eng.state_file.read_text(encoding="utf-8"), text)

    def test_apply_live_uses_keyword_not_reload(self):
        e = Env(bins={"hyprctl"}, responses=[(("hyprctl", "keyword"), ok("ok"))])
        self.addCleanup(e.__exit__)
        eng = ThemeEngine(e.ctx)
        self.assertEqual(eng.apply_live(eng.write(), {"HYPRLAND_INSTANCE_SIGNATURE": "sig"}), [])
        cmds = [c for c in e.runner.calls if c[:1] == ["hyprctl"]]
        self.assertEqual([c[2] for c in cmds], ["general:col.active_border", "general:col.inactive_border",
                                                "decoration:rounding"])
        self.assertFalse(any("reload" in c for c in cmds))

    def test_apply_live_outside_hyprland_does_nothing(self):
        self.assertEqual(self.eng.apply_live(self.eng.write(), {}), [])

    def test_snapshot_restore_brings_theme_back(self):
        rec = RecoveryManager(self.e.ctx, Registry(self.e.ctx))
        self.eng.set_override("clock", {"palette.primary": "#FFB86C"})
        snap = rec.snapshot("t")
        self.eng.reset(overrides=True)
        self.eng.set_preset("gaming-mode")
        rec.restore_snapshot(snap.name)
        t = self.tokens()
        self.assertEqual(t["id"], DEFAULT_ID)
        self.assertIn("clock", t["widget_overrides"])

    def test_parse_assignment(self):
        self.assertEqual(parse_assignment("material.opacity=0.5"), ("material.opacity", 0.5))
        self.assertEqual(parse_assignment("shape.radius_small=4"), ("shape.radius_small", 4))
        self.assertEqual(parse_assignment("palette.primary=#FFB86C"), ("palette.primary", "#FFB86C"))
        with self.assertRaises(ValueError):
            parse_assignment("palette.primary")


class Cli(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.addCleanup(self.e.__exit__)

    def run_cli(self, *argv):
        args = build_parser().parse_args(list(argv))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cmd_theme(self.e.ctx, args)
        return code, buf.getvalue()

    def test_set_and_status(self):
        self.assertEqual(self.run_cli("theme", "set", "developer-workspace")[0], 0)
        code, out = self.run_cli("theme", "status", "--json")
        data = json.loads(out)
        self.assertEqual(data["preset"], "developer-workspace")
        self.assertTrue(data["readable"])
        self.assertEqual(len(data["presets"]), 5)

    def test_unknown_theme_is_an_argument_error(self):
        code, out = self.run_cli("theme", "set", "nope", "--json")
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out)["ok"])

    def test_override_via_cli(self):
        self.assertEqual(self.run_cli("theme", "override", "clock", "palette.primary=#FFB86C", "material.opacity=0.4")[0], 0)
        self.assertEqual(ThemeEngine(self.e.ctx).state()["widget_overrides"]["clock"]["material"]["opacity"], 0.4)
        self.run_cli("theme", "override", "clock", "--clear")
        self.assertEqual(ThemeEngine(self.e.ctx).state()["widget_overrides"], {})
        self.assertEqual(self.run_cli("theme", "override", "clock", "palette.primary=blue")[0], 2)

    def test_shell_hook_skips_when_not_in_wallpaper_mode(self):
        code, out = self.run_cli("theme", "from-wallpaper", "--path", "/w/a.jpg", "--if-wallpaper-mode", "--json")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["skipped"])

    def test_validate_file(self):
        self.assertEqual(self.run_cli("theme", "validate", str(REPO / "themes" / "aurora-glass.json"))[0], 0)
        bad = self.e.tmp / "bad.json"
        bad.write_text(json.dumps({"schema_version": 1, "id": "x", "palette": {"bg": "nope"}}), encoding="utf-8")
        self.assertEqual(self.run_cli("theme", "validate", str(bad))[0], 2)


if __name__ == "__main__":
    unittest.main()
