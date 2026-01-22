"""Chat screen for Wangr agent."""

import logging
from pathlib import Path
from typing import Any

import requests
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, RichLog, Static
from textual.worker import Worker

from wangr.config import API_TIMEOUT, CHAT_API_URL
from wangr.tools import LocalToolExecutor

logger = logging.getLogger(__name__)
_LOG_FILE = Path.cwd() / "wangr_chat.log"
if not logger.handlers:
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(file_handler)


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
            if tool_calls:
                self._show_status_temp(f"Tool calls: {len(tool_calls)}")
            else:
                self._show_status_temp("No tool calls")
            self._append_assistant_message(response, tool_calls)
        elif event.state.name == "ERROR":
            input_box.disabled = False
            input_box.focus()
            self._stop_processing()
            self._show_status_temp("Request failed. Try again.")
            self._append_system_message("Request failed.")

    def _chat_request(self, message: str) -> tuple[str, list[dict[str, Any]]]:
        return self._real_chat_request(message)

    def _real_chat_request(self, message: str) -> tuple[str, list[dict[str, Any]]]:
        """Real API request with local apply_patch handling."""
        try:
            data = self._post_chat({"message": message, "history": self._history})
            reply = data.get("response", "")
            tool_calls = data.get("tool_calls", []) or []
            response_id = data.get("response_id")
            if tool_calls:
                tool_names = [
                    call.get("name") or call.get("type", "tool")
                    for call in tool_calls
                ]
                logger.info(
                    "Chat response tool calls (%s): %s",
                    len(tool_calls),
                    ", ".join(tool_names),
                )
            else:
                logger.info("Chat response had no tool calls")
            if tool_calls:
                followup_reply, tool_calls = self._process_tool_calls(tool_calls, response_id)
                if followup_reply:
                    reply = followup_reply
            self._history.append({"role": "user", "content": message})
            self._history.append({"role": "assistant", "content": reply})
            self._persist_state()
            return reply, tool_calls
        except Exception as exc:
            logger.error("Chat request failed: %s", exc)
            raise RuntimeError("chat request failed") from exc

    def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            CHAT_API_URL,
            json=payload,
            timeout=API_TIMEOUT * 12,
        )
        response.raise_for_status()
        logger.info("Chat API response: %s", response.text)
        return response.json()

    def _process_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
        response_id: str | None,
        max_rounds: int = 5,
    ) -> tuple[str, list[dict[str, Any]]]:
        reply = ""
        all_calls: list[dict[str, Any]] = []
        current_calls = tool_calls
        current_response_id = response_id

        for _ in range(max_rounds):
            outputs, decorated_calls = self._handle_tool_calls(current_calls)
            all_calls.extend(decorated_calls)
            if not outputs:
                break
            payload: dict[str, Any] = {"history": self._history, "tool_outputs": outputs}
            if current_response_id:
                payload["previous_response_id"] = current_response_id
            data = self._post_chat(payload)
            reply = data.get("response", "")
            current_calls = data.get("tool_calls", []) or []
            current_response_id = data.get("response_id", current_response_id)
            if not current_calls:
                break

        return reply, all_calls

    def _handle_tool_calls(
        self, tool_calls: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        outputs: list[dict[str, Any]] = []
        decorated_calls: list[dict[str, Any]] = []

        for call in tool_calls:
            operations, call_id = self._extract_apply_patch_operations(call)
            if operations:
                results = []
                for operation in operations:
                    ok, message = self._tool_executor.apply_patch_operation(operation)
                    results.append((ok, message))
                status = "completed" if all(ok for ok, _ in results) else "failed"
                message = "\n".join(msg for _, msg in results)
                tool_name = "apply_patch"
            else:
                status = "failed"
                message = "Error: Unsupported tool call"
                tool_name = call.get("name", "tool")

            if call_id:
                outputs.append(
                    {
                        "type": "apply_patch_call_output",
                        "call_id": call_id,
                        "status": status,
                        "output": message,
                    }
                )

            decorated = dict(call)
            decorated["name"] = tool_name
            decorated["status"] = status
            decorated["result"] = message
            decorated_calls.append(decorated)

        return outputs, decorated_calls

    @staticmethod
    def _extract_apply_patch_operations(
        call: dict[str, Any]
    ) -> tuple[list[dict[str, Any]] | None, str | None]:
        call_id = call.get("call_id") or call.get("id")
        if call.get("type") == "apply_patch_call":
            operation = call.get("operation")
            if operation:
                return [operation], call_id

        if call.get("name") == "apply_patch":
            operation = call.get("operation")
            if operation:
                return [operation], call_id
            arguments = call.get("arguments") or call.get("args") or {}
            patch = arguments.get("patch") if isinstance(arguments, dict) else None
            if patch:
                return ChatScreen._parse_begin_patch(patch), call_id

        return None, call_id

    @staticmethod
    def _parse_begin_patch(patch: str) -> list[dict[str, Any]]:
        operations: list[dict[str, Any]] = []
        lines = patch.splitlines()
        idx = 0
        while idx < len(lines):
            line = lines[idx]
            if line.startswith("*** Add File: "):
                path = line.replace("*** Add File: ", "", 1).strip()
                idx += 1
                content_lines = []
                while idx < len(lines) and not lines[idx].startswith("*** "):
                    if lines[idx].startswith("+"):
                        content_lines.append(lines[idx][1:])
                    idx += 1
                operations.append(
                    {"type": "create_file", "path": path, "diff": "\n".join(content_lines)}
                )
                continue
            if line.startswith("*** Update File: "):
                path = line.replace("*** Update File: ", "", 1).strip()
                idx += 1
                diff_lines = []
                while idx < len(lines) and not lines[idx].startswith("*** "):
                    diff_lines.append(lines[idx])
                    idx += 1
                operations.append(
                    {"type": "update_file", "path": path, "diff": "\n".join(diff_lines)}
                )
                continue
            if line.startswith("*** Delete File: "):
                path = line.replace("*** Delete File: ", "", 1).strip()
                operations.append({"type": "delete_file", "path": path})
            idx += 1
        return operations

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
