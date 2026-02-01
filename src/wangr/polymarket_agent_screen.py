"""Polymarket agent screen with streaming responses."""

import difflib
import json
from pathlib import Path
from typing import Any

import requests
from agents import apply_diff as agents_apply_diff
from rich.console import Group
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, RichLog, Static

from wangr.config import API_TIMEOUT, POLYMARKET_CHAT_API_URL
from wangr.settings import get_api_key


class EntityCard(Static):
    """Display card for extracted entities."""

    def __init__(self, entity_type: str, entities: list[dict[str, Any]]) -> None:
        super().__init__()
        self.entity_type = entity_type
        self.entities = entities

    def render(self) -> str:
        if not self.entities:
            return ""

        lines = []
        icon = {"markets": "📊", "events": "📅", "users": "👤"}.get(self.entity_type, "•")
        title = self.entity_type.title()
        lines.append(f"[bold]{icon} {title}[/bold]")

        for entity in self.entities[:5]:  # Limit to 5
            if self.entity_type == "markets":
                question = entity.get("question", entity.get("slug", "Unknown"))
                if len(question) > 50:
                    question = question[:47] + "..."
                lines.append(f"  • {question}")
            elif self.entity_type == "events":
                title = entity.get("title", entity.get("slug", "Unknown"))
                if len(title) > 50:
                    title = title[:47] + "..."
                lines.append(f"  • {title}")
            elif self.entity_type == "users":
                username = entity.get("username", entity.get("wallet", "Unknown")[:12])
                lines.append(f"  • {username}")

        if len(self.entities) > 5:
            lines.append(f"  [dim]... and {len(self.entities) - 5} more[/dim]")

        return "\n".join(lines)


