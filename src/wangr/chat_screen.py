"""Chat screen for Wangr agent."""

import difflib
import logging
from pathlib import Path
from typing import Any

import requests
from agents import apply_diff as agents_apply_diff
from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text
from textual import events
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
        self._pending_file_ops: dict[str, Any] | None = None
        self._auto_approve_chain = False

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
        if self._pending_file_ops:
            normalized = message.lower()
            if normalized not in {"y", "n"}:
                self._show_status_temp("Please enter 'y' or 'n'.")
                return
            decision = normalized == "y"
            event.input.value = ""
            self._append_user_message(message)
            event.input.disabled = True
            self._start_processing()
            self._worker = self.run_worker(
                lambda: self._resolve_pending_request(decision),
                thread=True,
                name="chat_pending",
            )
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
            self._stop_processing()
            response, tool_calls = event.worker.result
            if tool_calls:
                self._show_status_temp(f"Tool calls: {len(tool_calls)}")
            else:
                self._show_status_temp("No tool calls")
            self._append_assistant_message(response, tool_calls)
            if self._pending_file_ops:
                input_box.disabled = True
                self.focus()
            else:
                input_box.disabled = False
                input_box.focus()
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
            pending = data.get("pending_file_ops")
            if pending:
                self._pending_file_ops = pending
                self._auto_approve_chain = False
                prompt = self._prepare_pending_prompt(pending)
                return prompt, []
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

    def _post_chat_continue(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            f"{CHAT_API_URL}/continue",
            json=payload,
            timeout=API_TIMEOUT * 12,
        )
        response.raise_for_status()
        logger.info("Chat API continue response: %s", response.text)
        return response.json()

    def _resolve_pending_request(self, approved: bool) -> tuple[str, list[dict[str, Any]]]:
        pending = self._pending_file_ops
        if not pending:
            return "No pending operations.", []
        response, next_pending, auto_approved = self._resolve_pending(
            pending, approved, self._auto_approve_chain
        )
        self._pending_file_ops = next_pending
        self._auto_approve_chain = auto_approved
        if self._pending_file_ops:
            prompt = self._prepare_pending_prompt(self._pending_file_ops)
            return prompt, []
        return response, []

    def _prepare_pending_prompt(self, pending: dict[str, Any]) -> str:
        preview, approvable, _auto_outputs = self._categorize_patch_ops(pending)
        if preview:
            renderable = Group(Text("Proposed changes:", style="bold"), Syntax(preview, "diff"))
            self._append_assistant_renderable(renderable, [])
        elif approvable:
            self._append_assistant_message("[dim]Proposed changes (no diff preview available).[/dim]", [])
        if approvable:
            return "Apply these changes? Press Y/N."
        return "No approvable changes."

    def on_key(self, event: events.Key) -> None:
        if not self._pending_file_ops:
            return
        if self._worker and self._worker.is_running:
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
        self._worker = self.run_worker(
            lambda: self._resolve_pending_request(approved),
            thread=True,
            name="chat_pending",
        )

    def _resolve_pending(
        self, pending: dict[str, Any], approved: bool, auto_approve_chain: bool
    ) -> tuple[str, dict[str, Any] | None, bool]:
        pending_id = pending.get("id")
        operations = pending.get("operations", [])
        if not pending_id:
            raise ValueError("Missing pending operation id from server response.")

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
                    outputs.extend(self._deny_operations(approvable, "User denied apply_patch operation."))

        data = self._post_chat_continue(
            {"pending_id": pending_id, "tool_outputs": outputs}
        )
        response = data.get("response", "")
        next_pending = data.get("pending_file_ops")
        return response, next_pending, auto_approve_chain or (approved and bool(patch_ops) and not auto_outputs)

    def _execute_read_ops(self, operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results = []
        base_dir = Path.cwd()
        for op in operations:
            call_id = op.get("call_id")
            path = op.get("path", "")
            try:
                content = self._read_local_file(path, base_dir)
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

    def _categorize_patch_ops(
        self, pending: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
        previews = []
        approvable = []
        auto_outputs = []
        base_dir = Path.cwd()

        for op in pending.get("operations", []):
            if op.get("type") != "apply_patch":
                continue
            call_id = op.get("call_id")
            operation = op.get("operation", op)
            op_type = operation.get("type")
            try:
                diff = self._preview_operation(operation, base_dir)
                if diff:
                    previews.append(diff)
                    approvable.append(op)
                elif op_type in {"create_file", "delete_file"}:
                    approvable.append(op)
            except Exception as exc:
                path = operation.get("path", "<unknown>")
                auto_outputs.append({
                    "call_id": call_id,
                    "status": "failed",
                    "output": f"Preview error for {path}: {exc}",
                })

        return "\n\n".join(previews), approvable, auto_outputs

    def _apply_patch_ops(self, operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        return [{
            "call_id": op.get("call_id"),
            "status": "failed",
            "output": reason,
        } for op in operations]

    def _sanitize_diff(self, diff: str) -> str:
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
        return agents_apply_diff(input_text, self._sanitize_diff(diff), mode)

    def _normalize_operation(self, operation: dict[str, Any]) -> dict[str, Any]:
        if "operation" in operation and isinstance(operation["operation"], dict):
            operation = operation["operation"]
        op_type = operation.get("type")
        path = operation.get("path")
        if not op_type or not path:
            raise ValueError("Operation must include 'type' and 'path'.")
        return {"type": op_type, "path": path, "diff": operation.get("diff")}

    def _resolve_path(self, base_dir: Path, path: str) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            raise ValueError("Absolute paths are not allowed.")
        resolved = (base_dir / candidate).resolve()
        if not resolved.is_relative_to(base_dir.resolve()):
            raise ValueError("Path escapes the workspace root.")
        return resolved

    def _preview_operation(self, operation: dict[str, Any], base_dir: Path) -> str:
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

    def _apply_operation(self, operation: dict[str, Any], base_dir: Path) -> tuple[bool, str]:
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

    def _read_local_file(self, path: str, base_dir: Path) -> str:
        resolved = self._resolve_path(base_dir, path)
        return resolved.read_text()

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

    def _append_assistant_renderable(self, renderable: Any, tool_calls: list[dict[str, Any]]) -> None:
        self._entries.append(
            {"role": "assistant", "renderables": [renderable], "tool_calls": tool_calls}
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
                renderables = entry.get("renderables")
                if renderables:
                    for renderable in renderables:
                        log.write(renderable)
                else:
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
