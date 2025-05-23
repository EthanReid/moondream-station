from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Button, Input, LoadingIndicator, RichLog

from contextlib import redirect_stdout
import io

from cli import HypervisorCLI


class MinimalCLI(App):
    """A simplified interface for Moondream Station."""

    CSS_PATH = "minimal-cli.tcss"
    TITLE = "Moondream Minimal"

    def __init__(self, server_url: str = "http://localhost:2020", **kwargs) -> None:
        super().__init__(**kwargs)
        self.cli = HypervisorCLI(server_url)
        self.mode = "caption"

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="layout"):
            with ScrollableContainer(id="responses"):
                yield RichLog(id="log")
                yield LoadingIndicator(id="loader")
            with Horizontal(id="modes"):
                yield Button("Caption", id="caption_button", variant="primary")
                yield Button("Query", id="query_button")
                yield Button("Detect", id="detect_button")
                yield Button("Point", id="point_button")
            with Horizontal(id="inputs"):
                yield Input(placeholder="Image path", id="image_field")
                yield Input(placeholder="Prompt (optional)", id="prompt_field")
                yield Button("Run", id="run_button", variant="success")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#loader").display = False

    def _set_active_mode(self, active: str) -> None:
        for mode in ["caption", "query", "detect", "point"]:
            button = self.query_one(f"#{mode}_button", Button)
            button.variant = "primary" if mode == active else "default"
        self.mode = active

    @on(Button.Pressed, "#caption_button")
    def choose_caption(self) -> None:
        self._set_active_mode("caption")

    @on(Button.Pressed, "#query_button")
    def choose_query(self) -> None:
        self._set_active_mode("query")

    @on(Button.Pressed, "#detect_button")
    def choose_detect(self) -> None:
        self._set_active_mode("detect")

    @on(Button.Pressed, "#point_button")
    def choose_point(self) -> None:
        self._set_active_mode("point")

    @work(thread=True)
    def _run_inference(self, mode: str, image_path: str, prompt: str | None) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            if mode == "caption":
                self.cli.caption(image_path, stream=False)
            elif mode == "query" and prompt:
                self.cli.query(image_path, prompt, stream=False)
            elif mode == "detect" and prompt:
                self.cli.detect(image_path, prompt)
            elif mode == "point" and prompt:
                self.cli.point(image_path, prompt)
        return buffer.getvalue()

    @on(Button.Pressed, "#run_button")
    async def handle_run(self) -> None:
        image = self.query_one("#image_field", Input).value
        prompt = self.query_one("#prompt_field", Input).value or None
        loader = self.query_one("#loader")
        log = self.query_one("#log")
        loader.display = True
        worker = self._run_inference(self.mode, image, prompt)
        result = await worker.wait()
        loader.display = False
        if result:
            log.write(result)
            log.scroll_end(animate=False)


if __name__ == "__main__":
    app = MinimalCLI()
    app.run()
