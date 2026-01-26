"""Shared mixins for DataTable navigation and sorting."""

from __future__ import annotations

from typing import Any

from textual import events
from textual.widgets import DataTable

from wangr.sort_modal import SortModal


class TableNavigationMixin:
    """Shared keyboard navigation for a DataTable."""

    TABLE_SELECTOR: str = ""
    _pending_g: bool = False
    _g_timer = None

    def _table(self) -> DataTable:
        return self.query_one(self.TABLE_SELECTOR, DataTable)

    def action_cursor_down(self) -> None:
        self._table().action_cursor_down()

    def action_cursor_up(self) -> None:
        self._table().action_cursor_up()

    def action_page_down(self) -> None:
        self._table().action_page_down()

    def action_page_up(self) -> None:
        self._table().action_page_up()

    def action_cursor_top(self) -> None:
        table = self._table()
        if table.row_count > 0:
            table.move_cursor(row=0)

    def action_cursor_bottom(self) -> None:
        table = self._table()
        if table.row_count > 0:
            table.move_cursor(row=table.row_count - 1)

    def _clear_pending_g(self) -> None:
        self._pending_g = False
        if self._g_timer:
            self._g_timer.stop()
            self._g_timer = None

    def _handle_gg(self, event: events.Key, *, require_table_id: str | None = None) -> bool:
        if event.key != "g":
            self._clear_pending_g()
            return False
        if require_table_id:
            focused = self.focused
            if not isinstance(focused, DataTable) or focused.id != require_table_id:
                return False
        event.prevent_default()
        if self._pending_g:
            self._pending_g = False
            if self._g_timer:
                self._g_timer.stop()
                self._g_timer = None
            self.action_cursor_top()
        else:
            self._pending_g = True
            if self._g_timer:
                self._g_timer.stop()
            self._g_timer = self.set_timer(0.5, self._clear_pending_g)
        return True

    def on_key(self, event: events.Key) -> None:
        if self._handle_gg(event):
            return
        super_method = getattr(super(), "on_key", None)
        if callable(super_method):
            super_method(event)


class SortableTableMixin(TableNavigationMixin):
    """Shared sorting logic for a DataTable."""

    SORT_COLUMNS: list[tuple[str, str]] = []

    def _refresh_table(self) -> None:
        raise NotImplementedError

    def action_sort_by_column(self) -> None:
        self.app.push_screen(
            SortModal(self.SORT_COLUMNS, self.sort_column, self.sort_reverse),
            self._on_sort_selected,
        )

    def _on_sort_selected(self, result: dict | None) -> None:
        if not result:
            return
        self.sort_column = result.get("key")
        self.sort_reverse = result.get("reverse", self.sort_reverse)
        self._refresh_table()

    def action_toggle_sort_direction(self) -> None:
        if self.sort_column is None and self.SORT_COLUMNS:
            self.sort_column = self.SORT_COLUMNS[0][0]
        self.sort_reverse = not self.sort_reverse
        self._refresh_table()
