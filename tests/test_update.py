import os, subprocess, shutil, json, threading, time
from pathlib import Path
import argparse
from http.server import SimpleHTTPRequestHandler, HTTPServer
from manifest_handler import Manifest, generate_component_manifest, update_manifest_urls, extract_versions_from_manifest
from server_handler import MoondreamServer

TEST_FOLDER = "test_files"
REPO_DIR = Path(__file__).parent.parent
DEFAULT_IMAGE_URL = "https://raw.githubusercontent.com/m87-labs/moondream-station/refs/heads/main/assets/md_logo_clean.png"

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

# ====================

def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Run Moondream Station update tests",
        formatter_class = argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument("--base-manifest", type=str, required=True,
                       help="Path to base manifest JSON file")
    parser.add_argument("--test-manifest", type=str, required=True,
                       help="Path to test manifest JSON file")
    parser.add_argument("--test", type=str, required=False,
                       help='Comma-separated list of components to test, e.g. "bootstrap,hypervisor,cli,inference"')
    parser.add_argument("--with-capability", action="store_true",
                       help="Run capability tests after successful updates")
    parser.add_argument("--preserve-tarfile-links", action="store_true",
                       help="Use existing tarfile URLs from manifests instead of building new ones")
    parser.add_argument("--port", type=int, default=8000,
                       help='Port at which to start the webserver to serve manifests and tarfiles.')
    parser.add_argument("--system", type=str, default='ubuntu',
                        help='System for which to build and test moondream-station for.')
    
    return parser.parse_args()

# ==================

def run_capability_tests(moondream_server, models, image_url=DEFAULT_IMAGE_URL):
    """Unified capability testing for any model list"""
    if not models:
        return True, []
    
    if isinstance(models, str):
        models = [models]
    
    print(f"\nTesting capabilities for {len(models)} models...")
    failed_models = []
    
    for model_name in models:
        print(f"\nTesting {model_name}...")
        
        if not moondream_server.use_model(model_name):
            print(f"  ❌ Failed to switch to model")
            failed_models.append((model_name, ["model_switch"]))
            continue
        
        cap_results = moondream_server.test_model_capabilities(model_name, image_url)
        
        if "error" in cap_results and not cap_results["error"]:
            print(f"  ⏭️  Skipped (no expected responses)")
        elif all(v for k,v in cap_results.items() if k != "error"):
            print(f"  ✅ All capabilities passed")
        else:
            failed_tests = [k for k,v in cap_results.items() if not v]
            print(f"  ❌ Failed: {', '.join(failed_tests)}")
            failed_models.append((model_name, failed_tests))
    
    success = len(failed_models) == 0
    return success, failed_models

def test_bootstrap_hypervisor_cli_update(component, 
                                         executable_path, 
                                         base_manifest_path, 
                                         test_manifest_path, 
                                         test_path, 
                                         localhost_url, 
                                         system, 
                                         with_capability:bool=False, 
                                         update_timeout:int=5):
    base_manifest = Manifest(str(base_manifest_path))
    test_manifest = Manifest(str(test_manifest_path))

    base_version = getattr(base_manifest, f"current_{component}").version
    test_version = getattr(test_manifest, f"current_{component}").version

    if test_version == base_version:
        print(f"{component} test skipped - no version change ({test_version})")
        return True 

    component_manifest_path = test_path / f'{component}_update_manifest.json'
    
    generate_component_manifest(
        base_manifest_path=base_manifest_path,
        test_manifest_path=test_manifest_path,
        component=component,
        output_path=component_manifest_path
    )

    build_base_version(str(base_manifest_path), system=system)
    
    moondream = MoondreamServer(
        str(executable_path),
        base_manifest_url=f"{localhost_url}/base_manifest.json",
        update_manifest_url=f"{localhost_url}/{component}_update_manifest.json"
    )

    try:
        moondream.start(use_update_manifest=False)
        versions = moondream.get_versions()
        assert versions[component] == base_version, f"Wrong initial version: {versions[component]}"
        moondream.restart(True) #starts with updated manifest!
        
        assert moondream.check_updates() == False, f"Check updates does not show any update!"

        moondream.update_component(component) # this will kill the process
        time.sleep(update_timeout) # TODO: get rid of arbitrary sleep amount (this is to give ample time for update!)

        moondream.start(use_update_manifest=True)
        final_versions = moondream.get_versions()

        assert final_versions[component] == test_version
        print(f"✅ {component} update successful!")
        if with_capability:
            model = moondream.get_current_model()
            success, failed = run_capability_tests(moondream, model, DEFAULT_IMAGE_URL)
            if not success:
                print(f"⚠️ Capability test failed")
                return False
        return True

    except Exception as e:
        print(f"❌ {component} test failed: {e}")
        return False
    finally:
        moondream.stop()

