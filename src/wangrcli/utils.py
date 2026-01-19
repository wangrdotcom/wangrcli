"""Utility functions for the TUI Dashboard."""

import logging
from typing import Any

from wangrcli.config import BAR_WIDTH, PRICE_FORMAT_THRESHOLD, THOUSAND

logger = logging.getLogger(__name__)


def format_bar(left: str, right: str, val_l: float, val_r: float, width: int = BAR_WIDTH) -> str:
    """
    Render a horizontal bar chart.

    Args:
        left: Label for left side
        right: Label for right side
        val_l: Value for left side
        val_r: Value for right side
        width: Total width of the bar in characters

    Returns:
        Formatted bar chart string
    """
    total = val_l + val_r
    pct = int((val_l / total * width)) if total > 0 else width // 2
    bar = f"{'█' * pct}{'░' * (width - pct)}"
    return f"{left:<20} {bar} {right:>20}"


def safe_division(numerator: float, denominator: float, default: float = 0.0) -> float:
    """
    Safely divide with default for zero denominator.

    Args:
        numerator: The dividend
        denominator: The divisor
        default: Value to return if denominator is zero

    Returns:
        Result of division or default value
    """
    if denominator == 0:
        return default
    return numerator / denominator


def format_price(price: float, threshold: float = PRICE_FORMAT_THRESHOLD) -> str:
    """
    Format price with 'k' suffix for large values.

    Args:
        price: The price to format
        threshold: Threshold above which to use 'k' suffix

    Returns:
        Formatted price string
    """
    if price >= threshold:
        return f"${price/THOUSAND:.1f}k"
    return f"${price:.2f}"


def safe_float(value: Any, default: float = 0.0) -> float:
    """
    Safely convert value to float.

    Args:
        value: Value to convert
        default: Default value if conversion fails

    Returns:
        Float value or default
    """
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        logger.warning(f"Failed to convert {value} to float, using default {default}")
        return default


def safe_get_nested(data: dict, *keys: str, default: Any = None) -> Any:
    """
    Safely get nested dictionary value.

    Args:
        data: Dictionary to search
        *keys: Keys to traverse
        default: Default value if key not found

    Returns:
        Value at nested key or default
    """
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
        if current is default:
            return default
    return current


def format_time(minutes: float) -> str:
    """
    Format time duration in human-readable format.

    Args:
        minutes: Time in minutes

    Returns:
        Formatted time string
    """
    if minutes < 60:
        return f"{minutes:.0f}m"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:.1f}h"
    days = hours / 24
    return f"{days:.1f}d"
