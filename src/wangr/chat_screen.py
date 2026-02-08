"""Chat screen for Wangr agent with streaming responses."""

from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, RichLog

from wangr.config import CHAT_API_URL
from wangr.context_store import prepend_context_to_message
from wangr.entity_metadata import enrich_entities_in_background
from wangr.file_ops_mixin import FileOpsMixin
from wangr.stream_handler import iter_ndjson_events, should_suppress_status, stream_post


class ChatScreen(FileOpsMixin, Screen):
    """Streaming chat screen for general crypto queries."""

    BINDINGS = [
        ("b", "go_back", "Go Back"),
        ("ctrl+b", "go_back", "Go Back"),
        ("ctrl+l", "clear_chat", "Clear Chat"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._history: list[dict[str, Any]] = []
        self._entries: list[dict[str, Any]] = []
        self._streaming = False
        self._current_text = ""
        self._current_tool: str | None = None
        self._entities: dict[str, list[dict[str, Any]]] = {}
        self._processing_timer = None
        self._processing_frame = 0
        # File operations state (required by FileOpsMixin)
        self._pending_file_ops: dict[str, Any] | None = None
        self._pending_requires_approval = False
        self._auto_approve_chain = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        yield Container(
            RichLog(id="chat-log", wrap=True, highlight=True, markup=True),
            Input(placeholder="Ask Wangr\u2026", id="chat-input"),
            id="chat-container",
        )

    async def on_mount(self) -> None:
        self._restore_state()
        if not self._entries:
            self._entries.append(
                {
                    "role": "system",
                    "content": "[bold]\U0001f4ac Wangr Crypto Assistant[/bold]",
                }
            )
            self._entries.append(
                {
                    "role": "system",
                    "content": "Ask about whales, markets, or wallets. [dim](Ctrl+L to clear)[/dim]\n",
                }
            )
        self._render_entries()
        self.query_one("#chat-input", Input).focus()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_clear_chat(self) -> None:
        self._history = []
        self._entries = [
            {
                "role": "system",
                "content": "[bold]\U0001f4ac Wangr Crypto Assistant[/bold]",
            },
            {"role": "system", "content": "\u2713 History cleared.\n"},
        ]
        self._entities = {}
        self._pending_file_ops = None
        self._pending_requires_approval = False
        self._auto_approve_chain = False
        self._render_entries()
        self._persist_state()

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        message = event.value.strip()
        if not message:
            return
        if self._streaming:
            return
        # Handle Y/N for pending file ops
        if self._pending_file_ops and self._pending_requires_approval:
            normalized = message.lower()
            if normalized not in {"y", "n"}:
                return
            decision = normalized == "y"
            event.input.value = ""
            self._append_user_message(message)
            event.input.disabled = True
            self._start_processing()
            self.run_worker(
                lambda: self._resolve_pending_request(decision),
                thread=True,
                name="chat_pending",
            )
            return
        event.input.value = ""
        self._append_user_message(message)
        event.input.disabled = True
        self._start_streaming(message)

    def on_key(self, event: events.Key) -> None:
        """Handle Y/N key press for file operation approval."""
        if not self._pending_file_ops or not self._pending_requires_approval:
            return
        if self._streaming:
            return
        key = event.key.lower()
        if key not in {"y", "n"}:
            return
        event.stop()
        approved = key == "y"
        input_box = self.query_one("#chat-input", Input)
        input_box.value = ""
        input_box.disabled = True
        self._start_processing()
        self.run_worker(
            lambda: self._resolve_pending_request(approved),
            thread=True,
            name="chat_pending",
        )

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def _start_streaming(self, message: str) -> None:
        """Start streaming request in a worker thread."""
        self._streaming = True
        self._current_text = ""
        self._current_tool = None
        self._entities = {}
        self._start_processing()
        self.run_worker(
            lambda: self._stream_request(message),
            thread=True,
            name="chat_stream",
        )

    def _stream_request(self, message: str) -> tuple[str, list[dict[str, Any]]]:
        """Execute streaming request and process events."""
        try:
            enriched_message = prepend_context_to_message(message)
            response = stream_post(
                CHAT_API_URL,
                {"message": enriched_message, "history": self._history},
            )

            full_text, tool_calls = self._process_stream_response(response)

            # Store original message (without context prefix) in history
            self._history.append({"role": "user", "content": message})
            self._history.append({"role": "assistant", "content": full_text})

            return full_text, tool_calls

        except Exception as exc:
            self.app.call_from_thread(self._handle_error, str(exc))
            raise RuntimeError("stream request failed") from exc

    def _process_stream_response(
        self, response
    ) -> tuple[str, list[dict[str, Any]]]:
        """Process streaming response and return full text and tool calls."""
        full_text = ""
        tool_calls: list[dict[str, Any]] = []

        for event in iter_ndjson_events(response):
            # Check for pending_file_ops event
            if event.get("type") == "pending_file_ops":
                self.app.call_from_thread(self._handle_pending_file_ops, event)
                return full_text, tool_calls

            self._process_stream_event(event)

            if event.get("type") == "text_delta":
                full_text += event.get("content", "")
            elif event.get("type") == "text":
                full_text = event.get("content", "")
            elif event.get("type") == "done":
                tool_calls = event.get("tool_calls", [])

        return full_text, tool_calls

    def _process_stream_event(self, event: dict[str, Any]) -> None:
        """Process a single stream event (called from worker thread)."""
        event_type = event.get("type")

        if event_type == "status":
            msg = event.get("message", "")
            if not should_suppress_status(msg):
                self.app.call_from_thread(self._update_status, msg)

        elif event_type == "tool_start":
            self.app.call_from_thread(self._show_tool_start, event.get("name", "Tool"))

        elif event_type == "tool_end":
            self.app.call_from_thread(
                self._show_tool_end,
                event.get("name", "Tool"),
                event.get("duration", 0),
                event.get("entities", {}),
            )

        elif event_type == "text_start":
            self.app.call_from_thread(self._start_text_display)

        elif event_type == "text_delta":
            self.app.call_from_thread(
                self._append_text_delta, event.get("content", "")
            )

        elif event_type == "text_end":
            self.app.call_from_thread(self._finish_text_display)

        elif event_type == "done":
            self.app.call_from_thread(self._finish_streaming, event.get("duration", 0))

        elif event_type == "error":
            self.app.call_from_thread(
                self._handle_error, event.get("message", "Unknown error")
            )

    # ------------------------------------------------------------------
    # File ops (using FileOpsMixin)
    # ------------------------------------------------------------------

    def _handle_pending_file_ops(self, event: dict[str, Any]) -> None:
        """Handle pending file operations event."""
        self._pending_file_ops = {
            "id": event.get("id"),
            "operations": event.get("operations", []),
        }
        self._streaming = False
        self._stop_processing()
        self._remove_processing_placeholder()

        prompt = self._prepare_pending_prompt(self._pending_file_ops)
        if prompt:
            self._entries.append({"role": "assistant", "content": prompt})
            self._render_entries()

        input_box = self.query_one("#chat-input", Input)
        input_box.disabled = False
        input_box.focus()

    def _resolve_pending_request(
        self, approved: bool
    ) -> tuple[str, list[dict[str, Any]]]:
        pending = self._pending_file_ops
        if not pending:
            return "No pending operations.", []

        response, next_pending, new_auto = self._resolve_pending_core(
            pending, approved, self._auto_approve_chain, self._stream_continue_request
        )

        self._pending_file_ops = next_pending
        self._auto_approve_chain = new_auto
        if not next_pending:
            self._pending_requires_approval = False
            self._auto_approve_chain = False

        return response, []

    def _stream_continue_request(
        self, pending_id: str, tool_outputs: list[dict[str, Any]]
    ) -> tuple[str, dict[str, Any] | None]:
        """Stream the continue request response."""
        response = stream_post(
            f"{CHAT_API_URL}/continue",
            {"pending_id": pending_id, "tool_outputs": tool_outputs},
        )

        full_text = ""
        next_pending = None

        for event in iter_ndjson_events(response):
            if event.get("type") == "pending_file_ops":
                next_pending = {
                    "id": event.get("id"),
                    "operations": event.get("operations", []),
                }
                self.app.call_from_thread(self._handle_pending_file_ops, event)
                return full_text, next_pending

            self._process_stream_event(event)

            if event.get("type") == "text_delta":
                full_text += event.get("content", "")

        return full_text, None

    # ------------------------------------------------------------------
    # UI callbacks
    # ------------------------------------------------------------------

    def _update_status(self, message: str) -> None:
        if self._entries and self._entries[-1].get("role") == "pending":
            self._entries[-1]["content"] = f"{self._processing_text()} {message}"
            self._render_entries()

    def _show_tool_start(self, tool_name: str) -> None:
        self._current_tool = tool_name
        display_name = self._format_tool_name(tool_name)
        if self._entries and self._entries[-1].get("role") == "pending":
            self._entries[-1]["content"] = (
                f"{self._processing_text()} [cyan]{display_name}...[/cyan]"
            )
            self._render_entries()

    def _show_tool_end(
        self, tool_name: str, duration: float, entities: dict[str, Any]
    ) -> None:
        self._current_tool = None

        # Merge entities (all 5 types)
        for key in ["markets", "events", "users", "symbols", "tokens"]:
            if key in entities and entities[key]:
                if key not in self._entities:
                    self._entities[key] = []
                self._entities[key].extend(entities[key])

        # Launch background metadata enrichment for polymarket entities
        if any(entities.get(k) for k in ["markets", "events", "users"]):
            self.run_worker(
                lambda: enrich_entities_in_background(
                    entities, self._on_entity_enriched
                ),
                thread=True,
                name="chat_enrich",
            )

        display_name = self._format_tool_name(tool_name)
        if self._entries and self._entries[-1].get("role") == "pending":
            self._entries[-1]["content"] = (
                f"{self._processing_text()} [green]{display_name}[/green] [dim]({duration:.1f}s)[/dim]"
            )
            self._render_entries()

    def _on_entity_enriched(
        self, entity_type: str, key: str, metadata: dict[str, Any]
    ) -> None:
        """Callback from metadata enrichment worker."""
        entities = self._entities.get(entity_type, [])
        for e in entities:
            entity_key = e.get("slug") or e.get("wallet") or e.get("id")
            if entity_key == key:
                e.update(metadata)

    def _format_tool_name(self, tool_name: str) -> str:
        name_map = {
            "get_whale_trades": "Loading whale trades",
            "get_whale_positions": "Loading whale positions",
            "get_liquidations": "Loading liquidations",
            "get_market_data": "Loading market data",
            "get_token_price": "Loading price",
            "get_wallet_info": "Loading wallet",
            "search_whales": "Searching whales",
            "web_search": "Searching web",
            "apply_patch": "Applying changes",
            "read_file": "Reading file",
        }
        return name_map.get(tool_name, tool_name.replace("_", " ").title())

    def _start_text_display(self) -> None:
        self._stop_processing()
        self._current_text = ""
        if self._entries and self._entries[-1].get("role") == "pending":
            self._entries.pop()

        if self._entities:
            self._append_entities_display()

        self._entries.append({"role": "assistant_streaming", "content": ""})
        self._render_entries()

    def _append_text_delta(self, content: str) -> None:
        self._current_text += content
        if self._entries and self._entries[-1].get("role") == "assistant_streaming":
            self._entries[-1]["content"] = self._current_text
            self._render_entries()

    def _finish_text_display(self) -> None:
        if self._entries and self._entries[-1].get("role") == "assistant_streaming":
            self._entries[-1]["role"] = "assistant"
            self._render_entries()

    def _finish_streaming(self, duration: float) -> None:
        self._streaming = False
        self._stop_processing()
        self._persist_state()

        input_box = self.query_one("#chat-input", Input)
        input_box.disabled = False
        input_box.focus()

    def _handle_error(self, message: str) -> None:
        self._streaming = False
        self._stop_processing()
        self._remove_processing_placeholder()
        self._append_system_message(f"Error: {message}")

        input_box = self.query_one("#chat-input", Input)
        input_box.disabled = False
        input_box.focus()

    def on_worker_state_changed(self, event) -> None:
        if event.worker.name not in ("chat_stream", "chat_pending", "chat_enrich"):
            return

        if event.state.name == "ERROR" and event.worker.name != "chat_enrich":
            self._streaming = False
            self._stop_processing()
            input_box = self.query_one("#chat-input", Input)
            input_box.disabled = False
            input_box.focus()

    # ------------------------------------------------------------------
    # Entity display
    # ------------------------------------------------------------------

    def _append_entities_display(self) -> None:
        for entity_type in ["markets", "events", "users", "symbols", "tokens"]:
            entities = self._entities.get(entity_type, [])
            if entities:
                seen: set[str] = set()
                unique: list[dict[str, Any]] = []
                for e in entities:
                    key = (
                        e.get("id")
                        or e.get("slug")
                        or e.get("wallet")
                        or e.get("symbol")
                        or str(e)
                    )
                    if key not in seen:
                        seen.add(key)
                        unique.append(e)

                card_content = self._format_entity_card(entity_type, unique)
                self._entries.append({"role": "entity", "content": card_content})

    def _format_entity_card(
        self, entity_type: str, entities: list[dict[str, Any]]
    ) -> str:
        if not entities:
            return ""

        lines: list[str] = []
        icon = {
            "markets": "\U0001f4ca",
            "events": "\U0001f4c5",
            "users": "\U0001f464",
            "symbols": "\U0001f4c8",
            "tokens": "\U0001fa99",
        }.get(entity_type, "\u2022")
        title = entity_type.title()
        lines.append(f"[bold cyan]{icon} {title} Found[/bold cyan]")

        for entity in entities[:5]:
            if entity_type == "markets":
                question = entity.get("question", entity.get("slug", "Unknown"))
                if len(question) > 60:
                    question = question[:57] + "..."
                lines.append(f"  [dim]\u2022[/dim] {question}")
            elif entity_type == "events":
                title_text = entity.get("title", entity.get("slug", "Unknown"))
                if len(title_text) > 60:
                    title_text = title_text[:57] + "..."
                lines.append(f"  [dim]\u2022[/dim] {title_text}")
            elif entity_type == "users":
                username = entity.get("username") or entity.get("wallet", "")[:16]
                pnl = entity.get("pnl")
                if pnl is not None:
                    pnl_color = "green" if pnl >= 0 else "red"
                    lines.append(
                        f"  [dim]\u2022[/dim] {username} [{pnl_color}]${pnl:,.0f}[/{pnl_color}]"
                    )
                else:
                    lines.append(f"  [dim]\u2022[/dim] {username}")
            elif entity_type == "symbols":
                symbol = entity.get("symbol", "?")
                price = entity.get("price")
                change = entity.get("change_24h_pct")
                price_str = f"${price:,.2f}" if price is not None else ""
                change_str = ""
                if change is not None:
                    color = "green" if change >= 0 else "red"
                    change_str = f" [{color}]{change:+.1f}%[/{color}]"
                lines.append(f"  [dim]\u2022[/dim] {symbol} {price_str}{change_str}")
            elif entity_type == "tokens":
                symbol = entity.get("symbol", "?")
                name = entity.get("name", symbol)
                price = entity.get("price")
                price_str = f" ${price:,.4f}" if price is not None else ""
                lines.append(f"  [dim]\u2022[/dim] {name} ({symbol}){price_str}")

        if len(entities) > 5:
            lines.append(f"  [dim]... +{len(entities) - 5} more[/dim]")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Message helpers
    # ------------------------------------------------------------------

    def _append_user_message(self, message: str) -> None:
        self._entries.append({"role": "user", "content": message})
        self._render_entries()

    def _append_system_message(self, message: str) -> None:
        self._entries.append(
            {"role": "system", "content": f"[bold red]{message}[/bold red]"}
        )
        self._render_entries()

    # ------------------------------------------------------------------
    # Processing spinner
    # ------------------------------------------------------------------

    def _start_processing(self) -> None:
        self._processing_frame = 0
        self._append_processing_placeholder()
        if self._processing_timer:
            self._processing_timer.stop()
        self._processing_timer = self.set_interval(0.4, self._tick_processing)

    def _stop_processing(self) -> None:
        if self._processing_timer:
            self._processing_timer.stop()
            self._processing_timer = None

    def _tick_processing(self) -> None:
        self._processing_frame = (self._processing_frame + 1) % 8
        if self._entries and self._entries[-1].get("role") == "pending":
            tool_suffix = ""
            if self._current_tool:
                display_name = self._format_tool_name(self._current_tool)
                tool_suffix = f" [cyan]{display_name}...[/cyan]"
            self._entries[-1]["content"] = self._processing_text() + tool_suffix
            self._render_entries()

    def _processing_text(self) -> str:
        spinner = ["\u28fe", "\u28fd", "\u28fb", "\u28bf", "\u287f", "\u28df", "\u28ef", "\u28f7"]
        return f"{spinner[self._processing_frame % len(spinner)]} Thinking..."

    def _append_processing_placeholder(self) -> None:
        self._entries.append({"role": "pending", "content": self._processing_text()})
        self._render_entries()

    def _remove_processing_placeholder(self) -> None:
        if self._entries and self._entries[-1].get("role") == "pending":
            self._entries.pop()
            self._render_entries()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _render_entries(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.clear()

        for entry in self._entries:
            role = entry.get("role")
            content = entry.get("content", "")

            if role == "system":
                log.write(content)
            elif role == "user":
                self._render_user_block(log, content)
            elif role == "entity":
                log.write("")
                log.write(content)
            elif role == "diff":
                log.write("")
                renderable = entry.get("renderable")
                if renderable:
                    log.write(renderable)
            elif role in ("assistant", "assistant_streaming"):
                log.write("")
                for line in self._format_lines(content):
                    log.write(line)
                log.write("")
            elif role == "pending":
                log.write("")
                log.write(content)
                log.write("")

        self._persist_state()

    def _render_user_block(self, log: RichLog, message: str) -> None:
        bg = "on #1e2a36"
        log.write("")
        log.write(self._wrap_line("", background=bg))
        lines = message.splitlines() if message else [""]
        for idx, line in enumerate(lines):
            prefix = "> " if idx == 0 else ""
            log.write(self._wrap_line(f"{prefix}{line}", background=bg))
        log.write(self._wrap_line("", background=bg))

    def _format_lines(self, message: str) -> list[str]:
        lines = message.splitlines() if message else [""]
        return lines

    def _wrap_line(self, text: str, background: str | None = None) -> str:
        if not background:
            return text
        width = self._log_width()
        padded = text.ljust(width) if width > 0 else text
        return f"[{background}]{padded}[/]"

    def _log_width(self) -> int:
        log = self.query_one("#chat-log", RichLog)
        return log.size.width or log.min_width

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _restore_state(self) -> None:
        self._history = getattr(self.app, "chat_history", [])
        self._entries = getattr(self.app, "chat_entries", [])

    def _persist_state(self) -> None:
        self.app.chat_history = self._history
        self.app.chat_entries = self._entries
