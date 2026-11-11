"""Theme Engine (этап 4): токены темы как данные, палитра из обоев, переопределения на виджетах.

Источники и файлы:
  themes/<id>.json                       готовые темы (полный набор токенов, docs/TOKENS.md)
  ~/.local/state/hyprdesk/theme.json     выбор пользователя: режим, тема, палитра обоев, overrides
  ~/.local/state/hyprdesk/tokens.json    ИТОГ для оболочки и Manager (QML следит за файлом)
  ~/.local/state/hyprdesk/theme.conf     цвета и скругление для Hyprland (source в hyprland.conf)

Режимы:
  preset     палитра из выбранной темы;
  wallpaper  палитра строится из цветов обоев (material/motion/shape берутся из выбранной темы).

Переопределения виджетов (`widget_overrides`) хранятся в theme.json отдельно от палитры и
не сбрасываются ни при смене обоев, ни при смене темы. Сбрасываются только явной командой.

Ошибки не ломают сессию: битый или неизвестный файл -> значения по умолчанию + запись в журнал.
Извлечение цветов из картинки/видео живёт в hyprown/colorx.py; здесь только роли палитры.
"""
from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass

from .registry import atomic_write

SCHEMA = 1
STATE_SCHEMA = 1
DEFAULT_ID = "aurora-glass"
MODES = ("preset", "wallpaper")

ROLES = ("bg", "surface", "surface_alt", "primary", "secondary", "accent",
         "text", "text_muted", "border", "success", "warning", "error")

# Описание схемы: секция -> поле -> (тип, мин, макс) или набор допустимых строк.
SPEC: dict = {
    "palette": {**{r: ("color",) for r in ROLES}, "source": ("enum", ("preset", "wallpaper", "manual"))},
    "material": {
        "opacity": ("float", 0.0, 1.0), "blur_radius": ("int", 0, 64),
        "tint_strength": ("float", 0.0, 1.0), "highlight_strength": ("float", 0.0, 1.0),
        "glow_strength": ("float", 0.0, 1.0), "border_width": ("float", 0.0, 4.0),
    },
    "motion": {
        "duration_fast_ms": ("int", 0, 2000), "duration_normal_ms": ("int", 0, 4000),
        "duration_slow_ms": ("int", 0, 8000), "easing": ("str",),
        "spring": {"stiffness": ("float", 1.0, 2000.0), "damping": ("float", 0.0, 200.0),
                   "mass": ("float", 0.05, 50.0)},
    },
    "shape": {"radius_small": ("int", 0, 64), "radius_medium": ("int", 0, 64),
              "radius_large": ("int", 0, 96), "spacing_unit": ("int", 1, 64)},
    "typography": {"font_family": ("str",), "font_family_mono": ("str",),
                   "size_small": ("int", 6, 48), "size_body": ("int", 6, 64), "size_title": ("int", 6, 96)},
    "effects": {"quality": ("enum", ("simple", "balanced", "high", "ultra")),
                "liquid_glass": ("bool",), "spring_physics": ("bool",)},
}
OVERRIDABLE = ("palette", "material", "motion", "shape")
META = ("schema_version", "id", "name", "description")

COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
WID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
# Похоже на секрет: ключевые слова, известные префиксы ключей, длинная строка base64/hex без пробелов.
SECRET_RE = re.compile(r"(?i)(password|passwd|token|secret|api[_-]?key|bearer\s)"
                       r"|^(?:sk|ghp|gho|xox[abp])[-_][A-Za-z0-9]{8,}|^[A-Za-z0-9+/=_-]{40,}$")


# ---------------------------------------------------------------- проверка схемы
def _check_value(spec: tuple, value, where: str) -> str | None:
    kind = spec[0]
    if kind == "color":
        return None if isinstance(value, str) and COLOR_RE.match(value) else f"{where}: цвет должен быть #RRGGBB или #RRGGBBAA"
    if kind == "enum":
        return None if value in spec[1] else f"{where}: допустимо {', '.join(spec[1])}"
    if kind == "bool":
        return None if isinstance(value, bool) else f"{where}: нужно true или false"
    if kind == "str":
        if not isinstance(value, str) or not value.strip() or len(value) > 128:
            return f"{where}: нужна непустая строка до 128 символов"
        return f"{where}: значение похоже на пароль или токен" if SECRET_RE.search(value) else None
    if kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{where}: нужно число"
        if kind == "int" and not float(value).is_integer():
            return f"{where}: нужно целое число"
        lo, hi = spec[1], spec[2]
        return None if lo <= value <= hi else f"{where}: допустимо от {lo} до {hi}"
    return f"{where}: неизвестный тип"


