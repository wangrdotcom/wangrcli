"""Background entity metadata enrichment."""

from typing import Any, Callable

from wangr.api import get_json
from wangr.config import POLYMARKET_META_API_URL, POLYMARKET_TRADER_API_URL


def fetch_market_metadata(slug: str) -> dict[str, Any] | None:
    """Fetch market metadata: outcome_prices, volume_24hr, liquidity."""
    data, err = get_json(f"{POLYMARKET_META_API_URL}/markets/{slug}")
    return data if not err else None


def fetch_event_metadata(slug: str) -> dict[str, Any] | None:
    """Fetch event metadata: volume, market_count, category."""
    data, err = get_json(f"{POLYMARKET_META_API_URL}/events/{slug}")
    return data if not err else None


def fetch_user_metadata(wallet: str) -> dict[str, Any] | None:
    """Fetch user metadata: portfolio_value, total_pnl, is_whale."""
    data, err = get_json(f"{POLYMARKET_META_API_URL}/users/{wallet}")
    return data if not err else None


def fetch_trader_details(wallet: str) -> dict[str, Any] | None:
    """On-demand trader details from polymarket-api."""
    data, err = get_json(f"{POLYMARKET_TRADER_API_URL}/{wallet}")
    return data if not err else None


def enrich_entities_in_background(
    entities: dict[str, list[dict[str, Any]]],
    on_enriched: Callable[[str, str, dict[str, Any]], None],
) -> None:
    """Fetch metadata for each Polymarket entity and call *on_enriched*.

    Parameters
    ----------
    on_enriched:
        ``(entity_type, key, metadata)`` callback invoked for each enriched entity.
        Symbols and tokens arrive fully populated and are skipped.
    """
    for market in entities.get("markets", []):
        slug = market.get("slug")
        if slug:
            meta = fetch_market_metadata(slug)
            if meta:
                on_enriched("markets", slug, meta)

    for event in entities.get("events", []):
        slug = event.get("slug")
        if slug:
            meta = fetch_event_metadata(slug)
            if meta:
                on_enriched("events", slug, meta)

    for user in entities.get("users", []):
        wallet = user.get("wallet")
        if wallet:
            meta = fetch_user_metadata(wallet)
            if meta:
                on_enriched("users", wallet, meta)
