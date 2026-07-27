"""
report.py
---------
Builds the human- and machine-readable reconciliation report summarizing:
  - overall match statistics (exact / fuzzy / unmatched)
  - per-record discrepancies
  - invoice-level summary (from the PDF's page-1 account summary)
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from reconcile import MergedRecord


def build_report(
    records: list[MergedRecord],
    match_stats: dict,
    invoice_summary: dict,
) -> dict:
    total_discrepancies = sum(len(r.discrepancies) for r in records)
    per_record = []
    for r in records:
        if not r.discrepancies:
            continue
        per_record.append(
            {
                "row_no": r.census_row.row_no,
                "first_name": r.census_row.first_name,
                "last_name": r.census_row.last_name,
                "relationship": r.census_row.relationship,
                "match_method": r.match_method,
                "issues": r.discrepancies,
            }
        )

    return {
        "invoice_summary": invoice_summary,
        "match_stats": match_stats,
        "total_records": len(records),
        "records_with_discrepancies": len(per_record),
        "total_discrepancy_count": total_discrepancies,
        "discrepancies": per_record,
    }


def write_json_report(report: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str))
    return path


def write_csv_report(report: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["row_no", "first_name", "last_name", "relationship", "match_method", "issue"])
        for item in report["discrepancies"]:
            for issue in item["issues"]:
                writer.writerow(
                    [item["row_no"], item["first_name"], item["last_name"],
                     item["relationship"], item["match_method"], issue]
                )
    return path