def _walk(spec: dict, data, where: str, partial: bool, out: list[str]) -> None:
    if not isinstance(data, dict):
        out.append(f"{where}: нужен объект")
        return
    for key, value in data.items():
        if key not in spec:
            out.append(f"{where}.{key}: поле не описано в схеме (docs/TOKENS.md)")
        elif isinstance(spec[key], dict):
            _walk(spec[key], value, f"{where}.{key}", partial, out)
        else:
            err = _check_value(spec[key], value, f"{where}.{key}")
            if err:
                out.append(err)
    if not partial:
        for key in spec:
            if key not in data:
                out.append(f"{where}.{key}: поле отсутствует")


def validate_tokens(data, partial: bool = False) -> list[str]:
    """Пустой список = файл допустим. partial=True: можно указать не все поля."""
    if not isinstance(data, dict):
        return ["файл токенов должен быть JSON-объектом"]
    out: list[str] = []
    if data.get("schema_version") != SCHEMA:
        out.append(f"schema_version: ожидается {SCHEMA}, получено {data.get('schema_version')!r}")
    if not isinstance(data.get("id"), str) or not ID_RE.match(data.get("id", "")):
        out.append("id: латиница в нижнем регистре, цифры и дефис")
    for key in ("name", "description"):
        if key in data:
            err = _check_value(("str",), data[key], key)
            if err:
                out.append(err)
    for key, value in data.items():
        if key in META or key in ("widget_overrides", "mode"):
            continue
        if key not in SPEC:
            out.append(f"{key}: поле не описано в схеме (docs/TOKENS.md)")
            continue
        _walk(SPEC[key], value, key, partial, out)
    if not partial:
        for key in SPEC:
            if key not in data:
                out.append(f"{key}: секция отсутствует")
    if "widget_overrides" in data:
        out.extend(validate_overrides(data["widget_overrides"]))
    return out


def validate_overrides(ov) -> list[str]:
    if not isinstance(ov, dict):
        return ["widget_overrides: нужен объект"]
    out: list[str] = []
    for wid, body in ov.items():
        if not WID_RE.match(str(wid)):
            out.append(f"widget_overrides.{wid}: недопустимый id виджета")
            continue
        if not isinstance(body, dict):
            out.append(f"widget_overrides.{wid}: нужен объект")
            continue
        for section, value in body.items():
            if section not in OVERRIDABLE:
                out.append(f"widget_overrides.{wid}.{section}: переопределять можно {', '.join(OVERRIDABLE)}")
            elif section == "palette" and isinstance(value, dict) and "source" in value:
                out.append(f"widget_overrides.{wid}.palette.source: не переопределяется")
            else:
                _walk(SPEC[section], value, f"widget_overrides.{wid}.{section}", True, out)
    return out


# Миграции N -> N+1: MIGRATIONS[N] получает данные схемы N и возвращает схему N+1.
# Пока схема одна; новая версия схемы обязана добавить сюда функцию и тест.
MIGRATIONS: dict = {}


def migrate(data: dict) -> tuple[dict | None, str]:
    """Возвращает (данные текущей схемы | None, сообщение). None: версия новее известной."""
    v = data.get("schema_version")
    if not isinstance(v, int) or isinstance(v, bool):
        return None, "нет schema_version"
    if v > SCHEMA:
        return None, f"файл создан более новой версией (схема {v}), используются значения по умолчанию"
    while v < SCHEMA:
        step = MIGRATIONS.get(v)
        if step is None:
            return None, f"нет миграции со схемы {v}"
        data = step(data)
        v = data["schema_version"]
    return data, ""


