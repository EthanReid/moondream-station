from textual import events, on
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
    RichLog,
    Input,
)
from textual.screen import Screen
from textual.message import Message

from cli import HypervisorCLI
from config import Config


class KeyLogger(RichLog):
    def on_key(self, event: events.Key) -> None:
        self.write(event)


class CaptionInput(Static):
    def compose(self):
        yield Input(placeholder="Image Path", id="image_path_field")


class QueryInput(Static):
    def compose(self):
        yield Input(placeholder="Image Path", id="image_path_field")
        yield Input(placeholder="Prompt", id="prompt_field")


class DetectInput(Static):
    def compose(self):
        yield Input(placeholder="Image Path", id="image_path_field")
        yield Input(placeholder="Detect", id="prompt_field")


class PointInput(Static):
    def compose(self):
        yield Input(placeholder="Image Path", id="image_path_field")
        yield Input(placeholder="Point", id="prompt_field")


class Infer(Static):
    def compose(self) -> ComposeResult:
        with Horizontal(
            id="capibility_horizontal_group",
        ):
            yield Button("Caption", id="caption_button", variant="primary")
            yield Button("Query", id="query_button")
            yield Button("Detect", id="detect_button")
            yield Button("Point", id="point_button")
        with Container(id="capibility_input_container", classes="bottom"):
            yield Horizontal(CaptionInput())

    @on(Button.Pressed, "#caption_button")
    def handle_caption_button(self, event: Button.Pressed) -> None:
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
        self.query_one("#query_button").variant = "default"
        self.query_one("#caption_button").variant = "default"
        self.query_one("#detect_button").variant = "default"
        self.query_one("#point_button").variant = "primary"

        # Replace the content in the input container
        input_container = self.query_one("#capibility_input_container")
        input_container.remove_children()
        input_container.mount(PointInput())


class MainPanel(Static):
    def compose(self):
        yield Infer(id="infer_panel")


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

    def compose(self):
        yield Header()

        with Horizontal(id="main-layout"):
            with Vertical(id="sidebar"):
                yield Button("💬 Infer", id="infer_button", variant="primary")
                yield Button("🗄️  Logs", id="logs_button")
                yield Button("⚙️  Setting", id="setting_button")
            yield MainPanel(id="main_panel")

    @on(Button.Pressed, "#infer_button")
    def show_infer(self, event: Button.Pressed) -> None:
        self.query_one("#infer_button").variant = "primary"
        self.query_one("#logs_button").variant = "default"
        self.query_one("#setting_button").variant = "default"
        main = self.query_one("#main_panel")
        main.remove_children()
        main.mount(Infer(id="infer_panel"))

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
