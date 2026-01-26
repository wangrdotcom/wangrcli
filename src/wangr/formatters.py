"""Formatting helpers for numeric values."""

from typing import Any


def fmt_pct(value: Any, *, decimals: int = 2, empty: str = "") -> str:
    """Format a value as a percent string."""
    if value is None:
        return empty
    try:
        return f"{float(value):.{decimals}f}%"
    except (TypeError, ValueError):
        return str(value)


def fmt_usd(value: Any, *, decimals: int = 0, empty: str = "$0") -> str:
    """Format a value as USD with separators."""
    if value is None:
        return empty
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if decimals <= 0:
        return f"${num:,.0f}"
    return f"${num:,.{decimals}f}"


def pnl_color(value: Any, *, pos: str = "#2dd4bf", neg: str = "#f87171", neutral: str = "text") -> str:
    """Return a color token for positive/negative values."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return neutral
    return pos if num >= 0 else neg


def fmt_num(value: Any, *, decimals: int = 2, empty: str = "") -> str:
    """Format a number with separators for large values."""
    if value is None:
        return empty
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(num) >= 1000:
        return f"{num:,.0f}"
    return f"{num:.{decimals}f}"