# ---------------------------------------------------------------- цвет: sRGB <-> OKLCH
def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def rgb_to_hex(rgb) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02X}" for c in rgb)


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gam(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def rgb_to_oklch(rgb) -> tuple[float, float, float]:
    r, g, b = (_lin(c) for c in rgb)
    l_ = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m_ = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s_ = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (math.copysign(abs(x) ** (1 / 3), x) for x in (l_, m_, s_))
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return L, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360


def _oklch_to_linear(L: float, C: float, H: float) -> tuple[float, float, float]:
    a, b = C * math.cos(math.radians(H)), C * math.sin(math.radians(H))
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
            -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
            -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)


def _in_gamut(lin) -> bool:
    return all(-1e-4 <= c <= 1.0001 for c in lin)


def oklch_to_rgb(L: float, C: float, H: float) -> tuple[float, float, float]:
    """С отображением в гамут sRGB: хроматичность уменьшается, оттенок и светлота сохраняются."""
    L = max(0.0, min(1.0, L))
    lin = _oklch_to_linear(L, max(0.0, C), H)
    if not _in_gamut(lin):
        lo, hi = 0.0, max(0.0, C)
        for _ in range(24):
            mid = (lo + hi) / 2
            if _in_gamut(_oklch_to_linear(L, mid, H)):
                lo = mid
            else:
                hi = mid
        lin = _oklch_to_linear(L, lo, H)
    return tuple(_gam(max(0.0, min(1.0, c))) for c in lin)


def oklch_hex(L: float, C: float, H: float) -> str:
    return rgb_to_hex(oklch_to_rgb(L, C, H))


