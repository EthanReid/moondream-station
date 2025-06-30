import os, subprocess, shutil, json, threading, time
import requests
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
                      new_manifest_version: str = "v0.0.2") -> Path:
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
        output_path: The path at which the generated manifest is saved.
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

    return output_path

def generate_component_manifest(
    base_manifest_path: Path,
    component: str,
    version: str,
    tarball_path: str,
    serve_url: str,
    output_path: Path
) -> Path:
    """Generate manifest with update for single component only."""
    manifest = Manifest(str(base_manifest_path))
    
    # Update only the specified component
    tarball_name = Path(tarball_path).name
    url = f"{serve_url}/{tarball_name}"
    
    if component == "inference":
        # Add new inference version
        manifest.inference_clients[version] = InferenceClient(
            date=manifest.inference_clients[list(manifest.inference_clients.keys())[0]].date,
            url=url
        )
    else:
        current_component = getattr(manifest, f"current_{component}")
        current_component.version = version
        current_component.url = url
    
    manifest.save(str(output_path))
    return output_path

def serve_test_files(test_folder: Path, port: int = 8000):
    os.chdir(test_folder)
    server = HTTPServer(('localhost', port), SimpleHTTPRequestHandler)
    print(f"Serving test files from {test_folder} on http://localhost:{port}")
    
    # Run in background thread so it doesn't block
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    
    return server

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
    parser.add_argument("--port", type=int,
                        default=8000,
                        help='Port at which to start the webserver to serve manifests and tarfiles.')
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

# ==================
def test_bootstrap_hypervisor_cli_update(component:str, executable_path, base_manifest_path, test_path, test_versions, test_copied, localhost_url, update_timeout:int=5):

    base_manifest = Manifest(str(base_manifest_path))
    component_manifest_path = test_path / f'{component}_update_manifest.json'
    

    generate_component_manifest(
        base_manifest_path=base_manifest_path,
        component=component,
        version=test_versions[component],
        tarball_path=test_copied[component]["path"],
        serve_url=f"{localhost_url}/tarfiles",
        output_path=component_manifest_path
    )

    component_manifest = Manifest(str(component_manifest_path))

    component_version = getattr(component_manifest, f"current_{component}").version
    base_version = getattr(base_manifest, f"current_{component}").version

    if component_version == base_version:
        print(f"{component} test skipped - no version change ({component_version})")
        return True 

    build_base_version(str(base_manifest_path))
    
    moondream = MoondreamServer(
        str(executable_path),
        base_manifest_url=f"{localhost_url}/base_manifest.json",
        update_manifest_url=f"{localhost_url}/{component}_update_manifest.json"
    )

    try:
        moondream.start(use_update_manifest=False)
        versions = moondream.get_versions()
        assert versions[component] == component_version, f"Wrong initial version: {versions[component]}"
        moondream.restart(True) #starts with updated manifest!
        
        assert moondream.check_updates() == True, f"Check updates does not show any update!"

        moondream.update_component(component) # this will kill the process
        time.sleep(update_timeout) # TODO: get rid of arbitrary sleep amount (this is to give ample time for update!)

        moondream.start(use_update_manifest=True)
        final_versions = moondream.get_versions()

        assert final_versions[component] == component_version
        print("✅ Bootstrap update successful!")
        return True

    except Exception as e:
        print(f"❌ Bootstrap test failed: {e}")
        return False
    finally:
        moondream.stop()

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
    parent_dir = test_path.parent
    template_manifest_path = test_path / 'template_manifest.json'
    base_manifest_path = test_path / 'base_manifest.json'
    test_manifest_path = test_path / 'test_manifest.json'
    test_models_path = test_path / 'test_models.json'
    executable_path = parent_dir / 'output/moondream_station/moondream_station'

    localhost_port = args.port
    localhost_url = f"http://localhost:{localhost_port}"
    base_manifest_url = f"{localhost_url}/base_manifest.json"
    update_manifest_url = f"{localhost_url}/test_manifest.json"

    components = ["bootstrap", "hypervisor", "cli", "inference"]
       
    try:
        base_versions, test_versions = get_versions_from_args(args, components, test_path)
        
        print(f"\nBase versions: {base_versions}")
        print(f"\nTest versions: {test_versions}")

    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR: {e}")
    
    # now we will build the tarfiles using the test versions and base versions

    print(f"\n============ Building Tarfiles ================")
    print(f"Building base tarfiles")
    base_copied = create_and_copy_tarball(components=base_versions,
                                             test_folder=test_path
                                             )
    print(f"Copied base tarballs to {test_path}/tarfiles")
    
    print(f"\nBuilding test tarfiles")
    test_copied = create_and_copy_tarball(components=test_versions,
                            test_folder=test_path,
                                system="ubuntu")
    print(f"Copied test tarballs to {test_path}/tarfiles")

    # if we do not expect manifest to be present through the args, we need to build it.
    if not args.base_manifest:
        print(f"\n============ Building Base Manifest ================")
    generate_manifest(template_manifest_path=str(template_manifest_path),
                    tarball_info=base_copied,
                    serve_url=f"{localhost_url}/tarfiles",
                    output_path=str(base_manifest_path),
                    new_manifest_version="v0.0.1"
                    # no models.json in here cause we want to use the same as the template
                )
    
    if not args.test_manifest:
        print(f"\n============ Building Test Manifest ================")
    generate_manifest(template_manifest_path=str(base_manifest_path),
                    tarball_info=test_copied,
                    serve_url=f"{localhost_url}/tarfiles",
                    output_path=str(test_manifest_path),
                    models_json=str(test_models_path),
                    )

    # Start HTTP server at port
    print(f"\n============ Starting HTTP Server ================")
    server = serve_test_files(test_folder=test_path, port=localhost_port)
    
    # now we setup the individual manifests

    
if __name__ == "__main__":
    main()