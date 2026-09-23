"""Deterministic in-memory TDX package fixtures for offline tests."""

from __future__ import annotations

import io
import struct
import zipfile
from datetime import date
from typing import Iterable


def make_tdx_package(
    session: date,
    *,
    markets: Iterable[str] = ("sh", "sz", "bj"),
    rows_per_market: int = 1,
    duplicate_code: bool = False,
    truncated: bool = False,
    invalid_numeric: bool = False,
) -> bytes:
    """Create the smallest valid package shape without any live URL or data."""

    output = io.BytesIO()
    ymd = session.strftime("%y%m%d")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for market in markets:
            cod = bytearray()
            md1 = bytearray()
            for index in range(rows_per_market):
                code = "600000" if duplicate_code else f"{index + 1:06d}"
                record = bytearray(150)
                record[0:6] = code.encode("ascii")
                struct.pack_into("<H", record, 32, index)
                encoded_name = f"样本{index}".encode("gbk")
                record[40 : 40 + len(encoded_name)] = encoded_name
                cod.extend(record)
                block = bytearray(512)
                value = float("nan") if invalid_numeric and index == 0 else 10.0 + index
                struct.pack_into("<d", block, 4, 9.0)
                struct.pack_into("<4d", block, 12, value, value + 1, value - 1, value)
                struct.pack_into("<Q", block, 56, 1000 + index)
                struct.pack_into("<d", block, 72, 100_000 - index)
                md1.extend(block)
            if truncated:
                cod = cod[:-1]
            archive.writestr(f"{market}{ymd}.cod", bytes(cod))
            archive.writestr(f"{market}{ymd}.md1", bytes(md1))
    return output.getvalue()
