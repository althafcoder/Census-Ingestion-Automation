import json
from datetime import datetime
from typing import Dict, Any, List
from .models import AuditRun

class AuditTracker:
    def __init__(self, run_id: str, client: str = "prestige"):
        self.run = AuditRun(
            run_id=run_id,
            client=client,
            engine_version="2.0.0",
            config_version="1.0.0",
            plan_mapping_version="1.0.0",
            coverage_mapping_version="1.0.0",
            matching_threshold_version="1.0.0",
            timestamp=datetime.utcnow().isoformat()
        )
        self.events: List[Dict[str, Any]] = []

    def log_event(self, stage: str, details: Dict[str, Any]):
        self.events.append({
            "timestamp": datetime.utcnow().isoformat(),
            "stage": stage,
            "details": details
        })

    def save(self, filepath: str):
        data = {
            "run_info": self.run.__dict__,
            "events": self.events
        }
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
