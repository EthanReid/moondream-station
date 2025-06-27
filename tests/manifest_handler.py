import json
import requests
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
        
        # Models (#TODO : we will keep this as a dict for now!)
        self.models = data["models"]
        
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
