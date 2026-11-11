"""Горячие клавиши: реестр, конфликты, переназначение, сверка с запущенной сессией, Preview."""

import json
import unittest
from pathlib import Path

from hyprown.config import ConfigManager
from hyprown.keybinds import (KeyManager, check_combo, effective, load_registry, norm_mods, render_default,
                              render_user, untouched, valid_key, validate_registry, combo_text, NO_USER)
from tests.helpers import Env, REPO
from tests.hypr_fake import FakeHypr, make_instance


def by_id(binds, bid):
    return next(b for b in binds if b.id == bid)


class Registry(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.addCleanup(self.e.__exit__)
        self.km = KeyManager(self.e.ctx)

    def test_registry_has_no_duplicates_or_kde_clashes(self):
        self.assertEqual(validate_registry(self.km.binds), [])

    def test_committed_keybinds_conf_is_generated_from_registry(self):
        text = (REPO / "hypr" / "keybinds.conf").read_text(encoding="utf-8")
        self.assertEqual(text, render_default(self.km.binds), "запустите: bin/hyprown keys render --write")

    def test_checked_combos_from_the_report(self):
        """Win+M/E/W/Space/Enter: что на них висит и что они НЕ делают."""
        want = {("SUPER", "m"): "manager", ("SUPER", "e"): "canvas.edit", ("SUPER", "w"): "wallpaper.next",
                ("SUPER", "space"): "launcher", ("SUPER", "return"): "terminal"}
        eff = {(" ".join(e.mods), e.key.lower()): e.bind.id for e in effective(self.km.binds, NO_USER)}
        for combo, bid in want.items():
            self.assertEqual(eff[combo], bid, combo)
        for e in effective(self.km.binds, NO_USER):
            if e.key.lower() == "m":
                self.assertNotEqual(e.bind.dispatcher, "exit", "Super+M не должен выходить из сессии")
        exits = [e for e in effective(self.km.binds, NO_USER) if e.bind.dispatcher == "exit"]
        self.assertEqual([(" ".join(e.mods), e.key) for e in exits], [("SUPER SHIFT", "E")])

    def test_preview_never_uses_keys_that_kde_grabs(self):
        for e in effective(self.km.binds, NO_USER, "preview"):
            self.assertNotEqual(e.combo, (("ALT",), "space"))
        launcher = by_id(self.km.binds, "launcher")
        self.assertEqual(launcher.preview(), (("ALT",), "R"))

    def test_preview_has_no_duplicates(self):
        seen = {}
        for e in effective(self.km.binds, NO_USER, "preview"):
            self.assertNotIn(e.combo, seen, (e.bind.id, seen.get(e.combo)))
            seen[e.combo] = e.bind.id

    def test_workspace_keys_expand(self):
        ids = [b.id for b in self.km.binds if b.id.startswith("workspace.")]
        self.assertIn("workspace.move.9", ids)
        self.assertEqual(by_id(self.km.binds, "workspace.5").arg, "5")

    def test_parsing(self):
        self.assertEqual(norm_mods("shift super"), ("SUPER", "SHIFT"))
        self.assertEqual(norm_mods("$mainMod, SHIFT"), ("SUPER", "SHIFT"))
        with self.assertRaises(ValueError):
            norm_mods("HYPER")
        for k in ("a", "5", "RETURN", "F12", "mouse:272", "code:24", "XF86AudioMute"):
            self.assertTrue(valid_key(k), k)
        for k in ("", "ZZZ", "ab"):
            self.assertFalse(valid_key(k), k)


class Conflicts(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.addCleanup(self.e.__exit__)
        self.km = KeyManager(self.e.ctx)

    def kinds(self, mods, key, ignore=None):
        return {(c.level, c.kind) for c in check_combo(self.km.binds, self.km.user(), mods, key, ignore)}

    def test_duplicate_with_other_entry_is_an_error(self):
        self.assertIn(("error", "duplicate"), self.kinds("SUPER", "E", "manager"))
        self.assertIn(("error", "duplicate"), self.kinds("SUPER", "W", "manager"))

    def test_own_combo_is_not_a_conflict(self):
        self.assertNotIn(("error", "duplicate"), self.kinds("SUPER", "M", "manager"))

    def test_stock_hyprland_binding_is_a_warning_not_a_block(self):
        k = self.kinds("SUPER", "C", "manager")
        self.assertEqual(k, {("warn", "hyprland-default")})

    def test_kde_grab_in_preview_warns(self):
        self.assertIn(("warn", "host-reserved"), self.kinds("ALT", "SPACE", "manager"))

    def test_preview_clash_via_alt(self):
        """ALT+M в desktop свободно, но в Preview Super заменяется на Alt и занимает ту же комбинацию."""
        self.assertIn(("error", "duplicate"), self.kinds("ALT", "M", "terminal"))

    def test_invalid_input(self):
        self.assertIn(("error", "invalid"), self.kinds("HYPER", "A"))
        self.assertIn(("error", "invalid"), self.kinds("SUPER", "NOPE"))
        cs = check_combo(self.km.binds, self.km.user(), "SUPER", "X", "mouse.move", "bindm")
        self.assertEqual({c.kind for c in cs}, {"invalid"})

    def test_free_combo_has_no_conflicts(self):
        self.assertEqual(self.kinds("SUPER SHIFT", "X", "manager"), set())


class Reassign(unittest.TestCase):
    def mk(self, **kw):
        e = Env(**kw)
        self.addCleanup(e.__exit__)
        return e, KeyManager(e.ctx)

    def test_set_writes_unbind_then_bind_and_persists(self):
        e, km = self.mk()
        ok, msgs = km.set("manager", "SUPER SHIFT", "X")
        self.assertTrue(ok, msgs)
        data = json.loads((e.ctx.state_dir / "keybinds.user.json").read_text())
        self.assertEqual(data["overrides"]["manager"], {"mods": "SUPER SHIFT", "key": "X"})
        text = (e.ctx.state_dir / "keybinds.user.conf").read_text(encoding="utf-8")
        self.assertLess(text.index("unbind = $mainMod, M"), text.index("bind = $mainMod SHIFT, X, exec"))
        self.assertTrue(untouched(text))

    def test_conflict_blocks_write(self):
        e, km = self.mk()
        ok, msgs = km.set("manager", "SUPER", "E")
        self.assertFalse(ok)
        self.assertIn("canvas.edit", " ".join(msgs))
        self.assertFalse((e.ctx.state_dir / "keybinds.user.json").exists())

    def test_warning_needs_force(self):
        _, km = self.mk()
        ok, msgs = km.set("manager", "SUPER", "C")
        self.assertFalse(ok)
        self.assertIn("--force", " ".join(msgs))
        ok, _ = km.set("manager", "SUPER", "C", force=True)
        self.assertTrue(ok)

    def test_existing_user_choice_is_not_overwritten_without_consent(self):
        e, km = self.mk(yes=False)  # неинтерактивно и без --yes: подтверждение даётся как «нет»
        self.assertTrue(km.set("manager", "SUPER SHIFT", "X")[0])
        ok, msgs = km.set("manager", "SUPER SHIFT", "Y")
        self.assertFalse(ok)
        self.assertEqual(km.user()["overrides"]["manager"]["key"], "X")

    def test_existing_user_choice_replaced_when_confirmed(self):
        _, km = self.mk()
        km.set("manager", "SUPER SHIFT", "X")
        self.assertTrue(km.set("manager", "SUPER SHIFT", "Y")[0])
        self.assertEqual(km.user()["overrides"]["manager"]["key"], "Y")

    def test_hand_edited_user_conf_is_protected(self):
        e, km = self.mk(yes=False)
        km.ensure_user_conf()
        f = e.ctx.state_dir / "keybinds.user.conf"
        f.write_text("# моё\nbind = SUPER, F9, exec, firefox\n", encoding="utf-8")
        self.assertTrue(km.user_conf_hand_edited())
        ok, msgs = km.set("manager", "SUPER SHIFT", "X")
        self.assertFalse(ok)
        self.assertIn("firefox", f.read_text(encoding="utf-8"))
        self.assertFalse((e.ctx.state_dir / "keybinds.user.json").exists())

    def test_hand_edited_user_conf_is_backed_up_when_allowed(self):
        e, km = self.mk(yes=True)
        km.ensure_user_conf()
        f = e.ctx.state_dir / "keybinds.user.conf"
        f.write_text("bind = SUPER, F9, exec, firefox\n", encoding="utf-8")
        ok, msgs = km.set("manager", "SUPER SHIFT", "X")
        self.assertTrue(ok)
        backups = list(e.ctx.backup_dir.glob("keybinds.user.conf.*"))
        self.assertEqual(len(backups), 1)
        self.assertIn("firefox", backups[0].read_text(encoding="utf-8"))

    def test_setting_the_default_removes_override(self):
        _, km = self.mk()
        km.set("manager", "SUPER SHIFT", "X")
        km.set("manager", "SUPER", "M")
        self.assertEqual(km.user()["overrides"], {})

    def test_swap_is_rendered_with_all_unbinds_first(self):
        _, km = self.mk()
        user = {"overrides": {"canvas.edit": {"mods": "SUPER", "key": "W"},
                              "wallpaper.next": {"mods": "SUPER", "key": "E"}}, "disabled": []}
        lines = render_user(km.binds, user).splitlines()
        kinds = [ln.split("=")[0].strip() for ln in lines if "=" in ln]
        self.assertEqual(kinds, ["unbind", "unbind", "bind", "bind"])

    def test_critical_bind_needs_force_to_disable(self):
        _, km = self.mk()
        ok, msgs = km.disable("session.exit")
        self.assertFalse(ok)
        self.assertTrue(km.disable("session.exit", force=True)[0])
        self.assertTrue(km.disable("window.pseudo")[0])
        text = (km.store.conf).read_text(encoding="utf-8")
        self.assertIn("unbind = $mainMod, P", text)

    def test_reset(self):
        _, km = self.mk()
        km.set("manager", "SUPER SHIFT", "X")
        km.disable("window.pseudo")
        km.reset("manager")
        self.assertNotIn("manager", km.user()["overrides"])
        km.reset()
        self.assertEqual(km.user(), {"overrides": {}, "disabled": []})

    def test_listing_marks_override_and_conflict_free(self):
        _, km = self.mk()
        km.set("manager", "SUPER SHIFT", "X")
        row = next(r for r in km.listing() if r["id"] == "manager")
        self.assertTrue(row["overridden"])
        self.assertEqual(row["combo"], "Super+Shift+X")
        self.assertEqual(row["default"], "Super+M")
        self.assertEqual(row["conflicts"], [])


class RenderedModes(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.addCleanup(self.e.__exit__)

    def test_preview_render_uses_alt_and_avoids_alt_space(self):
        out = ConfigManager(self.e.ctx).render("preview", self.e.tmp / "p")
        text = (self.e.tmp / "p" / "keybinds.conf").read_text(encoding="utf-8")
        self.assertIn("bind = ALT, R, exec", text)
        self.assertNotIn("ALT, SPACE", text)
        self.assertIn("bind = ALT, M, exec", text)
        self.assertIn("keybinds.user.conf", out.read_text(encoding="utf-8"))

    def test_preview_render_applies_user_override(self):
        km = KeyManager(self.e.ctx)
        km.set("manager", "SUPER SHIFT", "X")
        ConfigManager(self.e.ctx).render("preview", self.e.tmp / "p")
        text = (self.e.tmp / "p" / "keybinds.user.conf").read_text(encoding="utf-8")
        self.assertIn("unbind = ALT, M", text)
        self.assertIn("bind = ALT SHIFT, X, exec", text)

    def test_desktop_render_sources_user_conf_after_defaults(self):
        out = ConfigManager(self.e.ctx).render("desktop", self.e.tmp / "d")
        main = out.read_text(encoding="utf-8")
        self.assertLess(main.index("keybinds.conf"), main.index("keybinds.user.conf"))
        self.assertTrue((self.e.ctx.state_dir / "keybinds.user.conf").exists())


class LiveSession(unittest.TestCase):
    """Сверка с `hyprctl binds` запущенной сессии."""

    def setUp(self):
        self.e = Env(bins={"hyprctl"})
        self.addCleanup(self.e.__exit__)
        self.km = KeyManager(self.e.ctx)
        self.env = {"HYPRLAND_INSTANCE_SIGNATURE": "sigA"}

    def attach_fake(self, ours):
        fh = FakeHypr(self.e.ctx, ours=ours)
        self.e.runner.responses[:] = fh.responses()
        return fh

    def test_stock_config_super_m_is_detected_as_exit(self):
        self.attach_fake(ours=False)
        rep = self.km.live(self.env)
        self.assertFalse(rep["ok"])
        row = next(i for i in rep["items"] if i["id"] == "manager")
        self.assertEqual(row["status"], "overridden")
        self.assertTrue(row["danger"], "Super+M = exit должен быть помечен опасным")
        self.assertIn("exit", row["detail"])
        kinds = {i["id"]: i["status"] for i in rep["items"]}
        self.assertEqual(kinds["canvas.edit"], "overridden")   # Super+E: файловый менеджер
        self.assertEqual(kinds["wallpaper.next"], "missing")   # Super+W нигде не назначен
        self.assertGreater(rep["default_hyprland_binds"], 0)

    def test_our_config_matches_registry(self):
        self.attach_fake(ours=True)
        rep = self.km.live(self.env)
        self.assertTrue(rep["ok"], [i for i in rep["items"] if i["status"] != "ok"])
        self.assertEqual(rep["summary"]["missing"], 0)

    def test_duplicate_on_one_combo_is_reported(self):
        fh = self.attach_fake(ours=True)
        fh.binds.append(fh._row("SUPER", "m", "exit", ""))
        rep = self.km.live(self.env)
        row = next(i for i in rep["items"] if i["id"] == "manager")
        self.assertEqual(row["status"], "duplicate")
        self.assertFalse(rep["ok"])

    def test_foreign_extra_binds_are_listed(self):
        fh = self.attach_fake(ours=True)
        fh.binds.append(fh._row("SUPER", "f9", "exec", "firefox"))
        rep = self.km.live(self.env)
        self.assertEqual(rep["extras"][0]["action"], "exec firefox")
        self.assertTrue(rep["ok"])  # чужая привязка на свободной клавише не нарушает наши

    def test_unreadable_answer(self):
        self.e.runner.responses[:] = [(("hyprctl", "-j", "binds"), __import__("tests.hypr_fake", fromlist=["ok"]).ok("не json"))]
        rep = self.km.live(self.env)
        self.assertIsNone(rep["ok"])

    def test_apply_live_unbinds_stock_super_m_before_binding_ours(self):
        fh = self.attach_fake(ours=False)
        res = self.km.apply_live(self.env)
        self.assertEqual(res["errors"], [])
        names = [(k[0], k[1].split(",")[0:2]) for k in fh.keywords]
        first_bind = next(i for i, k in enumerate(fh.keywords) if k[0] == "bind")
        self.assertIn(("unbind", ["SUPER", "M"]), names[:first_bind])
        self.assertTrue(self.km.live(self.env)["ok"])
        exits = [b for b in fh.binds if b["dispatcher"] == "exit"]
        self.assertEqual(len(exits), 1)  # остался только Super+Shift+E

    def test_apply_live_expands_variables_and_repo_path(self):
        fh = self.attach_fake(ours=False)
        self.km.apply_live(self.env)
        terminal = next(k for k in fh.keywords if k[0] == "bind" and k[1].startswith("SUPER,RETURN"))
        self.assertTrue(terminal[1].endswith(",exec,kitty"), terminal)
        mgr = next(k for k in fh.keywords if k[0] == "bind" and k[1].startswith("SUPER,M,exec"))
        self.assertIn(str(REPO / "bin" / "hyprown"), mgr[1])
        self.assertNotIn("$", " ".join(" ".join(k) for k in fh.keywords))

    def test_apply_live_honours_user_override(self):
        fh = self.attach_fake(ours=False)
        self.km.set("manager", "SUPER SHIFT", "X")
        self.km.apply_live(self.env)
        keys = [(b["modmask"], b["key"]) for b in fh.binds if b["dispatcher"] == "exec"]
        self.assertIn((65, "x"), keys)
        self.assertNotIn((64, "m"), keys)

    def test_would_replace_lists_what_attach_will_take_over(self):
        self.attach_fake(ours=False)
        clash = self.km.would_replace(self.km.live(self.env))
        self.assertIn("manager", [c["id"] for c in clash])

    def test_missing_target_programs_are_reported(self):
        e = Env(bins={"fuzzel"})
        self.addCleanup(e.__exit__)
        miss = KeyManager(e.ctx).missing_targets()
        self.assertTrue(any("kitty" in m for m in miss))
        self.assertFalse(any("fuzzel" in m for m in miss))


if __name__ == "__main__":
    unittest.main()
