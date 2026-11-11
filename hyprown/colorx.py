"""Извлечение доминирующих цветов из обоев (этап 4): картинка или первый кадр видео.

Как работает:
  1. ffmpeg (или ImageMagick, если ffmpeg нет или не справился) уменьшает картинку/первый кадр
     до RAW_SIDE x RAW_SIDE пикселей rgb24 и пишет их во временный файл. Видео: первый кадр.
  2. Пиксели складываются в корзины 4 бита на канал (16^3 = 4096 корзин); у каждой корзины
     считается средний цвет и доля пикселей.
  3. Возвращаются самые весомые корзины как Swatch; роли палитры выбирает
     theme.palette_from_swatches.

Почему так: нет зависимостей кроме ffmpeg/ImageMagick (ffmpeg уже нужен Wallpaper Engine для превью),
результат детерминирован, вызов ограничен по времени. Файл обоев только читается.
Ошибки дают ColorxError с понятным текстом; вызывающий код оставляет прежнюю палитру.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .theme import Swatch

RAW_SIDE = 64            # сторона уменьшенной картинки
TOP_SWATCHES = 48        # сколько корзин возвращаем
TIMEOUT = 30             # секунд на один вызов ffmpeg/magick
MAX_SOURCE_BYTES = 8 * 1024 ** 3  # больше 8 ГБ не читаем (защита от случайного файла)


class ColorxError(Exception):
    """Цвета не извлечены: нет файла, нет инструмента, инструмент не справился."""


def quantize(raw: bytes, top: int = TOP_SWATCHES) -> list:
    """rgb24 -> самые весомые цвета. Чистая функция: проверяется тестами без ffmpeg."""
    n = len(raw) // 3
    if n == 0:
        raise ColorxError("в картинке нет пикселей")
    sums: dict = {}
    for i in range(0, n * 3, 3):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        key = ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4)
        acc = sums.get(key)
        if acc is None:
            sums[key] = [r, g, b, 1]
        else:
            acc[0] += r
            acc[1] += g
            acc[2] += b
            acc[3] += 1
    # Сортировка по доле, затем по ключу: результат не зависит от порядка словаря.
    ordered = sorted(sums.items(), key=lambda kv: (-kv[1][3], kv[0]))[:top]
    return [Swatch((a[0] / a[3] / 255.0, a[1] / a[3] / 255.0, a[2] / a[3] / 255.0), a[3] / n)
            for _, a in ordered]


def _commands(src: str, out: str) -> list:
    side = RAW_SIDE
    magick = ["-resize", f"{side}x{side}!", "-depth", "8", f"rgb:{out}"]
    return [
        ("ffmpeg", ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", src, "-frames:v", "1",
                    "-vf", f"scale={side}:{side}:flags=area,format=rgb24", "-f", "rawvideo", out]),
        ("magick", ["magick", f"{src}[0]"] + magick),
        ("convert", ["convert", f"{src}[0]"] + magick),
    ]


def extract_swatches(ctx, path: str) -> list:
    """Доминирующие цвета файла обоев (картинка или видео, первый кадр)."""
    try:
        src = Path(path).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise ColorxError(f"путь не разобран: {exc}") from exc
    if not src.is_file():
        raise ColorxError(f"файл не найден: {src}")
    if src.stat().st_size > MAX_SOURCE_BYTES:
        raise ColorxError("файл слишком большой для разбора цветов")
    expected = RAW_SIDE * RAW_SIDE * 3
    tried: list = []
    fd, tmp = tempfile.mkstemp(prefix="hyprown-colorx-", suffix=".rgb")
    os.close(fd)
    try:
        # Путь абсолютный (resolve): имя, начинающееся с «-», не превратится в опцию.
        for tool, cmd in _commands(str(src), tmp):
            if not ctx.runner.which(tool):
                continue
            tried.append(tool)
            Path(tmp).write_bytes(b"")
            res = ctx.runner.run(cmd, mutates=False, timeout=TIMEOUT)
            if res.code != 0:
                continue
            data = Path(tmp).read_bytes()
            if len(data) == expected:
                return quantize(data)
        if not tried:
            raise ColorxError("нужен ffmpeg или ImageMagick (sudo dnf install ffmpeg-free)")
        raise ColorxError(f"{', '.join(tried)} не смогли прочитать {src.name} "
                          "(формат не поддерживается или файл повреждён)")
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
