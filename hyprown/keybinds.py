"""Реестр горячих клавиш: единый источник, проверка конфликтов, сверка с запущенной сессией.

Зачем это нужно (найденные проблемы):
  * В стандартном (автосгенерированном) конфиге Hyprland Super+M ВЫХОДИТ из сессии, а у нас
    Super+M открывает Manager; Super+E там файловый менеджер, у нас режим правки холста.
    Если запущен чужой конфиг, нажатие «нашей» клавиши делает чужое действие. Поэтому
    сверяем РЕАЛЬНО применённые привязки (`hyprctl -j binds`), а не только файл.
  * Список клавиш жил в одном рукописном файле без проверок: дубли и пересечения
    находились только руками.
  * В Preview Super заменяется на Alt, и Alt+Space перехватывает KDE (KRunner): лаунчер там
    переносится на Alt+R (поле preview_key в реестре).

Структура:
  manifests/keybinds.toml          реестр (единственный источник)
  hypr/keybinds.conf               ГЕНЕРИРУЕТСЯ из реестра (`hyprown keys render --write`)
  ~/.local/state/hyprdesk/keybinds.user.json    переназначения пользователя
  ~/.local/state/hyprdesk/keybinds.user.conf    ГЕНЕРИРУЕТСЯ: unbind старой + bind новой комбинации
Файл пользователя подключается ПОСЛЕ hypr/keybinds.conf и не затрагивает репозиторий.
Без разрешения мы не перезаписываем ни прежнее переназначение, ни вручную правленый файл.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .context import Ctx
from .registry import atomic_write

MOD_ORDER = ("SUPER", "CTRL", "ALT", "SHIFT")
MOD_ALIASES = {"SUPER": "SUPER", "WIN": "SUPER", "META": "SUPER", "MOD4": "SUPER", "LOGO": "SUPER",
               "$MAINMOD": "SUPER", "CTRL": "CTRL", "CONTROL": "CTRL", "ALT": "ALT", "MOD1": "ALT",
               "SHIFT": "SHIFT"}
# Биты modmask из `hyprctl binds`: SHIFT=1, CAPS=2, CTRL=4, ALT=8, MOD2(Num)=16, MOD3=32, SUPER=64, MOD5=128.
MODMASK = {1: "SHIFT", 4: "CTRL", 8: "ALT", 64: "SUPER"}

NAMED_KEYS = {
    "return", "enter", "space", "tab", "escape", "backspace", "delete", "insert", "home", "end", "prior", "next",
    "page_up", "page_down", "left", "right", "up", "down", "print", "pause", "menu", "minus", "equal", "comma",
    "period", "slash", "backslash", "semicolon", "apostrophe", "grave", "bracketleft", "bracketright",
    "caps_lock", "scroll_lock", "num_lock", "mouse_up", "mouse_down", "mouse_left", "mouse_right",
}

# Привязки автосгенерированного конфига Hyprland (examples/hyprland.conf). Нужны только для
# предупреждений: если сессия запущена с чужим конфигом, эти клавиши делают ЭТО.
DEFAULT_HYPRLAND = {
    (("SUPER",), "q"): "запуск терминала",
    (("SUPER",), "c"): "закрыть окно (killactive)",
    (("SUPER",), "m"): "ВЫХОД из Hyprland (exit)",
    (("SUPER",), "e"): "файловый менеджер",
    (("SUPER",), "v"): "плавающее окно",
    (("SUPER",), "r"): "лаунчер",
    (("SUPER",), "p"): "pseudo",
    (("SUPER",), "j"): "togglesplit",
    (("SUPER",), "s"): "скрытое рабочее пространство magic",
    (("SUPER", "SHIFT"), "s"): "окно в рабочее пространство magic",
}

# Глобальные клавиши KDE, которые перехватываются раньше, чем попадут во вложенный Preview.
HOST_RESERVED_PREVIEW = {
    (("ALT",), "space"): "KRunner / меню окна KDE",
    (("ALT",), "tab"): "переключение окон KDE",
    (("ALT", "SHIFT"), "tab"): "переключение окон KDE",
    (("ALT",), "f1"): "меню приложений KDE",
    (("ALT",), "f2"): "KRunner",
    (("ALT",), "f4"): "закрытие окна KDE",
}

USER_JSON = "keybinds.user.json"
USER_CONF = "keybinds.user.conf"
GEN_MARK = "# hyprown-keybinds-generated sha256="


# ---------------------------------------------------------------- разбор
def norm_mods(value) -> tuple:
    """'SUPER SHIFT' / ['super','shift'] / '$mainMod, SHIFT' -> ('SUPER', 'SHIFT') в каноническом порядке."""
    if isinstance(value, str):
        tokens = [t for t in re.split(r"[\s_+,]+", value.strip()) if t]
    else:
        tokens = [str(t) for t in value]
    out = set()
    for t in tokens:
        canon = MOD_ALIASES.get(t.upper())
        if not canon:
            raise ValueError(f"неизвестный модификатор «{t}» (допустимы SUPER, CTRL, ALT, SHIFT)")
        out.add(canon)
    return tuple(m for m in MOD_ORDER if m in out)


def valid_key(key: str) -> bool:
    k = key.strip().lower()
    if not k:
        return False
    if len(k) == 1 and k.isalnum() and k.isascii():
        return True
    if k in NAMED_KEYS:
        return True
    return bool(re.fullmatch(r"f([1-9]|1\d|2[0-4])|code:\d+|mouse:\d+|xf86[a-z0-9]+|kp_[a-z0-9_]+", k))


def combo_text(mods, key: str) -> str:
    m = norm_mods(mods)
    names = [("Ctrl" if x == "CTRL" else x.capitalize()) for x in m]
    return "+".join(names + [key[:1].upper() + key[1:] if len(key) > 1 else key.upper()])


def to_preview(mods: tuple) -> tuple:
    """В Preview главный модификатор Alt (hypr/hyprland.conf: $mainMod = ALT)."""
    return norm_mods(["ALT" if m == "SUPER" else m for m in mods])


# ---------------------------------------------------------------- модель
@dataclass
class Bind:
    id: str
    title: str
    category: str
    kind: str
    mods: tuple
    key: str
    dispatcher: str
    arg: str = ""
    preview_mods: tuple | None = None
    preview_key: str | None = None
    critical: bool = False

    def desktop(self) -> tuple:
        return self.mods, self.key

    def preview(self) -> tuple:
        mods = self.preview_mods if self.preview_mods is not None else to_preview(self.mods)
        return mods, (self.preview_key or self.key)


@dataclass
class Eff:
    """Действующая привязка: запись реестра с учётом переназначения пользователя."""
    bind: Bind
    mods: tuple
    key: str
    overridden: bool = False
    disabled: bool = False

    @property
    def combo(self) -> tuple:
        return (self.mods, self.key.lower())


@dataclass
class Conflict:
    level: str        # error: назначить нельзя; warn: можно с --force
    kind: str
    message: str
    with_id: str = ""

    def to_dict(self):
        return {"level": self.level, "kind": self.kind, "message": self.message, "with": self.with_id}


@dataclass
class LiveBind:
    mods: tuple
    key: str
    dispatcher: str
    arg: str
    mouse: bool = False
    submap: str = ""


def load_registry(ctx: Ctx) -> list[Bind]:
    path = ctx.repo / "manifests" / "keybinds.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1:
        raise ValueError(f"{path}: неподдерживаемая схема реестра клавиш")
    out, seen = [], set()
    for raw in data.get("bind", []):
        keys = raw.get("keys") or [raw.get("key")]
        if not all(keys):
            raise ValueError(f"{path}: у записи {raw.get('id')} нет key/keys")
        for k in keys:
            def fill(s, k=k):
                return s.replace("{k}", k) if isinstance(s, str) else s
            bid = f"{raw['id']}.{k}" if raw.get("keys") else raw["id"]
            if bid in seen:
                raise ValueError(f"{path}: повторяющийся id {bid}")
            seen.add(bid)
            pm = raw.get("preview_mods")
            out.append(Bind(
                id=bid, title=fill(raw.get("title", bid)), category=raw.get("category", ""),
                kind=raw.get("kind", "bind"), mods=norm_mods(raw.get("mods", "")), key=k,
                dispatcher=raw["dispatcher"], arg=fill(raw.get("arg", "")),
                preview_mods=norm_mods(pm) if pm is not None else None,
                preview_key=raw.get("preview_key"), critical=bool(raw.get("critical", False))))
    return out


# ---------------------------------------------------------------- пользовательские переназначения
class UserStore:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self.path = ctx.state_dir / USER_JSON
        self.conf = ctx.state_dir / USER_CONF

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return {"overrides": dict(data.get("overrides", {})), "disabled": list(data.get("disabled", []))}

    def save(self, data: dict) -> None:
        atomic_write(self.path, json.dumps({"schema": 1, **data}, indent=2, ensure_ascii=False) + "\n")


NO_USER = {"overrides": {}, "disabled": []}


def effective(binds: list[Bind], user: dict, mode: str = "desktop") -> list[Eff]:
    out = []
    for b in binds:
        ov = user["overrides"].get(b.id)
        if ov:
            mods = norm_mods(ov["mods"])
            if mode == "preview":
                mods = to_preview(mods)
            e = Eff(b, mods, ov["key"], overridden=True)
        else:
            mods, key = b.preview() if mode == "preview" else b.desktop()
            e = Eff(b, mods, key)
        e.disabled = b.id in user["disabled"]
        out.append(e)
    return out


# ---------------------------------------------------------------- рендер конфигов
def _mods_text(mods: tuple, mode: str) -> str:
    return " ".join("$mainMod" if (m == "SUPER" and mode == "desktop") else m for m in mods)


def _line(e: Eff, mode: str) -> str:
    b = e.bind
    tail = f", {b.arg}" if b.arg else ""
    return f"{b.kind} = {_mods_text(e.mods, mode)}, {e.key}, {b.dispatcher}{tail}"


def render_default(binds: list[Bind], mode: str = "desktop") -> str:
    """Текст hypr/keybinds.conf: значения по умолчанию, без пользовательских переназначений."""
    lines = ["# Горячие клавиши HyprlandOwn. ФАЙЛ СГЕНЕРИРОВАН из manifests/keybinds.toml:",
             "# правьте реестр или переназначайте клавиши через `hyprown keys` / Manager,",
             "# затем `hyprown keys render --write`. Переназначения пользователя лежат отдельно",
             "# (~/.local/state/hyprdesk/keybinds.user.conf) и подключаются после этого файла.",
             "$mainMod = " + ("ALT" if mode == "preview" else "SUPER")]
    last = None
    for e in effective(binds, NO_USER, mode):
        if e.bind.category != last:
            lines += ["", "# " + e.bind.category]
            last = e.bind.category
        lines.append(_line(e, mode))
    return "\n".join(lines) + "\n"


def render_user(binds: list[Bind], user: dict, mode: str = "desktop") -> str:
    """Переназначения: сначала снимаем ВСЕ затронутые комбинации, затем ставим новые (порядок важен для обменов)."""
    base = {e.bind.id: e for e in effective(binds, NO_USER, mode)}
    eff = {e.bind.id: e for e in effective(binds, user, mode)}
    changed = [i for i, e in eff.items() if e.overridden or e.disabled]
    lines = ["# Переназначения пользователя (hyprown keys). Не правьте вручную: файл пересоздаётся."]
    for i in changed:
        b = base[i]
        lines.append(f"unbind = {_mods_text(b.mods, mode)}, {b.key}")
    for i in changed:
        e = eff[i]
        if e.overridden and not e.disabled:
            lines.append(_line(e, mode))
    return "\n".join(lines) + "\n"


def _digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def stamp(body: str) -> str:
    return f"{GEN_MARK}{_digest(body)}\n{body}"


def untouched(text: str) -> bool:
    """True, если файл создан нами и не правился вручную."""
    head, _, body = text.partition("\n")
    return head.startswith(GEN_MARK) and head[len(GEN_MARK):].strip() == _digest(body)


# ---------------------------------------------------------------- проверка конфликтов
def validate_combo(mods, key: str, kind: str = "bind") -> list[Conflict]:
    try:
        norm_mods(mods)
    except ValueError as exc:
        return [Conflict("error", "invalid", str(exc))]
    if not valid_key(key):
        return [Conflict("error", "invalid",
                         f"неизвестное имя клавиши «{key}» (примеры: A, 1, RETURN, SPACE, left, F5, code:NN)")]
    if kind == "bindm" and not key.lower().startswith("mouse:"):
        return [Conflict("error", "invalid", "привязка мыши должна быть кнопкой mouse:272 или mouse:273")]
    return []


def check_combo(binds: list[Bind], user: dict, mods, key: str, ignore_id: str | None = None,
                kind: str = "bind") -> list[Conflict]:
    """Все проблемы назначения (mods, key). error блокирует; warn пропускается только с --force."""
    out = validate_combo(mods, key, kind)
    if out:
        return out
    mods = norm_mods(mods)
    k = key.strip().lower()
    for mode in ("desktop", "preview"):
        cand = (to_preview(mods) if mode == "preview" else mods, k)
        for e in effective(binds, user, mode):
            if e.bind.id == ignore_id or e.disabled:
                continue
            if e.combo == cand and not (mode == "preview" and any(c.with_id == e.bind.id for c in out)):
                where = "" if mode == "desktop" else " (в Preview Super заменяется на Alt)"
                out.append(Conflict("error", "duplicate",
                                    f"уже занято: «{e.bind.title}» ({e.bind.id}){where}", e.bind.id))
        if mode == "preview" and cand in HOST_RESERVED_PREVIEW:
            out.append(Conflict("warn", "host-reserved",
                                f"в Preview эту комбинацию перехватывает KDE: {HOST_RESERVED_PREVIEW[cand]}"))
    why = DEFAULT_HYPRLAND.get((mods, k))
    if why:
        out.append(Conflict("warn", "hyprland-default",
                            f"в стандартном конфиге Hyprland это «{why}»: если сессия запущена с чужим "
                            "конфигом, сработает стандартное действие"))
    seen, uniq = set(), []
    for c in out:
        if (c.kind, c.message) not in seen:
            seen.add((c.kind, c.message))
            uniq.append(c)
    return uniq


def validate_registry(binds: list[Bind]) -> list[str]:
    """Проблемы самого реестра по умолчанию (дубли, плохие клавиши, перехват KDE в Preview)."""
    problems = []
    for b in binds:
        for c in validate_combo(b.mods, b.key, b.kind):
            problems.append(f"{b.id}: {c.message}")
    for mode in ("desktop", "preview"):
        seen: dict = {}
        for e in effective(binds, NO_USER, mode):
            if e.combo in seen:
                problems.append(f"[{mode}] {e.bind.id} и {seen[e.combo]} используют одну комбинацию "
                                f"{combo_text(e.mods, e.key)}")
            seen[e.combo] = e.bind.id
            if mode == "preview" and e.combo in HOST_RESERVED_PREVIEW:
                problems.append(f"[preview] {e.bind.id}: {combo_text(e.mods, e.key)} перехватывает KDE "
                                f"({HOST_RESERVED_PREVIEW[e.combo]})")
    return problems


# ---------------------------------------------------------------- сверка с запущенной сессией
def parse_live(text: str) -> list[LiveBind]:
    out = []
    for r in json.loads(text or "[]"):
        mask = int(r.get("modmask", 0))
        mods = tuple(m for m in MOD_ORDER if any(bit & mask and name == m for bit, name in MODMASK.items()))
        key = str(r.get("key", "")).strip()
        if not key and r.get("keycode"):
            key = f"code:{r['keycode']}"
        out.append(LiveBind(mods, key.lower(), str(r.get("dispatcher", "")), str(r.get("arg", "")),
                            bool(r.get("mouse", False)), str(r.get("submap", ""))))
    return out


def expand_vars(arg: str, variables: dict) -> str:
    """Подставляет $переменные конфига (hyprctl keyword переменных не знает)."""
    s = arg or ""
    for _ in range(3):
        s = re.sub(r"\$(\w+)", lambda m: variables.get(m.group(1), m.group(0)), s)
    return s


def norm_arg(arg: str, variables: dict) -> str:
    """Сравнимый вид аргумента: $переменные подставлены, пути к hyprown сведены к слову hyprown."""
    s = re.sub(r"(?:\S*[/\\])?hyprown(?=\s|$)", "hyprown", expand_vars(arg, variables))
    return " ".join(s.split())


class KeyManager:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self.binds = load_registry(ctx)
        self.store = UserStore(ctx)

    # ---------- данные ----------
    def user(self) -> dict:
        return self.store.load()

    def variables(self) -> dict:
        out = {}
        try:
            text = (self.ctx.repo / "hypr" / "hyprland.conf").read_text(encoding="utf-8")
        except OSError:
            return out
        for m in re.finditer(r"(?m)^\$(\w+)\s*=\s*(.+?)\s*$", text):
            out[m.group(1)] = m.group(2)
        return out

    def get(self, bind_id: str) -> Bind:
        for b in self.binds:
            if b.id == bind_id:
                return b
        raise KeyError(f"нет такой привязки: {bind_id} (список: hyprown keys list)")

    def listing(self, mode: str = "desktop") -> list[dict]:
        user = self.user()
        rows = []
        for e in effective(self.binds, user, mode):
            b = e.bind
            others = check_combo(self.binds, user, e.mods, e.key, ignore_id=b.id, kind=b.kind)
            rows.append({"id": b.id, "title": b.title, "category": b.category, "kind": b.kind,
                         "mods": " ".join(e.mods), "key": e.key, "combo": combo_text(e.mods, e.key),
                         "default": combo_text(*b.desktop()), "default_mods": " ".join(b.mods),
                         "default_key": b.key, "dispatcher": b.dispatcher, "arg": b.arg,
                         "overridden": e.overridden, "disabled": e.disabled, "critical": b.critical,
                         "conflicts": [c.to_dict() for c in others]})
        return rows

    def check(self, mods, key: str, entry_id: str | None = None) -> list[Conflict]:
        kind = self.get(entry_id).kind if entry_id else "bind"
        return check_combo(self.binds, self.user(), mods, key, ignore_id=entry_id, kind=kind)

    def missing_targets(self) -> list[str]:
        """exec-привязки, чья программа не установлена (клавиша нажимается, но ничего не происходит)."""
        v, bad = self.variables(), []
        for b in self.binds:
            if b.dispatcher != "exec":
                continue
            first = (norm_arg(b.arg, v).split() or [""])[0]
            if first and not first.startswith(("hyprown", "~", "/")) and not self.ctx.runner.which(first):
                bad.append(f"{b.id}: программа «{first}» не найдена в PATH")
        return bad

    # ---------- запись конфигов ----------
    def ensure_user_conf(self) -> None:
        if not self.store.conf.exists():
            atomic_write(self.store.conf, stamp(render_user(self.binds, self.user())))

    def default_conf_path(self) -> Path:
        return self.ctx.repo / "hypr" / "keybinds.conf"

    def render_files(self, write: bool = False) -> str:
        text = render_default(self.binds)
        if write:
            atomic_write(self.default_conf_path(), text)
        return text

    def user_conf_hand_edited(self) -> bool:
        f = self.store.conf
        return f.exists() and not untouched(f.read_text(encoding="utf-8"))

    def write_user_conf(self, user: dict) -> str:
        """Пересоздаёт keybinds.user.conf. Вручную правленый файл сначала копируется в резервную."""
        f, note = self.store.conf, ""
        if self.user_conf_hand_edited():
            self.ctx.backup_dir.mkdir(parents=True, exist_ok=True)
            bak = self.ctx.backup_dir / f"{USER_CONF}.{time.strftime('%Y%m%d-%H%M%S')}"
            shutil.copy2(f, bak)
            note = f"прежний файл правился вручную, копия: {bak}"
        atomic_write(f, stamp(render_user(self.binds, user)))
        return note

    # ---------- изменение ----------
    def set(self, entry_id: str, mods, key: str, force: bool = False) -> tuple[bool, list[str]]:
        """Назначает комбинацию. Возвращает (успех, сообщения). При отказе ничего не пишет."""
        ui = self.ctx.ui
        b = self.get(entry_id)
        conflicts = self.check(mods, key, entry_id)
        errors = [c for c in conflicts if c.level == "error"]
        warns = [c for c in conflicts if c.level == "warn"]
        if errors:
            return False, ["Назначение отклонено: " + c.message for c in errors]
        if (norm_mods(mods), key.strip().lower()) == (b.mods, b.key.lower()):
            warns = []  # возврат к штатной комбинации проекта предупреждений не требует
        if warns and not force:
            return False, ["Предупреждение: " + c.message for c in warns] + \
                ["Чтобы всё равно назначить, повторите с --force."]
        user = self.user()
        if entry_id in user["overrides"]:
            old = user["overrides"][entry_id]
            if not ui.confirm(f"Для «{b.title}» уже назначено {combo_text(old['mods'], old['key'])}. Заменить?",
                              default=False, yes_ok=True):
                return False, ["Отменено: прежнее назначение сохранено."]
        if self.user_conf_hand_edited() and not ui.confirm(
                f"{self.store.conf} правился вручную. Пересоздать его (копия сохранится)?", default=False, yes_ok=True):
            return False, ["Отменено: файл с вашими правками не тронут."]
        m, k = norm_mods(mods), key.strip()
        if (m, k.lower()) == (b.mods, b.key.lower()):
            user["overrides"].pop(entry_id, None)  # назначили то, что и так по умолчанию
        else:
            user["overrides"][entry_id] = {"mods": " ".join(m), "key": k}
        if entry_id in user["disabled"]:
            user["disabled"].remove(entry_id)
        self.store.save(user)
        msgs = [f"{b.title}: {combo_text(m, k)}"]
        note = self.write_user_conf(user)
        return True, msgs + ([note] if note else [])

    def disable(self, entry_id: str, force: bool = False) -> tuple[bool, list[str]]:
        b = self.get(entry_id)
        if b.critical and not force:
            return False, [f"«{b.title}» аварийная привязка: без неё можно остаться без выхода. "
                           "Повторите с --force."]
        user = self.user()
        if entry_id not in user["disabled"]:
            user["disabled"].append(entry_id)
        self.store.save(user)
        note = self.write_user_conf(user)
        return True, [f"{b.title}: отключена"] + ([note] if note else [])

    def reset(self, entry_id: str | None = None) -> list[str]:
        user = self.user()
        if entry_id:
            self.get(entry_id)
            user["overrides"].pop(entry_id, None)
            if entry_id in user["disabled"]:
                user["disabled"].remove(entry_id)
        else:
            user = {"overrides": {}, "disabled": []}
        self.store.save(user)
        note = self.write_user_conf(user)
        return ["Значения по умолчанию возвращены"] + ([note] if note else [])

    # ---------- запущенная сессия ----------
    def live(self, env: dict, mode: str = "desktop") -> dict:
        res = self.ctx.runner.run(["hyprctl", "-j", "binds"], mutates=False, timeout=10, env=env)
        if not res.ok:
            return {"ok": None, "error": (res.err or res.out).strip() or "hyprctl binds завершился с ошибкой",
                    "items": [], "extras": [], "summary": {}}
        try:
            live = [b for b in parse_live(res.out) if b.submap == ""]
        except (ValueError, TypeError, AttributeError) as exc:
            return {"ok": None, "error": f"непонятный ответ hyprctl binds: {exc}",
                    "items": [], "extras": [], "summary": {}}
        v = self.variables()
        by_combo: dict = {}
        for lb in live:
            by_combo.setdefault((lb.mods, lb.key), []).append(lb)
        items, used = [], set()
        for e in effective(self.binds, self.user(), mode):
            if e.disabled:
                continue
            b, cands = e.bind, by_combo.get(e.combo, [])
            used.add(e.combo)
            row = {"id": b.id, "title": b.title, "combo": combo_text(e.mods, e.key),
                   "want": f"{b.dispatcher} {norm_arg(b.arg, v)}".strip(), "danger": False}
            same = [c for c in cands if c.dispatcher == b.dispatcher and norm_arg(c.arg, v) == norm_arg(b.arg, v)]
            if not cands:
                row.update(status="missing", detail="в запущенной сессии не назначена")
            elif not same:
                got = "; ".join(f"{c.dispatcher} {c.arg}".strip() for c in cands)
                row.update(status="overridden", detail=f"там другое действие: {got}",
                           danger=any(c.dispatcher == "exit" for c in cands))
            elif len(cands) > 1:
                row.update(status="duplicate", detail="на комбинацию повешено ещё: " + "; ".join(
                    f"{c.dispatcher} {c.arg}".strip() for c in cands if c not in same))
            else:
                row.update(status="ok", detail="")
            items.append(row)
        extras = []
        for combo, cands in by_combo.items():
            if combo in used:
                continue
            for c in cands:
                extras.append({"combo": combo_text(combo[0], combo[1]) if combo[1] else "?",
                               "action": f"{c.dispatcher} {c.arg}".strip(),
                               "hyprland_default": combo in DEFAULT_HYPRLAND})
        count = {s: sum(1 for i in items if i["status"] == s) for s in ("ok", "missing", "overridden", "duplicate")}
        count["foreign"] = len(extras)
        return {"ok": count["missing"] + count["overridden"] + count["duplicate"] == 0, "error": "",
                "items": items, "extras": extras, "summary": count,
                "default_hyprland_binds": sum(1 for x in extras if x["hyprland_default"])}

    def would_replace(self, live: dict) -> list[dict]:
        """Что именно отнимет apply_live у чужого конфига: комбинации, где сейчас другое действие."""
        return [i for i in live.get("items", []) if i["status"] in ("overridden", "duplicate")]

    def apply_live(self, env: dict, mode: str = "desktop") -> dict:
        """Ставит привязки через IPC (`hyprctl keyword`): работает и с чужим конфигом, без выхода из сессии.

        Сначала снимаются все комбинации реестра (в том числе чужие, вроде Super+M = exit), затем
        ставятся наши. `hyprctl reload` возвращает состояние, описанное в конфиге сессии.
        """
        v, errors = self.variables(), []
        eff = effective(self.binds, self.user(), mode)

        def kw(name: str, value: str) -> None:
            r = self.ctx.runner.run(["hyprctl", "keyword", name, value], env=env, timeout=10)
            text = (r.out or "").strip()
            if not r.ok or (text and text != "ok"):
                errors.append(f"{name} {value}: {text or r.err.strip()}")

        combos = {(e.mods, e.key) for e in effective(self.binds, NO_USER, mode)} | {(e.mods, e.key) for e in eff}
        for mods, key in sorted(combos):
            kw("unbind", f"{' '.join(mods)},{key}")
        bound = 0
        for e in eff:
            if e.disabled:
                continue
            b = e.bind
            arg = expand_vars(b.arg, v).replace("~/.local/bin/hyprown", str(self.ctx.repo / "bin" / "hyprown"))
            kw(b.kind, f"{' '.join(e.mods)},{e.key},{b.dispatcher}" + (f",{arg}" if arg else ""))
            bound += 1
        return {"bound": bound, "unbound": len(combos), "errors": errors}
