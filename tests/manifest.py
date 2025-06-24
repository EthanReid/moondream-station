
import shutil
import json
import logging
from pathlib import Path
from utils import DebugTracer
from config import Config

MANIFEST_DIR = "./test_manifests"

class Manifest:
    @staticmethod
    @DebugTracer.log_operation
    def update_version(version):
        version_file = Manifest._get_version_path(version)
        manifest_file = Manifest._get_current_path()
        
        if not version_file.exists():
            raise FileNotFoundError(f"Version manifest {version_file} not found")
        
        shutil.copy2(version_file, manifest_file)
        logging.debug(f"Updated manifest.json to version {version:03d}")
    
    @staticmethod
    @DebugTracer.log_operation
    def verify_environment():
        DebugTracer.log(f"Verifying test environment in {MANIFEST_DIR}", "MANIFEST")
        manifest_dir = Path(MANIFEST_DIR)
        if not manifest_dir.exists():
            DebugTracer.log(f"Manifest directory not found: {MANIFEST_DIR}", "MANIFEST")
            raise FileNotFoundError(f"Manifest directory {MANIFEST_DIR} not found")
        
        required = ['manifest_v001.json', 'manifest_v002.json', 'manifest_v003.json', 'manifest_v004.json', 'manifest_v005.json']
        missing = []
        for manifest_file in required:
            file_path = manifest_dir / manifest_file
            if not file_path.exists():
                missing.append(manifest_file)
                DebugTracer.log(f"Missing required file: {file_path}", "MANIFEST")
            else:
                DebugTracer.log(f"Found required file: {file_path}", "MANIFEST")
        
        if missing:
            DebugTracer.log(f"Missing files: {missing}", "MANIFEST")
            raise FileNotFoundError(f"Missing manifest files: {missing}")
        
        DebugTracer.log("Test environment verification completed", "MANIFEST")
        logging.debug("Test environment verified")

    @staticmethod
    def _get_version_path(version):
        return Path(MANIFEST_DIR) / f"manifest_v{version:03d}.json"

    @staticmethod  
    def _get_current_path():
        return Path(MANIFEST_DIR) / "manifest.json"

    @staticmethod
    def _check_files_exist(file_paths):
        missing = [path for path in file_paths if not path.exists()]
        if missing:
            raise FileNotFoundError(f"Missing manifest files: {[p.name for p in missing]}")

    @staticmethod
    def get_expected_versions(version):
        try:
            with open(Manifest._get_version_path(version)) as f:
                data = json.load(f)
            
            # Use comprehension for version fields
            expected = {field: data.get(f'{field}_version') for field in Config.MANIFEST_VERSIONS}
            expected['models'] = data.get('models', {})
            
            logging.debug(f"Expected versions from v{version:03d}: {expected}")
            return expected
            
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.warning(f"Failed to read expected versions from v{version:03d}: {e}")
            return {}