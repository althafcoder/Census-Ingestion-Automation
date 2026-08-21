import sys
import argparse
import traceback
from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime
import json

from main import run_legacy
from core.engine import NewEnginePipeline

class EngineRouter:
    @staticmethod
    def route_request(mode: str, args: argparse.Namespace) -> Dict[str, Any]:
        """
        Routes the execution based on the configured engine_mode.
        Supported modes: 'legacy', 'shadow', 'new'
        """
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        mode = mode.lower()
        
        if mode == "legacy":
            return run_legacy(args)
            
        elif mode == "shadow":
            # 1. Run legacy (Production Truth)
            try:
                legacy_result = run_legacy(args)
            except Exception as e:
                # If legacy fails, we bubble up the error since it is production truth
                raise e

            # 2. Run new engine (Shadow)
            new_result = None
            shadow_error = None
            try:
                # Mock output paths for shadow to avoid overwriting legacy outputs if they share a directory
                shadow_json = Path(f"reports/shadow/{run_id}/new_result.json")
                shadow_csv = Path(f"reports/shadow/{run_id}/new_result.csv")
                shadow_json.parent.mkdir(parents=True, exist_ok=True)
                
                pdf_paths = args.pdf or []
                census_path = args.census
                
                if census_path and pdf_paths:
                    new_result = NewEnginePipeline.run(
                        census_path=census_path,
                        pdf_paths=pdf_paths,
                        output_json=shadow_json,
                        output_csv=shadow_csv
                    )
            except Exception as e:
                shadow_error = traceback.format_exc()
                print(f"[SHADOW MODE WARNING] New engine failed during shadow execution:\n{shadow_error}")
            
            # 3. Run comparison
            try:
                from migration.shadow_comparator import ShadowComparator
                ShadowComparator.compare_runs(run_id, legacy_result, new_result, shadow_error)
            except Exception as e:
                print(f"[SHADOW MODE WARNING] Shadow comparator failed:\n{traceback.format_exc()}")
                
            # 4. ALWAYS return legacy result
            return legacy_result
            
        elif mode == "new":
            pdf_paths = args.pdf or []
            census_path = args.census
            return NewEnginePipeline.run(
                census_path=census_path,
                pdf_paths=pdf_paths,
                output_json=args.report_json,
                output_csv=args.report_csv,
                output_excel=args.output,
                template_path=args.template
            )
            
        else:
            raise ValueError(f"Unknown engine mode: {mode}")
