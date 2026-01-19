"""Braille and block-based sparkline utilities for terminal visualization."""

from typing import Sequence

# Block characters for sparklines (8 levels)
BLOCKS = " ▁▂▃▄▅▆▇█"


def block_sparkline(values: Sequence[float], width: int | None = None) -> str:
    """
    Render a sparkline using block characters.

    Args:
        values: Sequence of numeric values to plot
        width: Target width (will resample if needed). None = use len(values)

    Returns:
        String of block characters representing the data

    Example:
        >>> block_sparkline([1, 3, 5, 7, 5, 3, 1])
        '▁▃▅▇▅▃▁'
    """
    if not values:
        return ""

    vals = list(values)

    # Resample if width specified and different from len(values)
    if width and width != len(vals):
        vals = _resample(vals, width)

    min_val = min(vals)
    max_val = max(vals)
    val_range = max_val - min_val

    if val_range == 0:
        # All values are the same, use middle block
        return BLOCKS[4] * len(vals)

    result = []
    for v in vals:
        # Normalize to 0-1, then map to block index (0-8)
        normalized = (v - min_val) / val_range
        idx = int(normalized * 8)
        idx = min(idx, 8)  # Clamp to valid range
        result.append(BLOCKS[idx])

    return "".join(result)


def ratio_bar(
    left_val: float,
    right_val: float,
    width: int = 20,
    left_char: str = "█",
    right_char: str = "░",
) -> str:
    """
    Render a horizontal bar showing ratio between two values.

    Args:
        left_val: Value for left portion
        right_val: Value for right portion
        width: Total bar width in characters
        left_char: Character for left portion
        right_char: Character for right portion

    Returns:
        Bar string like '████████░░░░'

    Example:
        >>> ratio_bar(70, 30, width=10)
        '███████░░░'
    """
    total = left_val + right_val
    if total == 0:
        left_count = width // 2
    else:
        left_count = int((left_val / total) * width)

    left_count = max(0, min(width, left_count))
    right_count = width - left_count

    return left_char * left_count + right_char * right_count


def mini_bar(value: float, max_val: float, width: int = 10, char: str = "█") -> str:
    """
    Render a single-value horizontal bar.

    Args:
        value: Current value
        max_val: Maximum possible value (for scaling)
        width: Total bar width
        char: Character to use for filled portion

    Returns:
        Bar string like '████░░░░░░'

    Example:
        >>> mini_bar(75, 100, width=10)
        '███████░░░'
    """
    if max_val == 0:
        filled = 0
    else:
        filled = int((value / max_val) * width)

    filled = max(0, min(width, filled))
    return char * filled + "░" * (width - filled)


def format_with_trend(current: float, previous: float | None) -> str:
    """
    Format a value with trend arrow indicator.

    Args:
        current: Current value
        previous: Previous value (None if no history)

    Returns:
        String with arrow like '↑' '↓' '→' or '' if no previous

    Example:
        >>> format_with_trend(100, 90)
        '↑'
        >>> format_with_trend(100, 110)
        '↓'
    """
    if previous is None:
        return ""

    diff = current - previous
    threshold = abs(previous) * 0.001  # 0.1% threshold for "no change"

    if diff > threshold:
        return "↑"
    elif diff < -threshold:
        return "↓"
    else:
        return "→"


def labeled_ratio_bar(
    left_label: str,
    right_label: str,
    left_val: float,
    right_val: float,
    width: int = 20,
    label_width: int = 20,
) -> str:
    """
    Render a labeled ratio bar with values on each side.

    Args:
        left_label: Label for left side (e.g., "Long")
        right_label: Label for right side (e.g., "Short")
        left_val: Value for left portion
        right_val: Value for right portion
        width: Bar width (not including labels)
        label_width: Fixed width for labels (for alignment)

    Returns:
        Formatted string like 'Long                 ███████░░░                 Short'
    """
    bar = ratio_bar(left_val, right_val, width)
    return f"{left_label:<{label_width}} {bar} {right_label:>{label_width}}"


def _resample(values: list[float], target_width: int) -> list[float]:
    """
    Resample values to target width using simple averaging.

    Args:
        values: Original values
        target_width: Desired number of output values

    Returns:
        Resampled list of target_width length
    """
    if target_width <= 0:
        return []

    n = len(values)
    if n == 0:
        return [0.0] * target_width

    if n == target_width:
        return values

    result = []
    for i in range(target_width):
        # Map target index to source range
        start = (i * n) / target_width
        end = ((i + 1) * n) / target_width

        # Average values in this range
        start_idx = int(start)
        end_idx = min(int(end) + 1, n)

        if start_idx >= end_idx:
            result.append(values[min(start_idx, n - 1)])
        else:
            chunk = values[start_idx:end_idx]
            result.append(sum(chunk) / len(chunk))

    return result
