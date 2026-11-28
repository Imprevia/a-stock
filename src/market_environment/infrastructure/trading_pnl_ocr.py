"""Bounded local screenshot recognition for the simulated-trade list."""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from statistics import median
from time import monotonic

from PIL import Image, UnidentifiedImageError

from ..domain.models.trading_pnl import MAX_IMAGE_BYTES, ScreenshotError

MAX_PIXELS = 12_000_000
MONTH = re.compile(r"(20\d{2})年(0?[1-9]|1[0-2])月")
DAY = re.compile(r"(?<!\d)(\d{1,2})[-/](\d{1,2})(?!\d)")
SECURITY = re.compile(r"(?<!\d)(\d{6})\.(SH|SZ|BJ)(?![A-Za-z])", re.I)
SHARES = re.compile(r"(\d+(?:,\d{3})*)(?:/(\d+(?:,\d{3})*))?股")
NUMBER = re.compile(r"^[￥¥]?(\d+(?:,\d{3})*(?:\.\d{1,6})?)$")
STATUSES = (
    ("部成部撤", "canceled"), ("部分撤单", "canceled"), ("撤单", "canceled"),
    ("已撤", "canceled"), ("部分成交", "partial"), ("未成交", "pending"),
    ("待成交", "pending"), ("已报", "pending"), ("全部交成", "filled"), ("成交", "filled"),
)


@dataclass(frozen=True)
class Word:
    left: int
    top: int
    width: int
    height: int
    text: str

    @property
    def middle(self) -> float:
        return self.top + self.height / 2


@dataclass(frozen=True)
class Screenshot:
    digest: str
    image: bytes
    media_type: str
    rows: list[dict]
    hints: list[str]


def image_digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class ScreenshotRecognizer:
    def __init__(self, executable: str = "tesseract", timeout: int = 12) -> None:
        self.executable = executable
        self.timeout = timeout

    def __call__(self, raw: bytes) -> Screenshot:
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise ScreenshotError("每张截图限 5 MB")
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in {"PNG", "JPEG"} or image.width * image.height > MAX_PIXELS:
                    raise ScreenshotError("请上传像素尺寸在限制内的 PNG 或 JPEG 截图")
                width, height = image.size
                prepared = image.convert("RGB")
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
            raise ScreenshotError("截图无法解码") from exc
        deadline = monotonic() + self.timeout
        words = self._recognize(prepared, "chi_sim+eng", deadline)
        # The Latin model can read 年 and 月 as letters when next to compact digits.
        headings = self._recognize(prepared.crop((0, 0, max(1, int(width * 0.31)), height)), "chi_sim", deadline)
        rows, hints = parse_trade_rows(words, width, height, month_words=headings)
        if any(not row["fields"]["status"] for row in rows):
            status_words = self._recognize(prepared.crop((int(width * 0.72), 0, width, height)), "chi_sim", deadline)
            rows, hints = parse_trade_rows(words, width, height, month_words=headings, status_words=status_words)
        if len(rows) > 120:
            raise ScreenshotError("截图记录过多，请按月份分段上传")
        with io.BytesIO() as preview:
            prepared.save(preview, format="JPEG", quality=88)
            return Screenshot(image_digest(raw), preview.getvalue(), "image/jpeg", rows, hints)

    def _recognize(self, image: Image.Image, languages: str, deadline: float) -> list[Word]:
        with io.BytesIO() as buffer:
            image.save(buffer, format="PNG")
            pixels = buffer.getvalue()
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ScreenshotError("截图识别超时，请裁剪后重试")
        try:
            result = subprocess.run(
                [self.executable, "stdin", "stdout", "-l", languages, "--psm", "11", "tsv"],
                input=pixels, capture_output=True, timeout=remaining, check=True,
                env={**os.environ, "OMP_THREAD_LIMIT": "1"},
            )
        except subprocess.TimeoutExpired as exc:
            raise ScreenshotError("截图识别超时，请裁剪后重试") from exc
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ScreenshotError("本地中文 OCR 不可用，请检查 Tesseract 及语言数据") from exc
        return _words(result.stdout.decode("utf-8", errors="replace"))


def _words(tsv: str) -> list[Word]:
    words: list[Word] = []
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t"):
        if row.get("level") != "5" or not (value := row.get("text", "").strip()):
            continue
        text = unicodedata.normalize("NFKC", value).translate(str.maketrans("–—−", "---"))
        words.append(Word(int(row["left"]), int(row["top"]), int(row["width"]), int(row["height"]), text))
    return words


def _join(words: list[Word]) -> str:
    return "".join(word.text.replace(" ", "") for word in words)


def _number(words: list[Word]) -> str | None:
    match = NUMBER.fullmatch(_join(words))
    return match[1].replace(",", "") if match else None


