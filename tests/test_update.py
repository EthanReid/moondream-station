import os, subprocess, shutil, json, threading
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, HTTPServer
from manifest_handler import Manifest, InferenceClient

TARBALL_BASE = "output"
TEST_FOLDER = "test_files"

def create_and_extract_tarball(
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
    parent_dir = Path(__file__).parent.parent

    if app_dir is not None:
        app_path = Path(app_dir).resolve()
    else:
        app_path = parent_dir / "app"

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
        
    # for each component, we run the build.sh script with the given version and system
    for component, version in components.items():
        build_name = component
        if component == "bootstrap" or component == "inference":
            build_name = "dev"
        
        cmd = ['bash', 'build.sh', build_name, system, f'--version={version}','--build-clean']
        
        print(f"Building {component} at {version} with command : {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=app_path, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Build failed for {component} with version {version}: {result.stderr}")
        print(f"Build output for {component}:\n{result.stdout}")

        # now we copy the tarballs to the temp folder
        tarball_name = f"{tarfile_map[component]}.tar.gz"
        tarball_versioned_name = f"{tarfile_map[component]}_{version}.tar.gz"
        
        if base_folder is None:
            tarball_path = parent_dir / "output" / tarball_name
            search_location = parent_dir / "output"
        else:
            tarball_path = base_folder / tarball_name  
            search_location = base_folder

        if not os.path.exists(tarball_path):
            raise FileNotFoundError(f"Tarball {tarball_name} not found in {search_location}")
        
        # copy the tarball to the temp folder
        dest_folder = test_folder / 'tarfiles'
        dest_folder.mkdir(parents=True, exist_ok=True)
        tarball_versioned_path = dest_folder / tarball_versioned_name

        shutil.copy2(tarball_path, tarball_versioned_path) #TODO add checking copy success
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

def generate_manifest(base_manifest: str, 
                      tarball_info: dict[str, dict[str, str]],
                      serve_url: str,
                      models_json: str = None,
                      output_path: str = None,
                      new_manifest_version: str = "v0.0.2") -> Manifest:
    """
    Generate a manifest based on the base manifest and the provided tarball information.
    Args:
        base_manifest (str): Path to the base manifest JSON file.
        tarball_info (dict): A dictionary containing component names as keys and their version and path
                                as values. Example: {"bootstrap": {"version": "v0.0.2", "path": "path/to/tarball"}}
        serve_url (str): The URL where the tarballs will be served.
        models_json (str, optional): Path to a JSON file containing models to be included in the manifest.
        output_path (str, optional): Path where the generated manifest will be saved.
        new_manifest_version (str, optional): The version of the manifest to be generated. Defaults to "v0.0.2".
    Returns:
        Manifest: An instance of the Manifest class populated with the provided information.
    """
    
    manifest = Manifest(base_manifest)
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

    components = {
        "bootstrap": "v0.0.2",
        "hypervisor": "v0.0.1",
        "cli": "v0.0.3",
        "inference": "v0.0.2"
    }

    test_path = Path(__file__).parent / TEST_FOLDER
    copied = create_and_extract_tarball(components=components,
                            test_folder=test_path,
                                system="ubuntu")
    print(copied)
    base_path = "/home/snow/projects/moondream-station-2/tests/test_files/base_manifest.json"
    print (f"Base manifest path: {test_path / 'base_manifest.json'}")
    generate_manifest(base_manifest=str(test_path / "base_manifest.json"),
                    tarball_info=copied,
                    serve_url="http://localhost:8000/tarfiles",
                    output_path=str(test_path / "test_manifest.json"),
                    models_json=str(test_path / "test_models.json"),
                    )

    server = serve_test_files(test_folder=test_path, port=8000)
    import requests
    response = requests.get("http://localhost:8000/base_manifest.json")
    print(response.json())
    server.shutdown()  # Shutdown the server after use

if __name__ == "__main__":
    main()