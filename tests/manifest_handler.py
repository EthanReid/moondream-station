import json
import requests
from pathlib import Path
from dataclasses import dataclass

@dataclass
class Component:
    version: str
    url: str

@dataclass
class InferenceClient:
    date: str
    url: str

class Manifest:
    def __init__(self, manifest_source: str):
        # Load JSON
        data = self._load_manifest(manifest_source)
        
        # Map to attributes
        self.manifest_version = data["manifest_version"]
        self.manifest_date = data["manifest_date"]
        self.notes = data.get("notes", [])
        
        # Components
        self.current_bootstrap = Component(**data["current_bootstrap"])
        self.current_cli = Component(**data["current_cli"])
        self.current_hypervisor = Component(**data["current_hypervisor"])
        
        self.models = data["models"] #This gets loaded from models.json!
        
        # Inference clients
        self.inference_clients = {
            version: InferenceClient(**info) 
            for version, info in data["inference_clients"].items()
        }
    
    def _load_manifest(self, manifest_source: str) -> dict:
        """Load manifest from a JSON file or string."""
        if isinstance(manifest_source, str):
            if manifest_source.startswith(('http://', 'https://')):
                response = requests.get(manifest_source, timeout=10)
                response.raise_for_status()
                return response.json()
            else:
                with open(manifest_source, 'r') as f:
                    return json.load(f)
        elif isinstance(manifest_source, dict):
            return manifest_source
        else:
            raise ValueError("Manifest source must be a url, file path or a dict.")
    
    def to_dict(self) -> dict:
        """Convert back to JSON-serializable dict."""
        return {
            "manifest_version": self.manifest_version,
            "manifest_date": self.manifest_date,
            "current_bootstrap": {
                "version": self.current_bootstrap.version,
                "url": self.current_bootstrap.url
            },
            "current_cli": {
                "version": self.current_cli.version,
                "url": self.current_cli.url
            },
            "current_hypervisor": {
                "version": self.current_hypervisor.version,
                "url": self.current_hypervisor.url
            },
            "models": self.models,
            "inference_clients": {
                v: {"date": ic.date, "url": ic.url}
                for v, ic in self.inference_clients.items()
            },
            "notes": self.notes
        }
    
    def save(self, path: str):
        """Save manifest to file."""
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

def generate_component_manifest(
    base_manifest_path: Path,
    test_manifest_path: Path,  # Add this parameter
    component: str,
    output_path: Path
) -> Path:
    """Generate manifest with update for single component only."""
    manifest = Manifest(str(base_manifest_path))
    test_manifest = Manifest(str(test_manifest_path))
    
    if component == "model":
        # For model testing, use inference clients from test manifest
        manifest.inference_clients = test_manifest.inference_clients
        manifest.models = test_manifest.models
    else:
        test_component = getattr(test_manifest, f"current_{component}")
        current_component = getattr(manifest, f"current_{component}")
        current_component.version = test_component.version
        current_component.url = test_component.url
    
    manifest.save(str(output_path))
    return output_path

def extract_versions_from_manifest(manifest: Manifest) -> dict[str, str]:
    """Extract component versions from a manifest."""
    versions = {
        "bootstrap": manifest.current_bootstrap.version,
        "cli": manifest.current_cli.version,
        "hypervisor": manifest.current_hypervisor.version,
    }
    # For inference, get the first/latest version
    if manifest.inference_clients:
        versions["inference"] = list(manifest.inference_clients.keys())[0]
    return versions

def update_manifest_urls(manifest: Manifest, tarball_info: dict, serve_url: str) -> None:
    """Update manifest URLs to point to local tarfiles."""
    for component, info in tarball_info.items():
        version = info["version"]
        tarball_name = Path(info["path"]).name
        url = f"{serve_url}/tarfiles/{tarball_name}"
        
        if component == "inference":
            # Update ALL inference clients to use local URLs
            for inf_version in manifest.inference_clients.keys():
                # Construct expected tarball name for this version
                expected_tarball = f"inference_bootstrap_{inf_version}.tar.gz"
                expected_url = f"{serve_url}/tarfiles/{expected_tarball}"
                # Check if this tarball exists locally
                if (Path(info["path"]).parent / expected_tarball).exists():
                    manifest.inference_clients[inf_version].url = expected_url
        else:
            current_component = getattr(manifest, f"current_{component}")
            if current_component.version == version:
                current_component.url = url