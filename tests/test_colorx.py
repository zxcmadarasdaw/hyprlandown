"""Извлечение цветов из обоев (hyprown/colorx.py) и связка с палитрой: без настоящего ffmpeg."""
import contextlib
import io
import json
import unittest
from pathlib import Path

from hyprown.cli import build_parser, cmd_theme
from hyprown.colorx import RAW_SIDE, ColorxError, extract_swatches, quantize
from hyprown.theme import ThemeEngine, hue_dist, palette_from_swatches, palette_problems, rgb_to_oklch
from tests.helpers import Env, bad, ok

N = RAW_SIDE * RAW_SIDE


def pixels(*parts):
    """parts: (rgb, доля) -> raw rgb24 на N пикселей."""
    out = bytearray()
    for rgb, frac in parts:
        out += bytes(rgb) * int(N * frac)
    out += bytes(parts[-1][0]) * (N - len(out) // 3)
    return bytes(out)


def writer(raw):
    """Ответ «ffmpeg»: пишет raw в последний аргумент (выходной файл)."""
    def respond(cmd):
        out = cmd[-1]
        Path(out[4:] if out.startswith("rgb:") else out).write_bytes(raw)  # ImageMagick: rgb:ФАЙЛ
        return ok()
    return respond


class Quantize(unittest.TestCase):
    def test_weights_sum_to_one_and_sorted(self):
        sw = quantize(pixels(((10, 20, 40), 0.6), ((230, 70, 40), 0.3), ((60, 200, 100), 0.1)))
        self.assertAlmostEqual(sum(s.weight for s in sw), 1.0, places=6)
        self.assertEqual([s.weight for s in sw], sorted((s.weight for s in sw), reverse=True))
        self.assertEqual(len(sw), 3)

    def test_average_colour_of_bucket(self):
        sw = quantize(bytes((16, 16, 16, 31, 31, 31)))  # один бакет (оба в 0x1)
        self.assertEqual(len(sw), 1)
        self.assertAlmostEqual(sw[0].rgb[0], 23.5 / 255, places=6)

    def test_top_limit(self):
        raw = bytes(v for i in range(300) for v in ((i * 7) % 256, (i * 13) % 256, (i * 29) % 256))
        self.assertLessEqual(len(quantize(raw, top=10)), 10)

    def test_deterministic(self):
        raw = pixels(((1, 2, 3), 0.5), ((200, 100, 50), 0.5))
        self.assertEqual([(s.rgb, s.weight) for s in quantize(raw)], [(s.rgb, s.weight) for s in quantize(raw)])

    def test_empty_is_an_error(self):
        with self.assertRaises(ColorxError):
            quantize(b"")


class Extract(unittest.TestCase):
    def setUp(self):
        self.raw = pixels(((14, 26, 43), 0.6), ((232, 70, 43), 0.25), ((43, 140, 232), 0.15))

    def env(self, bins, responses):
        e = Env(bins=bins, responses=responses)
        self.addCleanup(e.__exit__)
        self.img = e.tmp / "wall.jpg"
        self.img.write_bytes(b"x")
        return e

    def test_ffmpeg_path(self):
        e = self.env({"ffmpeg"}, [(("ffmpeg",), writer(self.raw))])
        sw = extract_swatches(e.ctx, str(self.img))
        self.assertEqual(len(sw), 3)
        cmd = e.runner.calls[0]
        self.assertEqual(cmd[0], "ffmpeg")
        self.assertIn("-frames:v", cmd)           # первый кадр видео
        self.assertIn("-nostdin", cmd)
        self.assertEqual(cmd[cmd.index("-i") + 1], str(self.img.resolve()))

    def test_falls_back_to_imagemagick(self):
        e = self.env({"ffmpeg", "magick"}, [(("ffmpeg",), bad(1, "svg?")), (("magick",), writer(self.raw))])
        self.assertEqual(len(extract_swatches(e.ctx, str(self.img))), 3)
        self.assertEqual([c[0] for c in e.runner.calls], ["ffmpeg", "magick"])

    def test_no_tools(self):
        e = self.env(set(), [])
        with self.assertRaises(ColorxError) as cm:
            extract_swatches(e.ctx, str(self.img))
        self.assertIn("ffmpeg", str(cm.exception))

    def test_tool_failure_and_short_output(self):
        e = self.env({"ffmpeg"}, [(("ffmpeg",), bad(1, "invalid data"))])
        with self.assertRaises(ColorxError):
            extract_swatches(e.ctx, str(self.img))
        e = self.env({"ffmpeg"}, [(("ffmpeg",), writer(b"\x00" * 10))])
        with self.assertRaises(ColorxError):
            extract_swatches(e.ctx, str(self.img))

    def test_missing_file(self):
        e = self.env({"ffmpeg"}, [])
        with self.assertRaises(ColorxError):
            extract_swatches(e.ctx, str(e.tmp / "nope.png"))

    def test_leading_dash_name_is_not_an_option(self):
        e = self.env({"ffmpeg"}, [(("ffmpeg",), writer(self.raw))])
        odd = e.tmp / "-rf.png"
        odd.write_bytes(b"x")
        extract_swatches(e.ctx, str(odd))
        cmd = e.runner.calls[0]
        self.assertEqual(cmd[cmd.index("-i") + 1], str(odd.resolve()))
        self.assertFalse(cmd[cmd.index("-i") + 1].startswith("-"))

    def test_source_file_is_untouched_and_temp_removed(self):
        e = self.env({"ffmpeg"}, [(("ffmpeg",), writer(self.raw))])
        extract_swatches(e.ctx, str(self.img))
        self.assertEqual(self.img.read_bytes(), b"x")
        self.assertFalse(Path(e.runner.calls[0][-1]).exists())

    def test_ffmpeg_is_a_read_only_call(self):
        """В dry-run чтение всё равно выполняется (mutates=False): палитру можно показать без изменений."""
        e = self.env({"ffmpeg"}, [(("ffmpeg",), writer(self.raw))])
        e.runner.dry_run = True
        self.assertEqual(len(extract_swatches(e.ctx, str(self.img))), 3)


class EndToEnd(unittest.TestCase):
    """Критерий этапа 4: смена обоев меняет палитру, override сохраняется."""

    def setUp(self):
        self.raws = {
            "a.jpg": pixels(((14, 26, 43), 0.6), ((232, 70, 43), 0.25), ((43, 140, 232), 0.15)),
            "b.jpg": pixels(((40, 14, 10), 0.55), ((245, 158, 11), 0.35), ((120, 220, 90), 0.10)),
        }
        self.cur = {"raw": b""}
        e = Env(bins={"ffmpeg"}, responses=[(("ffmpeg",), lambda c: self._ff(c))])
        self.e = e
        self.addCleanup(e.__exit__)
        for n in self.raws:
            (e.tmp / n).write_bytes(b"x")

    def _ff(self, cmd):
        name = Path(cmd[cmd.index("-i") + 1]).name
        Path(cmd[-1]).write_bytes(self.raws[name])
        return ok()

    def run_cli(self, *argv):
        args = build_parser().parse_args(list(argv))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cmd_theme(self.e.ctx, args)
        return code, buf.getvalue()

    def tokens(self):
        return json.loads(ThemeEngine(self.e.ctx).tokens_file.read_text(encoding="utf-8"))

    def test_wallpaper_change_changes_palette_and_keeps_override(self):
        self.run_cli("theme", "override", "clock-1", "palette.primary=#FFB86C")
        code, _ = self.run_cli("theme", "from-wallpaper", "--switch", "--path", str(self.e.tmp / "a.jpg"))
        self.assertEqual(code, 0)
        first = self.tokens()
        self.assertEqual(first["palette"]["source"], "wallpaper")
        code, _ = self.run_cli("theme", "from-wallpaper", "--if-wallpaper-mode", "--path", str(self.e.tmp / "b.jpg"))
        self.assertEqual(code, 0)
        second = self.tokens()
        self.assertNotEqual(first["palette"]["primary"], second["palette"]["primary"])
        self.assertNotEqual(first["palette"]["bg"], second["palette"]["bg"])
        self.assertEqual(second["widget_overrides"]["clock-1"]["palette"]["primary"], "#FFB86C")
        self.assertEqual(palette_problems(second["palette"]), [])

    def test_palette_follows_wallpaper_hues(self):
        sw = extract_swatches(self.e.ctx, str(self.e.tmp / "a.jpg"))
        pal = palette_from_swatches(sw)
        src = [rgb_to_oklch(s.rgb)[2] for s in sw[1:]]
        h = rgb_to_oklch(tuple(int(pal["primary"][i:i + 2], 16) / 255 for i in (1, 3, 5)))[2]
        self.assertTrue(any(hue_dist(h, x) < 15 for x in src), (h, src))

    def test_mode_wallpaper_builds_palette_from_current_wallpaper(self):
        """wallpaper.json: монитор -> общие -> первый; режим сразу получает палитру."""
        st = self.e.ctx.state_dir
        st.mkdir(parents=True, exist_ok=True)
        (st / "wallpaper.json").write_text(json.dumps(
            {"schema_version": 1, "all": {"path": str(self.e.tmp / "b.jpg")}, "monitors": {}}), encoding="utf-8")
        code, _ = self.run_cli("theme", "mode", "wallpaper")
        self.assertEqual(code, 0)
        self.assertEqual(self.tokens()["palette"]["source"], "wallpaper")
        self.assertEqual(ThemeEngine(self.e.ctx).state()["wallpaper"]["path"], str(self.e.tmp / "b.jpg"))

    def test_broken_wallpaper_keeps_previous_palette(self):
        self.run_cli("theme", "from-wallpaper", "--switch", "--path", str(self.e.tmp / "a.jpg"))
        before = self.tokens()
        (self.e.tmp / "c.jpg").write_bytes(b"x")
        self.raws["c.jpg"] = b"\x00" * 5
        code, _ = self.run_cli("theme", "from-wallpaper", "--path", str(self.e.tmp / "c.jpg"))
        self.assertEqual(code, 1)
        self.assertEqual(self.tokens(), before)

    def test_current_wallpaper_resolution(self):
        eng = ThemeEngine(self.e.ctx)
        self.assertEqual(eng.current_wallpaper(), "")
        st = self.e.ctx.state_dir
        st.mkdir(parents=True, exist_ok=True)
        (st / "wallpaper.json").write_text(json.dumps({"schema_version": 1, "all": {"path": "/w/all.jpg"},
                                                       "monitors": {"DP-1": {"path": "/w/dp1.jpg"}}}), encoding="utf-8")
        self.assertEqual(eng.current_wallpaper("DP-1"), "/w/dp1.jpg")
        self.assertEqual(eng.current_wallpaper("HDMI-A-1"), "/w/all.jpg")


if __name__ == "__main__":
    unittest.main()
