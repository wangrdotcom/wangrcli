"""Chat screen for Wangr agent."""

import logging
import os
from pathlib import Path
from typing import Any

import requests
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, RichLog, Static
from textual.worker import Worker

from wangrcli.config import API_TIMEOUT, CHAT_API_URL
from wangrcli.tools import LocalToolExecutor

logger = logging.getLogger(__name__)

# Set to True to test tool execution without backend changes
SIMULATION_MODE = os.getenv("WANGR_CHAT_SIMULATION", "").lower() in {"1", "true", "yes", "on"}


class ChatScreen(Screen):
    """Interactive chat screen."""

    BINDINGS = [
        ("b", "go_back", "Go Back"),
        ("ctrl+b", "go_back", "Go Back"),
        ("ctrl+l", "clear_chat", "Clear Chat"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._history: list[dict[str, Any]] = []
        self._entries: list[dict[str, Any]] = []
        self._worker: Worker | None = None
        self._processing_timer = None
        self._processing_frame = 0
        self._pending_index: int | None = None
        self._tool_executor = LocalToolExecutor(working_directory=str(Path.cwd()))

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        yield Container(
            RichLog(id="chat-log", wrap=True, highlight=True, markup=True),
            Static("", id="chat-status"),
            Input(placeholder="Ask Wangr…", id="chat-input"),
            id="chat-container",
        )

    async def on_mount(self) -> None:
        self._restore_state()
        if not self._entries:
            self._entries.append({"role": "system", "content": "[bold]💬 Wangr Crypto Assistant[/bold]"})
            self._entries.append(
                {"role": "system", "content": "Ask about whales, markets, or wallets. [dim](Ctrl+L to clear)[/dim]\n"}
            )
        self._render_entries()
        self.query_one("#chat-input", Input).focus()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_clear_chat(self) -> None:
        self._history = []
        self._entries = [
            {"role": "system", "content": "[bold]💬 Wangr Crypto Assistant[/bold]"},
            {"role": "system", "content": "✓ History cleared.\n"},
        ]
        self._render_entries()
        self._persist_state()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        message = event.value.strip()
        if not message:
            return
        if self._worker and self._worker.is_running:
            return
        event.input.value = ""
        self._append_user_message(message)
        event.input.disabled = True
        self._start_processing()
        self._worker = self.run_worker(
            lambda: self._chat_request(message),
            thread=True,
            name="chat_request",
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker != self._worker:
            return
        input_box = self.query_one("#chat-input", Input)
        if event.state.name == "SUCCESS":
            input_box.disabled = False
            input_box.focus()
            self._stop_processing()
            response, tool_calls = event.worker.result
            self._append_assistant_message(response, tool_calls)
        elif event.state.name == "ERROR":
            input_box.disabled = False
            input_box.focus()
            self._stop_processing()
            self._show_status_temp("Request failed. Try again.")
            self._append_system_message("Request failed.")

    def _chat_request(self, message: str) -> tuple[str, list[dict[str, Any]]]:
        if SIMULATION_MODE:
            return self._simulate_chat_with_tools(message)
        return self._real_chat_request(message)

    def _real_chat_request(self, message: str) -> tuple[str, list[dict[str, Any]]]:
        """Real API request (when backend supports tool execution)."""
        try:
            response = requests.post(
                CHAT_API_URL,
                json={"message": message, "history": self._history},
                timeout=API_TIMEOUT * 12,
            )
            response.raise_for_status()
            data = response.json()
            reply = data.get("response", "")
            tool_calls = data.get("tool_calls", [])
            self._history.append({"role": "user", "content": message})
            self._history.append({"role": "assistant", "content": reply})
            self._persist_state()
            return reply, tool_calls
        except Exception as exc:
            logger.error("Chat request failed: %s", exc)
            raise RuntimeError("chat request failed") from exc

    def _simulate_chat_with_tools(self, message: str) -> tuple[str, list[dict[str, Any]]]:
        """Simulate AI responses with tool calls for testing."""
        msg_lower = message.lower()
        tool_calls_executed: list[dict[str, Any]] = []

        # Detect tool-triggering commands in the message
        if "read " in msg_lower or "show " in msg_lower or "cat " in msg_lower:
            # Extract filename - simple parsing
            for word in message.split():
                if "." in word and not word.startswith("."):
                    tool_call = {
                        "id": f"sim_{len(tool_calls_executed)}",
                        "name": "read_file",
                        "arguments": {"path": word.strip("\"'")},
                    }
                    result = self._execute_tool(tool_call)
                    tool_calls_executed.append({**tool_call, "result": result})
                    break

        elif "list " in msg_lower or "ls " in msg_lower or "files" in msg_lower:
            pattern = "*"
            if "*.py" in msg_lower:
                pattern = "*.py"
            elif "*.md" in msg_lower:
                pattern = "*.md"
            tool_call = {
                "id": f"sim_{len(tool_calls_executed)}",
                "name": "list_files",
                "arguments": {"pattern": pattern, "path": "."},
            }
            result = self._execute_tool(tool_call)
            tool_calls_executed.append({**tool_call, "result": result})

        elif "write " in msg_lower or "create " in msg_lower:
            # Look for filename and content pattern
            parts = message.split(":", 1)
            if len(parts) == 2:
                # Try to extract path from first part
                path = None
                for word in parts[0].split():
                    if "." in word:
                        path = word.strip("\"'")
                        break
                if path:
                    content = parts[1].strip()
                    tool_call = {
                        "id": f"sim_{len(tool_calls_executed)}",
                        "name": "write_file",
                        "arguments": {"path": path, "content": content},
                    }
                    result = self._execute_tool(tool_call)
                    tool_calls_executed.append({**tool_call, "result": result})

        elif "edit " in msg_lower:
            # This is harder to parse, provide guidance
            return (
                "[Simulation] To test edit_file, use format:\n"
                "`edit <file>: old_string >>> new_string`",
                []
            )

        # Build response based on what was executed
        if tool_calls_executed:
            response_parts = ["[Simulation Mode] Executed tools:\n"]
            for tc in tool_calls_executed:
                response_parts.append(f"**{tc['name']}**({tc['arguments']})")
                result_preview = tc["result"][:500] if len(tc["result"]) > 500 else tc["result"]
                response_parts.append(f"```\n{result_preview}\n```\n")
            return "\n".join(response_parts), tool_calls_executed
        else:
            # No tools detected, just echo
            return (
                f"[Simulation Mode] No tools triggered.\n\n"
                f"Try commands like:\n"
                f"- `read config.py`\n"
                f"- `list *.py`\n"
                f"- `create test.txt: hello world`\n\n"
                f"Your message: {message}",
                []
            )

    def _execute_tool(self, tool_call: dict[str, Any]) -> str:
        """Execute a single tool call locally."""
        name = tool_call.get("name", "")
        arguments = tool_call.get("arguments", {})
        return self._tool_executor.execute(name, arguments)

    def _append_user_message(self, message: str) -> None:
        self._entries.append({"role": "user", "content": message})
        self._render_entries()

    def _append_assistant_message(self, message: str, tool_calls: list[dict[str, Any]]) -> None:
        self._entries.append(
            {"role": "assistant", "content": message, "tool_calls": tool_calls}
        )
        self._render_entries()

    def _append_system_message(self, message: str) -> None:
        self._entries.append({"role": "system", "content": f"[bold red]{message}[/bold red]"})
        self._render_entries()

    def _format_lines(self, message: str, background: str | None = None) -> list[str]:
        """Format chat message lines for display."""
        lines = message.splitlines() if message else [""]
        formatted: list[str] = []
        for line in lines:
            if line.startswith("- "):
                formatted.append(self._wrap_line(f"  - {line[2:]}", background))
            elif line.strip() == "":
                formatted.append(self._wrap_line("", background))
            else:
                formatted.append(self._wrap_line(f"  {line}", background))
        return formatted

    def _wrap_line(
        self,
        text: str,
        background: str | None = None,
        style: str | None = None,
    ) -> str:
        if not background and not style:
            return text
        width = self._log_width()
        padded = text.ljust(width) if width > 0 else text
        if background and style:
            return f"[{background}][{style}]{padded}[/][/{background}]"
        if background:
            return f"[{background}]{padded}[/]"
        return f"[{style}]{padded}[/]"

    def _write_log(self, line: str) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.write(line)

    def _restore_state(self) -> None:
        self._history = getattr(self.app, "chat_history", [])
        self._entries = getattr(self.app, "chat_entries", [])

    def _persist_state(self) -> None:
        self.app.chat_history = self._history
        self.app.chat_entries = self._entries

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
        self._remove_processing_placeholder()
        self.query_one("#chat-status", Static).update("")

    def _tick_processing(self) -> None:
        self._processing_frame = (self._processing_frame + 1) % 4
        if self._pending_index is not None:
            self._entries[self._pending_index]["content"] = self._processing_text()
            self._render_entries()

    def _processing_text(self) -> str:
        spinner = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]
        return f"{spinner[self._processing_frame % len(spinner)]} Thinking..."

    def _log_width(self) -> int:
        log = self.query_one("#chat-log", RichLog)
        return log.size.width or log.min_width

    def _show_status_temp(self, message: str, seconds: float = 2.0) -> None:
        status = self.query_one("#chat-status", Static)
        status.update(message)
        self.set_timer(seconds, lambda: status.update(""))

    def _append_processing_placeholder(self) -> None:
        """Append a placeholder assistant response with animation."""
        if self._pending_index is not None:
            return
        self._pending_index = len(self._entries)
        self._entries.append({"role": "pending", "content": self._processing_text()})
        self._render_entries()

    def _remove_processing_placeholder(self) -> None:
        """Remove the placeholder assistant response."""
        if self._pending_index is None:
            return
        self._entries.pop(self._pending_index)
        self._pending_index = None
        self._render_entries()

    def _render_entries(self) -> None:
        """Re-render the log from stored entries."""
        log = self.query_one("#chat-log", RichLog)
        log.clear()
        for entry in self._entries:
            role = entry.get("role")
            content = entry.get("content", "")
            if role == "system":
                log.write(content)
                continue
            if role == "user":
                self._render_user_block(log, content)
                continue
            if role == "assistant":
                log.write("")
                for line in self._format_lines(content):
                    log.write(line)
                tool_calls = entry.get("tool_calls") or []
                if tool_calls:
                    tool_list = ", ".join(call.get("name", "tool") for call in tool_calls)
                    log.write(f"[dim]Tools used: {tool_list}[/dim]")
                log.write("")
                log.write("")
                continue
            if role == "pending":
                log.write("")
                for line in self._format_lines(content):
                    log.write(line)
                log.write("")
                log.write("")
        self._persist_state()

    def _render_user_block(self, log: RichLog, message: str) -> None:
        bg = "on #1e2a36"
        log.write("")
        log.write(self._wrap_line("", background=bg))
        lines = message.splitlines() if message else [""]
        for idx, line in enumerate(lines):
            prefix = "  > " if idx == 0 else "    "
            log.write(self._wrap_line(f"{prefix}{line}", background=bg))
        log.write(self._wrap_line("", background=bg))
