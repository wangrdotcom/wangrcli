"""Mixin providing file operation logic shared between agent screens."""

import difflib
from pathlib import Path
from typing import Any, Callable

from agents import apply_diff as agents_apply_diff
from rich.console import Group
from rich.text import Text


class FileOpsMixin:
    """
    Mixin for screens that handle pending_file_ops.

    Requires the consuming class to have:
    - self._pending_file_ops: dict | None
    - self._pending_requires_approval: bool
    - self._auto_approve_chain: bool
    - self._entries: list[dict]
    """

    # ------------------------------------------------------------------
    # Diff helpers
    # ------------------------------------------------------------------

    def _sanitize_diff(self, diff: str) -> str:
        lines = []
        for line in diff.splitlines():
            if line.startswith("*** Begin Patch") or line.startswith("*** End Patch"):
                continue
            if (
                line.startswith("*** Update File")
                or line.startswith("*** Add File")
                or line.startswith("*** Delete File")
            ):
                continue
            if line.startswith("diff --git") or line.startswith("index "):
                continue
            if line.startswith("--- ") or line.startswith("+++ "):
                continue
            lines.append(line)
        return "\n".join(lines)

    def _apply_diff(self, input_text: str, diff: str, mode: str = "default") -> str:
        return agents_apply_diff(input_text, self._sanitize_diff(diff), mode)

    def _extract_create_content(self, diff: str) -> str:
        """Extract file content from a create_file diff.

        Strips V4A patch markers and ``+`` line prefixes, matching the
        behaviour of ``_parse_begin_patch`` / ``LocalToolExecutor``.
        """
        if not diff:
            return ""
        sanitized = self._sanitize_diff(diff)
        lines = sanitized.splitlines()
        extracted: list[str] = []
        for line in lines:
            if line.startswith("+"):
                extracted.append(line[1:])
            elif not line.strip():
                extracted.append("")
            else:
                # Non-prefixed, non-empty line — treat as raw content
                extracted.append(line)
        return "\n".join(extracted)

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

    # ------------------------------------------------------------------
    # Operation normalisation & path resolution
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Preview & apply
    # ------------------------------------------------------------------

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
            new_content = self._extract_create_content(op.get("diff") or "")
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
            old_lines, new_lines, fromfile=op["path"], tofile=to_name, lineterm=""
        )
        return "\n".join(diff_lines)

    def _apply_operation(
        self, operation: dict[str, Any], base_dir: Path
    ) -> tuple[bool, str]:
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
                content = self._extract_create_content(op.get("diff") or "")
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

    # ------------------------------------------------------------------
    # Categorise / execute / deny
    # ------------------------------------------------------------------

    def _categorize_patch_ops(
        self, pending: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
        previews: list[str] = []
        approvable: list[dict[str, Any]] = []
        auto_outputs: list[dict[str, Any]] = []
        base_dir = Path.cwd()

        for op in pending.get("operations", []):
            if op.get("type") not in ("apply_patch", "read_file"):
                continue
            if op.get("type") == "read_file":
                continue

            call_id = op.get("call_id")
            operation = op.get("operation", op)
            # Propagate diff from outer level if not in inner operation
            if isinstance(operation, dict) and "diff" not in operation and "diff" in op:
                operation = {**operation, "diff": op["diff"]}
            op_type = operation.get("type")
            try:
                diff = self._preview_operation(operation, base_dir)
                if diff:
                    previews.append(diff)
                if op_type in {"create_file", "update_file", "delete_file"}:
                    approvable.append(op)
            except Exception as exc:
                path = operation.get("path", "<unknown>")
                auto_outputs.append(
                    {
                        "call_id": call_id,
                        "status": "failed",
                        "output": f"Preview error for {path}: {exc}",
                    }
                )

        return "\n\n".join(previews), approvable, auto_outputs

    def _execute_read_ops(
        self, operations: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        base_dir = Path.cwd()
        for op in operations:
            call_id = op.get("call_id")
            path = op.get("path", "")
            try:
                resolved = self._resolve_path(base_dir, path)
                content = resolved.read_text()
                results.append(
                    {"call_id": call_id, "status": "completed", "output": content}
                )
            except Exception as exc:
                results.append(
                    {
                        "call_id": call_id,
                        "status": "failed",
                        "output": f"Error reading file: {exc}",
                    }
                )
        return results

    def _apply_patch_ops(
        self, operations: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        base_dir = Path.cwd()
        for op in operations:
            call_id = op.get("call_id")
            operation = op.get("operation", op)
            # Propagate diff from outer level if not in inner operation
            if isinstance(operation, dict) and "diff" not in operation and "diff" in op:
                operation = {**operation, "diff": op["diff"]}
            success, output = self._apply_operation(operation, base_dir)
            results.append(
                {
                    "call_id": call_id,
                    "status": "completed" if success else "failed",
                    "output": output,
                }
            )
        return results

    def _deny_operations(
        self, operations: list[dict[str, Any]], reason: str
    ) -> list[dict[str, Any]]:
        return [
            {"call_id": op.get("call_id"), "status": "failed", "output": reason}
            for op in operations
        ]

    # ------------------------------------------------------------------
    # Approval prompt
    # ------------------------------------------------------------------

    def _prepare_pending_prompt(self, pending: dict[str, Any]) -> str:
        """Prepare the approval prompt with diff preview.

        Subclasses must implement ``_append_diff_entry(renderable)`` to insert
        the diff renderable into ``_entries`` in their own format.
        """
        preview, approvable, _auto_outputs = self._categorize_patch_ops(pending)
        self._pending_requires_approval = bool(approvable)

        if preview:
            renderable = Group(
                Text("Proposed changes:", style="bold"),
                self._render_diff(preview),
            )
            self._append_diff_entry(renderable)
        elif approvable:
            self._entries.append(
                {
                    "role": "system",
                    "content": "[dim]Proposed changes (no diff preview available).[/dim]",
                }
            )

        if approvable:
            return "Apply these changes? [bold]Y[/bold]/[bold]N[/bold]"
        return ""

    def _append_diff_entry(self, renderable: Any) -> None:
        """Override in subclass to control how diffs are stored in _entries."""
        self._entries.append({"role": "diff", "renderable": renderable})

    # ------------------------------------------------------------------
    # Resolve pending operations (core logic)
    # ------------------------------------------------------------------

    def _resolve_pending_core(
        self,
        pending: dict[str, Any],
        approved: bool,
        auto_approve_chain: bool,
        continue_fn: Callable[
            [str, list[dict[str, Any]]], tuple[str, dict[str, Any] | None]
        ],
    ) -> tuple[str, dict[str, Any] | None, bool]:
        """Execute pending operations and call *continue_fn* to get the next response.

        Parameters
        ----------
        continue_fn:
            ``(pending_id, tool_outputs) -> (response_text, next_pending_or_None)``
        """
        pending_id = pending.get("id")
        operations = pending.get("operations", [])
        if not pending_id:
            raise ValueError("Missing pending operation id.")

        read_ops = [op for op in operations if op.get("type") == "read_file"]
        patch_ops = [op for op in operations if op.get("type") == "apply_patch"]

        outputs: list[dict[str, Any]] = []
        auto_outputs: list[dict[str, Any]] = []

        if read_ops:
            outputs.extend(self._execute_read_ops(read_ops))

        if patch_ops:
            _preview, approvable, auto_outputs = self._categorize_patch_ops(pending)
            outputs.extend(auto_outputs)

            if approvable:
                if approved or auto_approve_chain:
                    outputs.extend(self._apply_patch_ops(approvable))
                else:
                    outputs.extend(
                        self._deny_operations(approvable, "User denied operation.")
                    )

        response, next_pending = continue_fn(pending_id, outputs)
        new_auto = auto_approve_chain or (
            approved and bool(patch_ops) and not auto_outputs
        )
        return response, next_pending, new_auto
