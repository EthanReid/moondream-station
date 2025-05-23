from textual import events, on, work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Button, Input, Static, RichLog, Label, LoadingIndicator

import io
from contextlib import redirect_stdout

from cli import HypervisorCLI
from config import Config


class KeyLogger(RichLog):
    """Simple logger that records key events."""

    def on_key(self, event: events.Key) -> None:
        self.write(event)


class CaptionForm(Static):
    """Input form for caption mode."""

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Input(placeholder="Image Path", id="image_path_field")
            yield Button("Submit", id="submit_button", variant="success")


class PromptForm(Static):
    """Input form for modes that require a prompt."""

    def __init__(self, placeholder: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.placeholder = placeholder

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Image Path", id="image_path_field")
        with Horizontal():
            yield Input(placeholder=self.placeholder, id="prompt_field")
            yield Button("Submit", id="submit_button", variant="success")


class ResponseCard(Static):
    """Container used to display inference results."""

    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.text = text

    def on_mount(self) -> None:
        self.update(self.text)


class InferPanel(Static):
    """Panel handling all inference interactions."""

    def __init__(self, cli: HypervisorCLI, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cli = cli
        self.mode = "caption"

    def compose(self) -> ComposeResult:
        with Vertical(id="infer_layout"):
            with Horizontal(id="mode_bar"):
                yield Button("Caption", id="caption_button", variant="primary")
                yield Button("Query", id="query_button")
                yield Button("Detect", id="detect_button")
                yield Button("Point", id="point_button")
            with ScrollableContainer(id="response_container"):
                yield LoadingIndicator(id="loading_indicator")
            yield Container(CaptionForm(id="active_form"), id="input_container")

    def on_mount(self) -> None:
        self.query_one("#loading_indicator", LoadingIndicator).display = False

    def _update_buttons(self, active: str) -> None:
        buttons = ["caption_button", "query_button", "detect_button", "point_button"]
        for bid in buttons:
            self.query_one(f"#{bid}").variant = "primary" if bid == active else "default"

    def _set_form(self, form: Static) -> None:
        container = self.query_one("#input_container")
        container.remove_children()
        container.mount(form)

    @on(Button.Pressed, "#caption_button")
    def set_caption(self, event: Button.Pressed) -> None:
        self.mode = "caption"
        self._update_buttons("caption_button")
        self._set_form(CaptionForm())

    @on(Button.Pressed, "#query_button")
    def set_query(self, event: Button.Pressed) -> None:
        self.mode = "query"
        self._update_buttons("query_button")
        self._set_form(PromptForm("Prompt"))

    @on(Button.Pressed, "#detect_button")
    def set_detect(self, event: Button.Pressed) -> None:
        self.mode = "detect"
        self._update_buttons("detect_button")
        self._set_form(PromptForm("Detect"))

    @on(Button.Pressed, "#point_button")
    def set_point(self, event: Button.Pressed) -> None:
        self.mode = "point"
        self._update_buttons("point_button")
        self._set_form(PromptForm("Point"))

    @work(thread=True)
    def _run_inference(self, mode: str, image_path: str, prompt: str | None) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            if mode == "caption":
                self.cli.caption(image_path, stream=False)
            elif mode == "query" and prompt is not None:
                self.cli.query(image_path, prompt, stream=False)
            elif mode == "detect" and prompt is not None:
                self.cli.detect(image_path, prompt)
            elif mode == "point" and prompt is not None:
                self.cli.point(image_path, prompt)
        return buffer.getvalue()

    @on(Button.Pressed, "#submit_button")
    async def handle_submit(self, event: Button.Pressed) -> None:
        image_path = self.query_one("#input_container #image_path_field", Input).value
        prompt = None
        try:
            prompt = self.query_one("#input_container #prompt_field", Input).value
        except Exception:
            prompt = None

        loader = self.query_one("#loading_indicator", LoadingIndicator)
        loader.display = True
        worker = self._run_inference(self.mode, image_path, prompt)
        result = await worker.wait()
        loader.display = False

        container = self.query_one("#response_container")
        loader_widget = self.query_one("#loading_indicator")
        if result:
            await container.mount(ResponseCard(result, classes="response-card"), before=loader_widget)
            container.scroll_end(animate=False)


class MainPanel(Static):
    def __init__(self, cli: HypervisorCLI, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cli = cli

    def compose(self) -> ComposeResult:
        yield InferPanel(self.cli, id="infer_panel")


class LogsPanel(Static):
    def compose(self) -> ComposeResult:
        yield KeyLogger(id="logs_view")


class SettingsPanel(Static):
    def compose(self) -> ComposeResult:
        cfg = Config()
        with ScrollableContainer(id="settings_container"):
            for key, value in cfg.core_config.items():
                yield Label(f"{key}: {value}")


class MoondreamCLI(App):
    CSS_PATH = "moondream-cli.tcss"
    TITLE = "Moondream Station"

    def __init__(self, server_url: str = "http://localhost:2020", **kwargs) -> None:
        super().__init__(**kwargs)
        self.cli = HypervisorCLI(server_url)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main_layout"):
            with Vertical(id="sidebar"):
                yield Button("💬 Infer", id="infer_button", variant="primary")
                yield Button("🗄️  Logs", id="logs_button")
                yield Button("⚙️  Setting", id="setting_button")
            yield Container(id="main_panel")

    def on_mount(self) -> None:
        self.show_infer()

    def _swap_panel(self, panel: Static) -> None:
        main = self.query_one("#main_panel")
        main.remove_children()
        main.mount(panel)

    @on(Button.Pressed, "#infer_button")
    def show_infer(self, event: Button.Pressed | None = None) -> None:
        self.query_one("#infer_button").variant = "primary"
        self.query_one("#logs_button").variant = "default"
        self.query_one("#setting_button").variant = "default"
        self._swap_panel(InferPanel(self.cli, id="infer_panel"))

    @on(Button.Pressed, "#logs_button")
    def show_logs(self, event: Button.Pressed) -> None:
        self.query_one("#infer_button").variant = "default"
        self.query_one("#logs_button").variant = "primary"
        self.query_one("#setting_button").variant = "default"
        self._swap_panel(LogsPanel(id="logs_panel"))

    @on(Button.Pressed, "#setting_button")
    def show_settings(self, event: Button.Pressed) -> None:
        self.query_one("#infer_button").variant = "default"
        self.query_one("#logs_button").variant = "default"
        self.query_one("#setting_button").variant = "primary"
        self._swap_panel(SettingsPanel(id="settings_panel"))


if __name__ == "__main__":
    app = MoondreamCLI()
    app.run()
