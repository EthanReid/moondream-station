import os
import sys
import shlex
import asyncio
import time  # For polling logic in admin commands

# Adjust sys.path to allow imports from parent and sibling directories
# Assumes moondream_tui.py is in app/textual_cli/
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)  # 'app' directory

if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

hypervisor_dir = os.path.join(parent_dir, "hypervisor")
if hypervisor_dir not in sys.path:
    sys.path.insert(0, hypervisor_dir)

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll, Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Input, RichLog, Button, Static
from textual.reactive import reactive
from textual.binding import Binding
from textual import work

# Imports from the moondream_cli library
from moondream_cli.cli import HypervisorCLI, VERSION as CLI_VERSION
from moondream_cli.utils.image import load_image
from moondream_cli.formatters import (
    MOONDREAM_BANNER,
    model_commands_box,
    admin_commands_box,
)
from config import (
    Config,
)  # For accessing config if needed, though HypervisorCLI handles most


class MoondreamTUI(App):
    TITLE = "Moondream Station TUI"
    CSS_PATH = "moondream_tui.css"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear_log", "Clear Log", show=True),
    ]

    def __init__(self, server_url="http://localhost:2020", **kwargs):
        super().__init__(**kwargs)
        self.cli = HypervisorCLI(server_url)
        self.config = Config()  # For direct config access if needed

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-app-container"):
            with Vertical(
                id="model-picker-panel", scrollable=True
            ):  # Changed from VerticalScroll
                yield Static("Loading models...", id="model-picker-content")
            with Vertical(id="inference-panel"):
                with Horizontal(id="action-buttons-panel"):
                    yield Button("Caption", id="btn_caption", variant="primary")
                    yield Button("Query", id="btn_query", variant="primary")
                    yield Button("Detect", id="btn_detect", variant="success")
                    yield Button("Point", id="btn_point", variant="success")
                yield RichLog(highlight=True, markup=True, id="output_log", wrap=True)
                yield Static(
                    id="streaming_line_display", markup=True, classes="-hidden"
                )
                yield Input(
                    placeholder="Enter command or use buttons above",
                    id="command_input",
                )
        yield Footer()

    async def on_mount(self) -> None:
        """Called when app starts."""
        log = self.query_one("#output_log", RichLog)
        log.write(MOONDREAM_BANNER)
        log.write(f"Moondream CLI Version: {CLI_VERSION}")
        log.write(f"Hypervisor Server: {self.cli.server_url}")
        log.write("Welcome to Moondream Station TUI!")
        log.write("Use buttons for actions or type 'help' for commands.")

        self.query_one("#command_input", Input).focus()

        # Perform an initial health check
        await self.handle_command_submission("health", silent=True)
        # Populate model list
        self.admin_get_models([])  # Call the worker method

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        command_text = event.value.strip()
        log = self.query_one("#output_log", RichLog)

        if command_text:  # Only log if there's actual command text
            log.write(f"[bold cyan]> {command_text}[/]")

        event.input.value = ""  # Clear input

        if not command_text:
            return

        await self.handle_command_submission(command_text)
        log.scroll_end(animate=True, duration=0.1)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        command_input = self.query_one("#command_input", Input)
        log = self.query_one("#output_log", RichLog)

        button_id = event.button.id
        if button_id == "btn_caption":
            command_input.value = "caption YOUR_IMAGE_PATH "
            log.write(
                "[italic]Hint: Replace YOUR_IMAGE_PATH and press Enter, or add options.[/italic]"
            )
        elif button_id == "btn_query":
            command_input.value = 'query "YOUR_QUESTION" YOUR_IMAGE_PATH '
            log.write(
                "[italic]Hint: Replace YOUR_QUESTION, YOUR_IMAGE_PATH and press Enter, or add options.[/italic]"
            )
        elif button_id == "btn_detect":
            command_input.value = "detect YOUR_OBJECT YOUR_IMAGE_PATH "
            log.write(
                "[italic]Hint: Replace YOUR_OBJECT, YOUR_IMAGE_PATH and press Enter.[/italic]"
            )
        elif button_id == "btn_point":
            command_input.value = "point YOUR_OBJECT YOUR_IMAGE_PATH "
            log.write(
                "[italic]Hint: Replace YOUR_OBJECT, YOUR_IMAGE_PATH and press Enter.[/italic]"
            )

        command_input.focus()

    async def handle_command_submission(self, command_text: str, silent: bool = False):
        log = self.query_one("#output_log", RichLog)
        try:
            parts = shlex.split(command_text)
            command = parts[0].lower()
            args = parts[1:]
        except ValueError:
            if not silent:
                log.write("[bold red]Error: Invalid command syntax (check quotes).[/]")
            return

        # Command dispatching
        if command == "help":
            await self.command_help(args)
        elif command == "caption":
            self.command_caption(args)
        elif command == "query":
            self.command_query(args)
        elif command == "detect":
            self.command_detect(args)
        elif command == "point":
            self.command_point(args)
        elif command == "health":
            self.command_health(args, silent=silent)
        elif command == "admin":
            await self.command_admin(args)
        elif command == "clear" or command == "cls":
            self.action_clear_log()
        elif command == "exit" or command == "quit":
            self.exit()
        else:
            if not silent:
                log.write(f"Unknown command: {command}. Type 'help'.")
        if not silent:  # Ensure input is focused after command unless silent
            self.query_one("#command_input", Input).focus()

    async def command_help(self, args: list):
        log = self.query_one("#output_log", RichLog)
        if not args:
            log.write("\\n[bold]Moondream TUI Command Help[/bold]")
            log.write(model_commands_box())  # From formatters.py
            log.write(
                "\\nType 'help \\[command\\]' for more information on a specific command."
            )
            log.write("For admin commands, type 'admin' or 'help admin'.")
        else:
            topic = args[0].lower()
            if topic == "caption":
                log.write(
                    "Usage: caption IMAGE_PATH \\[--length short|normal|long\\] \\[--no-stream\\] \\[--max-tokens N\\]"
                )
            elif topic == "query":
                log.write(
                    "Usage: query QUESTION IMAGE_PATH \\[--no-stream\\] \\[--max-tokens N\\]"
                )
            elif topic == "detect":
                log.write("Usage: detect OBJECT IMAGE_PATH")
            elif topic == "point":
                log.write("Usage: point OBJECT IMAGE_PATH")
            elif topic == "health":
                log.write("Usage: health (Checks server health)")
            elif topic == "admin":
                log.write(admin_commands_box())
            else:
                log.write(f"No detailed help available for: {topic}")

    @work(exclusive=True, thread=True)
    async def command_health(self, args: list, silent: bool = False):
        log = self.query_one("#output_log", RichLog)
        if not silent:
            self.call_from_thread(log.write, "Checking server health...")
        try:
            result = self.cli.admin_commands._make_request(
                "GET", "/v1/health", silent=silent
            )
            if result:
                if not silent:
                    self.call_from_thread(
                        log.write, f"  Server status: {result.get('status', 'unknown')}"
                    )
                    self.call_from_thread(
                        log.write,
                        f"  Hypervisor: {result.get('hypervisor', 'unknown')}",
                    )
                    self.call_from_thread(
                        log.write,
                        f"  Inference server: {result.get('inference_server', 'unknown')}",
                    )
                    self.call_from_thread(
                        log.write, f"  Timestamp: {result.get('timestamp', 'unknown')}"
                    )
            elif not silent:
                self.call_from_thread(
                    log.write,
                    "[bold red]Failed to get health status or server unreachable.[/]",
                )
        except Exception as e:
            if not silent:
                self.call_from_thread(
                    log.write, f"[bold red]Error checking health: {e}[/]"
                )

    def _parse_inference_args(self, args: list, require_question: bool = False):
        """Helper to parse common arguments for caption and query."""
        parsed_args = {
            "image_path": None,
            "question": None,
            "length": "normal",
            "stream": True,
            "max_tokens": 500,
        }

        pos_args_count = 0
        i = 0
        while i < len(args):
            arg = args[i]
            if arg.startswith("--"):
                if arg == "--no-stream":
                    parsed_args["stream"] = False
                elif arg == "--length" and i + 1 < len(args):
                    parsed_args["length"] = args[i + 1]
                    i += 1
                elif arg == "--max-tokens" and i + 1 < len(args):
                    try:
                        parsed_args["max_tokens"] = int(args[i + 1])
                        i += 1
                    except ValueError:
                        raise ValueError(f"Invalid max_tokens value: {args[i+1]}")
                else:
                    raise ValueError(f"Unknown option: {arg}")
            else:  # Positional arguments
                if require_question:
                    if pos_args_count == 0:  # Question
                        if parsed_args["question"] is None:
                            parsed_args["question"] = (
                                ""  # Initialize if it's the first part of a multi-word question
                            )
                        parsed_args["question"] += (
                            " " if parsed_args["question"] else ""
                        ) + arg
                    elif pos_args_count == 1:  # Image path after question
                        parsed_args["image_path"] = arg
                        pos_args_count += 1  # To prevent further positional args
                    # If question is multi-word, we keep appending until an option or image_path is found.
                    # This logic needs refinement if image_path can appear before the full question.
                    # For now, assume question parts come first, then image_path.
                    # A more robust parser would be shlex + custom logic.
                    # This simple parser assumes image_path is the last non-flag arg if question is present.
                    # Or the only non-flag arg if no question.

                    # Try to identify if current arg is likely an image path to stop question accumulation
                    if parsed_args["image_path"] is None and (
                        arg.endswith((".jpg", ".png", ".jpeg", ".bmp", ".gif"))
                        or os.path.exists(arg)
                    ):
                        if (
                            parsed_args["question"] and not parsed_args["image_path"]
                        ):  # If question has content, this must be image
                            parsed_args["image_path"] = arg
                            pos_args_count = 2  # Mark image_path as found
                        elif not parsed_args[
                            "question"
                        ]:  # If no question yet, this could be image_path (for caption)
                            parsed_args["image_path"] = arg
                            pos_args_count = 1

                else:  # For caption (only image_path is positional)
                    if pos_args_count == 0:
                        parsed_args["image_path"] = arg
                        pos_args_count += 1
                    else:
                        raise ValueError("Too many positional arguments for caption.")
            i += 1

        if require_question and not parsed_args["question"]:
            raise ValueError("Missing question.")
        if not parsed_args["image_path"]:
            raise ValueError("Missing image path.")

        return parsed_args

    @work(exclusive=True, thread=True)
    async def command_caption(self, args: list):
        log = self.query_one("#output_log", RichLog)
        streaming_display = self.query_one("#streaming_line_display", Static)
        try:
            p_args = self._parse_inference_args(args, require_question=False)
            image_path = p_args["image_path"]
            length = p_args["length"]
            stream = p_args["stream"]
            max_tokens = p_args["max_tokens"]
        except ValueError as e:
            self.call_from_thread(
                log.write,
                f"[bold red]Usage Error (caption): {e}",  # Simplified f-string
            )
            return

        try:
            image = load_image(image_path)
        except FileNotFoundError:
            self.call_from_thread(
                log.write, f"[bold red]Error: Image not found at '{image_path}'[/]"
            )
            return
        except Exception as e:
            self.call_from_thread(
                log.write, f"[bold red]Error loading image '{image_path}': {e}[/]"
            )
            return

        self.call_from_thread(
            log.write,
            f"Generating {'streaming ' if stream else ''}caption for '{os.path.basename(image_path)}' (length: {length}, max_tokens: {max_tokens})...",
        )

        try:
            if stream:
                response_stream = self.cli.vl_client.caption(
                    image,
                    length=length,
                    stream=True,
                    settings={"max_tokens": max_tokens},
                )

                current_line_buffer = "Caption: "
                self.call_from_thread(streaming_display.remove_class, "-hidden")
                self.call_from_thread(streaming_display.update, current_line_buffer)

                for chunk in response_stream[
                    "caption"
                ]:  # Assuming "caption" is the key for chunks
                    if chunk:  # Process only non-empty chunks
                        current_line_buffer += chunk
                        self.call_from_thread(
                            streaming_display.update, current_line_buffer
                        )

                self.call_from_thread(streaming_display.add_class, "-hidden")
                self.call_from_thread(log.write, current_line_buffer)
                self.call_from_thread(
                    streaming_display.update, ""
                )  # Clear the streaming display
            else:  # Non-streaming
                result = self.cli.vl_client.caption(
                    image,
                    length=length,
                    stream=False,
                    settings={"max_tokens": max_tokens},
                )
                self.call_from_thread(log.write, f"Caption: {result.get('caption')}")

            self.call_from_thread(
                log.write, "[bold green]------ Caption Completed ------[/]"
            )

        except Exception as e:
            self.call_from_thread(
                log.write, f"[bold red]Error generating caption: {e}[/]"
            )
            if "Connection refused" in str(e) or "URLError" in str(e):
                self.call_from_thread(
                    log.write,
                    "[bold red]Moondream Station may not be running or reachable.[/]",
                )
            if stream:
                self.call_from_thread(streaming_display.add_class, "-hidden")
                self.call_from_thread(streaming_display.update, "")  # Clear it

    @work(exclusive=True, thread=True)
    async def command_query(self, args: list):
        log = self.query_one("#output_log", RichLog)
        streaming_display = self.query_one("#streaming_line_display", Static)
        try:
            p_args = self._parse_inference_args(args, require_question=True)
            question = p_args["question"]
            image_path = p_args["image_path"]
            stream = p_args["stream"]
            max_tokens = p_args["max_tokens"]
        except ValueError as e:
            self.call_from_thread(
                log.write,
                f"[bold red]Usage: query QUESTION IMAGE_PATH [--no-stream] [--max-tokens N][/]\nError: {e}",
            )
            return

        try:
            image = load_image(image_path)
        except FileNotFoundError:
            self.call_from_thread(
                log.write, f"[bold red]Error: Image not found at '{image_path}'[/]"
            )
            return
        except Exception as e:
            self.call_from_thread(
                log.write, f"[bold red]Error loading image '{image_path}': {e}[/]"
            )
            return

        self.call_from_thread(
            log.write,
            f"Answering {'streaming ' if stream else ''}query for '{os.path.basename(image_path)}': \"{question}\" (max_tokens: {max_tokens})...",
        )
        try:
            if stream:
                response_stream = self.cli.vl_client.query(
                    image, question, stream=True, settings={"max_tokens": max_tokens}
                )

                current_line_buffer = "Answer: "
                self.call_from_thread(streaming_display.remove_class, "-hidden")
                self.call_from_thread(streaming_display.update, current_line_buffer)

                for chunk in response_stream[
                    "answer"
                ]:  # Assuming "answer" is the key for chunks
                    if chunk:
                        current_line_buffer += chunk
                        self.call_from_thread(
                            streaming_display.update, current_line_buffer
                        )

                self.call_from_thread(streaming_display.add_class, "-hidden")
                self.call_from_thread(log.write, current_line_buffer)
                self.call_from_thread(
                    streaming_display.update, ""
                )  # Clear the streaming display
            else:  # Non-streaming
                result = self.cli.vl_client.query(
                    image, question, stream=False, settings={"max_tokens": max_tokens}
                )
                self.call_from_thread(log.write, f"Answer: {result.get('answer')}")

            self.call_from_thread(
                log.write, "[bold green]------ Query Completed ------[/]"
            )
        except Exception as e:
            self.call_from_thread(log.write, f"[bold red]Error answering query: {e}[/]")
            if "Connection refused" in str(e) or "URLError" in str(e):
                self.call_from_thread(
                    log.write,
                    "[bold red]Moondream Station may not be running or reachable.[/]",
                )
            if stream:
                self.call_from_thread(streaming_display.add_class, "-hidden")
                self.call_from_thread(streaming_display.update, "")  # Clear it

    @work(exclusive=True, thread=True)
    async def command_detect(self, args: list):
        log = self.query_one("#output_log", RichLog)
        if len(args) != 2:
            self.call_from_thread(
                log.write, "[bold red]Usage: detect OBJECT_TO_DETECT IMAGE_PATH[/]"
            )
            return

        obj_to_detect, image_path = args[0], args[1]

        try:
            image = load_image(image_path)
        except FileNotFoundError:
            self.call_from_thread(
                log.write, f"[bold red]Error: Image not found at '{image_path}'[/]"
            )
            return
        except Exception as e:
            self.call_from_thread(
                log.write, f"[bold red]Error loading image '{image_path}': {e}[/]"
            )
            return

        self.call_from_thread(
            log.write,
            f"Detecting '{obj_to_detect}' in '{os.path.basename(image_path)}'...",
        )
        try:
            result = self.cli.vl_client.detect(image, obj_to_detect)
            objects = result.get("objects", [])
            if not objects:
                self.call_from_thread(
                    log.write, f"No '{obj_to_detect}' objects detected."
                )
            else:
                self.call_from_thread(
                    log.write, f"Detected {len(objects)} '{obj_to_detect}' object(s):"
                )
                for obj_data in objects:
                    self.call_from_thread(log.write, f"  - Position: {obj_data}")
            self.call_from_thread(
                log.write, "[bold green]------ Detection Completed ------[/]"
            )
        except AttributeError:
            self.call_from_thread(
                log.write,
                "[bold red]Error: 'detect' functionality might not be available directly on vl_client or is not yet implemented in this TUI's call pattern.[/]",
            )
            self.call_from_thread(
                log.write,
                "Please check if the underlying 'moondream.VisionLanguageModel' supports a 'detect' method.",
            )
        except Exception as e:
            self.call_from_thread(
                log.write, f"[bold red]Error during detection: {e}[/]"
            )

    @work(exclusive=True, thread=True)
    async def command_point(self, args: list):
        log = self.query_one("#output_log", RichLog)
        if len(args) != 2:
            self.call_from_thread(
                log.write, "[bold red]Usage: point OBJECT_TO_POINT_AT IMAGE_PATH[/]"
            )
            return

        obj_to_point, image_path = args[0], args[1]
        try:
            image = load_image(image_path)
        except FileNotFoundError:
            self.call_from_thread(
                log.write, f"[bold red]Error: Image not found at '{image_path}'[/]"
            )
            return
        except Exception as e:
            self.call_from_thread(
                log.write, f"[bold red]Error loading image '{image_path}': {e}[/]"
            )
            return

        self.call_from_thread(
            log.write,
            f"Finding points for '{obj_to_point}' in '{os.path.basename(image_path)}'...",
        )
        try:
            result = self.cli.vl_client.point(image, obj_to_point)
            points = result.get("points", [])
            if not points:
                self.call_from_thread(
                    log.write, f"No points found for '{obj_to_point}'."
                )
            else:
                self.call_from_thread(
                    log.write, f"Found {len(points)} point(s) for '{obj_to_point}':"
                )
                for point_data in points:
                    self.call_from_thread(log.write, f"  - Point: {point_data}")
            self.call_from_thread(
                log.write, "[bold green]------ Pointing Completed ------[/]"
            )
        except AttributeError:
            self.call_from_thread(
                log.write,
                "[bold red]Error: 'point' functionality might not be available directly on vl_client or is not yet implemented in this TUI's call pattern.[/]",
            )
            self.call_from_thread(
                log.write,
                "Please check if the underlying 'moondream.VisionLanguageModel' supports a 'point' method.",
            )
        except Exception as e:
            self.call_from_thread(log.write, f"[bold red]Error finding points: {e}[/]")

    async def command_admin(self, args: list):
        log = self.query_one("#output_log", RichLog)
        if not args:
            log.write(admin_commands_box())
            log.write("Usage: admin <subcommand> [options]")
            return

        subcommand = args[0].lower()
        admin_args = args[1:]

        # Admin subcommand dispatching
        if subcommand == "health":  # Admin health is same as top-level health
            self.command_health([])
        elif subcommand == "get-config":
            self.admin_get_config(admin_args)
        elif subcommand == "model-list" or subcommand == "get-models":
            self.admin_get_models(admin_args)
        elif subcommand == "set-model" or subcommand == "model-use":
            self.admin_set_model(admin_args)
        elif subcommand == "check-updates":
            self.admin_check_updates(admin_args)
        elif subcommand == "update":  # update-all
            await self.admin_update_all(admin_args)
        elif subcommand == "update-hypervisor":
            await self.admin_update_component("hypervisor", admin_args)
        elif subcommand == "update-bootstrap":
            await self.admin_update_component("bootstrap", admin_args)
        # Add more admin commands here based on AdminCommands.py
        # e.g. set-inference-url, update-manifest, toggle-metrics, reset
        else:
            log.write(f"Unknown admin subcommand: {subcommand}. Type 'admin' for list.")

    @work(exclusive=True, thread=True)
    async def admin_get_config(self, args: list):
        log = self.query_one("#output_log", RichLog)
        self.call_from_thread(log.write, "Getting server configuration...")
        try:
            result = self.cli.admin_commands._make_request("GET", "/config")
            if result:
                self.call_from_thread(
                    log.write, "[bold u]Current Server Configuration:[/]"
                )
                for k, v in result.items():
                    self.call_from_thread(log.write, f"  {k}: {v}")
            else:
                self.call_from_thread(
                    log.write,
                    "[bold red]Failed to get configuration or server unreachable.[/]",
                )
        except Exception as e:
            self.call_from_thread(
                log.write, f"[bold red]Error getting configuration: {e}[/]"
            )

    @work(exclusive=True, thread=True)
    async def admin_get_models(self, args: list):
        log = self.query_one("#output_log", RichLog)
        model_picker_content = self.query_one("#model-picker-content", Static)
        self.call_from_thread(log.write, "Retrieving available models for picker...")
        self.call_from_thread(model_picker_content.update, "Fetching models...")

        try:
            result = self.cli.admin_commands._make_request("GET", "/admin/get_models")
            if result:
                model_display_lines = [
                    "[bold u]Available Models:[/u] (Use 'admin set-model ID --confirm')"
                ]
                for model_id, model_data in result.items():
                    model_display_lines.append(f"  [bold]{model_id}[/bold]")
                    # Add more details if desired, e.g., release date, size
                    # model_display_lines.append(f"    Size: {model_data.get('model_size', 'N/A')}")

                self.call_from_thread(
                    model_picker_content.update, "\n".join(model_display_lines)
                )
                self.call_from_thread(
                    log.write, f"Found {len(result)} models. Displayed in Model Picker."
                )

                # Also log to main log for record, but less verbosely
                summary_log_lines = ["[bold u]Available Models (summary):[/u]"]
                for model_id in result.keys():
                    summary_log_lines.append(f"  - {model_id}")
                self.call_from_thread(log.write, "\n".join(summary_log_lines))

            else:
                self.call_from_thread(
                    model_picker_content.update,
                    "No models available or server unreachable.",
                )
                self.call_from_thread(
                    log.write, "No models available or server unreachable."
                )
        except Exception as e:
            self.call_from_thread(
                model_picker_content.update, "[bold red]Error retrieving models.[/]"
            )
            self.call_from_thread(
                log.write, f"[bold red]Error retrieving models for picker: {e}[/]"
            )

    @work(exclusive=True, thread=True)
    async def admin_set_model(self, args: list):
        log = self.query_one("#output_log", RichLog)
        if not args or len(args) < 1:
            self.call_from_thread(
                log.write, "[bold red]Usage: admin set-model MODEL_ID [--confirm][/]"
            )
            return

        model_id = args[0]
        confirm = "--confirm" in args

        if not confirm:
            self.call_from_thread(
                log.write,
                f"To set model to '{model_id}', please confirm by adding --confirm flag.",
            )
            self.call_from_thread(
                log.write, "Example: admin set-model moondream2 --confirm"
            )
            return

        self.call_from_thread(
            log.write, f"Initiating change of model to: {model_id}..."
        )
        try:
            data = {"model": model_id, "confirm": True}
            initial_result = self.cli.admin_commands._make_request(
                "POST", "/admin/set_model", data
            )

            if not initial_result:
                self.call_from_thread(
                    log.write,
                    f"[bold red]Failed to initiate model change to {model_id}. Server might be busy or model invalid.[/]",
                )
                return

            self.call_from_thread(
                log.write,
                f"Model change to '{model_id}' initiated. Waiting for model initialization...",
            )
            self.call_from_thread(
                log.write, "This may take several minutes. Polling status..."
            )

            start_time = time.time()
            timeout = 300  # 5 minutes
            last_status_msg = ""

            while time.time() - start_time < timeout:
                await asyncio.sleep(3)
                status_result = self.cli.admin_commands._make_request(
                    "GET", "/admin/status", silent=True
                )
                current_hypervisor_status = (
                    status_result.get("hypervisor", "unknown")
                    if status_result
                    else "unknown"
                )
                current_inference_status = (
                    status_result.get("inference", "unknown")
                    if status_result
                    else "unknown"
                )
                status_msg = f"Status: Hypervisor='{current_hypervisor_status}', Inference='{current_inference_status}'"

                if status_msg != last_status_msg:
                    self.call_from_thread(log.write, status_msg)
                    last_status_msg = status_msg

                if current_inference_status == "ok" and current_hypervisor_status in [
                    "initialized",
                    "ok",
                ]:
                    self.call_from_thread(
                        log.write,
                        f"[bold green]Model '{model_id}' initialization completed successfully![/]",
                    )
                    # Consider refreshing model picker or indicating active model in the future.
                    # For now, user can re-run `admin get-models` or check `admin get-config`.
                    return

            self.call_from_thread(
                log.write,
                f"[bold yellow]Timeout waiting for model '{model_id}' to initialize. Last status: {last_status_msg}[/]",
            )
            self.call_from_thread(
                log.write, "Please check server logs for more details."
            )

        except Exception as e:
            self.call_from_thread(log.write, f"[bold red]Error setting model: {e}[/]")

    @work(exclusive=True, thread=True)
    async def admin_check_updates(self, args: list):
        log = self.query_one("#output_log", RichLog)
        self.call_from_thread(log.write, "Checking for available updates...")
        try:
            result = self.cli.admin_commands._make_request(
                "GET", "/admin/check_updates"
            )
            if result:
                self.call_from_thread(log.write, "[bold u]Update Status:[/]")
                components = {
                    "bootstrap": "Bootstrap",
                    "hypervisor": "Hypervisor",
                    "model": "Model",
                    "cli": "CLI (Server-side check)",
                }
                any_updates = False
                for key, name in components.items():
                    if key in result:
                        status = result[key]
                        version_info = status.get("version") or status.get(
                            "revision", "N/A"
                        )
                        needs_update = status.get("ood", False)
                        update_status_msg = (
                            "[bold yellow]Update available[/]"
                            if needs_update
                            else "[green]Up to date[/]"
                        )
                        if needs_update:
                            any_updates = True
                        self.call_from_thread(
                            log.write, f"  {name}: {version_info} - {update_status_msg}"
                        )
                    else:
                        self.call_from_thread(log.write, f"  {name}: Status unknown")

                if any_updates:
                    self.call_from_thread(
                        log.write,
                        "Run 'admin update --confirm' to install all available updates.",
                    )
                else:
                    self.call_from_thread(
                        log.write, "All components appear to be up to date."
                    )
            else:
                self.call_from_thread(
                    log.write,
                    "[bold red]Failed to check for updates or server unreachable.[/]",
                )
        except Exception as e:
            self.call_from_thread(
                log.write, f"[bold red]Error checking updates: {e}[/]"
            )

    @work(exclusive=True, thread=True)
    async def admin_update_all(self, args: list):
        log = self.query_one("#output_log", RichLog)
        confirm = "--confirm" in args
        if not confirm:
            self.call_from_thread(
                log.write, "Usage: admin update --confirm (to update all components)"
            )
            return

        self.call_from_thread(
            log.write, "Starting update process for all components..."
        )
        try:
            self.call_from_thread(log.write, "Checking for updates first...")
            updates_result = self.cli.admin_commands._make_request(
                "GET", "/admin/check_updates", silent=True
            )
            if not updates_result:
                self.call_from_thread(
                    log.write,
                    "[bold red]Failed to check for updates. Aborting update all.[/]",
                )
                return

            updated_something = False

            if updates_result.get("model", {}).get("ood", False):
                self.call_from_thread(
                    log.write, "Model update available. Attempting to set to latest..."
                )
                models_list = self.cli.admin_commands._make_request(
                    "GET", "/admin/get_models", silent=True
                )
                if models_list:
                    latest_model_id = next(iter(models_list.keys()), None)
                    if latest_model_id:
                        self.call_from_thread(
                            log.write,
                            f"Attempting to switch to model: {latest_model_id}",
                        )
                        await self.admin_set_model([latest_model_id, "--confirm"])
                        updated_something = True
                    else:
                        self.call_from_thread(
                            log.write,
                            "[yellow]Could not determine latest model to update.[/]",
                        )
                else:
                    self.call_from_thread(
                        log.write,
                        "[yellow]Could not fetch model list to determine latest model.[/]",
                    )

            if updates_result.get("cli", {}).get("ood", False):
                self.call_from_thread(
                    log.write,
                    "CLI (server-side component) update available. Attempting update...",
                )
                cli_update_data = {"confirm": True}
                cli_update_res = self.cli.admin_commands._make_request(
                    "POST", "/admin/update_cli", cli_update_data
                )
                if cli_update_res and cli_update_res.get("status") == "ok":
                    self.call_from_thread(
                        log.write,
                        "[green]CLI update initiated on server successfully.[/]",
                    )
                    updated_something = True
                elif (
                    cli_update_res
                    and "restarting" in cli_update_res.get("message", "").lower()
                ):
                    self.call_from_thread(
                        log.write,
                        "[yellow]CLI update initiated. Server component may be restarting.[/]",
                    )
                    updated_something = True
                else:
                    self.call_from_thread(
                        log.write,
                        f"[red]CLI update initiation failed or status unknown: {cli_update_res}[/]",
                    )

            if updates_result.get("hypervisor", {}).get("ood", False):
                self.call_from_thread(
                    log.write,
                    "Hypervisor update available. This will restart the server.",
                )
                await self.admin_update_component("hypervisor", ["--confirm"])
                self.call_from_thread(
                    log.write,
                    "Hypervisor update initiated. Server is restarting. TUI may lose connection.",
                )
                self.call_from_thread(
                    log.write,
                    "Please wait a moment and then try 'health' or other commands.",
                )
                return

            if updates_result.get("bootstrap", {}).get("ood", False):
                self.call_from_thread(
                    log.write,
                    "Bootstrap update available. This will restart the server.",
                )
                await self.admin_update_component("bootstrap", ["--confirm"])
                self.call_from_thread(
                    log.write,
                    "Bootstrap update initiated. Server is restarting. TUI may lose connection.",
                )
                self.call_from_thread(
                    log.write,  # Added consistent message
                    "Please wait a moment and then try 'health' or other commands.",
                )
                return

            if (
                not updated_something
                and not updates_result.get("hypervisor", {}).get("ood", False)
                and not updates_result.get("bootstrap", {}).get("ood", False)
            ):
                self.call_from_thread(
                    log.write,
                    "[green]No components seemed to require an update based on current check.[/]",
                )
            elif updated_something:
                self.call_from_thread(
                    log.write,
                    "[bold green]Update process for available non-restarting components initiated.[/]",
                )

        except Exception as e:
            self.call_from_thread(
                log.write, f"[bold red]Error during 'update all' process: {e}[/]"
            )

    @work(exclusive=True, thread=True)
    async def admin_update_component(self, component_type: str, args: list):
        log = self.query_one("#output_log", RichLog)
        confirm = "--confirm" in args
        if not confirm:
            self.call_from_thread(
                log.write, f"Usage: admin update-{component_type} --confirm"
            )
            return

        self.call_from_thread(
            log.write,
            f"Initiating update for {component_type}. This will restart the server component...",
        )
        try:
            data = {"confirm": True}
            endpoint = f"/admin/update_{component_type}"

            result = self.cli.admin_commands._make_request(
                "POST", endpoint, data, timeout=(5, 15)
            )

            if result:
                status = result.get("status", "unknown")
                message = result.get("message", "No specific message from server.")
                self.call_from_thread(
                    log.write,
                    f"[green]{component_type.capitalize()} update initiated. Server response: Status='{status}', Message='{message}'[/]",
                )
            else:
                self.call_from_thread(
                    log.write,
                    f"[yellow]{component_type.capitalize()} update initiated. The server component is likely restarting or the request timed out.[/]",
                )
                self.call_from_thread(
                    log.write,
                    "This is often normal for update commands that restart parts of the server.",
                )

            self.call_from_thread(
                log.write,
                f"The {component_type} update process has been started on the server.",
            )
            self.call_from_thread(
                log.write,
                "This may take a few minutes. Try the 'health' command after a short while to check server status.",
            )

        except Exception as e:
            self.call_from_thread(
                log.write, f"[bold red]Error initiating {component_type} update: {e}[/]"
            )

    def action_clear_log(self) -> None:
        log = self.query_one("#output_log", RichLog)
        log.clear()
        log.write(MOONDREAM_BANNER)
        log.write("Log cleared. Type 'help' for commands.")


if __name__ == "__main__":
    app = MoondreamTUI()
    app.run()
