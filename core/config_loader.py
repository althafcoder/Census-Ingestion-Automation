import json
from pathlib import Path
from typing import Any, Dict

class ClientConfig:
    def __init__(self, client_name: str, base_dir: Path):
        self.client_name = client_name
        self.client_dir = base_dir / "clients" / client_name
        
        self.config = self._load_json("config.json")
        self.census_mapping = self._load_json("census_mapping.json")
        self.plan_mapping = self._load_json("plan_mapping.json")
        self.coverage_mapping = self._load_json("coverage_mapping.json")
        self.invoice_mapping = self._load_json("invoice_mapping.json")

    def _load_json(self, filename: str) -> Dict[str, Any]:
        filepath = self.client_dir / filename
        if filepath.exists():
            with open(filepath, 'r') as f:
                return json.load(f)
        return {}

    def get_template_path(self) -> Path:
        return self.client_dir / "output_template.xlsx"
