import os
import certifi
import sys
import time
import subprocess
import platform
import stat
import logging
import tarfile
import json
import shutil
import signal

from functools import partial

from display_utils import print_banner, Spinner
from config import DEFAULT_CONFIG
from misc import download_file


MINIFORGE_MAC_URL = "https://depot.moondream.ai/station/Miniforge3-MacOSX-arm64.sh"
PYTHON_VERSION = "3.10"
BOOTSTRAP_VERSION = "v0.0.2"
HYPERVISOR_TAR_URL = "https://depot.moondream.ai/station/md_station_hypervisor.tar.gz"
POSTHOG_PROJECT_API_KEY = "phc_8S71qk0L1WlphzX448tekgbnS1ut266W4J48k9kW0Cx"
SSL_CERT_FILE = "SSL_CERT_FILE"


os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["DYLD_LIBRARY_PATH"] = (
    os.path.abspath(".") + ":" + os.environ.get("DYLD_LIBRARY_PATH", "")
)

sys.stdout.reconfigure(line_buffering=True, write_through=True)


def is_macos():
    """Check if the current platform is macOS.

    Returns:
        bool: True if running on macOS, False otherwise.
    """
    return platform.system().lower().startswith("darwin")


def get_app_dir() -> str:
    """Get the application support directory for Moondream Station."""
    home = os.path.expanduser("~")
    app_support_dir = os.path.join(home, "Library", "MoondreamStation")
    os.makedirs(app_support_dir, exist_ok=True)
    return app_support_dir


