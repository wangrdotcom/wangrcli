from pathlib import Path

from textual.app import App
from textual.worker import Worker

from wangr.dashboard_screen import DashboardScreen
from wangr.data import fetch_arbitrage_data, fetch_arbitrage_dex_data, fetch_whales_full_data, fetch_woi_full_data


class WangrApp(App):
    TITLE = "Wangr Terminal"
    CSS_PATH = str(Path(__file__).with_name("dashboard.tcss"))
    BINDINGS = [
        ("q", "quit", "Quit the app"),
    ]

    # Screen transitions for smooth navigation
    ENABLE_COMMAND_PALETTE = False

    def on_mount(self) -> None:
        self.theme = "gruvbox"
        if not hasattr(self, "whales_full_cache"):
            self.whales_full_cache = {}
        if not hasattr(self, "woi_full_cache"):
            self.woi_full_cache = {}
        if not hasattr(self, "arb_cache"):
            self.arb_cache = {}
        self.run_worker(
            fetch_whales_full_data,
            thread=True,
            name="preload_whales_full",
        )
        self.run_worker(
            fetch_woi_full_data,
            thread=True,
            name="preload_woi_full",
        )
        self.run_worker(
            lambda: fetch_arbitrage_data("futures"),
            thread=True,
            name="preload_arb_futures",
        )
        self.run_worker(
            lambda: fetch_arbitrage_data("spot"),
            thread=True,
            name="preload_arb_spot",
        )
        self.run_worker(
            fetch_arbitrage_dex_data,
            thread=True,
            name="preload_arb_dex",
        )
        self.push_screen(DashboardScreen({}))

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state.name != "SUCCESS":
            return
        if event.worker.name == "preload_whales_full":
            if event.worker.result:
                self.whales_full_cache = event.worker.result
        elif event.worker.name == "preload_woi_full":
            if event.worker.result:
                self.woi_full_cache = event.worker.result
        elif event.worker.name == "preload_arb_futures":
            if event.worker.result:
                self.arb_cache["futures"] = event.worker.result
        elif event.worker.name == "preload_arb_spot":
            if event.worker.result:
                self.arb_cache["spot"] = event.worker.result
        elif event.worker.name == "preload_arb_dex":
            if event.worker.result:
                self.arb_cache["dex"] = event.worker.result


def main() -> None:
    app = WangrApp()
    app.run()


if __name__ == "__main__":
    main()
