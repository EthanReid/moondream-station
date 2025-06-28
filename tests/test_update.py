import os, subprocess, shutil, json, threading
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, HTTPServer
from manifest_handler import Manifest, InferenceClient
from server_handler import MoondreamServer

TARBALL_BASE = "output"
TEST_FOLDER = "test_files"

def create_and_extract_tarball( #TODO: Change this name to create and copy tarballs!
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

def model_uses_version(models, version):
    return any(
        model.get("inference_client") == version
        for category in models.values()
        for model in category.values()
    )

def generate_manifest(base_manifest_path: str,
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
    
    manifest = Manifest(base_manifest_path)
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

# ====================


def main():

    test_path = Path(__file__).parent / TEST_FOLDER
    base_manifest_path = test_path / 'base_manifest.json'
    

    # first extract the components from either the args or from the test_manifest file

    # say we get this from that
    test_components = {
        "bootstrap": "v0.0.2",
        "hypervisor": "v0.0.1",
        "cli": "v0.0.3",
        "inference": "v0.0.2"
    }

    # we also need the base components.
    # we need to fetch them from the base_manifest.
    # TODO: Implement getting them from the base manifest
    # say these are the base components:
    base_components = {
        "bootstrap": "v0.0.1",
        "hypervisor": "v0.0.1",
        "cli": "v0.0.1",
        "inference": "v0.0.1"
    }

    
    test_copied = create_and_extract_tarball(components=test_components,
                            test_folder=test_path,
                                system="ubuntu")
    print(test_copied)

    # build base after test so that we start with base build
    base_copied = create_and_extract_tarball(components=base_components,
                                             test_folder=test_path
                                             )
    
    print(base_copied)

    # build_base_version(base_manifest_path=str(base_manifest_path)) #TODO: We don't need this anymore?

    generate_manifest(base_manifest_path=str(base_manifest_path),
                    tarball_info=test_copied,
                    serve_url="http://localhost:8000/tarfiles",
                    output_path=str(test_path / "test_manifest.json"),
                    models_json=str(test_path / "test_models.json"),
                    )

    server = serve_test_files(test_folder=test_path, port=8000)
    import requests
    response = requests.get("http://localhost:8000/base_manifest.json")
    print(response.json())
    exe_path = "/home/snow/projects/moondream-station-2/output/moondream_station/moondream_station"

    moondream = MoondreamServer(exe_path, str(test_path / "base_manifest.json"), str(test_path / "test_manifest.json"))
    moondream.start()
    versions = moondream.get_versions()
    print(versions)
    moondream.restart()
    notes = ["Hello World, this is the Moondream Station manifest."]
    moondream.pull_manifest(notes) # TODO: Is this necessary?
    # TODO: check updates!
    moondream.update_component("bootstrap") #update component kills moondream!
    moondream.start(True)
    new_versions = moondream.get_versions()
    print(new_versions)
    moondream.stop()
    server.shutdown()  # Shutdown the server after use

if __name__ == "__main__":
    main()