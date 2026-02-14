"""Shared context pane handling for chat-style screens."""

from typing import Any

from wangr.context_store import (
    clear_pinned,
    load_pinned,
    make_pinned_entity,
    pin_entity,
    unpin_entity,
)


class ContextCommandsMixin:
    """Provide keyboard-driven context management in a side pane."""

    _ENTITY_TYPES = ("markets", "events", "users", "symbols", "tokens")

    def _init_context_commands_state(self) -> None:
        self._discovered_context: dict[str, list[dict[str, Any]]] = {
            entity_type: [] for entity_type in self._ENTITY_TYPES
        }
        self._selected_entity_type = "markets"
        self._selected_discovered_index: dict[str, int] = {
            entity_type: 0 for entity_type in self._ENTITY_TYPES
        }
        self._selected_pinned_index = 0
        self._context_scope = "discovered"
        self._context_focused = False
        self._context_status = ""
        self._last_context_sent_count = 0
        self._active_trader_source_hint = str(
            getattr(self, "_default_trader_source_hint", "")
        )

    def _clear_discovered_context(self) -> None:
        for entity_type in self._ENTITY_TYPES:
            self._discovered_context[entity_type] = []
            self._selected_discovered_index[entity_type] = 0

    def _update_discovered_entities(
        self, entity_type: str, entities: list[dict[str, Any]]
    ) -> None:
        if entity_type not in self._discovered_context:
            return
        self._discovered_context[entity_type] = entities
        self._clamp_discovered_selection(entity_type)
        self._render_context_pane()

    def action_toggle_context_focus(self) -> None:
        self._set_context_focus(not self._context_focused)

    def _set_context_focus(self, focused: bool) -> None:
        from textual.widgets import Input

        self._context_focused = focused
        self._context_status = (
            "Context focus ON (j/k move, g group, s scope, a ask, p pin, u unpin, x clear, Esc/F2 exit)."
            if focused
            else ""
        )

        try:
            pane = self.query_one(self._context_pane_id)
            if focused:
                pane.add_class("context-focused")
            else:
                pane.remove_class("context-focused")
        except Exception:
            pass

        try:
            input_box = self.query_one(self._chat_input_id, Input)
            if focused:
                input_box.disabled = True
            else:
                if not getattr(self, "_streaming", False):
                    input_box.disabled = False
                    input_box.focus()
        except Exception:
            pass

        self._render_context_pane()

    def _handle_context_focus_key(self, key: str) -> bool:
        normalized = key.lower()
        if normalized == "f2":
            self.action_toggle_context_focus()
            return True

        if not self._context_focused:
            return False

        if normalized in {"escape"}:
            self._set_context_focus(False)
            return True
        if normalized in {"j", "down"}:
            self.action_context_next()
            return True
        if normalized in {"k", "up"}:
            self.action_context_prev()
            return True
        if normalized == "g":
            self.action_context_cycle_group()
            return True
        if normalized == "s":
            self.action_context_toggle_scope()
            return True
        if normalized == "a":
            self.action_context_ask_selected()
            return True
        if normalized == "p":
            self.action_context_pin_selected()
            return True
        if normalized == "u":
            self.action_context_unpin_selected()
            return True
        if normalized == "x":
            self.action_context_clear_all()
            return True
        return False

    def _pinned_count(self) -> int:
        return len(load_pinned())

    def _append_context_send_indicator(self) -> None:
        count = self._pinned_count()
        self._last_context_sent_count = count
        if count:
            suffix = "item" if count == 1 else "items"
            self._context_status = f"Sending with {count} pinned {suffix}."
        else:
            self._context_status = "Sending without pinned context."
        self._render_context_pane()

    def _set_active_trader_source_hint(self, message: str) -> None:
        text = message.lower()
        pm_tokens = ("polymarket", "prediction market", " pm", "pm ", "gamma")
        hl_tokens = ("hyperliquid", " hl", "hl ", "perp", "perps")
        if any(token in text for token in pm_tokens):
            self._active_trader_source_hint = "pm"
            return
        if any(token in text for token in hl_tokens):
            self._active_trader_source_hint = "hl"
            return
        self._active_trader_source_hint = str(
            getattr(self, "_default_trader_source_hint", "")
        )

    def _render_context_pane(self) -> None:
        from textual.widgets import RichLog

        try:
            log = self.query_one(self._context_log_id, RichLog)
        except Exception:
            return

        pinned = self._pinned_for_display()
        self._clamp_pinned_selection(pinned)

        items, title = self._active_context_items(pinned)
        scope_pills = self._scope_pills()
        group_pills = self._group_pills()
        focus_badge = (
            "[black on #2f81f7] CONTEXT FOCUS ON [/]"
            if self._context_focused
            else "[black on #3a3f47] F2 Focus Context [/]"
        )

        lines: list[str] = [
            f"[bold]AI Context[/bold]  {focus_badge}",
            "",
            f"[dim]Scope:[/dim] {scope_pills}",
            f"[dim]Groups:[/dim] {group_pills}",
            f"[dim]↗[/dim] [bold]{title}[/bold]",
        ]
        if not items:
            lines.append("  [dim]No items yet.[/dim]")
        else:
            for i, item in enumerate(items, start=1):
                selected = self._is_selected(item["scope"], item["index"])
                marker = "[bold cyan]>[/bold cyan]" if selected else " "
                change = item.get("change")
                change_badge = self._format_change_badge(change)
                badges = " ".join(item.get("badges", []))
                lines.append(
                    f"{marker} [bold]{item['title']}[/bold] [dim]{item.get('value', '')}[/dim] {change_badge} {badges}".rstrip()
                )
                subtitle = item.get("subtitle")
                if subtitle:
                    lines.append(f"  [dim]{subtitle}[/dim]")
                if item["scope"] == "pinned":
                    action = "[#6bd968]Unpin[/#6bd968] [dim]Ctrl+U[/dim]"
                else:
                    action = "[#6bd968]Pin[/#6bd968] [dim]Ctrl+P[/dim]"
                lines.append(
                    f"  [#58a6ff]Ask about this[/#58a6ff] [dim]Ctrl+A[/dim]  [dim]|[/dim]  {action}"
                )
                if i < len(items):
                    lines.append("  [dim]────────────────────────[/dim]")

        lines.append("")
        lines.append("[dim]F2 toggles context focus. In focus mode: j/k, g, s, a, p, u, x.[/dim]")
        if self._context_status:
            lines.append(f"[dim]{self._context_status}[/dim]")

        log.clear()
        for line in lines:
            log.write(line)

    def action_context_toggle_scope(self) -> None:
        self._context_scope = "pinned" if self._context_scope == "discovered" else "discovered"
        self._context_status = f"Scope: {self._context_scope}"
        self._render_context_pane()

    def action_context_cycle_group(self) -> None:
        current = self._ENTITY_TYPES.index(self._selected_entity_type)
        self._selected_entity_type = self._ENTITY_TYPES[(current + 1) % len(self._ENTITY_TYPES)]
        self._context_scope = "discovered"
        self._context_status = f"Group: {self._selected_entity_type}"
        self._clamp_discovered_selection(self._selected_entity_type)
        self._render_context_pane()

    def action_context_next(self) -> None:
        if self._context_scope == "pinned":
            pinned = self._pinned_for_display()
            if pinned:
                self._selected_pinned_index = (self._selected_pinned_index + 1) % len(pinned)
            self._render_context_pane()
            return

        items = self._discovered_context.get(self._selected_entity_type, [])
        if items:
            idx = self._selected_discovered_index[self._selected_entity_type]
            self._selected_discovered_index[self._selected_entity_type] = (idx + 1) % len(items)
        self._render_context_pane()

    def action_context_prev(self) -> None:
        if self._context_scope == "pinned":
            pinned = self._pinned_for_display()
            if pinned:
                self._selected_pinned_index = (self._selected_pinned_index - 1) % len(pinned)
            self._render_context_pane()
            return

        items = self._discovered_context.get(self._selected_entity_type, [])
        if items:
            idx = self._selected_discovered_index[self._selected_entity_type]
            self._selected_discovered_index[self._selected_entity_type] = (idx - 1) % len(items)
        self._render_context_pane()

    def action_context_pin_selected(self) -> None:
        items = self._discovered_context.get(self._selected_entity_type, [])
        if not items:
            self._context_status = "No discovered item selected."
            self._render_context_pane()
            return

        idx = self._selected_discovered_index[self._selected_entity_type]
        entity = items[idx]
        pinned = self._to_pinned_entity(self._selected_entity_type, entity)
        if not pinned:
            self._context_status = "Selected item is missing required fields."
            self._render_context_pane()
            return

        pin_entity(pinned)
        self._context_status = f"Pinned {pinned['label']}"
        self._render_context_pane()

    def action_context_unpin_selected(self) -> None:
        pinned = self._pinned_for_display()
        if not pinned:
            self._context_status = "No pinned item selected."
            self._render_context_pane()
            return

        target = pinned[self._selected_pinned_index]
        unpin_entity(target["type"], target["id"])
        self._context_status = f"Unpinned {target['label']}"
        self._render_context_pane()

    def action_context_ask_selected(self) -> None:
        from textual.widgets import Input

        label = self._selected_item_label()
        if not label:
            self._context_status = "No item selected."
            self._render_context_pane()
            return

        try:
            input_box = self.query_one(self._chat_input_id, Input)
        except Exception:
            return
        input_box.value = f"Tell me about {label}"
        input_box.focus()
        self._context_status = f'Prepared prompt for "{label}"'
        self._render_context_pane()

    def action_context_clear_all(self) -> None:
        clear_pinned()
        self._selected_pinned_index = 0
        self._context_status = "Cleared pinned context."
        self._render_context_pane()

    def _pinned_for_display(self) -> list[dict[str, Any]]:
        pinned = load_pinned()
        return sorted(
            pinned, key=lambda item: int(item.get("pinnedAt", 0)), reverse=True
        )

    def _is_selected(self, scope: str, index: int) -> bool:
        if scope == "pinned":
            return self._context_scope == "pinned" and self._selected_pinned_index == index
        selected = self._selected_discovered_index[self._selected_entity_type]
        return self._context_scope == "discovered" and selected == index

    def _display_entity_type(self, entity_type: str) -> str:
        names = {
            "markets": "Market",
            "events": "Event",
            "users": "Trader",
            "symbols": "Asset",
            "tokens": "Token",
            "market": "Market",
            "event": "Event",
            "user": "Trader",
            "symbol": "Asset",
            "token": "Token",
        }
        return names.get(entity_type, entity_type.title())

    def _entity_label(self, entity_type: str, entity: dict[str, Any]) -> str:
        if entity_type == "markets":
            return entity.get("question") or entity.get("slug", "Unknown")
        if entity_type == "events":
            return entity.get("title") or entity.get("slug", "Unknown")
        if entity_type == "users":
            return entity.get("username") or entity.get("wallet", "Unknown")
        if entity_type == "symbols":
            return entity.get("symbol", "Unknown")
        if entity_type == "tokens":
            name = entity.get("name")
            symbol = entity.get("symbol", "Unknown")
            return f"{name} ({symbol})" if name else symbol
        return str(entity)

    def _clamp_discovered_selection(self, entity_type: str) -> None:
        items = self._discovered_context.get(entity_type, [])
        if not items:
            self._selected_discovered_index[entity_type] = 0
            return
        idx = self._selected_discovered_index[entity_type]
        self._selected_discovered_index[entity_type] = max(0, min(idx, len(items) - 1))

    def _clamp_pinned_selection(self, pinned: list[dict[str, Any]]) -> None:
        if not pinned:
            self._selected_pinned_index = 0
            return
        self._selected_pinned_index = max(
            0, min(self._selected_pinned_index, len(pinned) - 1)
        )

    def _active_context_items(
        self, pinned: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], str]:
        if self._context_scope == "pinned":
            items = [
                self._context_item_from_pinned(idx, item)
                for idx, item in enumerate(pinned)
            ]
            return items, f"Pinned ({len(items)})"

        entity_type = self._selected_entity_type
        discovered = self._discovered_context.get(entity_type, [])
        items = [
            self._context_item_from_discovered(entity_type, idx, entity)
            for idx, entity in enumerate(discovered)
        ]
        title = f"{self._display_entity_type(entity_type)}s ({len(items)})"
        return items, title

    def _scope_pills(self) -> str:
        disc = (
            "[black on #2f81f7] DISCOVERED [/]"
            if self._context_scope == "discovered"
            else "[black on #3a3f47] DISCOVERED [/]"
        )
        pin = (
            "[black on #2f81f7] PINNED [/]"
            if self._context_scope == "pinned"
            else "[black on #3a3f47] PINNED [/]"
        )
        return f"{disc} {pin}"

    def _group_pills(self) -> str:
        chips: list[str] = []
        for entity_type in self._ENTITY_TYPES:
            count = len(self._discovered_context.get(entity_type, []))
            label = f"{self._display_entity_type(entity_type)} {count}"
            active = self._context_scope == "discovered" and self._selected_entity_type == entity_type
            if active:
                chips.append(f"[black on #2f81f7] {label} [/]")
            else:
                chips.append(f"[black on #3a3f47] {label} [/]")
        return " ".join(chips)

    def _context_item_from_pinned(self, index: int, item: dict[str, Any]) -> dict[str, Any]:
        data = item.get("data", {})
        entity_type = item.get("type", "")
        title = item.get("label", item.get("id", "Unknown"))
        value = self._price_text(data.get("price"))
        change = data.get("change_24h_pct")
        subtitle = self._build_subtitle(entity_type, data)
        badges = self._build_badges(entity_type, data, item.get("source"))
        return {
            "scope": "pinned",
            "index": index,
            "title": title,
            "subtitle": subtitle,
            "value": value,
            "change": change,
            "badges": badges,
        }

    def _context_item_from_discovered(
        self, entity_type: str, index: int, entity: dict[str, Any]
    ) -> dict[str, Any]:
        title = self._entity_label(entity_type, entity)
        value = self._price_text(entity.get("price"))
        change = entity.get("change_24h_pct")
        subtitle = self._build_subtitle(entity_type, entity)
        badges = self._build_badges(entity_type, entity, entity.get("source"))
        return {
            "scope": "discovered",
            "index": index,
            "title": title,
            "subtitle": subtitle,
            "value": value,
            "change": change,
            "badges": badges,
        }

    def _selected_item_label(self) -> str | None:
        if self._context_scope == "pinned":
            pinned = self._pinned_for_display()
            if not pinned:
                return None
            item = pinned[self._selected_pinned_index]
            return item.get("label", item.get("id"))

        discovered = self._discovered_context.get(self._selected_entity_type, [])
        if not discovered:
            return None
        idx = self._selected_discovered_index[self._selected_entity_type]
        return self._entity_label(self._selected_entity_type, discovered[idx])

    def _price_text(self, price: Any) -> str:
        if price is None:
            return ""
        try:
            numeric = float(price)
        except (TypeError, ValueError):
            return ""
        if numeric >= 1000:
            return f"${numeric:,.0f}"
        if numeric >= 1:
            return f"${numeric:,.2f}"
        return f"${numeric:,.4f}"

    def _format_change_badge(self, change: Any) -> str:
        try:
            pct = float(change)
        except (TypeError, ValueError):
            return ""
        color = "#ff6b6b" if pct < 0 else "#6bd968"
        return f"[black on {color}] {pct:+.2f}% [/]"

    def _build_subtitle(self, entity_type: str, data: dict[str, Any]) -> str:
        if entity_type in {"users", "user"}:
            parts: list[str] = []
            portfolio = self._money_text(data.get("portfolio_value"))
            pnl = self._money_text(data.get("pnl") if data.get("pnl") is not None else data.get("total_pnl"))
            if portfolio:
                parts.append(f"Portfolio {portfolio}")
            if pnl:
                parts.append(f"PnL {pnl}")
            return " | ".join(parts) if parts else "Trader"

        if entity_type in {"markets", "market"}:
            parts = []
            yes = self._yes_odds_text(data)
            if yes:
                parts.append(f"Yes {yes}")
            volume = self._money_text(data.get("volume_24hr") or data.get("volume"))
            liquidity = self._money_text(data.get("liquidity"))
            if volume:
                parts.append(f"Vol {volume}")
            if liquidity:
                parts.append(f"Liq {liquidity}")
            return " | ".join(parts) if parts else "Market"

        if entity_type in {"events", "event"}:
            parts = []
            category = data.get("category")
            market_count = data.get("market_count")
            volume = self._money_text(data.get("volume"))
            if category:
                parts.append(str(category))
            if market_count:
                parts.append(f"{market_count} mkts")
            if volume:
                parts.append(f"Vol {volume}")
            return " | ".join(parts) if parts else "Event"

        if entity_type in {"symbols", "symbol", "tokens", "token"}:
            name = data.get("name")
            return str(name) if name else self._display_entity_type(entity_type)

        return self._display_entity_type(entity_type)

    def _build_badges(
        self, entity_type: str, data: dict[str, Any], source: Any
    ) -> list[str]:
        badges: list[str] = []
        if entity_type in {"users", "user"}:
            venue = self._venue_badge(source or self._default_trader_source(data))
            if venue:
                badges.append(venue)
            if data.get("is_whale"):
                badges.append("[black on #2f81f7] WHALE [/]")
            if data.get("is_super_trader"):
                badges.append("[black on #d29922] SUPER [/]")
        return badges

    def _venue_badge(self, source: Any) -> str:
        text = str(source or "").lower().strip()
        if not text:
            return ""
        if any(token in text for token in ("poly", "pm")):
            return "[black on #f97316] PM [/]"
        if any(token in text for token in ("hyper", "hl")):
            return "[black on #06b6d4] HL [/]"
        return f"[black on #3a3f47] {text.upper()[:8]} [/]"

    def _default_trader_source(self, data: dict[str, Any]) -> str:
        explicit = data.get("source")
        if explicit:
            return str(explicit)
        if self._active_trader_source_hint:
            return str(self._active_trader_source_hint)
        return str(getattr(self, "_default_trader_source_hint", ""))

    def _yes_odds_text(self, data: dict[str, Any]) -> str:
        outcome = data.get("outcome_prices")
        if isinstance(outcome, dict):
            yes = outcome.get("Yes")
            if yes is not None:
                try:
                    val = float(yes)
                    pct = val * 100 if val <= 1 else val
                    return f"{pct:.0f}%"
                except (TypeError, ValueError):
                    return ""
        return ""

    def _money_text(self, value: Any) -> str:
        if value is None:
            return ""
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return ""
        sign = "-" if amount < 0 else ""
        amount = abs(amount)
        if amount >= 1_000_000_000:
            return f"{sign}${amount / 1_000_000_000:.2f}B"
        if amount >= 1_000_000:
            return f"{sign}${amount / 1_000_000:.2f}M"
        if amount >= 1_000:
            return f"{sign}${amount / 1_000:.1f}K"
        return f"{sign}${amount:,.0f}"

    def _to_pinned_entity(
        self, entity_type: str, entity: dict[str, Any]
    ) -> dict[str, Any] | None:
        if entity_type == "markets":
            slug = entity.get("slug")
            if not slug:
                return None
            label = entity.get("question") or slug
            return make_pinned_entity("market", slug, label, entity, "polymarket")

        if entity_type == "events":
            slug = entity.get("slug")
            if not slug:
                return None
            label = entity.get("title") or slug
            return make_pinned_entity("event", slug, label, entity, "polymarket")

        if entity_type == "users":
            wallet = entity.get("wallet")
            if not wallet:
                return None
            label = entity.get("username") or wallet[:10]
            source = entity.get("source") or self._default_trader_source(entity)
            return make_pinned_entity("user", wallet, label, entity, source)

        if entity_type == "symbols":
            symbol = entity.get("symbol")
            if not symbol:
                return None
            label = symbol
            return make_pinned_entity("symbol", symbol, label, entity, "general")

        if entity_type == "tokens":
            symbol = entity.get("symbol")
            if not symbol:
                return None
            label = entity.get("name") or symbol
            return make_pinned_entity("token", symbol, label, entity, "general")

        return None
