"""Helpers for active tab/label highlighting."""

from textual.widgets import Static


def update_active_tab(
    screen,
    mapping: dict[str, str],
    active_key: str,
    *,
    active_class: str = "coin-toggle-active",
) -> None:
    """Apply active class to the selected label and clear it from others."""
    for key, selector in mapping.items():
        label = screen.query_one(selector, Static)
        if key == active_key:
            label.add_class(active_class)
        else:
            label.remove_class(active_class)
