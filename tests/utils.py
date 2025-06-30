import os, subprocess, shutil, threading
from pathlib import Path
REPO_DIR = Path(__file__).parent.parent
TEST_FOLDER = "test_files"
from manifest_handler import Manifest
from http.server import SimpleHTTPRequestHandler, HTTPServer

def create_and_copy_tarball(
        components: dict[str, str], # {"bootstrap": "v0.0.2", "hypervisor": "v0.0.1"}
        test_folder:Path,
        base_folder: Path = None,
        system: str = "ubuntu",
        app_dir: str = None,
        ) -> dict[str, Path]:
    """
    Create tarballs for the given components and extract them to the test folder.
    Args:
        components (dict): A dictionary where keys are component names and values are their versions.
        test_folder (Path): The folder where the tarballs will be extracted.
        base_folder (Path, optional): The base folder where the tarballs are located. Defaults to None.
        system (str, optional): The system for which the tarballs are built. Defaults to "ubuntu".
        app_dir (str, optional): The directory where the build script is located. Defaults to None.
    Returns:
        dict: A dictionary where keys are component names and values are the paths to the extracted tar
    """
    repo_dir = REPO_DIR

    if app_dir is not None:
        app_path = Path(app_dir).resolve()
    else:
        app_path = repo_dir / "app"

    # check if build.sh exists first
    build_path = app_path / "build.sh"
    if not os.path.exists(build_path):
        raise FileNotFoundError(f"build.sh not found in {app_path}")
    
    copied = {}

    tarfile_map = {
            "bootstrap": "moondream_station_ubuntu",
            "hypervisor": "hypervisor",
            "cli": "moondream-cli",
            "inference": "inference_bootstrap"
    }

    # build everything via dev at once
    cmd = ['bash', 'build.sh', 'dev', system, '--build-clean']

    # add component versions
    for component, version in components.items():
        cmd.append(f'--{component}-version={version}')
    
    print(f"Building all components via dev: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=app_path, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Dev build failed: {result.stderr}")
    print(f"Dev build output:\n{result.stdout}")

    # iterate through the component list and use that to copy the tarfiles and rename them
    for component, version in components.items():
        tarball_name = f"{tarfile_map[component]}.tar.gz"
        tarball_versioned_name = f"{tarfile_map[component]}_{version}.tar.gz"

        if base_folder is None:
            tarball_path = repo_dir / "output" / tarball_name
            search_location = repo_dir / "output"
        else:
            tarball_path = base_folder / tarball_name  
            search_location = base_folder
        
        if not os.path.exists(tarball_path):
            raise FileNotFoundError(f"Tarball {tarball_name} not found in {search_location}")
        
        dest_folder = test_folder / 'tarfiles'
        dest_folder.mkdir(parents=True, exist_ok=True)
        tarball_versioned_path = dest_folder / tarball_versioned_name

        #copy tarball to the test folder with version added in the name
        shutil.copy2(tarball_path, tarball_versioned_path)

        copied[component] = {
            "version": version,
            "path": str(tarball_versioned_path)
        }
        
    return copied

def build_base_version(base_manifest_path: str, system: str = 'ubuntu', app_dir=None) -> None:
    repo_dir = REPO_DIR

    if app_dir is not None:
        app_path = Path(app_dir).resolve()
    else:
        app_path = repo_dir / "app"

    cmd = ['bash', 'build.sh', 'dev', system, '--build-clean']
    manifest = Manifest(base_manifest_path)
    
    for component in ["bootstrap", "hypervisor", "cli"]:
        version = getattr(manifest, f"current_{component}").version
        cmd.append(f'--{component}-version={version}')
    
    inference = max(manifest.inference_clients.keys(), # since we may have multiple inference version keys!
                key=lambda v: [int(x) for x in v[1:].split('.')])
    
    cmd.append(f'--inference-version={inference}')
    
    print(f"Building base version from manifest {base_manifest_path} with command : {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=app_path, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Dev build failed: {result.stderr}")
    print(f"Dev build output:\n{result.stdout}")



def serve_test_files(test_folder: Path, port: int = 8000):
    os.chdir(test_folder)
    server = HTTPServer(('localhost', port), SimpleHTTPRequestHandler)
    print(f"Serving test files from {test_folder} on http://localhost:{port}")
    
    # Run in background thread so it doesn't block
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    
    return server
