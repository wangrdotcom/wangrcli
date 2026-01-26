"""Local tool executor for AI-driven file operations."""

from pathlib import Path
from typing import Any
import logging

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 1_000_000  # 1MB
MAX_LINES = 2000


class LocalToolExecutor:
    """Executes file operation tools locally."""

    def __init__(self, working_directory: str = ".") -> None:
        self.cwd = Path(working_directory).resolve()

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool and return the result as a string."""
        method = getattr(self, f"_execute_{tool_name}", None)
        if not method:
            return f"Error: Unknown tool '{tool_name}'"

        try:
            return method(**arguments)
        except Exception as e:
            logger.exception(f"Tool execution error: {tool_name}")
            return f"Error: {e}"

    def _resolve_path(self, path: str) -> Path:
        """Resolve path relative to working directory."""
        p = Path(path)
        if p.is_absolute():
            return p
        return self.cwd / p

    def _is_safe_path(self, path: Path) -> bool:
        """Ensure path is within allowed directories."""
        try:
            resolved = path.resolve()
            resolved.relative_to(self.cwd)
            return True
        except ValueError:
            return False

    def _execute_read_file(
        self, path: str, offset: int = 0, limit: int = MAX_LINES
    ) -> str:
        """Read file with line numbers."""
        file_path = self._resolve_path(path)
        if not self._is_safe_path(file_path):
            return f"Error: Path outside working directory: {path}"

        if not file_path.exists():
            return f"Error: File not found: {path}"

        if not file_path.is_file():
            return f"Error: Not a file: {path}"

        # Check file size
        try:
            size = file_path.stat().st_size
            if size > MAX_FILE_SIZE:
                return f"Error: File too large ({size:,} bytes, max {MAX_FILE_SIZE:,})"
        except OSError as e:
            return f"Error: Cannot access file: {e}"

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"Error: Cannot read binary file: {path}"

        lines = content.splitlines()
        total_lines = len(lines)

        # Clamp offset and limit
        offset = max(0, min(offset, total_lines))
        limit = min(limit, MAX_LINES)
        selected = lines[offset : offset + limit]

        # Format with line numbers
        numbered = "\n".join(
            f"{i + offset + 1:>6}| {line}" for i, line in enumerate(selected)
        )

        header = f"File: {path} ({total_lines} lines)"
        if offset > 0 or total_lines > offset + limit:
            end_line = min(offset + limit, total_lines)
            header += f" [showing lines {offset + 1}-{end_line}]"

        return f"{header}\n{numbered}"

    def _execute_edit_file(
        self, path: str, old_string: str, new_string: str
    ) -> str:
        """Edit file by replacing old_string with new_string."""
        file_path = self._resolve_path(path)
        if not self._is_safe_path(file_path):
            return f"Error: Path outside working directory: {path}"

        if not file_path.exists():
            return f"Error: File not found: {path}"

        if not file_path.is_file():
            return f"Error: Not a file: {path}"

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"Error: Cannot read binary file: {path}"

        # Check for exact match
        count = content.count(old_string)
        if count == 0:
            # Provide helpful context
            preview = old_string[:50] + "..." if len(old_string) > 50 else old_string
            return f"Error: old_string not found in {path}. Looking for: {repr(preview)}"
        if count > 1:
            return f"Error: old_string found {count} times in {path}. Must be unique. Add more surrounding context."

        # Perform replacement
        new_content = content.replace(old_string, new_string, 1)
        file_path.write_text(new_content, encoding="utf-8")

        # Report what changed
        old_lines = old_string.count("\n") + 1
        new_lines = new_string.count("\n") + 1
        return f"Successfully edited {path} (replaced {old_lines} lines with {new_lines} lines)"

    def _execute_write_file(self, path: str, content: str) -> str:
        """Write content to file."""
        file_path = self._resolve_path(path)

        # Safety check for path traversal
        if not self._is_safe_path(file_path):
            return f"Error: Path outside working directory: {path}"

        # Create parent directories if needed
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return f"Error: Cannot create directory: {e}"

        try:
            file_path.write_text(content, encoding="utf-8")
        except OSError as e:
            return f"Error: Cannot write file: {e}"

        lines = content.count("\n") + 1 if content else 0
        return f"Successfully wrote {path} ({lines} lines)"

    def _execute_list_files(
        self, pattern: str = "*", path: str = "."
    ) -> str:
        """List files matching glob pattern."""
        search_path = self._resolve_path(path)
        if not self._is_safe_path(search_path):
            return f"Error: Path outside working directory: {path}"

        if not search_path.exists():
            return f"Error: Directory not found: {path}"

        if not search_path.is_dir():
            return f"Error: Not a directory: {path}"

        try:
            matches = list(search_path.glob(pattern))
        except Exception as e:
            return f"Error: Invalid glob pattern: {e}"

        # Sort: directories first, then files, alphabetically
        matches.sort(key=lambda p: (p.is_file(), p.name.lower()))

        if not matches:
            return f"No files matching '{pattern}' in {path}"

        result = [f"Files matching '{pattern}' in {path}:"]
        max_results = 100

        for match in matches[:max_results]:
            try:
                relative = match.relative_to(search_path)
            except ValueError:
                relative = match.name

            if match.is_dir():
                result.append(f"  [dir]  {relative}/")
            else:
                # Show file size
                try:
                    size = match.stat().st_size
                    if size >= 1_000_000:
                        size_str = f"{size / 1_000_000:.1f}M"
                    elif size >= 1_000:
                        size_str = f"{size / 1_000:.1f}K"
                    else:
                        size_str = f"{size}B"
                    result.append(f"  {size_str:>6}  {relative}")
                except OSError:
                    result.append(f"         {relative}")

        if len(matches) > max_results:
            result.append(f"  ... and {len(matches) - max_results} more")

        return "\n".join(result)

    def apply_patch_operation(self, operation: dict[str, Any]) -> tuple[bool, str]:
        """Apply an apply_patch operation and return (success, message)."""
        op_type = operation.get("type")
        path = operation.get("path")
        if not op_type or not path:
            return False, "Error: Missing operation type or path"

        file_path = self._resolve_path(path)
        if not self._is_safe_path(file_path):
            return False, f"Error: Path outside working directory: {path}"

        if op_type == "create_file":
            if file_path.exists():
                return False, f"Error: File already exists: {path}"
            diff = operation.get("diff", "")
            try:
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(diff, encoding="utf-8")
            except OSError as exc:
                return False, f"Error: Cannot create file: {exc}"
            return True, f"Created {path}"

        if op_type == "update_file":
            if not file_path.exists():
                return False, f"Error: File not found: {path}"
            if not file_path.is_file():
                return False, f"Error: Not a file: {path}"
            try:
                content = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return False, f"Error: Cannot read binary file: {path}"
            diff = operation.get("diff", "")
            ok, result = self._apply_v4a_diff(content, diff)
            if not ok:
                return False, result
            try:
                file_path.write_text(result, encoding="utf-8")
            except OSError as exc:
                return False, f"Error: Cannot write file: {exc}"
            return True, f"Updated {path}"

        if op_type == "delete_file":
            if not file_path.exists():
                return False, f"Error: File not found: {path}"
            if not file_path.is_file():
                return False, f"Error: Not a file: {path}"
            try:
                file_path.unlink()
            except OSError as exc:
                return False, f"Error: Cannot delete file: {exc}"
            return True, f"Deleted {path}"

        return False, f"Error: Unsupported operation type: {op_type}"

    def _apply_v4a_diff(self, content: str, diff: str) -> tuple[bool, str]:
        """Apply a V4A-style diff to content and return (success, new_content_or_error)."""
        if not diff:
            return False, "Error: Empty diff"

        diff_lines = diff.splitlines()
        if not any(line.startswith("@@") for line in diff_lines):
            return False, "Error: Unsupported diff format (missing @@ hunk headers)"

        hunks: list[list[str]] = []
        current: list[str] = []
        for line in diff_lines:
            if line.startswith("@@"):
                if current:
                    hunks.append(current)
                    current = []
                continue
            if line.startswith("\\ No newline at end of file"):
                continue
            current.append(line)
        if current:
            hunks.append(current)

        new_lines = content.splitlines()
        for hunk in hunks:
            old_chunk = [line[1:] for line in hunk if line.startswith(" ") or line.startswith("-")]
            new_chunk = [line[1:] for line in hunk if line.startswith(" ") or line.startswith("+")]
            if not old_chunk:
                return False, "Error: Hunk has no context to match"
            matches = self._find_sublist(new_lines, old_chunk)
            if not matches:
                return False, "Error: Hunk context not found"
            if len(matches) > 1:
                return False, "Error: Hunk context is not unique"
            start = matches[0]
            new_lines = new_lines[:start] + new_chunk + new_lines[start + len(old_chunk):]

        new_content = "\n".join(new_lines)
        if content.endswith("\n") and not new_content.endswith("\n"):
            new_content += "\n"
        return True, new_content

    @staticmethod
    def _find_sublist(haystack: list[str], needle: list[str]) -> list[int]:
        if not needle:
            return []
        indices: list[int] = []
        max_start = len(haystack) - len(needle)
        for idx in range(max_start + 1):
            if haystack[idx:idx + len(needle)] == needle:
                indices.append(idx)
        return indices
