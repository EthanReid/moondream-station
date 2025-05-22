from textual import events, on, work
from textual.app import App, ComposeResult
from textual.containers import (
    Container,
    Horizontal,
    Vertical,
    ScrollableContainer,
    VerticalGroup,
)
from textual.widgets import (
    Header,
    Footer,
    Static,
    Button,
    Select,
    Label,
    LoadingIndicator,
    Input,
    RichLog,
)
from textual.screen import Screen
from textual.message import Message

import io
from contextlib import redirect_stdout

from cli import HypervisorCLI
from config import Config


class KeyLogger(RichLog):
    def on_key(self, event: events.Key) -> None:
        self.write(event)


class CaptionInput(Static):
    def compose(self):
        with Horizontal():
            yield Button("Submit", id="submit_button", variant="success")
            yield Input(placeholder="Image Path", id="image_path_field")


class QueryInput(Static):
    def compose(self):
        yield Input(placeholder="Image Path", id="image_path_field")
        with Horizontal():
            yield Button("Submit", id="submit_button", variant="success")
            yield Input(placeholder="Prompt", id="prompt_field")


class DetectInput(Static):
    def compose(self):
        yield Input(placeholder="Image Path", id="image_path_field")
        with Horizontal():
            yield Button("Submit", id="submit_button", variant="success")
            yield Input(placeholder="Detect", id="prompt_field")


class PointInput(Static):
    def compose(self):
        yield Input(placeholder="Image Path", id="image_path_field")
        with Horizontal():
            yield Button("Submit", id="submit_button", variant="success")
            yield Input(placeholder="Point", id="prompt_field")


class ResponseCard(Static):
    """Simple container used to display inference results."""

    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.text = text

    def on_mount(self) -> None:
        self.update(self.text)


class Infer(Static):
    def __init__(self, cli: HypervisorCLI, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cli = cli
        self.mode = "caption"

    def compose(self) -> ComposeResult:
        with Vertical(id="infer_layout"):
            with Horizontal(id="capibility_horizontal_group"):
                yield Button("Caption", id="caption_button", variant="primary")
                yield Button("Query", id="query_button")
                yield Button("Detect", id="detect_button")
                yield Button("Point", id="point_button")
            with ScrollableContainer(id="response_container"):
                yield LoadingIndicator(id="loading_indicator")
            yield Container(id="capibility_input_container", classes="bottom")

    def on_mount(self) -> None:
        """Mount the default input on start so layout positions correctly."""
        input_container = self.query_one("#capibility_input_container")
        input_container.mount(CaptionInput())
        # hide loading indicator initially
        self.query_one("#loading_indicator").display = False

    @on(Button.Pressed, "#caption_button")
    def handle_caption_button(self, event: Button.Pressed) -> None:
        self.mode = "caption"
        self.query_one("#caption_button").variant = "primary"
        self.query_one("#query_button").variant = "default"
        self.query_one("#detect_button").variant = "default"
        self.query_one("#point_button").variant = "default"

        # Replace the content in the input container
        input_container = self.query_one("#capibility_input_container")
        input_container.remove_children()
        input_container.mount(CaptionInput())

    @on(Button.Pressed, "#query_button")
    def handle_query_button(self, event: Button.Pressed) -> None:
        self.mode = "query"
        self.query_one("#caption_button").variant = "default"
        self.query_one("#query_button").variant = "primary"
        self.query_one("#detect_button").variant = "default"
        self.query_one("#point_button").variant = "default"

        # Replace the content in the input container
        input_container = self.query_one("#capibility_input_container")
        input_container.remove_children()
        input_container.mount(QueryInput())

    @on(Button.Pressed, "#detect_button")
    def handle_detect_button(self, event: Button.Pressed) -> None:
        self.mode = "detect"
        self.query_one("#caption_button").variant = "default"
        self.query_one("#query_button").variant = "default"
        self.query_one("#detect_button").variant = "primary"
        self.query_one("#point_button").variant = "default"

        # Replace the content in the input container
        input_container = self.query_one("#capibility_input_container")
        input_container.remove_children()
        input_container.mount(DetectInput())

    @on(Button.Pressed, "#point_button")
    def handle_point_button(self, event: Button.Pressed) -> None:
        self.mode = "point"
        self.query_one("#query_button").variant = "default"
        self.query_one("#caption_button").variant = "default"
        self.query_one("#detect_button").variant = "default"
        self.query_one("#point_button").variant = "primary"

        # Replace the content in the input container
        input_container = self.query_one("#capibility_input_container")
        input_container.remove_children()
        input_container.mount(PointInput())

    @work(thread=True)
    def _run_inference(self, mode: str, image_path: str, prompt: str | None) -> str:
        """Run inference command and capture output."""
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
    async def handle_submit_button(self, event: Button.Pressed) -> None:
        image_input = self.query_one("#capibility_input_container #image_path_field", Input)
        image_path = image_input.value
        prompt_value = None
        try:
            prompt_value = self.query_one("#capibility_input_container #prompt_field", Input).value
        except Exception:
            prompt_value = None

        loader = self.query_one("#loading_indicator")
        loader.display = True

        worker = self._run_inference(self.mode, image_path, prompt_value)
        result = await worker.wait()
        loader.display = False

        container = self.query_one("#response_container", ScrollableContainer)
        if result:
            container.mount(ResponseCard(result, classes="response-card"), before=loader)
        container.scroll_end(animate=False)


class MainPanel(Static):
    def __init__(self, cli: HypervisorCLI, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cli = cli

    def compose(self):
        yield Infer(self.cli, id="infer_panel")


class LogsPanel(Static):
    def compose(self):
        yield KeyLogger(id="logs_view")


class SettingsPanel(Static):
    def compose(self):
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

    def compose(self):
        yield Header()

        with Horizontal(id="main-layout"):
            with Vertical(id="sidebar"):
                yield Button("💬 Infer", id="infer_button", variant="primary")
                yield Button("🗄️  Logs", id="logs_button")
                yield Button("⚙️  Setting", id="setting_button")
            yield MainPanel(self.cli, id="main_panel")

    @on(Button.Pressed, "#infer_button")
    def show_infer(self, event: Button.Pressed) -> None:
        self.query_one("#infer_button").variant = "primary"
        self.query_one("#logs_button").variant = "default"
        self.query_one("#setting_button").variant = "default"
        main = self.query_one("#main_panel")
        main.remove_children()
        main.mount(Infer(self.cli, id="infer_panel"))

    @on(Button.Pressed, "#logs_button")
    def show_logs(self, event: Button.Pressed) -> None:
        self.query_one("#infer_button").variant = "default"
        self.query_one("#logs_button").variant = "primary"
        self.query_one("#setting_button").variant = "default"
        main = self.query_one("#main_panel")
        main.remove_children()
        main.mount(LogsPanel(id="logs_panel"))

    @on(Button.Pressed, "#setting_button")
    def show_settings(self, event: Button.Pressed) -> None:
        self.query_one("#infer_button").variant = "default"
        self.query_one("#logs_button").variant = "default"
        self.query_one("#setting_button").variant = "primary"
        main = self.query_one("#main_panel")
        main.remove_children()
        main.mount(SettingsPanel(id="settings_panel"))


if __name__ == "__main__":
    app = MoondreamCLI()
    app.run()