def test_inference_update(executable_path, 
                          base_manifest_path, 
                          test_manifest_path, 
                          localhost_url, 
                          system,
                          with_capability=False, 
                          update_timeout: int = 5):
    base_manifest = Manifest(str(base_manifest_path))
    test_manifest = Manifest(str(test_manifest_path))
    
    # Get inference versions
    base_version = list(base_manifest.inference_clients.keys())[0]
    test_version = list(test_manifest.inference_clients.keys())[0]
    
    if test_version == base_version:
        print(f"Inference test skipped - no version change ({test_version})")
        return True
    
    # Get all models from test manifest
    all_models = []
    for category, models in test_manifest.models.items():
        for model_name, model_info in models.items():
            all_models.append((category, model_name, model_info.get("inference_client")))
    
    # Find model with new inference version
    model_with_new_version = next(((cat, name) for cat, name, inf in all_models 
                                   if inf == test_version), None)
    
    if not model_with_new_version:
        print(f"ERROR: No models use inference {test_version}")
        return False
    
    build_base_version(str(base_manifest_path), system=system)
    
    moondream = MoondreamServer(
        str(executable_path),
        base_manifest_url=f"{localhost_url}/base_manifest.json",
        update_manifest_url=f"{localhost_url}/test_manifest.json"
    )
    
    try:
        # Start with test manifest
        moondream.start(use_update_manifest=True)
        
        # Get current model
        current_model = moondream.get_current_model()
        
        target_category, target_model = model_with_new_version
        
        # If already on target model, switch away and back
        if current_model == target_model:
            # Pick any other model from our list
            other_model = next(((cat, name) for cat, name, _ in all_models 
                               if name != target_model), None)
            if not other_model:
                print("ERROR: Need at least 2 models to test")
                return False
            
            print(f"Switching to {other_model[1]} then back to {target_model}...")
            moondream.use_model(other_model[1])
            time.sleep(2)
            moondream.use_model(target_model)
        else:
            print(f"Switching to {target_model} with inference {test_version}...")
            moondream.use_model(target_model)
        
        time.sleep(update_timeout)
        
        # Verify inference version changed
        final_versions = moondream.get_versions()
        assert final_versions["inference"] == test_version
        
        print(f"✅ Inference update successful!")

        if with_capability:
            all_models = moondream.get_model_list()
            success, failed_models = run_capability_tests(moondream, all_models, DEFAULT_IMAGE_URL)
            
            if not success:
                print(f"\n⚠️ {len(failed_models)} models had issues:")
                for model, tests in failed_models:
                    print(f"  - {model}: {', '.join(tests)}")
                return False
            else:
                print(f"\n✅ All {len(all_models)} models passed capability tests!")
        return True
        
    except Exception as e:
        print(f"❌ Inference test failed: {e}")
        return False
    finally:
        moondream.stop()

def test_model_update(executable_path, 
                      base_manifest_path, 
                      test_manifest_path, 
                      test_path, 
                      localhost_url, 
                      system,
                      update_timeout: int = 5):

    # Generate model update manifest
    model_manifest_path = test_path / 'model_update_manifest.json'
    generate_component_manifest(
        base_manifest_path=base_manifest_path,
        test_manifest_path=test_manifest_path,
        component="model",
        output_path=model_manifest_path
    )
    
    build_base_version(str(base_manifest_path), system=system)
    
    moondream = MoondreamServer(
        str(executable_path),
        base_manifest_url=f"{localhost_url}/base_manifest.json",
        update_manifest_url=f"{localhost_url}/model_update_manifest.json"
    )
    
    try:
        moondream.start(use_update_manifest=False)
        
        initial_models = moondream.get_model_list()
        print(f"Initial: {len(initial_models)} models")
        
        moondream.restart(use_update_manifest=True)
        
        has_updates = moondream.check_updates("model")
        assert has_updates, "No model updates detected!"
        
        moondream.update_component("model")
        time.sleep(update_timeout)
        
        moondream.start(use_update_manifest=True)
        
        updated_models = moondream.get_model_list()
        print(f"Updated: {len(updated_models)} models")
        
            # we always test all models with capabilities
        success, failed_models = run_capability_tests(moondream, updated_models, DEFAULT_IMAGE_URL)
        
        # Summary
        if not success:
            print(f"\n❌ Model update failed: {len(failed_models)}/{len(updated_models)} models had issues:")
            for model, tests in failed_models:
                print(f"  - {model}: {', '.join(tests)}")
            return False
        else:
            print(f"\n✅ Model update successful! All {len(updated_models)} models passed.")
            return True
        
    except Exception as e:
        print(f"❌ Model test failed: {e}")
        return False
    finally:
        moondream.stop()

