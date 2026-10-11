from __future__ import annotations

from statistics import median


def percentile(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def price_stats(prices: list[float]) -> tuple[float | None, float | None, float | None]:
    clean = sorted(p for p in prices if p is not None and p > 0)
    if not clean:
        return None, None, None
    return percentile(clean, 25), median(clean), percentile(clean, 75)
