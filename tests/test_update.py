import os, subprocess, shutil, json, threading, time
import pytest
from pathlib import Path
import argparse
from http.server import SimpleHTTPRequestHandler, HTTPServer
from manifest_handler import Manifest, InferenceClient
from server_handler import MoondreamServer

TARBALL_BASE = "output"
TEST_FOLDER = "test_files"

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
    repo_dir = Path(__file__).parent.parent

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

def model_uses_version(models, version):
    return any(
        model.get("inference_client") == version
        for category in models.values()
        for model in category.values()
    )

def build_base_version(base_manifest_path: str, system: str = 'ubuntu', app_dir=None) -> None:
    repo_dir = Path(__file__).parent.parent

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

def generate_manifest(template_manifest_path: str,
                      tarball_info: dict[str, dict[str, str]],
                      serve_url: str,
                      models_json: str = None,
                      output_path: str = None,
                      new_manifest_version: str = "v0.0.2") -> Manifest:
    """
    Generate a manifest based on the base manifest and the provided tarball information.
    Args:
        base_manifest_path (str): Path to the base manifest JSON file.
        tarball_info (dict): A dictionary containing component names as keys and their version and path
                                as values. Example: {"bootstrap": {"version": "v0.0.2", "path": "path/to/tarball"}}
        serve_url (str): The URL where the tarballs will be served.
        models_json (str, optional): Path to a JSON file containing models to be included in the manifest.
        output_path (str, optional): Path where the generated manifest will be saved.
        new_manifest_version (str, optional): The version of the manifest to be generated. Defaults to "v0.0.2".
    Returns:
        Manifest: An instance of the Manifest class populated with the provided information.
    """
    
    manifest = Manifest(template_manifest_path)
    print(manifest.to_dict())

    # Update manifest version
    manifest.manifest_version = new_manifest_version

    # If models_json is provided, update the manifest with models
    if models_json:
        with open(models_json, 'r') as f:
            test_models = json.load(f)
        
        total_models = sum(len(category) for category in test_models.values())
        if total_models == 0:
            raise ValueError("Models JSON must contain at least one model")
        
        manifest.models = test_models
        print(f"Replaced models from {models_json}")

    for component, info in tarball_info.items():
        version = info["version"]
        tarball_name = Path(info["path"]).name
        url = f"{serve_url}/{tarball_name}"

        print(f"Updating manifest for {component} with version {version} and URL {url}") #TODO: Remove this in prod
        
        if component == "inference":
            if not model_uses_version(manifest.models, version):
                print(f"WARNING: No models use inference_client {version}")

            curr_version = list(manifest.inference_clients.keys())[0]
            curr_date = manifest.inference_clients[curr_version].date
            manifest.inference_clients[version] = InferenceClient(
                date=curr_date, # TODO: Allow update with user defined date?
                url=url
            )
        else:
            current_component = getattr(manifest, f"current_{component}")
            current_component.version = version
            current_component.url = url

    if output_path:
        manifest.save(output_path)
        print(f"Manifest saved to {output_path}")

    return manifest

def serve_test_files(test_folder: Path, port: int = 8000):
    os.chdir(test_folder)
    server = HTTPServer(('localhost', port), SimpleHTTPRequestHandler)
    print(f"Serving test files from {test_folder} on http://localhost:{port}")
    
    # Run in background thread so it doesn't block
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    
    return server


# =========== Test fixtures =============
@pytest.fixture(scope="session")
def server(test_environment):
    """New server for each test."""
    server = MoondreamServer(...)
    yield server
    server.stop()

# ==================== Tests ====================


# ====================

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Run Moondream Station update tests",
        formatter_class = argparse.RawDescriptionHelpFormatter
    )

    # get the start state
    # start state can be either just versions, or a full on manifest.json
    # it's on the user that the input manifest.json is correct

    # using a mutually exclusive group means we only need to use one of the arguments.
    base_group = parser.add_mutually_exclusive_group(required=True)
    base_group.add_argument("--base-versions", type=str, 
                           help='Base versions JSON, e.g. \'{"bootstrap": "v0.0.1"}\'')
    base_group.add_argument("--base-manifest", action="store_true",
                           help="Use ./test_files/base_manifest.json")

    test_group = parser.add_mutually_exclusive_group(required=True)
    test_group.add_argument("--test-versions", type=str,
                           help='Test versions JSON, e.g. \'{"bootstrap": "v0.0.2"}\'')
    test_group.add_argument("--test-manifest", action="store_true",
                           help="Use ./test_files/test_manifest.json")
    return parser.parse_args()

def get_versions_from_args(args, components: list[str], test_path: str):
    """Extract base and test versions from arguments."""

    # Get base versions
    if args.base_manifest:
        manifest_path = test_path / 'base_manifest.json'
        if not manifest_path.exists():
            raise FileNotFoundError(f"Base manifest not found at {manifest_path}")
        base_manifest = Manifest(str(manifest_path))
        base_versions = {
            "bootstrap": base_manifest.current_bootstrap.version,
            "cli": base_manifest.current_cli.version,
            "hypervisor": base_manifest.current_hypervisor.version,
            "inference": list(base_manifest.inference_clients.keys())[0]
        }
    else:
        base_versions = json.loads(args.base_versions)
        # Fill in default as v0.0.1 for base manifest
        for comp in components:
            base_versions.setdefault(comp, "v0.0.1")
    
    # Get test versions
    if args.test_manifest:
        manifest_path = test_path / 'test_manifest.json'
        if not manifest_path.exists():
            raise FileNotFoundError(f"Test manifest not found at {manifest_path}")
        test_manifest = Manifest(str(manifest_path))
        test_versions = {
            "bootstrap": test_manifest.current_bootstrap.version,
            "cli": test_manifest.current_cli.version,
            "hypervisor": test_manifest.current_hypervisor.version,
            "inference": list(test_manifest.inference_clients.keys())[0]
        }
    else:
        test_versions = json.loads(args.test_versions)
        # we don't need defaults for versions cause we will use the versions in base manifest as default.
    
    return base_versions, test_versions

def main():

    # what to not reset each test:
    # built tarballs - expensive to build each time.
    # http server - only serves files

    # what to reset:
    # manifests per test
    # moondream server base build
    # the moondream server instance
    # server should start from base manifest each time
    
    args = parse_arguments()

    test_path = Path(__file__).parent / TEST_FOLDER
    template_manifest_path = test_path / 'template_manifest.json'
    base_manifest_path = test_path / 'base_manifest.json'
    test_manifest_path = test_path / 'test_manifest.json'
    test_models_path = test_path / 'test_models.json'

    components = ["bootstrap", "hypervisor", "cli", "inference"]
       
    try:
        base_versions, test_versions = get_versions_from_args(args, components, test_path)
        
        print(f"Base versions: {base_versions}")
        print(f"Test versions: {test_versions}")

    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR: {e}")
    

    
if __name__ == "__main__":
    main()