def main():
    args = parse_arguments()
    valid_components = ["inference","bootstrap", "hypervisor", "model", "cli"]
    
    if args.test:
        test_components = [c.strip() for c in args.test.split(",")]
        invalid = [c for c in test_components if c not in valid_components]
        if invalid:
            print(f"ERROR: Invalid components specified: {invalid}")
            print(f"Valid components are: {valid_components}")
            return
    else:
        test_components = valid_components

    test_path = Path(__file__).parent / TEST_FOLDER
    executable_path = REPO_DIR / 'output/moondream_station/moondream_station'
    localhost_port = args.port
    localhost_url = f"http://localhost:{localhost_port}"
    
    # Load manifests using Manifest object
    base_manifest = Manifest(args.base_manifest)
    test_manifest = Manifest(args.test_manifest)

    latest_inference = max(base_manifest.inference_clients.keys(), 
                      key=lambda v: [int(x) for x in v[1:].split('.')])
    if not any(model.get("inference_client") == latest_inference 
            for category in base_manifest.models.values() 
            for model in category.values()):
        print(f"ERROR: No models in base manifest use latest inference client '{latest_inference}'")
        return
    
    if not args.preserve_tarfile_links:
        print(f"\n============ Building Tarfiles ================")
        
        # Extract versions from manifests
        base_versions = extract_versions_from_manifest(base_manifest)
        test_versions = extract_versions_from_manifest(test_manifest)
        
        print(f"Base versions: {base_versions}")
        print(f"Test versions: {test_versions}")
        
        # Build tarfiles for all components
        print(f"\nBuilding base tarfiles")
        base_copied = create_and_copy_tarball(
            components=base_versions,
            test_folder=test_path,
            system=args.system
        )
        
        print(f"\nBuilding test tarfiles")
        test_copied = create_and_copy_tarball(
            components=test_versions,
            test_folder=test_path,
            system=args.system
        )
        
        # Update manifest URLs to point to local tarfiles
        update_manifest_urls(base_manifest, base_copied, localhost_url)
        update_manifest_urls(test_manifest, test_copied, localhost_url)
    
    # Save manifests to test folder
    base_manifest_path = test_path / 'base_manifest.json'
    test_manifest_path = test_path / 'test_manifest.json'
    
    base_manifest.save(str(base_manifest_path))
    test_manifest.save(str(test_manifest_path))

    # Start HTTP server at port
    print(f"\n============ Starting HTTP Server ================")
    server = serve_test_files(test_folder=test_path, port=localhost_port)

    print(f"\n============ Running Component Tests ================")
    
    # Only test the specified components
    for component in test_components:
        print(f"\n--- Testing {component} update ---")
        if component == "model":
            test_model_update(
                executable_path=executable_path,
                base_manifest_path=base_manifest_path,
                test_manifest_path=test_manifest_path,
                test_path=test_path,
                localhost_url=localhost_url,
                system=args.system
            )
        elif component == "inference":
            test_inference_update(
                executable_path=executable_path,
                base_manifest_path=base_manifest_path,
                test_manifest_path=test_manifest_path,
                localhost_url=localhost_url,
                system=args.system,
                with_capability=args.with_capability
            )
        else:
            test_bootstrap_hypervisor_cli_update(
                component=component,
                executable_path=executable_path,
                base_manifest_path=base_manifest_path,
                test_manifest_path=test_manifest_path,
                test_path=test_path,
                localhost_url=localhost_url,
                system=args.system,
                with_capability=args.with_capability
            )
    
    print(f"\n============ Stopping HTTP Server ================")
    server.shutdown() #TODO: Make it so if anything happens, server shuts down!
    
if __name__ == "__main__":
    main()