def luminance(hex_color: str) -> float:
    r, g, b = (_lin(c) for c in hex_to_rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def hue_dist(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


# ---------------------------------------------------------------- палитра из образцов обоев
@dataclass
class Swatch:
    """Цвет из обоев (sRGB 0..1) и его доля в картинке. Строит hyprown/colorx.py."""
    rgb: tuple
    weight: float

    @property
    def lch(self) -> tuple[float, float, float]:
        return rgb_to_oklch(self.rgb)


# Светлота OKLCH ролей тёмной темы: иерархия bg < surface < surface_alt < border при любых обоях.
DARK = {"bg": 0.17, "surface": 0.215, "surface_alt": 0.26, "border": 0.36,
        "primary": 0.76, "secondary": 0.74, "accent": 0.82, "text": 0.95, "text_muted": 0.74}
STATUS_HUES = {"success": 145.0, "warning": 75.0, "error": 18.0}
MIN_CONTRAST = {"text": 7.0, "text_muted": 4.5, "primary": 4.5, "secondary": 4.5, "accent": 4.5,
                "success": 4.5, "warning": 4.5, "error": 4.5}
CHROMATIC = 0.045   # ниже этой хроматичности цвет считаем серым
MIN_HUE_GAP = 28.0  # акценты должны отличаться оттенком, иначе палитра однотонная


def _lift(L: float, C: float, H: float, against: str, need: float) -> str:
    """Поднимает светлоту, пока контраст с фоном не станет достаточным."""
    while True:
        col = oklch_hex(L, C, H)
        if contrast(col, against) >= need or L >= 0.995:
            return col
        L = min(0.995, L + 0.01)


def palette_from_swatches(swatches: list, fallback_hue: float = 264.0) -> dict:
    """Роли палитры (тёмная тема) из цветов обоев.

    * фон и поверхности берут оттенок самого «весомого» цвета почти без насыщенности:
      обои не должны превращать панели в цветные пятна;
    * primary - самый заметный насыщенный цвет (насыщенность x корень из площади);
      secondary и accent - другие оттенки картинки, отстоящие минимум на MIN_HUE_GAP,
      а если таких нет, производные от primary;
    * статусные цвета сохраняют смысловой оттенок (зелёный/жёлтый/красный);
    * все роли текста и акцентов проходят проверку контраста с фоном (WCAG);
    * серые обои: оттенок fallback_hue со сдержанной насыщенностью.
    """
    sw = [s for s in swatches if s.weight > 0]
    total = sum(s.weight for s in sw) or 1.0
    lchs = [(s.lch, s.weight / total) for s in sw]

    base_h, base_c = fallback_hue, 0.0
    if lchs:
        base = max(lchs, key=lambda x: x[1])[0]
        base_h, base_c = base[2], base[1]
    if base_c < 0.02:
        base_h = fallback_hue

    chroma = sorted(((lch, w) for lch, w in lchs if lch[1] >= CHROMATIC),
                    key=lambda x: x[0][1] * math.sqrt(x[1]), reverse=True)
    picks: list[tuple[float, float]] = []
    for lch, _ in chroma:
        if all(hue_dist(lch[2], h) >= MIN_HUE_GAP for h, _ in picks):
            picks.append((lch[2], lch[1]))
        if len(picks) == 3:
            break
    if not picks:
        picks = [(base_h, 0.09)]
    p_h, p_c = picks[0]
    s_h, s_c = picks[1] if len(picks) > 1 else ((p_h + 40) % 360, p_c * 0.9)
    a_h, a_c = picks[2] if len(picks) > 2 else ((p_h - 35) % 360, p_c * 0.85)

    def clamp(c: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, c))

    tint = clamp(base_c * 0.35, 0.012, 0.035)
    pal = {
        "source": "wallpaper",
        "bg": oklch_hex(DARK["bg"], tint, base_h),
        "surface": oklch_hex(DARK["surface"], tint * 1.1, base_h),
        "surface_alt": oklch_hex(DARK["surface_alt"], tint * 1.25, base_h),
        "border": oklch_hex(DARK["border"], min(0.06, tint * 1.6), base_h),
    }
    bg = pal["bg"]
    pal["primary"] = _lift(DARK["primary"], clamp(p_c, 0.09, 0.17), p_h, bg, MIN_CONTRAST["primary"])
    pal["secondary"] = _lift(DARK["secondary"], clamp(s_c, 0.08, 0.16), s_h, bg, MIN_CONTRAST["secondary"])
    pal["accent"] = _lift(DARK["accent"], clamp(a_c, 0.07, 0.15), a_h, bg, MIN_CONTRAST["accent"])
    pal["text"] = _lift(DARK["text"], 0.015, base_h, bg, MIN_CONTRAST["text"])
    pal["text_muted"] = _lift(DARK["text_muted"], 0.03, base_h, bg, MIN_CONTRAST["text_muted"])
    for role, hue in STATUS_HUES.items():
        pal[role] = _lift(0.78, 0.14, hue, bg, MIN_CONTRAST[role])
    return {k: pal[k] for k in ("source",) + ROLES}


def palette_problems(pal: dict) -> list[str]:
    """Читаемость любой палитры (готовой темы, обоев, ручной): контраст ролей с фоном."""
    out = []
    for role, need in MIN_CONTRAST.items():
        if role in pal and "bg" in pal:
            c = contrast(pal[role][:7], pal["bg"][:7])
            if c < need - 1e-9:
                out.append(f"{role}: контраст с фоном {c:.2f} < {need}")
    return out


# ---------------------------------------------------------------- состояние и сборка
def deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def default_state() -> dict:
    return {"schema_version": STATE_SCHEMA, "mode": "preset", "preset": DEFAULT_ID,
            "wallpaper": None, "widget_overrides": {}}


def _rgba(hex_color: str, alpha: str) -> str:
    return f"rgba({hex_color[1:7].lower()}{alpha})"


class ThemeEngine:
    def __init__(self, ctx):
        self.ctx = ctx
        self.dir = ctx.repo / "themes"
        self.state_file = ctx.state_dir / "theme.json"
        self.tokens_file = ctx.state_dir / "tokens.json"
        self.hypr_file = ctx.state_dir / "theme.conf"
        self.warnings: list[str] = []
        self._presets: dict | None = None

    def log(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)
        try:
            d = self.ctx.state_dir / "logs"
            d.mkdir(parents=True, exist_ok=True)
            with (d / "theme.log").open("a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except OSError:
            pass

    # ---------- готовые темы ----------
    def presets(self) -> dict:
        if self._presets is not None:
            return self._presets
        out: dict = {}
        for f in sorted(self.dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                self.log(f"тема {f.name} не читается: {exc}")
                continue
            data, why = migrate(data) if isinstance(data, dict) else (None, "не объект")
            problems = validate_tokens(data) if data else [why]
            if problems:
                self.log(f"тема {f.name} отброшена: {problems[0]}")
                continue
            out[data["id"]] = data
        if DEFAULT_ID not in out:
            raise RuntimeError(f"нет встроенной темы {DEFAULT_ID} в {self.dir}")
        self._presets = out
        return out

    def preset(self, pid: str) -> dict:
        p = self.presets()
        if pid not in p:
            raise KeyError(f"нет темы «{pid}». Есть: {', '.join(sorted(p))}")
        return p[pid]

    # ---------- состояние пользователя ----------
    def state(self) -> dict:
        st = default_state()
        if not self.state_file.exists():
            return st
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.log(f"theme.json не читается ({exc}): тема по умолчанию")
            return st
        if not isinstance(raw, dict):
            self.log("theme.json не объект: тема по умолчанию")
            return st
        v = raw.get("schema_version", 0)
        if not isinstance(v, int) or v > STATE_SCHEMA:
            self.log("theme.json создан более новой версией: тема по умолчанию, файл не перезаписывается")
            st["_readonly"] = True
            return st
        if raw.get("mode") in MODES:
            st["mode"] = raw["mode"]
        if isinstance(raw.get("preset"), str) and ID_RE.match(raw["preset"]):
            st["preset"] = raw["preset"]
        wp = raw.get("wallpaper")
        if isinstance(wp, dict) and isinstance(wp.get("palette"), dict):
            pal = {k: v for k, v in wp["palette"].items() if k in ROLES or k == "source"}
            if all(k in pal for k in ROLES) and not validate_tokens(
                    {"schema_version": SCHEMA, "id": "x", "palette": pal}, partial=True):
                st["wallpaper"] = {"path": str(wp.get("path", "")), "palette": pal}
            else:
                self.log("theme.json: палитра обоев повреждена и отброшена")
        ov = raw.get("widget_overrides", {})
        if not isinstance(ov, dict):
            ov = {}
        good = {w: b for w, b in ov.items() if not validate_overrides({w: b})}
        if len(good) != len(ov):
            self.log("widget_overrides: отброшены записи с ошибками: "
                     + ", ".join(sorted(set(ov) - set(good))))
        st["widget_overrides"] = good
        return st

    def save_state(self, st: dict) -> None:
        if st.get("_readonly"):
            raise RuntimeError("theme.json создан более новой версией HyprlandOwn: изменения не сохраняются")
        clean = {k: v for k, v in st.items() if not k.startswith("_")}
        atomic_write(self.state_file, json.dumps(clean, ensure_ascii=False, indent=2) + "\n")

    # ---------- итоговые токены ----------
    def resolve(self, st: dict | None = None) -> dict:
        st = st or self.state()
        presets = self.presets()
        base = presets.get(st["preset"])
        if base is None:
            self.log(f"тема «{st['preset']}» не найдена, используется {DEFAULT_ID}")
            base = presets[DEFAULT_ID]
        tokens = copy.deepcopy(base)
        if st["mode"] == "wallpaper":
            if st.get("wallpaper"):
                tokens["palette"] = deep_merge(tokens["palette"], st["wallpaper"]["palette"])
                tokens["palette"]["source"] = "wallpaper"
            else:
                self.log("режим «из обоев», но палитра обоев ещё не построена: цвета темы")
        tokens["widget_overrides"] = copy.deepcopy(st.get("widget_overrides", {}))
        if tokens["effects"]["quality"] == "simple":
            tokens["material"]["glow_strength"] = 0.0
        problems = validate_tokens(tokens)
        if problems:
            self.log("итоговые токены не прошли проверку, тема по умолчанию: " + problems[0])
            tokens = copy.deepcopy(presets[DEFAULT_ID])
            tokens["widget_overrides"] = {}
        tokens["mode"] = st["mode"]
        return tokens

    def hypr_conf(self, tokens: dict) -> str:
        p = tokens["palette"]
        return ("# Сгенерировано `hyprown theme` из токенов темы (этап 4). Не правьте вручную.\n"
                "general {\n"
                f"    col.active_border = {_rgba(p['primary'], 'ee')} {_rgba(p['secondary'], 'ee')} 45deg\n"
                f"    col.inactive_border = {_rgba(p['border'], 'aa')}\n"
                "}\n"
                "decoration {\n"
                f"    rounding = {tokens['shape']['radius_large']}\n"
                "}\n")

    def write(self, st: dict | None = None) -> dict:
        """Пишет tokens.json и theme.conf. Оболочка подхватывает tokens.json сама (следит за файлом)."""
        tokens = self.resolve(st)
        atomic_write(self.tokens_file, json.dumps(tokens, ensure_ascii=False, indent=2) + "\n")
        atomic_write(self.hypr_file, self.hypr_conf(tokens))
        return tokens

    def ensure_files(self) -> None:
        """Файлы, на которые ссылаются hyprland.conf и оболочка, должны существовать."""
        if not self.tokens_file.exists() or not self.hypr_file.exists():
            self.write()

    def apply_live(self, tokens: dict, env: dict) -> list[str]:
        """Цвета рамок и скругление без `hyprctl reload` (reload сбросил бы привязки Attach)."""
        if not env.get("HYPRLAND_INSTANCE_SIGNATURE") or not self.ctx.runner.which("hyprctl"):
            return []
        p, errors = tokens["palette"], []
        for key, val in (("general:col.active_border",
                          f"{_rgba(p['primary'], 'ee')} {_rgba(p['secondary'], 'ee')} 45deg"),
                         ("general:col.inactive_border", _rgba(p["border"], "aa")),
                         ("decoration:rounding", str(tokens["shape"]["radius_large"]))):
            r = self.ctx.runner.run(["hyprctl", "keyword", key, val], env=env, timeout=10)
            text = (r.out or r.err or "").strip()
            if r.code != 0 or (text and text.lower() != "ok"):
                errors.append(f"{key}: {text or 'код ' + str(r.code)}")
        return errors

    # ---------- действия пользователя ----------
    def set_preset(self, pid: str) -> dict:
        self.preset(pid)
        st = self.state()
        st["preset"], st["mode"] = pid, "preset"
        self.save_state(st)
        return self.write(st)

    def set_mode(self, mode: str) -> dict:
        if mode not in MODES:
            raise ValueError(f"режим: {', '.join(MODES)}")
        st = self.state()
        st["mode"] = mode
        self.save_state(st)
        return self.write(st)

    def set_wallpaper_palette(self, path: str, swatches: list, switch_mode: bool = False) -> dict:
        st = self.state()
        st["wallpaper"] = {"path": path, "palette": palette_from_swatches(swatches)}
        if switch_mode:
            st["mode"] = "wallpaper"
        self.save_state(st)
        return self.write(st)

    def set_override(self, wid: str, assignments: dict) -> dict:
        """assignments: {"palette.primary": "#FFB86C", "material.opacity": 0.5}."""
        if not WID_RE.match(wid):
            raise ValueError("недопустимый id виджета")
        st = self.state()
        body = copy.deepcopy(st["widget_overrides"].get(wid, {}))
        for dotted, value in assignments.items():
            parts = dotted.split(".")
            if parts[0] not in OVERRIDABLE or len(parts) < 2:
                raise ValueError(f"{dotted}: переопределять можно {', '.join(OVERRIDABLE)} (пример: palette.primary)")
            node = body
            for p in parts[:-1]:
                node = node.setdefault(p, {})
                if not isinstance(node, dict):
                    raise ValueError(f"{dotted}: неверный путь")
            node[parts[-1]] = value
        bad = validate_overrides({wid: body})
        if bad:
            raise ValueError("; ".join(bad))
        st["widget_overrides"][wid] = body
        self.save_state(st)
        return self.write(st)

    def clear_override(self, wid: str, field: str | None = None) -> dict:
        st = self.state()
        body = st["widget_overrides"].get(wid)
        if body is not None:
            if field:
                parts = field.split(".")
                chain = [body]
                for p in parts[:-1]:
                    nxt = chain[-1].get(p)
                    if not isinstance(nxt, dict):
                        break
                    chain.append(nxt)
                else:
                    chain[-1].pop(parts[-1], None)
                # убрать опустевшие ветви
                for i in range(len(chain) - 1, 0, -1):
                    if not chain[i]:
                        chain[i - 1].pop(parts[i - 1], None)
                if not body:
                    st["widget_overrides"].pop(wid)
            else:
                st["widget_overrides"].pop(wid)
        self.save_state(st)
        return self.write(st)

    def reset(self, overrides: bool = False) -> dict:
        """Откат этапа 4: стандартная палитра. Переопределения виджетов сохраняются, если не просили."""
        keep = {} if overrides else self.state().get("widget_overrides", {})
        st = default_state()
        st["widget_overrides"] = keep
        self.save_state(st)
        return self.write(st)

    # ---------- обои и виджеты оболочки (только чтение их файлов состояния) ----------
    def _read_json(self, name: str):
        try:
            data = json.loads((self.ctx.state_dir / name).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def current_wallpaper(self, monitor: str | None = None) -> str:
        """Текущие обои из wallpaper.json (схема quickshell/hyprdesk/lib/wallpaper.js): монитор, общие, первый."""
        st = self._read_json("wallpaper.json") or {}
        mons = st.get("monitors") if isinstance(st.get("monitors"), dict) else {}

        def path_of(m) -> str:
            return m.get("path", "") if isinstance(m, dict) and isinstance(m.get("path"), str) else ""

        if monitor and path_of(mons.get(monitor)):
            return path_of(mons[monitor])
        if path_of(st.get("all")):
            return path_of(st["all"])
        for name in sorted(mons):
            if path_of(mons[name]):
                return path_of(mons[name])
        return ""

    def widgets(self) -> list[dict]:
        """Виджеты холста (canvas.json): id, тип и мониторы, где они стоят. Для редактора цветов."""
        st = self._read_json("canvas.json") or {}
        seen: dict[str, dict] = {}
        mons = st.get("monitors") if isinstance(st.get("monitors"), dict) else {}
        for mon, layout in sorted(mons.items()):
            for w in (layout.get("widgets") or []) if isinstance(layout, dict) else []:
                if not isinstance(w, dict) or not isinstance(w.get("id"), str) or not WID_RE.match(w["id"]):
                    continue
                row = seen.setdefault(w["id"], {"id": w["id"], "type": str(w.get("type", "")), "monitors": []})
                row["monitors"].append(mon)
        if not seen:  # оболочка ещё не сохраняла холст: раскладка по умолчанию (lib/canvas.js)
            seen = {"clock-1": {"id": "clock-1", "type": "clock", "monitors": []},
                    "note-1": {"id": "note-1", "type": "note", "monitors": []}}
        return list(seen.values())

    def summary(self) -> dict:
        st = self.state()
        tokens = self.resolve(st)
        problems = palette_problems(tokens["palette"])
        return {"mode": st["mode"], "preset": st["preset"],
                "presets": [{"id": p["id"], "name": p["name"], "description": p.get("description", ""),
                             "palette": {r: p["palette"][r] for r in ("bg", "surface", "primary", "secondary", "accent", "text")}}
                            for p in self.presets().values()],
                "wallpaper": st.get("wallpaper"), "palette": tokens["palette"],
                "widget_overrides": st["widget_overrides"],
                "widgets": self.widgets(), "current_wallpaper": self.current_wallpaper(),
                "readable": not problems, "problems": problems, "warnings": list(self.warnings)}


def parse_assignment(text: str) -> tuple[str, object]:
    """'material.opacity=0.5' -> ('material.opacity', 0.5); цвета и строки остаются строками."""
    if "=" not in text:
        raise ValueError(f"«{text}»: нужно поле=значение, например palette.primary=#FFB86C")
    key, raw = text.split("=", 1)
    key, raw = key.strip(), raw.strip()
    if raw.lower() in ("true", "false"):
        return key, raw.lower() == "true"
    for conv in (int, float):
        try:
            return key, conv(raw)
        except ValueError:
            pass
    return key, raw
