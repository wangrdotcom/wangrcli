"""User context pinning: persist and serialize pinned entities."""

import json
import time
from pathlib import Path
from typing import Any

from wangr.settings import CONFIG_DIR

CONTEXT_FILE: Path = CONFIG_DIR / "context.json"


# ------------------------------------------------------------------
# Data helpers
# ------------------------------------------------------------------


def make_pinned_entity(
    entity_type: str,
    entity_id: str,
    label: str,
    data: dict[str, Any],
    source: str,
    note: str = "",
) -> dict[str, Any]:
    """Create a pinned entity dict."""
    return {
        "type": entity_type,
        "id": entity_id,
        "label": label,
        "data": data,
        "note": note,
        "pinnedAt": int(time.time() * 1000),
        "source": source,
    }


# ------------------------------------------------------------------
# Persistence
# ------------------------------------------------------------------


def load_pinned() -> list[dict[str, Any]]:
    """Load all pinned entities from disk."""
    if not CONTEXT_FILE.exists():
        return []
    try:
        data = json.loads(CONTEXT_FILE.read_text())
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_pinned(pinned: list[dict[str, Any]]) -> None:
    """Save pinned entities to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONTEXT_FILE.write_text(json.dumps(pinned, indent=2))


def pin_entity(entity: dict[str, Any]) -> list[dict[str, Any]]:
    """Add an entity to the pin list (deduplicates by type+id). Returns updated list."""
    pinned = load_pinned()
    pinned = [
        p
        for p in pinned
        if not (p["type"] == entity["type"] and p["id"] == entity["id"])
    ]
    pinned.append(entity)
    save_pinned(pinned)
    return pinned


def unpin_entity(entity_type: str, entity_id: str) -> list[dict[str, Any]]:
    """Remove a pinned entity. Returns updated list."""
    pinned = load_pinned()
    pinned = [
        p for p in pinned if not (p["type"] == entity_type and p["id"] == entity_id)
    ]
    save_pinned(pinned)
    return pinned


# ------------------------------------------------------------------
# Serialization for AI
# ------------------------------------------------------------------


def serialize_context_for_ai(pinned: list[dict[str, Any]]) -> str:
    """Format pinned entities as a <User Context> block to prepend to user messages."""
    if not pinned:
        return ""
    lines = [
        "<User Context>",
        "The user has pinned the following items for reference:",
    ]
    for p in pinned:
        lines.append(_format_pin_line(p))
    lines.append("</User Context>")
    return "\n".join(lines)


def prepend_context_to_message(message: str) -> str:
    """If there are pinned entities, wrap the message with context."""
    pinned = load_pinned()
    context = serialize_context_for_ai(pinned)
    if not context:
        return message
    return f"{context}\n\n{message}"


# ------------------------------------------------------------------
# Formatting helpers
# ------------------------------------------------------------------


def _format_pin_line(p: dict[str, Any]) -> str:
    t = p["type"]
    data = p.get("data", {})
    note_suffix = f' \u2014 User note: "{p["note"]}"' if p.get("note") else ""

    if t == "market":
        question = data.get("question", p["label"])
        slug = p["id"]
        yes_pct = data.get("outcome_prices", {}).get("Yes")
        price_part = f" [Yes: {_pct(yes_pct)}]" if yes_pct is not None else ""
        return f'- Polymarket Market: "{question}" (slug: {slug}){price_part}{note_suffix}'

    if t == "event":
        title = data.get("title", p["label"])
        slug = p["id"]
        return f'- Polymarket Event: "{title}" (slug: {slug}){note_suffix}'

    if t == "user":
        wallet = p["id"]
        username = data.get("username", "")
        tags = []
        if data.get("is_whale"):
            tags.append("Whale")
        if data.get("is_super_trader"):
            tags.append("Super Trader")
        portfolio = data.get("portfolio_value")
        tag_str = " ".join(f"[{tg}]" for tg in tags)
        pf_str = f" [Portfolio: ${portfolio:,.0f}]" if portfolio else ""
        name_str = f' (tag: "{username}")' if username else ""
        return f"- Polymarket Trader: {wallet[:6]}...{wallet[-4:]}{name_str} {tag_str}{pf_str}{note_suffix}"

    if t == "symbol":
        symbol = p["id"]
        price = data.get("price")
        price_str = f" [Price: ${price:,.0f}]" if price else ""
        return f"- Asset: {symbol}{price_str}{note_suffix}"

    if t == "token":
        symbol = p["id"]
        name = data.get("name", symbol)
        return f"- Token: {name} ({symbol}){note_suffix}"

    return f"- {t}: {p['label']}{note_suffix}"


def _pct(value: float | int) -> str:
    """Format a 0-1 probability as a percentage string."""
    return f"{value * 100:.0f}%" if value <= 1 else f"{value:.0f}%"
