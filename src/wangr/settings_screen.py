"""Settings screen for API key configuration."""

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Static
from textual.worker import Worker

from wangr.settings import (
    clear_api_key,
    get_api_key,
    set_api_key,
    validate_api_key,
)


class SettingsScreen(Screen):
    """Screen for managing settings, including API key."""

    BINDINGS = [
        ("b", "go_back", "Go Back"),
        ("escape", "go_back", "Go Back"),
    ]

    def __init__(self, on_key_validated: callable | None = None) -> None:
        super().__init__()
        self._worker: Worker | None = None
        self._on_key_validated = on_key_validated

    def compose(self) -> ComposeResult:
        yield Footer()
        yield Container(
            Vertical(
                Label("Settings", classes="settings-title"),
                Static("", classes="settings-spacer"),
                Label("API Key", classes="settings-label"),
                Static(
                    "Enter your API key to access the Chat agent.",
                    classes="settings-description",
                ),
                Input(
                    placeholder="Paste your API key here...",
                    id="api-key-input",
                    password=True,
                    classes="settings-input",
                ),
                Static("", id="validation-status", classes="settings-status"),
                Container(
                    Button("Validate & Save", id="btn-validate", variant="primary"),
                    Button("Clear Key", id="btn-clear", variant="warning"),
                    Button("Back", id="btn-back"),
                    classes="settings-buttons",
                ),
                classes="settings-form",
            ),
            id="settings-container",
        )

    async def on_mount(self) -> None:
        """Load existing API key if present."""
        existing_key = get_api_key()
        if existing_key:
            input_widget = self.query_one("#api-key-input", Input)
            input_widget.value = existing_key
            self._set_status("API key loaded from settings.", "info")
        self.query_one("#api-key-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-validate":
            self._start_validation()
        elif event.button.id == "btn-clear":
            self._clear_key()
        elif event.button.id == "btn-back":
            self.action_go_back()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Validate on Enter key."""
        if event.input.id == "api-key-input":
            self._start_validation()

    def action_go_back(self) -> None:
        """Return to previous screen."""
        self.app.pop_screen()

    def _start_validation(self) -> None:
        """Start API key validation."""
        if self._worker and self._worker.is_running:
            return

        api_key = self.query_one("#api-key-input", Input).value.strip()
        if not api_key:
            self._set_status("Please enter an API key.", "error")
            return

        self._set_status("Validating...", "pending")
        self._disable_buttons(True)
        self._worker = self.run_worker(
            lambda: validate_api_key(api_key),
            thread=True,
            name="validate_key",
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle validation result."""
        if event.worker != self._worker:
            return

        if event.state.name == "SUCCESS":
            self._disable_buttons(False)
            is_valid, message = event.worker.result
            if is_valid:
                api_key = self.query_one("#api-key-input", Input).value.strip()
                set_api_key(api_key)
                self._set_status(f"✓ {message}", "success")
                if self._on_key_validated:
                    self._on_key_validated()
            else:
                self._set_status(f"✗ {message}", "error")
        elif event.state.name == "ERROR":
            self._disable_buttons(False)
            self._set_status("Validation failed. Please try again.", "error")

    def _clear_key(self) -> None:
        """Clear the stored API key."""
        clear_api_key()
        self.query_one("#api-key-input", Input).value = ""
        self._set_status("API key cleared.", "info")

    def _set_status(self, message: str, status_type: str = "info") -> None:
        """Update the status message with styling."""
        status_widget = self.query_one("#validation-status", Static)
        if status_type == "error":
            status_widget.update(f"[red]{message}[/red]")
        elif status_type == "success":
            status_widget.update(f"[green]{message}[/green]")
        elif status_type == "pending":
            status_widget.update(f"[yellow]{message}[/yellow]")
        else:
            status_widget.update(f"[dim]{message}[/dim]")

    def _disable_buttons(self, disabled: bool) -> None:
        """Enable or disable form buttons."""
        self.query_one("#btn-validate", Button).disabled = disabled
        self.query_one("#btn-clear", Button).disabled = disabled
        self.query_one("#api-key-input", Input).disabled = disabled