class PolymarketAgentScreen(Screen):
    """Streaming chat screen for Polymarket queries."""

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
        # File operations state
        self._pending_file_ops: dict[str, Any] | None = None
        self._pending_requires_approval = False
        self._auto_approve_chain = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        yield Container(
            RichLog(id="polymarket-log", wrap=True, highlight=True, markup=True),
            Input(placeholder="Ask about Polymarket...", id="polymarket-input"),
            id="polymarket-container",
        )

    async def on_mount(self) -> None:
        self._restore_state()
        if not self._entries:
            self._entries.append(
                {"role": "system", "content": "[bold]🎯 Polymarket Agent[/bold]"}
            )
            self._entries.append(
                {
                    "role": "system",
                    "content": "Ask about markets, events, or traders. [dim](Ctrl+L to clear)[/dim]\n",
                }
            )
        self._render_entries()
        self.query_one("#polymarket-input", Input).focus()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_clear_chat(self) -> None:
        self._history = []
        self._entries = [
            {"role": "system", "content": "[bold]🎯 Polymarket Agent[/bold]"},
            {"role": "system", "content": "History cleared.\n"},
        ]
        self._entities = {}
        self._pending_file_ops = None
        self._pending_requires_approval = False
        self._auto_approve_chain = False
        self._render_entries()
        self._persist_state()

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
                name="polymarket_pending",
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
        input_box = self.query_one("#polymarket-input", Input)
        input_box.value = ""
        input_box.disabled = True
        self._start_processing()
        self.run_worker(
            lambda: self._resolve_pending_request(approved),
            thread=True,
            name="polymarket_pending",
        )

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
            name="polymarket_stream",
        )

    def _stream_request(self, message: str) -> tuple[str, list[dict[str, Any]]]:
        """Execute streaming request and process events."""
        try:
            headers = {"Content-Type": "application/json"}
            api_key = get_api_key()
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            response = requests.post(
                POLYMARKET_CHAT_API_URL,
                json={"message": message, "history": self._history},
                headers=headers,
                timeout=API_TIMEOUT * 12,
                stream=True,
            )
            response.raise_for_status()

            full_text, tool_calls = self._process_stream_response(response)

            # Update history
            self._history.append({"role": "user", "content": message})
            self._history.append({"role": "assistant", "content": full_text})

            return full_text, tool_calls

        except Exception as exc:
            self.app.call_from_thread(self._handle_error, str(exc))
            raise RuntimeError("stream request failed") from exc

    def _process_stream_response(self, response) -> tuple[str, list[dict[str, Any]]]:
        """Process streaming response and return full text and tool calls."""
        full_text = ""
        tool_calls: list[dict[str, Any]] = []

        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.strip():
                continue
            try:
                event = json.loads(line)

                # Check for pending_file_ops event
                if event.get("type") == "pending_file_ops":
                    self.app.call_from_thread(self._handle_pending_file_ops, event)
                    # Stop processing this stream - will continue after approval
                    return full_text, tool_calls

                self._process_stream_event(event)

                # Collect final data
                if event.get("type") == "text_delta":
                    full_text += event.get("content", "")
                elif event.get("type") == "done":
                    tool_calls = event.get("tool_calls", [])
            except json.JSONDecodeError:
                continue

        return full_text, tool_calls

    def _handle_pending_file_ops(self, event: dict[str, Any]) -> None:
        """Handle pending file operations event."""
        self._pending_file_ops = {
            "id": event.get("id"),
            "operations": event.get("operations", []),
        }
        self._streaming = False  # Allow input for Y/N approval
        self._stop_processing()
        self._remove_processing_placeholder()

        # Prepare and show approval prompt
        prompt = self._prepare_pending_prompt(self._pending_file_ops)
        if prompt:
            self._entries.append({"role": "assistant", "content": prompt})
            self._render_entries()

        # Enable input for Y/N
        input_box = self.query_one("#polymarket-input", Input)
        input_box.disabled = False
        input_box.focus()

    def _prepare_pending_prompt(self, pending: dict[str, Any]) -> str:
        """Prepare the approval prompt with diff preview."""
        preview, approvable, _auto_outputs = self._categorize_patch_ops(pending)
        self._pending_requires_approval = bool(approvable)

        if preview:
            renderable = Group(
                Text("Proposed changes:", style="bold"),
                self._render_diff(preview),
            )
            self._entries.append({"role": "diff", "renderable": renderable})
        elif approvable:
            self._entries.append({
                "role": "system",
                "content": "[dim]Proposed changes (no diff preview available).[/dim]"
            })

        if approvable:
            return "Apply these changes? [bold]Y[/bold]/[bold]N[/bold]"
        return ""

    def _categorize_patch_ops(
        self, pending: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
        """Categorize patch operations into preview, approvable, and auto outputs."""
        previews = []
        approvable = []
        auto_outputs = []
        base_dir = Path.cwd()

        for op in pending.get("operations", []):
            if op.get("type") not in ("apply_patch", "read_file"):
                continue

            # Handle read_file operations automatically
            if op.get("type") == "read_file":
                continue

            call_id = op.get("call_id")
            operation = op.get("operation", op)
            op_type = operation.get("type")

            try:
                diff = self._preview_operation(operation, base_dir)
                if diff:
                    previews.append(diff)
                if op_type in {"create_file", "update_file", "delete_file"}:
                    approvable.append(op)
            except Exception as exc:
                path = operation.get("path", "<unknown>")
                auto_outputs.append({
                    "call_id": call_id,
                    "status": "failed",
                    "output": f"Preview error for {path}: {exc}",
                })

        return "\n\n".join(previews), approvable, auto_outputs

    def _preview_operation(self, operation: dict[str, Any], base_dir: Path) -> str:
        """Generate diff preview for an operation."""
        op = self._normalize_operation(operation)
        target = self._resolve_path(base_dir, op["path"])

        if op["type"] == "delete_file":
            if not target.exists():
                raise ValueError(f"File not found: {op['path']}")
            old_content = target.read_text()
            new_content = ""
        elif op["type"] == "create_file":
            if target.exists():
                raise ValueError(f"File already exists: {op['path']}")
            old_content = ""
            new_content = self._apply_diff("", op.get("diff") or "", mode="create")
        elif op["type"] == "update_file":
            if not target.exists():
                raise ValueError(f"File not found: {op['path']}")
            old_content = target.read_text()
            new_content = self._apply_diff(old_content, op.get("diff") or "")
        else:
            raise ValueError(f"Unsupported operation type: {op['type']}")

        if old_content == new_content:
            return ""

        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()
        to_name = op["path"] if op["type"] != "delete_file" else "(deleted)"
        diff_lines = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=op["path"],
            tofile=to_name,
            lineterm="",
        )
        return "\n".join(diff_lines)

    def _render_diff(self, preview: str) -> Group:
        """Render a diff with theme-matching colors."""
        lines = preview.splitlines()
        width = len(str(len(lines))) if lines else 1
        rendered = []
        for idx, line in enumerate(lines, start=1):
            text = Text()
            text.append(f"{idx:>{width}} ", style="dim")
            if line.startswith("+++") or line.startswith("---"):
                text.append(line, style="dim")
            elif line.startswith("@@"):
                text.append(line, style="cyan")
            elif line.startswith("+"):
                text.append(line, style="green")
            elif line.startswith("-"):
                text.append(line, style="red")
            else:
                text.append(line, style="white")
            rendered.append(text)
        return Group(*rendered)

    def _normalize_operation(self, operation: dict[str, Any]) -> dict[str, Any]:
        """Normalize operation format."""
        if "operation" in operation and isinstance(operation["operation"], dict):
            operation = operation["operation"]
        op_type = operation.get("type")
        path = operation.get("path")
        if not op_type or not path:
            raise ValueError("Operation must include 'type' and 'path'.")
        return {"type": op_type, "path": path, "diff": operation.get("diff")}

    def _resolve_path(self, base_dir: Path, path: str) -> Path:
        """Resolve and validate path within workspace."""
        candidate = Path(path)
        if candidate.is_absolute():
            raise ValueError("Absolute paths are not allowed.")
        resolved = (base_dir / candidate).resolve()
        if not resolved.is_relative_to(base_dir.resolve()):
            raise ValueError("Path escapes the workspace root.")
        return resolved

    def _sanitize_diff(self, diff: str) -> str:
        """Remove patch markers from diff."""
        lines = []
        for line in diff.splitlines():
            if line.startswith("*** Begin Patch") or line.startswith("*** End Patch"):
                continue
            if line.startswith("*** Update File") or line.startswith("*** Add File") or line.startswith("*** Delete File"):
                continue
            if line.startswith("diff --git") or line.startswith("index "):
                continue
            if line.startswith("--- ") or line.startswith("+++ "):
                continue
            lines.append(line)
        return "\n".join(lines)

    def _apply_diff(self, input_text: str, diff: str, mode: str = "default") -> str:
        """Apply diff to input text."""
        return agents_apply_diff(input_text, self._sanitize_diff(diff), mode)

    def _apply_operation(self, operation: dict[str, Any], base_dir: Path) -> tuple[bool, str]:
        """Apply a file operation."""
        try:
            op = self._normalize_operation(operation)
            target = self._resolve_path(base_dir, op["path"])

            if op["type"] == "delete_file":
                if not target.exists():
                    return False, f"File not found: {op['path']}"
                target.unlink()
                return True, f"Deleted {op['path']}"
            if op["type"] == "create_file":
                if target.exists():
                    return False, f"File already exists: {op['path']}"
                content = self._apply_diff("", op.get("diff") or "", mode="create")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
                return True, f"Created {op['path']}"
            if op["type"] == "update_file":
                if not target.exists():
                    return False, f"File not found: {op['path']}"
                old_content = target.read_text()
                new_content = self._apply_diff(old_content, op.get("diff") or "")
                if new_content != old_content:
                    target.write_text(new_content)
                return True, f"Updated {op['path']}"
            return False, f"Unsupported operation type: {op['type']}"
        except Exception as exc:
            return False, str(exc)

    def _resolve_pending_request(self, approved: bool) -> tuple[str, list[dict[str, Any]]]:
        """Resolve pending file operations."""
        pending = self._pending_file_ops
        if not pending:
            return "No pending operations.", []

        response, next_pending, new_auto_approve = self._resolve_pending(
            pending, approved, self._auto_approve_chain
        )

        self._pending_file_ops = next_pending
        self._auto_approve_chain = new_auto_approve
        if not next_pending:
            self._pending_requires_approval = False
            self._auto_approve_chain = False

        return response, []

    def _resolve_pending(
        self, pending: dict[str, Any], approved: bool, auto_approve_chain: bool
    ) -> tuple[str, dict[str, Any] | None, bool]:
        """Execute pending operations and continue streaming."""
        pending_id = pending.get("id")
        operations = pending.get("operations", [])

        if not pending_id:
            raise ValueError("Missing pending operation id.")

        read_ops = [op for op in operations if op.get("type") == "read_file"]
        patch_ops = [op for op in operations if op.get("type") == "apply_patch"]

        outputs = []
        auto_outputs = []

        if read_ops:
            outputs.extend(self._execute_read_ops(read_ops))

        if patch_ops:
            _preview, approvable, auto_outputs = self._categorize_patch_ops(pending)
            outputs.extend(auto_outputs)

            if approvable:
                if approved or auto_approve_chain:
                    outputs.extend(self._apply_patch_ops(approvable))
                else:
                    outputs.extend(self._deny_operations(approvable, "User denied operation."))

        # Call continue endpoint with streaming
        response, next_pending = self._stream_continue_request(pending_id, outputs)
        return response, next_pending, auto_approve_chain or (approved and bool(patch_ops) and not auto_outputs)

    def _execute_read_ops(self, operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Execute read file operations."""
        results = []
        base_dir = Path.cwd()
        for op in operations:
            call_id = op.get("call_id")
            path = op.get("path", "")
            try:
                resolved = self._resolve_path(base_dir, path)
                content = resolved.read_text()
                results.append({
                    "call_id": call_id,
                    "status": "completed",
                    "output": content,
                })
            except Exception as exc:
                results.append({
                    "call_id": call_id,
                    "status": "failed",
                    "output": f"Error reading file: {exc}",
                })
        return results

    def _apply_patch_ops(self, operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Apply patch operations."""
        results = []
        base_dir = Path.cwd()
        for op in operations:
            call_id = op.get("call_id")
            operation = op.get("operation", op)
            success, output = self._apply_operation(operation, base_dir)
            results.append({
                "call_id": call_id,
                "status": "completed" if success else "failed",
                "output": output,
            })
        return results

    def _deny_operations(self, operations: list[dict[str, Any]], reason: str) -> list[dict[str, Any]]:
        """Deny operations with a reason."""
        return [{
            "call_id": op.get("call_id"),
            "status": "failed",
            "output": reason,
        } for op in operations]

    def _stream_continue_request(
        self, pending_id: str, tool_outputs: list[dict[str, Any]]
    ) -> tuple[str, dict[str, Any] | None]:
        """Stream the continue request response."""
        headers = {"Content-Type": "application/json"}
        api_key = get_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        response = requests.post(
            f"{POLYMARKET_CHAT_API_URL}/continue",
            json={"pending_id": pending_id, "tool_outputs": tool_outputs},
            headers=headers,
            timeout=API_TIMEOUT * 12,
            stream=True,
        )
        response.raise_for_status()

        full_text = ""
        next_pending = None

        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.strip():
                continue
            try:
                event = json.loads(line)

                # Check for another pending_file_ops
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
            except json.JSONDecodeError:
                continue

        return full_text, None

    def _process_stream_event(self, event: dict[str, Any]) -> None:
        """Process a single stream event (called from worker thread)."""
        event_type = event.get("type")

        if event_type == "status":
            self.app.call_from_thread(self._update_status, event.get("message", ""))

        elif event_type == "tool_start":
            tool_name = event.get("name", "Tool")
            self.app.call_from_thread(self._show_tool_start, tool_name)

        elif event_type == "tool_end":
            tool_name = event.get("name", "Tool")
            duration = event.get("duration", 0)
            entities = event.get("entities", {})
            self.app.call_from_thread(self._show_tool_end, tool_name, duration, entities)

        elif event_type == "text_start":
            self.app.call_from_thread(self._start_text_display)

        elif event_type == "text_delta":
            content = event.get("content", "")
            self.app.call_from_thread(self._append_text_delta, content)

        elif event_type == "text_end":
            self.app.call_from_thread(self._finish_text_display)

        elif event_type == "done":
            duration = event.get("duration", 0)
            self.app.call_from_thread(self._finish_streaming, duration)

        elif event_type == "error":
            message = event.get("message", "Unknown error")
            self.app.call_from_thread(self._handle_error, message)

    def _update_status(self, message: str) -> None:
        """Update status message in the log."""
        if self._entries and self._entries[-1].get("role") == "pending":
            self._entries[-1]["content"] = f"{self._processing_text()} {message}"
            self._render_entries()

    def _show_tool_start(self, tool_name: str) -> None:
        """Show tool start indicator."""
        self._current_tool = tool_name
        display_name = self._format_tool_name(tool_name)
        if self._entries and self._entries[-1].get("role") == "pending":
            self._entries[-1]["content"] = f"{self._processing_text()} [cyan]{display_name}...[/cyan]"
            self._render_entries()

    def _show_tool_end(
        self, tool_name: str, duration: float, entities: dict[str, Any]
    ) -> None:
        """Show tool completion and extract entities."""
        self._current_tool = None

        # Merge entities
        for key in ["markets", "events", "users"]:
            if key in entities and entities[key]:
                if key not in self._entities:
                    self._entities[key] = []
                self._entities[key].extend(entities[key])

        display_name = self._format_tool_name(tool_name)
        if self._entries and self._entries[-1].get("role") == "pending":
            self._entries[-1]["content"] = (
                f"{self._processing_text()} [green]{display_name}[/green] [dim]({duration:.1f}s)[/dim]"
            )
            self._render_entries()

    def _format_tool_name(self, tool_name: str) -> str:
        """Format tool name for display."""
        name_map = {
            "search_gamma_markets": "Searching markets",
            "get_gamma_markets": "Fetching markets",
            "get_gamma_market_by_slug": "Fetching market",
            "get_gamma_market_by_id": "Fetching market",
            "get_gamma_events": "Fetching events",
            "get_gamma_event_by_slug": "Fetching event",
            "get_gamma_event_by_id": "Fetching event",
            "get_gamma_tags": "Fetching tags",
            "get_user_portfolio_summary": "Loading portfolio",
            "get_user_positions": "Loading positions",
            "get_user_closed_positions": "Loading closed positions",
            "get_trades": "Fetching trades",
            "get_market_info": "Loading market info",
            "get_event_activity": "Loading activity",
            "get_trader_leaderboard": "Loading leaderboard",
            "web_search": "Searching web",
            "apply_patch": "Applying changes",
            "read_file": "Reading file",
        }
        return name_map.get(tool_name, tool_name.replace("_", " ").title())

    def _start_text_display(self) -> None:
        """Start displaying streamed text."""
        self._stop_processing()
        self._current_text = ""
        # Remove pending placeholder
        if self._entries and self._entries[-1].get("role") == "pending":
            self._entries.pop()

        # Add entity cards if we have entities
        if self._entities:
            self._append_entities_display()

        # Start new assistant entry for streaming text
        self._entries.append({"role": "assistant_streaming", "content": ""})
        self._render_entries()

    def _append_text_delta(self, content: str) -> None:
        """Append text delta to current streaming response."""
        self._current_text += content
        if self._entries and self._entries[-1].get("role") == "assistant_streaming":
            self._entries[-1]["content"] = self._current_text
            self._render_entries()

    def _finish_text_display(self) -> None:
        """Finish text display."""
        if self._entries and self._entries[-1].get("role") == "assistant_streaming":
            self._entries[-1]["role"] = "assistant"
            self._render_entries()

    def _append_entities_display(self) -> None:
        """Add entity display cards."""
        for entity_type in ["markets", "events", "users"]:
            entities = self._entities.get(entity_type, [])
            if entities:
                # Deduplicate by id/slug/wallet
                seen = set()
                unique = []
                for e in entities:
                    key = e.get("id") or e.get("slug") or e.get("wallet") or str(e)
                    if key not in seen:
                        seen.add(key)
                        unique.append(e)

                card_content = self._format_entity_card(entity_type, unique)
                self._entries.append({"role": "entity", "content": card_content})

    def _format_entity_card(self, entity_type: str, entities: list[dict[str, Any]]) -> str:
        """Format entities for display."""
        if not entities:
            return ""

        lines = []
        icon = {"markets": "📊", "events": "📅", "users": "👤"}.get(entity_type, "•")
        title = entity_type.title()
        lines.append(f"[bold cyan]{icon} {title} Found[/bold cyan]")

        for entity in entities[:5]:
            if entity_type == "markets":
                question = entity.get("question", entity.get("slug", "Unknown"))
                if len(question) > 60:
                    question = question[:57] + "..."
                lines.append(f"  [dim]•[/dim] {question}")
            elif entity_type == "events":
                title_text = entity.get("title", entity.get("slug", "Unknown"))
                if len(title_text) > 60:
                    title_text = title_text[:57] + "..."
                lines.append(f"  [dim]•[/dim] {title_text}")
            elif entity_type == "users":
                username = entity.get("username") or entity.get("wallet", "")[:16]
                pnl = entity.get("pnl")
                if pnl is not None:
                    pnl_str = f"[green]${pnl:,.0f}[/green]" if pnl >= 0 else f"[red]${pnl:,.0f}[/red]"
                    lines.append(f"  [dim]•[/dim] {username} {pnl_str}")
                else:
                    lines.append(f"  [dim]•[/dim] {username}")

        if len(entities) > 5:
            lines.append(f"  [dim]... +{len(entities) - 5} more[/dim]")

        return "\n".join(lines)

    def _finish_streaming(self, duration: float) -> None:
        """Finish streaming response."""
        self._streaming = False
        self._stop_processing()
        self._persist_state()

        # Re-enable input
        input_box = self.query_one("#polymarket-input", Input)
        input_box.disabled = False
        input_box.focus()

    def _handle_error(self, message: str) -> None:
        """Handle streaming error."""
        self._streaming = False
        self._stop_processing()
        self._remove_processing_placeholder()
        self._append_system_message(f"Error: {message}")

        input_box = self.query_one("#polymarket-input", Input)
        input_box.disabled = False
        input_box.focus()

    def on_worker_state_changed(self, event) -> None:
        """Handle worker completion."""
        if event.worker.name not in ("polymarket_stream", "polymarket_pending"):
            return

        if event.state.name == "ERROR":
            self._streaming = False
            self._stop_processing()
            input_box = self.query_one("#polymarket-input", Input)
            input_box.disabled = False
            input_box.focus()

    def _append_user_message(self, message: str) -> None:
        self._entries.append({"role": "user", "content": message})
        self._render_entries()

    def _append_system_message(self, message: str) -> None:
        self._entries.append({"role": "system", "content": f"[bold red]{message}[/bold red]"})
        self._render_entries()

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
        spinner = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]
        return f"{spinner[self._processing_frame % len(spinner)]} Thinking..."

    def _append_processing_placeholder(self) -> None:
        self._entries.append({"role": "pending", "content": self._processing_text()})
        self._render_entries()

    def _remove_processing_placeholder(self) -> None:
        if self._entries and self._entries[-1].get("role") == "pending":
            self._entries.pop()
            self._render_entries()

    def _render_entries(self) -> None:
        """Re-render the log from stored entries."""
        log = self.query_one("#polymarket-log", RichLog)
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
        log = self.query_one("#polymarket-log", RichLog)
        return log.size.width or log.min_width

    def _restore_state(self) -> None:
        self._history = getattr(self.app, "polymarket_history", [])
        self._entries = getattr(self.app, "polymarket_entries", [])

    def _persist_state(self) -> None:
        self.app.polymarket_history = self._history
        self.app.polymarket_entries = self._entries