def configure_logging(log_dir: str) -> logging.Logger:
    """Configure logging for the bootstrap process.

    Args:
        log_dir: Directory where log files will be stored

    Returns:
        Logger: Configured logger instance
    """
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Debug logs
    log_file = os.path.join(log_dir, "bootstrap.log")
    fh = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    fh.setFormatter(fmt)

    # console logs
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def setup_miniforge_installer(
    installer_url: str, embed_dir: str, logger: logging.Logger, python_version: str
):
    """Download and run Miniforge installer to set up Python environment.

    Args:
        installer_url: URL to download the Miniforge installer
        embed_dir: Directory where Miniforge will be installed
        logger: Logger instance for output
        python_version: Python version to install

    Raises:
        RuntimeError: If installation fails
        FileNotFoundError: If conda executable not found
    """
    if os.path.isdir(embed_dir):
        logger.info(f"Miniforge directory '{embed_dir}' already exists.")
        return
    os.makedirs(embed_dir, exist_ok=True)

    installer_name = os.path.join(embed_dir, "Miniforge.sh")
    download_file(installer_url, installer_name, logger)

    st = os.stat(installer_name)
    os.chmod(installer_name, st.st_mode | stat.S_IEXEC)

    logger.info(f"Running Miniforge installer in {embed_dir}")
    cmd = [installer_name, "-u", "-b", "-p", os.path.abspath(embed_dir)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    logger.info(f"Miniforge installer return code: {res.returncode}")
    if res.stdout:
        logger.debug(f"Installer stdout:\n{res.stdout}")
    if res.stderr:
        logger.debug(f"Installer stderr:\n{res.stderr}")

    if res.returncode != 0:
        raise RuntimeError("Miniforge installation failed.")

    os.remove(installer_name)
    logger.info("Miniforge installation complete.")

    conda_bin = os.path.join(embed_dir, "bin", "conda")
    if not os.path.isfile(conda_bin):
        raise FileNotFoundError(f"Cannot find conda at {conda_bin}")

    logger.info(f"Forcing Miniforge Python to {python_version}")
    force_cmd = [conda_bin, "install", "-y", f"python={python_version}"]
    res2 = subprocess.run(force_cmd, capture_output=True, text=True)
    logger.info(f"conda install python={python_version} return code: {res2.returncode}")
    if res2.stdout:
        logger.debug(f"Conda python install stdout:\n{res2.stdout}")
    if res2.stderr:
        logger.debug(f"Conda python install stderr:\n{res2.stderr}")

    if res2.returncode != 0:
        raise RuntimeError(f"Failed to install python={python_version} via conda.")


def install_libvips_conda(embed_dir: str, logger: logging.Logger):
    """Install libvips library using conda.
    This is needed for PyVips.

    Args:
        embed_dir: Directory with conda installation
        logger: Logger instance for output

    Raises:
        FileNotFoundError: If conda executable not found
        RuntimeError: If installation fails
    """
    conda_bin = os.path.join(embed_dir, "bin", "conda")
    if not os.path.isfile(conda_bin):
        raise FileNotFoundError(f"Cannot find conda at {conda_bin}")

    logger.info(f"Installing libvips with conda in {embed_dir}")
    cmd = [conda_bin, "install", "-y", "conda-forge::libvips"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    logger.info(f"Conda install libvips return code: {res.returncode}")
    if res.stdout:
        logger.debug(f"Conda libvips install stdout:\n{res.stdout}")
    if res.stderr:
        logger.debug(f"Conda libvips install stderr:\n{res.stderr}")

    if res.returncode != 0:
        raise RuntimeError("Failed to install libvips via conda.")


def setup_miniforge_if_needed(
    py_versions_dir: str, python_version: str, logger: logging.Logger
) -> str:
    """Set up Miniforge Python environment if not already present.

    Args:
        py_versions_dir: Directory for Python versions
        python_version: Python version to install
        logger: Logger instance for output

    Returns:
        str: Path to the Python version directory
    """
    # Check if Python version exists in py_versions directory
    version_dir = os.path.join(py_versions_dir, f"python-{python_version}")
    python_bin = os.path.join(version_dir, "bin", "python")

    if os.path.isdir(version_dir) and os.path.isfile(python_bin):
        logger.info(f"Found existing Python {python_version} at {version_dir}")
        return version_dir

    # Setup new Python installation
    logger.info(f"Setting up Python {python_version} in {version_dir}")
    os.makedirs(py_versions_dir, exist_ok=True)
    setup_miniforge_installer(MINIFORGE_MAC_URL, version_dir, logger, python_version)
    install_libvips_conda(version_dir, logger)

    return version_dir


def check_py_version_exists(
    py_versions_dir: str, python_version: str, logger: logging.Logger
) -> str:
    """Check if a specific Python version exists in the versions directory.

    Args:
        py_versions_dir: Directory for Python versions
        python_version: Python version to check for
        logger: Logger instance for output

    Returns:
        str: Path to the version directory if exists, None otherwise
    """
    version_dir = os.path.join(py_versions_dir, f"python-{python_version}")
    python_bin = os.path.join(version_dir, "bin", "python")

    if os.path.isdir(version_dir) and os.path.isfile(python_bin):
        logger.info(f"Found existing Python {python_version} at {version_dir}")
        return version_dir

    return None


def create_venv(venv_dir: str, embed_dir: str, logger: logging.Logger):
    """Create a virtual environment.

    Args:
        venv_dir: Directory for the virtual environment
        embed_dir: Directory with Python installation
        logger: Logger instance for output

    Raises:
        FileNotFoundError: If Python executable not found
        RuntimeError: If venv creation fails
    """
    python_bin = os.path.join(embed_dir, "bin", "python")
    if not os.path.isfile(python_bin):
        raise FileNotFoundError(f"Cannot find {python_bin}")

    logger.info(f"Creating venv at {venv_dir} using {python_bin}")
    result = subprocess.run(
        [python_bin, "-m", "venv", venv_dir], capture_output=True, text=True
    )
    logger.info(f"Venv creation return code: {result.returncode}")
    if result.stdout:
        logger.debug(f"Venv creation stdout:\n{result.stdout}")
    if result.stderr:
        logger.debug(f"Venv creation stderr:\n{result.stderr}")

    if result.returncode != 0:
        raise RuntimeError("Failed to create venv.")


def setup_env_if_needed(
    venv_dir: str, py_versions_dir: str, python_version: str, logger: logging.Logger
) -> str:
    """Set up Python environment if not already present.

    Args:
        venv_dir: Directory for the virtual environment
        py_versions_dir: Directory for Python versions
        python_version: Python version to install
        logger: Logger instance for output

    Returns:
        str: Path to the virtual environment directory
    """
    if os.path.isdir(venv_dir):
        logger.info(f"Found existing venv '{venv_dir}'. Skipping setup.")
        return venv_dir

    print("Setting up Python environment (this may take several minutes)")
    embed_dir = setup_miniforge_if_needed(py_versions_dir, python_version, logger)
    create_venv(venv_dir, embed_dir, logger)
    install_requirements(venv_dir, logger)

    return venv_dir


def install_requirements(venv_dir: str, logger: logging.Logger):
    """Install Python requirements from requirements.txt.

    Args:
        venv_dir: Virtual environment directory
        logger: Logger instance for output

    Raises:
        FileNotFoundError: If Python executable not found
    """
    requirements_file = "requirements.txt"
    python_bin = os.path.join(venv_dir, "bin", "python")
    if not os.path.isfile(python_bin):
        raise FileNotFoundError(f"Cannot find {python_bin}")

    logger.info("Upgrading pip...")
    res = subprocess.run(
        [python_bin, "-m", "pip", "install", "--upgrade", "pip"],
        capture_output=True,
        text=True,
    )
    logger.info(f"Pip upgrade return code: {res.returncode}")
    if res.stdout:
        logger.debug(f"Pip upgrade stdout:\n{res.stdout}")
    if res.stderr:
        logger.debug(f"Pip upgrade stderr:\n{res.stderr}")

    if not os.path.isfile(requirements_file):
        logger.info(f"'{requirements_file}' not found, skipping requirements install.")
        return

    logger.info(f"Installing requirements from {requirements_file}")
    res = subprocess.run(
        [python_bin, "-m", "pip", "install", "-U", "-r", requirements_file],
        capture_output=True,
        text=True,
    )
    logger.info(f"Requirements install return code: {res.returncode}")
    if res.stdout:
        logger.debug(f"Requirements install stdout:\n{res.stdout}")
    if res.stderr:
        logger.debug(f"Requirements install stderr:\n{res.stderr}")

    logger.info("Checking installed packages in venv")
    check_packages = subprocess.run(
        [python_bin, "-m", "pip", "list"], capture_output=True, text=True
    )
    if check_packages.returncode == 0:
        logger.debug(f"Packages:\n{check_packages.stdout}")
    else:
        logger.debug(f"Error listing packages:\n{check_packages.stderr}")


def _unset_sll_cert(signum: int, frame, logger: logging.Logger) -> None:
    """
    Signal handler that unsets $SSL_CERT_FILE and terminates the process.
    """
    os.environ.pop("SSL_CERT_FILE", None)
    sys.exit(128 + signum)


def run_main_loop(venv_dir: str, app_dir: str, logger: logging.Logger):
    """Run the hypervisor server in a loop, restarting if needed.
    If exit code 99 is intercepted, update bootstrap. The update subprocess
    will kill and restart bootstrap.
    If an error code other than 99 or 0 is recieved, bootstrap does not restart the hypervisor server.

    Args:
        venv_dir: Virtual environment directory
        app_dir: Application directory
        logger: Logger instance for output
    """
    main_py = "hypervisor_server.py"
    python_bin = os.path.join(venv_dir, "bin", "python")
    return_code = 0

    handler = partial(_unset_sll_cert, logger)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    while return_code == 0:
        if not os.path.isfile(main_py):
            logger.warning(f"'{main_py}' not found.")
            return

        logger.info(f"Launching {main_py} via {python_bin}")
        print(f"Launching {main_py} via {python_bin}")

        proc = subprocess.Popen([python_bin, main_py])
        return_code = proc.wait()
        logger.warning(f"{main_py} exited with code {return_code}; restarting in 5s.")
        print("return code is", return_code)
        if return_code == 99:
            update_bootstrap(app_dir, logger)

        time.sleep(5)


def download_and_extract_hypervisor(app_dir: str, logger: logging.Logger) -> bool:
    """Download and extract hypervisor package if not present.

    Args:
        app_dir: Application directory
        logger: Logger instance for output

    Returns:
        bool: True if hypervisor server is available

    Raises:
        Exception: If download or extraction fails
    """
    main_py = "hypervisor_server.py"
    if os.path.isfile(main_py):
        return True

    logger.info(f"'{main_py}' not found. Downloading hypervisor package...")
    tar_path = os.path.join(app_dir, "hypervisor.tar.gz")

    try:
        download_file(HYPERVISOR_TAR_URL, tar_path, logger)

        logger.info(f"Extracting hypervisor package to {app_dir}")
        with tarfile.open(tar_path, "r:gz") as tar:
            tar.extractall(path=app_dir)

        logger.info("Extraction complete")
        os.remove(tar_path)
        logger.info(f"Removed {tar_path}")

        return os.path.isfile(main_py)
    except Exception as e:
        logger.error(f"Error downloading/extracting hypervisor package: {e}")
        if os.path.exists(tar_path):
            os.remove(tar_path)
        raise


def update_bootstrap(app_dir: str, logger: logging.Logger) -> bool:
    """Check for bootstrap updates in the manifest and update if needed.
    Uses data/manifest as a source of truth.

    Args:
        app_dir: The application directory path
        logger: Logger instance

    Returns:
        bool: True if update was successful and restart is needed, False otherwise
    """
    manifest_path = os.path.join(app_dir, "data", "manifest.json")
    if not os.path.exists(manifest_path):
        logger.warning(
            f"Manifest file not found at {manifest_path}, skipping bootstrap update"
        )
        return False

    try:
        # Load manifest file
        with open(manifest_path, "r") as f:
            manifest = json.load(f)

        bootstrap_info = manifest.get("current_bootstrap", {})
        bootstrap_url = bootstrap_info.get("url")
        bootstrap_version = bootstrap_info.get("version")

        if not bootstrap_url:
            logger.info(f"No bootstrap URL found in manifest, skipping update")
            return False

        logger.info(
            f"Found bootstrap version {bootstrap_version} at URL: {bootstrap_url}"
        )

        # Path to the running executable inside the bundle
        current_exe = os.path.abspath(sys.argv[0])
        if not os.path.exists(current_exe):
            logger.error(f"Cannot determine current executable path: {current_exe}")
            return False

        # Walk up until we reach the *.app bundle root
        current_app_bundle = current_exe
        while not current_app_bundle.endswith(
            ".app"
        ) and current_app_bundle != os.path.dirname(current_app_bundle):
            current_app_bundle = os.path.dirname(current_app_bundle)

        if not current_app_bundle.endswith(".app") or not os.path.isdir(
            current_app_bundle
        ):
            logger.error(f"Failed to locate the running *.app bundle for {current_exe}")
            return False
        else:
            logger.info(
                f"Current bundle is {current_app_bundle}, this will be replaced."
            )

        # Set up directories for download and extraction
        download_dir = os.path.join(app_dir, "tmp")
        os.makedirs(download_dir, exist_ok=True)
        tar_path = os.path.join(download_dir, f"bootstrap_{bootstrap_version}.tar.gz")

        try:
            # Download the bootstrap tarball
            logger.info(
                f"Downloading bootstrap tarball from {bootstrap_url} to {tar_path}"
            )
            download_file(bootstrap_url, tar_path, logger)

            # Create extraction directory
            os.makedirs(download_dir, exist_ok=True)

            # Extract the tarball
            logger.info(f"Extracting bootstrap archive to {download_dir}")
            with tarfile.open(tar_path, "r:gz") as tar:
                tar.extractall(path=download_dir)

            bootstrap_exe = os.path.join(
                download_dir, "moondream_station", "Moondream Station.app"
            )

            if os.path.isfile(bootstrap_exe):
                logger.error(
                    f"Error: Expected bootstrap executable not found in archive"
                )
                return False

            logger.info(f"Found bootstrap executable at {bootstrap_exe}")

            # Set executable permissions
            try:
                os.chmod(bootstrap_exe, 0o755)
                logger.info(f"Set executable permissions")
            except:
                logger.info("Could not set executable permissions")

            # Use the update_bootstrap.sh script to handle the update process
            update_script_path = os.path.join(app_dir, "update_bootstrap.sh")
            if not os.path.exists(update_script_path):
                logger.error(f"Update script not found at {update_script_path}")
                return False

            logger.info(
                f"Bootstrap update prepared, relaunching with version {bootstrap_version}"
            )

            # Launch the updater in its own Terminal window.
            osa_cmd = [
                "osascript",
                "-e",
                (
                    'tell application "Terminal"\n'
                    "    activate\n"
                    f'    do script "/bin/bash \\"{update_script_path}\\" '
                    f'\\"{bootstrap_exe}\\" \\"{current_app_bundle}\\" {os.getpid()} 2"\n'
                    "end tell"
                ),
            ]
            subprocess.Popen(osa_cmd)

        except Exception as e:
            logger.error(f"Error during bootstrap update: {e}")
            # Clean up
            if os.path.exists(tar_path):
                os.remove(tar_path)
            if os.path.exists(download_dir):
                shutil.rmtree(download_dir)
            return False

    except Exception as e:
        logger.error(f"Error checking for bootstrap updates: {e}")
        return False


def update_config_bootstrap_version(app_dir: str, logger: logging.Logger) -> None:
    """Update config.json with the current active version (defined at the top of the file)

    Args:
        app_dir: The application directory path
        logger: Logger instance
    """
    os.makedirs(os.path.join(app_dir, "data"), exist_ok=True)
    config_path = os.path.join(app_dir, "data", "config.json")
    try:
        # If the config file doesn't exist, create it with default settings
        if not os.path.isfile(config_path):
            logger.info(f"Config file not found at {config_path}, creating new config")
            config_data = DEFAULT_CONFIG
            config_data["active_bootstrap"] = BOOTSTRAP_VERSION
        else:
            # Load existing config
            with open(config_path, "r") as f:
                config_data = json.load(f)
            # Update bootstrap version
            if config_data.get("active_bootstrap") != BOOTSTRAP_VERSION:
                logger.info(
                    f"Updating bootstrap version in config from {config_data.get('active_bootstrap', 'none')} to {BOOTSTRAP_VERSION}"
                )
                config_data["active_bootstrap"] = BOOTSTRAP_VERSION
            else:
                logger.info(
                    f"Bootstrap version in config already set to {BOOTSTRAP_VERSION}"
                )
                return

        # Save updated config
        with open(config_path, "w") as f:
            json.dump(config_data, f, indent=4)
        logger.info(f"Updated config.json with bootstrap version {BOOTSTRAP_VERSION}")

    except Exception as e:
        logger.error(f"Error updating config with bootstrap version: {e}")


def is_setup(app_dir: str) -> bool:
    """Check if the application is properly set up. Looks for
    data/config.json and hypervisor_server.py

    Args:
        app_dir: Application directory

    Returns:
        bool: True if application is properly set up
    """
    if (not os.path.isfile(os.path.join(app_dir, "data", "config.json"))) or (
        not os.path.isfile("hypervisor_server.py")
    ):
        return False
    return True


def main():
    """Entry point for Moondream Station.

    Handles setup of Python environment, downloads necessary components,
    and launches the hypervisor server loop.
    """
    start_time = time.time()
    if not is_macos():
        sys.exit("Only macOS is supported.")

    print_banner()
    os.environ["md_ph_k"] = POSTHOG_PROJECT_API_KEY

    app_dir = get_app_dir()
    logger = configure_logging(app_dir)

    os.chdir(app_dir)
    venv_dir = os.path.join(app_dir, ".venv")
    py_versions_dir = os.path.abspath(os.path.join(app_dir, "py_versions"))

    logger.info(f"Platform: {platform.system()} {platform.release()}")
    logger.info(f"Application directory: {app_dir}")
    logger.info("Starting hypervisor bootstrap...")

    try:
        download_and_extract_hypervisor(app_dir, logger)
        setup_env_if_needed(venv_dir, py_versions_dir, PYTHON_VERSION, logger)
    except Exception as e:
        logger.error(e)
        result = subprocess.run(["rm", "-rf", str(app_dir)], check=True)
        logger.info(result)
        sys.exit(1)

    update_config_bootstrap_version(app_dir, logger)

    if not is_setup(app_dir):
        logger.error("Set up failed, resetting app_dir")
        result = subprocess.run(["rm", "-rf", str(app_dir)], check=True)
        logger.info(result)
        print(
            "Setup failed. Try restarting the app, if this continues to fail, try redownloading the app."
        )
        sys.exit(1)

    elapsed_time = time.time() - start_time
    print(f"Bootup completed in {elapsed_time:.2f} seconds")
    print("Starting Moondream Station...\n")

    run_main_loop(venv_dir, app_dir, logger)


if __name__ == "__main__":
    main()
