"""Custom animated widgets for the TUI dashboard."""

from textual.widgets import Static
from textual.reactive import reactive


class LoadingSpinner(Static):
    """Animated loading spinner using braille patterns."""

    SPINNER_FRAMES = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]
    SHIMMER_FRAMES = ["░", "▒", "▓", "█", "▓", "▒", "░", " "]

    frame: reactive[int] = reactive(0)
    _timer = None

    def __init__(
        self,
        text: str = "Loading",
        style: str = "spinner",
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._text = text
        self._style = style
        self._frames = self.SPINNER_FRAMES if style == "spinner" else self.SHIMMER_FRAMES

    def on_mount(self) -> None:
        """Start the animation timer."""
        self._timer = self.set_interval(0.1, self._advance_frame)
        self._update_display()

    def on_unmount(self) -> None:
        """Stop the animation timer."""
        if self._timer:
            self._timer.stop()
            self._timer = None

    def _advance_frame(self) -> None:
        """Advance to the next frame."""
        self.frame = (self.frame + 1) % len(self._frames)

    def watch_frame(self, _: int) -> None:
        """Update display when frame changes."""
        self._update_display()

    def _update_display(self) -> None:
        """Update the displayed text."""
        spinner = self._frames[self.frame]
        self.update(f"{spinner} {self._text}")


class PulseDot(Static):
    """Pulsing dot indicator for live data."""

    PULSE_FRAMES = ["●", "◉", "○", "◉"]

    frame: reactive[int] = reactive(0)
    _timer = None

    def __init__(
        self,
        active: bool = True,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._active = active

    def on_mount(self) -> None:
        """Start the pulse timer."""
        if self._active:
            self._timer = self.set_interval(0.5, self._advance_frame)
        self._update_display()

    def on_unmount(self) -> None:
        """Stop the pulse timer."""
        if self._timer:
            self._timer.stop()
            self._timer = None

    def _advance_frame(self) -> None:
        """Advance to the next frame."""
        self.frame = (self.frame + 1) % len(self.PULSE_FRAMES)

    def watch_frame(self, _: int) -> None:
        """Update display when frame changes."""
        self._update_display()

    def _update_display(self) -> None:
        """Update the displayed dot."""
        if self._active:
            self.update(self.PULSE_FRAMES[self.frame])
        else:
            self.update("○")

    def set_active(self, active: bool) -> None:
        """Set the active state."""
        self._active = active
        if active and not self._timer:
            self._timer = self.set_interval(0.5, self._advance_frame)
        elif not active and self._timer:
            self._timer.stop()
            self._timer = None
        self._update_display()


class TickerValue(Static):
    """Value display with tick animation on change."""

    value: reactive[str] = reactive("")
    _previous_value: float = 0.0
    _flash_timer = None

    def __init__(
        self,
        initial_value: str = "",
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.value = initial_value

    def set_value(self, new_value: str, numeric_value: float = None) -> None:
        """Update value with tick animation if changed."""
        self.value = new_value

        if numeric_value is not None:
            if numeric_value > self._previous_value:
                self.add_class("tick-up")
                self.remove_class("tick-down", "tick-neutral")
                self._schedule_flash_reset()
            elif numeric_value < self._previous_value:
                self.add_class("tick-down")
                self.remove_class("tick-up", "tick-neutral")
                self._schedule_flash_reset()
            self._previous_value = numeric_value

    def _schedule_flash_reset(self) -> None:
        """Schedule the flash class to be removed."""
        if self._flash_timer:
            self._flash_timer.stop()
        self._flash_timer = self.set_timer(0.5, self._reset_flash)

    def _reset_flash(self) -> None:
        """Reset the flash animation."""
        self.remove_class("tick-up", "tick-down")
        self.add_class("tick-neutral")
        self._flash_timer = None

    def watch_value(self, new_value: str) -> None:
        """Update display when value changes."""
        self.update(new_value)

    def on_unmount(self) -> None:
        """Cleanup timer."""
        if self._flash_timer:
            self._flash_timer.stop()
            self._flash_timer = None
