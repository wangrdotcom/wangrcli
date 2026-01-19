"""Sort selection modal for DataTable screens."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Static


class SortModal(ModalScreen[dict | None]):
    """Modal to choose a sort column and direction."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("b", "cancel", "Cancel"),
        ("enter", "confirm", "Confirm"),
        ("S", "toggle_direction", "Toggle Direction"),
        ("down,j", "cursor_down", "Down"),
        ("up,k", "cursor_up", "Up"),
    ]

    def __init__(
        self,
        columns: list[tuple[str, str]],
        current_key: str | None,
        sort_reverse: bool,
    ) -> None:
        super().__init__()
        self.columns = columns
        self.sort_reverse = sort_reverse
        self._initial_index = 0
        if current_key:
            keys = [key for key, _label in columns]
            if current_key in keys:
                self._initial_index = keys.index(current_key)

    def compose(self) -> ComposeResult:
        direction = "DESC" if self.sort_reverse else "ASC"
        yield Container(
            Label("Sort by column", classes="sort-modal-title"),
            Static(f"Direction: {direction} (press Shift+S to toggle)", id="sort-direction"),
            ListView(
                *[
                    ListItem(Label(label), id=f"col-{key}")
                    for key, label in self.columns
                ],
                id="sort-list",
            ),
            classes="sort-modal",
        )

    async def on_mount(self) -> None:
        list_view = self.query_one("#sort-list", ListView)
        list_view.index = self._initial_index
        list_view.focus()

    def action_toggle_direction(self) -> None:
        """Toggle sort direction."""
        self.sort_reverse = not self.sort_reverse
        direction = "DESC" if self.sort_reverse else "ASC"
        self.query_one("#sort-direction", Static).update(
            f"Direction: {direction} (press Shift+S to toggle)"
        )

    def action_confirm(self) -> None:
        """Confirm current selection."""
        self._dismiss_with_selection()

    def action_cancel(self) -> None:
        """Cancel selection."""
        self.dismiss(None)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Confirm selection with Enter."""
        event.stop()
        self._dismiss_with_selection()

    def _dismiss_with_selection(self) -> None:
        """Dismiss modal with current selection."""
        list_view = self.query_one("#sort-list", ListView)
        index = list_view.index or 0
        key = self.columns[index][0]
        self.dismiss({"key": key, "reverse": self.sort_reverse})

    def action_cursor_down(self) -> None:
        """Move selection down."""
        list_view = self.query_one("#sort-list", ListView)
        list_view.index = min((list_view.index or 0) + 1, len(self.columns) - 1)

    def action_cursor_up(self) -> None:
        """Move selection up."""
        list_view = self.query_one("#sort-list", ListView)
        list_view.index = max((list_view.index or 0) - 1, 0)
