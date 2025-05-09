import logging
import os
import tarfile
from pathlib import Path
import os, stat, textwrap
import subprocess
import shutil
import shlex

from config import Config
from manifest import Manifest
from misc import download_file, check_platform

logger = logging.getLogger("hypervisor")
PLATFORM = check_platform()


class CLIVisor:
    """
    Responsible for downloading, installing, launching, and updating the CLI.
    """

    def __init__(self, config: Config, manifest: Manifest):
        self.config = config
        self.manifest = manifest
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        logger.debug(f"clivisor initialized")

    def boot(self):
        """
        Ensure the CLI is installed and launch it in a new terminal window.

        Downloads the CLI if not present, installs it, and launches in a new Terminal.
        """
        cli_path = os.path.join(self.base_dir, "moondream_cli", "moondream-cli.py")
        if not os.path.exists(cli_path):
            self._download_and_extract_cli(self.manifest.current_cli["url"])
            install_moondream_cli(
                cli_path,
                os.path.join(self.base_dir, ".venv"),
            )

        # Launch CLI in a new terminal window as a non-blocking subprocess
        logger.info("Launching CLI in a new window")
        try:
            if PLATFORM == "macOS":
                self.launch_cli_mac()
            elif PLATFORM == "ubuntu":
                self.launch_cli_ubuntu()
            else:
                raise ValueError(f"Moondream-cli only supports macOS and Ubuntu, therefore it cannot be launched on {PLATFORM}")
           
        except Exception as e:
            logger.error(f"Failed to launch CLI in new window: {e}")

        print(
            "\nIf a terminal window with the CLI does not automatically appear, you can launch it by executing 'moondream' in a new window.\n"
        )
    
    def launch_cli_mac():
        applescript = """
        tell application "Terminal"
            do script "moondream"
        end tell
        """
        subprocess.Popen(["osascript", "-e", applescript])
        logger.info("CLI launched successfully in new window")

    def launch_cli_ubuntu():
        cmd = [
            "gnome-terminal",
            "--",
            "bash",
            "-c",
            f"{shlex.quote("moondream")}; exec bash",
        ]
        subprocess.Popen(
            cmd,
            start_new_session=True,
            close_fds=True,
        )

    def check_for_update(self, update_manifest: bool = True) -> dict:
        """
        Check if a CLI update is available.

        Args:
            update_manifest: If True, refresh manifest data before checking

        Returns:
            dict: Status containing "ood" (out of date) flag and current version
        """
        if update_manifest:
            self.manifest.update()

        ret_value = {
            "ood": False,
            "version": self.manifest.current_hypervisor["version"],
        }
        if self.config.active_cli != self.manifest.current_cli["version"]:
            ret_value["ood"] = True
        return ret_value

    def update(self) -> None:
        """
        Update CLI to the latest version if needed.

        Checks if an update is available and downloads/installs if necessary.
        """
        update_status = self.check_for_update()
        if not update_status["ood"]:
            return

        self._download_and_extract_cli(self.manifest.current_cli["url"])
        install_moondream_cli(
            os.path.join(self.base_dir, "moondream_cli", "moondream-cli.py"),
            os.path.join(self.base_dir, ".venv"),
        )

    def _download_and_extract_cli(self, url: str) -> bool:
        """
        Download and extract the CLI package.

        Args:
            url: URL to download the CLI package from

        Returns:
            bool: True if download and extraction succeeded
        """
        print("downloading cli")
        logger.debug(f"Downloading CLI from {url}")

        moondream_cli_dir = os.path.join(self.base_dir, "moondream_cli")
        moondream_cli_path = os.path.join(moondream_cli_dir, "moondream-cli.py")

        # Remove existing CLI directory to ensure clean installation
        # This prevents issues with outdated or leftover files
        if os.path.isdir(moondream_cli_dir):
            logger.debug(
                f"'{moondream_cli_dir}' already exists, removing to ensure clean installation"
            )
            try:
                shutil.rmtree(moondream_cli_dir)
                logger.debug(f"Successfully removed existing moondream_cli directory")
            except Exception as e:
                logger.error(f"Error removing existing moondream_cli directory: {e}")
                # Continue anyway as extraction might still work

        tar_path = os.path.join(self.base_dir, "moondream_cli.tar.gz")

        try:
            download_file(url, tar_path, logger)

            logger.debug(f"Extracting moondream_cli package to {self.base_dir}")
            with tarfile.open(tar_path, "r:gz") as tar:
                tar.extractall(path=self.base_dir)

            logger.debug("Extraction complete")
            os.remove(tar_path)
            logger.debug(f"Removed {tar_path}")

            return os.path.isfile(moondream_cli_path)
        except Exception as e:
            logger.error(f"Error downloading/extracting moondream_cli package: {e}")
            if os.path.exists(tar_path):
                os.remove(tar_path)
            return False


def install_moondream_cli(
    cli_py_path: str,
    venv_path: str,
    cli_name: str = "moondream",
) -> Path:
    """
    Create ~/.local/bin/moondream-cli that executes `cli_py_path`
    with the Python interpreter inside `venv_path`.

    Parameters
    ----------
    cli_py_path : str
        Absolute or ~-relative path to moondream_cli/moondream-cli.py
    venv_path   : str
        Path to *the root of the virtual-env* (the directory that
        contains bin/python).
    cli_name    : str, default "moondream-cli"
        The command typed at the shell.
    """
    cli_py = Path(cli_py_path).expanduser().resolve()
    venv_py = Path(venv_path).expanduser().resolve() / "bin" / "python"

    if not cli_py.exists():
        raise FileNotFoundError(f"CLI file not found: {cli_py}")
    if not venv_py.exists():
        raise FileNotFoundError(f"Python interpreter not found: {venv_py}")

    home = Path.home()
    bin_dir = home / ".local" / "bin"
    wrapper = bin_dir / cli_name
    bin_dir.mkdir(parents=True, exist_ok=True)

    # Script to execute the CLI
    script = textwrap.dedent(
        f"""\
        #!/usr/bin/env sh
        exec "{venv_py}" "{cli_py}" "$@"
        """
    )

    wrapper.write_text(script)
    wrapper.chmod(0o755)  
    logger.debug(f"Installed wrapper → {wrapper}")

    # Ensure ~/.local/bin on PATH for zsh + bash (idempotent)
    path_line = 'export PATH="$HOME/.local/bin:$PATH"'
    if PLATFORM == "macOS":
        path_files = [
            home / ".zprofile",
            home / ".zshrc",
            home / ".bash_profile",
            home / ".bashrc",
        ]
    else:
        path_files = [
            home / ".profile",
            home / ".zshrc",
            home / ".bashrc",
        ]

    for rc in path_files:
        try:
            if rc.exists():
                lines = rc.read_text().splitlines()
            else:
                lines = []
            if path_line not in lines:
                with rc.open("a") as f:
                    if lines:
                        f.write("\n")
                    f.write(path_line + "\n")
                logger.debug(f"Added PATH line to {rc.name}")
        except OSError as e:
            logger.error(f"⚠️  Could not update {rc}: {e}")
            print(f"⚠️  Could not update {rc}: {e}")

    return wrapper
