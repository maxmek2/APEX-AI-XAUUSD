"""Fixed Range Volume Profile calculated from OHLCV/tick-volume candles.

For OTC XAUUSD feeds this is a tick-volume profile, not centralized exchange volume.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Iterable

@dataclass(frozen=True)
class ProfileLevel:
    price: float
    volume: float

@dataclass(frozen=True)
class FixedRangeVolumeProfile:
    start_index: int
    end_index: int
    rows: int
    value_area_percent: float
    poc: float
    vah: float
    val: float
    total_volume: float
    hvn: list[dict]
    lvn: list[dict]
    levels: list[dict]


def calculate_frvp(candles: Iterable, start_index: int = 0, end_index: int | None = None,
                    rows: int = 48, value_area_percent: float = 70.0,
                    hvn_threshold: float = 1.5, lvn_threshold: float = 0.5) -> dict:
    data = list(candles)
    if not data:
        raise ValueError("candles cannot be empty")
    if end_index is None:
        end_index = len(data) - 1
    if start_index < 0 or end_index >= len(data) or start_index > end_index:
        raise ValueError("Invalid fixed range indices")
    if rows < 8 or rows > 300:
        raise ValueError("rows must be between 8 and 300")
    if not 50 <= value_area_percent <= 99:
        raise ValueError("value_area_percent must be between 50 and 99")
    selected = data[start_index:end_index + 1]
    low = min(float(c.low) for c in selected)
    high = max(float(c.high) for c in selected)
    if high <= low:
        raise ValueError("Fixed range must contain a non-zero price range")
    step = (high - low) / rows
    volumes = [0.0] * rows
    # OHLCV bars do not reveal traded volume at each price. Allocate each bar's
    # tick volume evenly across the price bins touched by its high-low range.
    for c in selected:
        c_low, c_high, vol = float(c.low), float(c.high), max(0.0, float(c.volume))
        first = max(0, min(rows - 1, int((c_low - low) / step)))
        last = max(0, min(rows - 1, int((c_high - low) / step)))
        count = last - first + 1
        share = vol / count if count else 0.0
        for i in range(first, last + 1):
            volumes[i] += share
    total = sum(volumes)
    if total <= 0:
        raise ValueError("Total volume must be positive")
    centers = [low + (i + 0.5) * step for i in range(rows)]
    poc_i = max(range(rows), key=lambda i: volumes[i])
    target = total * value_area_percent / 100.0
    left = right = poc_i
    accumulated = volumes[poc_i]
    while accumulated < target and (left > 0 or right < rows - 1):
        left_vol = volumes[left - 1] if left > 0 else -1
        right_vol = volumes[right + 1] if right < rows - 1 else -1
        if right_vol > left_vol:
            right += 1; accumulated += volumes[right]
        else:
            left -= 1; accumulated += volumes[left]
    mean = total / rows
    levels = [{"price": round(centers[i], 6), "volume": round(volumes[i], 6)} for i in range(rows)]
    hvn = [x for x in levels if x["volume"] >= mean * hvn_threshold]
    lvn = [x for x in levels if x["volume"] <= mean * lvn_threshold]
    return asdict(FixedRangeVolumeProfile(
        start_index=start_index, end_index=end_index, rows=rows,
        value_area_percent=value_area_percent, poc=round(centers[poc_i], 6),
        vah=round(centers[right], 6), val=round(centers[left], 6),
        total_volume=round(total, 6), hvn=hvn, lvn=lvn, levels=levels))
