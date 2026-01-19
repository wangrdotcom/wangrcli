"""Base screen class for screens with periodic data fetching."""

import logging
from typing import Any, Optional

import requests
from textual.screen import Screen
from textual.worker import Worker

from wangr.config import API_TIMEOUT, FETCH_INTERVAL, FRONTPAGE_API_URL

logger = logging.getLogger(__name__)


class DataFetchingScreen(Screen):
    """Base class for screens that periodically fetch data from API."""

    FETCH_URL: str = FRONTPAGE_API_URL
    FETCH_INTERVAL: float = FETCH_INTERVAL

    def __init__(self, data: dict) -> None:
        """
        Initialize the screen with initial data.

        Args:
            data: Initial dashboard data
        """
        super().__init__()
        self.data = data
        self.update_timer: Optional[Any] = None
        self._current_worker: Optional[Worker] = None

    async def on_mount(self) -> None:
        """Called when screen is mounted. Displays cached data and starts fetching."""
        self._update_display()
        # Defer network fetch until after first render so UI paints immediately.
        self.call_after_refresh(self._schedule_fetch)

    def on_unmount(self) -> None:
        """Called when screen is unmounted. Stops timer and cancels pending workers."""
        if self.update_timer:
            self.update_timer.stop()
            self.update_timer = None
        if self._current_worker and self._current_worker.is_running:
            self._current_worker.cancel()
            self._current_worker = None

    def _schedule_fetch(self) -> None:
        """Schedule periodic data fetching."""
        if not self.is_mounted:
            return
        self._fetch_data()
        self.update_timer = self.set_interval(self.FETCH_INTERVAL, self._fetch_data)

    def _fetch_data(self) -> None:
        """
        Fetch fresh data in background.

        Prevents spawning duplicate workers if previous fetch is still running.
        """
        # Cancel previous worker if still running to prevent memory leak
        if self._current_worker and self._current_worker.is_running:
            logger.debug("Previous worker still running, skipping fetch")
            return

        # Show refresh indicator
        self._on_refresh_start()

        # Spawn new worker with unique name to prevent conflicts
        worker_name = f"data_fetch_{self.__class__.__name__}_{id(self)}"
        self._current_worker = self.run_worker(
            self._fetch_dashboard_data,
            thread=True,
            name=worker_name
        )

    def _on_refresh_start(self) -> None:
        """Called when data refresh starts. Override to show indicator."""
        pass

    def _on_refresh_end(self) -> None:
        """Called when data refresh ends. Override to hide indicator."""
        pass

    def _fetch_dashboard_data(self) -> dict:
        """
        Fetch data from API.

        Returns:
            Dictionary with fetched data, or empty dict on error
        """
        try:
            resp = requests.get(self.FETCH_URL, timeout=API_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch data from {self.FETCH_URL}: {e}")
            return {}
        except ValueError as e:
            logger.error(f"Failed to parse JSON from {self.FETCH_URL}: {e}")
            return {}

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """
        Update display when new data arrives.

        Args:
            event: Worker state change event
        """
        # Only process if this is our current worker
        if event.worker != self._current_worker:
            return

        # Hide refresh indicator
        self._on_refresh_end()

        if event.state.name == "SUCCESS":
            new_data = event.worker.result
            if new_data:
                self._process_new_data(new_data)
                self._update_display()
            else:
                logger.warning("Received empty data from worker")

    def _process_new_data(self, new_data: dict) -> None:
        """
        Process new data received from API.

        Subclasses should override this to extract relevant data.

        Args:
            new_data: Fresh data from API
        """
        self.data = new_data

    def _update_display(self) -> None:
        """
        Update the screen display with current data.

        Subclasses must implement this method.
        """
        raise NotImplementedError("Subclasses must implement _update_display()")

    def action_go_back(self) -> None:
        """Navigate back to previous screen."""
        self.app.pop_screen()