def _lines(words: list[Word], line_height: float) -> list[list[Word]]:
    lines: list[list[Word]] = []
    for word in sorted(words, key=lambda item: item.middle):
        if not lines or word.middle - median(item.middle for item in lines[-1]) > line_height * 0.52:
            lines.append([])
        lines[-1].append(word)
    return [sorted(line, key=lambda item: item.left) for line in lines]


def _fields(top: list[Word], bottom: list[Word], width: int, month: tuple[int, int] | None, status_hint: str) -> dict:
    top_text, bottom_text = _join(top), _join(bottom)
    left = _join([word for word in top + bottom if word.left < width * 0.23])
    def security_column(words: list[Word]) -> str:
        return _join([word for word in words if width * 0.20 <= word.left < width * 0.54])

    code = SECURITY.search(security_column(bottom)) or SECURITY.search(security_column(top))
    day = DAY.search(left)
    clock = re.search(r"\d{2}:\d{2}(?::\d{2})?", left)
    side = "buy" if "买入" in left else "sell" if "卖出" in left else ""
    status = next((result for label, result in STATUSES if label in top_text + bottom_text or label in status_hint), "")
    shares = SHARES.search(top_text) or SHARES.search(bottom_text)
    ordered = int(shares[2].replace(",", "")) if shares and shares[2] else None
    quantity = int(shares[1].replace(",", "")) if shares else None
    filled = quantity if status == "filled" or ordered is not None else None
    if status == "pending" or status == "canceled" and "全部撤单" in top_text + bottom_text:
        filled, ordered = 0, ordered if ordered is not None else quantity
    elif status == "canceled" and ordered is None:
        ordered = quantity
    values = {
        "date": f"{month[0]:04d}-{month[1]:02d}-{int(day[2]):02d}"
        if month and day and int(day[1]) == month[1] else "",
        "security": code[0].upper() if code else "",
        "name": _join([word for word in top if width * 0.20 <= word.left < width * 0.54]),
        "side": side, "status": status, "filled_quantity": filled, "ordered_quantity": ordered,
        "price": _number([word for word in bottom if width * 0.54 <= word.left < width * 0.76]),
        "amount": _number([word for word in top if word.left >= width * 0.76]),
        "time": clock[0] if clock else None,
        "cumulative": (status == "partial" or status == "canceled") and filled != 0,
    }
    if status == "filled" and ordered is not None:
        values["filled_quantity"] = ordered if quantity == ordered else None
    if filled == 0:
        values.update(price=None, amount=None)
    return values


def parse_trade_rows(
    words: list[Word], width: int, height: int, *,
    month_words: list[Word] | None = None, status_words: list[Word] | None = None,
) -> tuple[list[dict], list[str]]:
    if not words:
        return [], []
    typical_height = median(word.height for word in words)
    lines = _lines(words, typical_height)
    rows: list[dict] = []
    hints: list[str] = []
    month: tuple[int, int] | None = None
    headings = []
    for line in _lines(month_words or [], typical_height):
        if heading := MONTH.search(_join(line)):
            headings.append((line[0].middle, (int(heading[1]), int(heading[2]))))
    status_lines = [(line[0].middle, _join(line)) for line in _lines(status_words or [], typical_height)]
    used: set[int] = set()
    for index, line in enumerate(lines):
        while headings and headings[0][0] <= line[0].middle + typical_height / 2:
            _, month = headings.pop(0)
            if not MONTH.search(_join(line)):
                count = re.search(r"\d+笔", _join([word for word in line if word.left > width * 0.65]))
                hints.append(f"{month[0]}年{month[1]:02d}月{count[0] if count else ''}")
        line_text = _join(line)
        if heading := MONTH.search(line_text):
            month = (int(heading[1]), int(heading[2]))
            hints.append(line_text[:100])
            continue
        if "今日盈亏" in line_text:
            hints.append("识别到今日盈亏摘要，请核对其交易日和估值时点")
            continue
        left_text = _join([word for word in line if word.left < width * 0.23])
        code_text = _join([word for word in line if width * 0.20 <= word.left < width * 0.54])
        if not (DAY.search(left_text) or SECURITY.search(code_text)):
            continue
        top = lines[index - 1] if index else []
        if not top or index - 1 in used or MONTH.search(_join(top)) or line[0].middle - top[0].middle > typical_height * 3.0:
            top = []
        neighborhood = _join(top) + line_text
        if not (SECURITY.search(code_text) or any(label in neighborhood for label, _ in STATUSES)):
            continue
        status_hint = "".join(value for middle, value in status_lines if abs(middle - line[0].middle) < typical_height * 0.75)
        fields = _fields(top, line, width, month, status_hint)
        used.update((index - 1, index))
        region = top + line
        rows.append({
            "fields": fields,
            "raw": "\n".join(text for text in (_join(top), line_text) if text)[:400],
            "region": [min(word.top for word in region) / height, max(word.top + word.height for word in region) / height],
        })
    return rows, hints[:48]
