"""
main.py
-------
CLI entry point: runs the full extract -> normalize -> reconcile -> fill
pipeline end to end.

Usage
~~~~~
    python src/main.py \\
        --pdf input/Benefits_Invoice_-_May_2026.pdf \\
        --census input/Census.xlsx \\
        --template input/prestige_templet_-_Format.xlsx \\
        --output output/Prestige_Census_Filled.xlsx \\
        --report output/reconciliation_report.json

Run with no arguments to use the defaults in config.py (matches the
sample files shipped in input/).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import config
from census_extractor import extract_census
from pdf_extractor import extract_employee_benefits, extract_invoice_summary
from reconcile import match_employees
from fill_template import fill_template
from report import build_report, write_json_report, write_csv_report


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Census/PDF-invoice reconciliation pipeline")
    p.add_argument("--pdf", type=Path, default=config.DEFAULT_PDF)
    p.add_argument("--census", type=Path, default=config.DEFAULT_CENSUS_XLSX)
    p.add_argument("--template", type=Path, default=config.DEFAULT_TEMPLATE_XLSX)
    p.add_argument("--output", type=Path, default=config.DEFAULT_FILLED_OUTPUT)
    p.add_argument("--report-json", type=Path, default=config.DEFAULT_RECONCILIATION_REPORT)
    p.add_argument("--report-csv", type=Path, default=config.DEFAULT_RECONCILIATION_CSV)
    return p.parse_args(argv)


def run(args: argparse.Namespace) -> dict:
    for path, label in [(args.pdf, "PDF invoice"), (args.census, "Census workbook"), (args.template, "Template")]:
        if not path.exists():
            raise FileNotFoundError(f"{label} not found at: {path}")

    print(f"[1/5] Extracting census demographics from {args.census.name} ...")
    census_rows = extract_census(args.census)
    print(f"      -> {len(census_rows)} census rows "
          f"({sum(1 for r in census_rows if not r.is_dependent)} employees, "
          f"{sum(1 for r in census_rows if r.is_dependent)} dependents)")

    print(f"[2/5] Extracting per-employee benefits from {args.pdf.name} ...")
    pdf_employees = extract_employee_benefits(args.pdf)
    invoice_summary = extract_invoice_summary(args.pdf)
    print(f"      -> {len(pdf_employees)} employee blocks parsed from invoice")
    print(f"      -> invoice summary: {invoice_summary}")

    print("[3/5] Matching + reconciling census rows against invoice data ...")
    merged_records, match_stats = match_employees(census_rows, pdf_employees)
    print(f"      -> exact matches: {match_stats['exact_matches']}, "
          f"fuzzy matches: {match_stats['fuzzy_matches']}, "
          f"unmatched census employees: {len(match_stats['unmatched_census_employees'])}")

    print(f"[4/5] Filling Prestige template -> {args.output}")
    fill_template(merged_records, args.template, args.output)

    print(f"[5/5] Writing reconciliation report -> {args.report_json} / {args.report_csv}")
    report = build_report(merged_records, match_stats, invoice_summary)
    write_json_report(report, args.report_json)
    write_csv_report(report, args.report_csv)

    print("\nDone.")
    print(f"  Filled template : {args.output}")
    print(f"  JSON report     : {args.report_json}")
    print(f"  CSV report      : {args.report_csv}")
    print(f"  Records with discrepancies: {report['records_with_discrepancies']} / {report['total_records']}")

    return report


if __name__ == "__main__":
    sys.exit(0 if run(parse_args()) else 1)
