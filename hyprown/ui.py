"""Интерфейс пользователя: терминал (цвет, шаги, вопросы) и JSON-поток для Manager.

Правила: никаких выдуманных процентов. Длинные шаги показывают бегущее время и
настоящий вывод команд; результат шага: успех или ошибка.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from contextlib import contextmanager

BANNER = r"""
  _   _                  _                 _  ___
 | | | |_   _ _ __  _ __| | __ _ _ __   __| |/ _ \__      ___ __
 | |_| | | | | '_ \| '__| |/ _` | '_ \ / _` | | | \ \ /\ / / '_ \
 |  _  | |_| | |_) | |  | | (_| | | | | (_| | |_| |\ V  V /| | | |
 |_| |_|\__, | .__/|_|  |_|\__,_|_| |_|\__,_|\___/  \_/\_/ |_| |_|
        |___/|_|
"""

_C = {"reset": "0", "bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33",
      "blue": "34", "magenta": "35", "cyan": "36"}


class UI:
    """Терминальный интерфейс. assume_yes: все вопросы получают ответ по умолчанию «да»."""

    def __init__(self, assume_yes: bool = False, color: bool | None = None, stream=None,
                 interactive: bool | None = None):
        self.out = stream or sys.stdout
        self.assume_yes = assume_yes
        isatty = bool(getattr(self.out, "isatty", lambda: False)())
        self.color = isatty if color is None else color
        self.interactive = (isatty and sys.stdin.isatty()) if interactive is None else interactive
        self.json_mode = False

    def c(self, text: str, *styles: str) -> str:
        if not self.color:
            return text
        codes = ";".join(_C[s] for s in styles)
        return f"\033[{codes}m{text}\033[0m"

    def _p(self, text: str = ""):
        print(text, file=self.out, flush=True)

    def banner(self):
        self._p(self.c(BANNER, "cyan"))
        self._p(self.c("  Рабочий стол Hyprland + Quickshell для Fedora", "bold"))
        self._p()

    def title(self, text: str):
        self._p()
        self._p(self.c("== " + text + " ==", "bold", "blue"))

    def info(self, text: str):
        self._p("  " + text)

    def ok(self, text: str):
        self._p("  " + self.c("✓", "green") + " " + text)

    def warn(self, text: str):
        self._p("  " + self.c("⚠", "yellow") + " " + text)

    def error(self, text: str):
        self._p("  " + self.c("✗", "red") + " " + text)

    def event(self, kind: str, **data):
        """Структурное событие. В терминале молчит, в JSON-режиме уходит строкой JSONL."""

    def table(self, rows: list[list[str]], header: list[str] | None = None):
        rows = [[str(x) for x in r] for r in rows]
        if header:
            rows = [header] + rows
        if not rows:
            return
        widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
        for n, r in enumerate(rows):
            line = "  " + "  ".join(c.ljust(widths[i]) for i, c in enumerate(r))
            self._p(self.c(line, "bold") if header and n == 0 else line)

    def confirm(self, question: str, default: bool = True) -> bool:
        if self.assume_yes:
            self._p(f"  ? {question} [авто: {'да' if default else 'нет'}]")
            return default
        if not self.interactive:
            self.error(f"Нужно подтверждение, но терминал неинтерактивный: {question}. "
                       "Запустите в терминале или добавьте --yes.")
            return False
        hint = "Д/н" if default else "д/Н"
        while True:
            ans = input(f"  ? {question} [{hint}] ").strip().lower()
            if not ans:
                return default
            if ans in ("д", "да", "y", "yes"):
                return True
            if ans in ("н", "нет", "n", "no"):
                return False

    def choose_many(self, title: str, items: list[tuple[str, str, bool]]) -> list[str]:
        """Меню с галочками. items: (id, подпись, включено). Возвращает выбранные id."""
        state = {i[0]: i[2] for i in items}
        if self.assume_yes or not self.interactive:
            return [k for k, v in state.items() if v]
        while True:
            self._p()
            self._p(self.c(title, "bold"))
            for n, (cid, label, _) in enumerate(items, 1):
                mark = self.c("[x]", "green") if state[cid] else "[ ]"
                self._p(f"  {n:>2}. {mark} {label}")
            ans = input("  Номера для переключения, Enter: продолжить, q: выйти > ").strip().lower()
            if ans == "":
                return [k for k, v in state.items() if v]
            if ans == "q":
                return []
            for tok in ans.replace(",", " ").split():
                if tok.isdigit() and 1 <= int(tok) <= len(items):
                    cid = items[int(tok) - 1][0]
                    state[cid] = not state[cid]

    @contextmanager
    def step(self, title: str):
        """Шаг с бегущим временем. Результат (ok/fail) задаёт вызывающий через s.fail()/s.warn()."""
        s = _Step(self, title)
        s.start()
        try:
            yield s
        except Exception as exc:  # шаг упал: показываем и пробрасываем дальше
            s.finish("fail", str(exc))
            raise
        else:
            s.finish(s.status or "ok", s.note)


class _Step:
    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, ui: UI, title: str):
        self.ui, self.title = ui, title
        self.status = None
        self.note = ""
        self._stop = threading.Event()
        self._thread = None
        self._t0 = time.monotonic()
        self.live = ui.color and ui.interactive

    def fail(self, note: str = ""):
        self.status, self.note = "fail", note

    def warn(self, note: str = ""):
        self.status, self.note = "warn", note

    def start(self):
        self.ui.event("step_start", title=self.title)
        if self.live:
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        else:
            self.ui.info("→ " + self.title)

    def _spin(self):
        i = 0
        while not self._stop.is_set():
            el = int(time.monotonic() - self._t0)
            self.ui.out.write(f"\r  {self.ui.c(self.FRAMES[i % 10], 'cyan')} {self.title} ({el} с)\033[K")
            self.ui.out.flush()
            i += 1
            self._stop.wait(0.12)

    def pause(self):
        """Остановить анимацию перед потоковым выводом команды."""
        if self._thread:
            self._stop.set()
            self._thread.join()
            self.ui.out.write("\r\033[K")
            self._thread = None
            self.ui.info("→ " + self.title)

    def finish(self, status: str, note: str = ""):
        self.pause()
        if self.live:
            self.ui.out.write("\r\033[K")
        el = time.monotonic() - self._t0
        suffix = f" ({el:.1f} с)" if el >= 1 else ""
        text = self.title + (": " + note if note else "") + suffix
        {"ok": self.ui.ok, "warn": self.ui.warn, "fail": self.ui.error}[status](text)
        self.ui.event("step_end", title=self.title, status=status, note=note)


class JsonUI(UI):
    """Поток JSON-строк для графического Manager: по одной записи на строку."""

    def __init__(self, assume_yes: bool = False, stream=None):
        super().__init__(assume_yes=assume_yes, color=False, stream=stream, interactive=False)
        self.json_mode = True

    def _emit(self, kind, **data):
        print(json.dumps({"event": kind, **data}, ensure_ascii=False), file=self.out, flush=True)

    def event(self, kind, **data):
        self._emit(kind, **data)

    def banner(self):
        pass

    def title(self, text):
        self._emit("title", text=text)

    def info(self, text):
        self._emit("info", text=text)

    def ok(self, text):
        self._emit("ok", text=text)

    def warn(self, text):
        self._emit("warn", text=text)

    def error(self, text):
        self._emit("error", text=text)

    def table(self, rows, header=None):
        self._emit("table", header=header, rows=rows)

    def confirm(self, question, default=True):
        if self.assume_yes:
            return default
        self._emit("error", text=f"Нужно подтверждение: {question}. Manager обязан показать план и вызвать команду с --yes.")
        return False

    def step(self, title):
        return _JsonStep(self, title)


@contextmanager
def _noop():
    yield


class _JsonStep:
    def __init__(self, ui, title):
        self.ui, self.title, self.status, self.note = ui, title, None, ""

    def fail(self, note=""):
        self.status, self.note = "fail", note

    def warn(self, note=""):
        self.status, self.note = "warn", note

    def pause(self):
        pass

    def __enter__(self):
        self.ui.event("step_start", title=self.title)
        return self

    def __exit__(self, et, ev, tb):
        if et:
            self.ui.event("step_end", title=self.title, status="fail", note=str(ev))
            return False
        self.ui.event("step_end", title=self.title, status=self.status or "ok", note=self.note)
        return False
