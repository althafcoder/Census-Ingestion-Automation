"""
main.py
-------
CLI entry point: runs the full extract -> normalize -> reconcile -> fill
pipeline end to end.

Usage
~~~~~
    python main.py \\
        --pdf input/Benefits_Invoice_-_May_2026.pdf \\
        --census input/Census.xlsx \\
        --template input/prestige_templet_-_Format.xlsx

Run with no arguments to use the defaults in config.py.
The script will prompt for any missing input files.
All files (input copies, extracted data, output) are stored under processing/.
"""
from __future__ import annotations

# IMPORTANT: Import torch first on Windows to prevent DLL initialization conflicts (WinError 1114)
# if other C-extensions like PyMuPDF (fitz) are loaded before it.
try:
    import torch
except ImportError:
    pass

import argparse
import shutil
import sys
from pathlib import Path

import config
from census_extractor import extract_census, save_census_to_excel
from pdf_extractor import extract_employee_benefits
from reconcile import match_employees
from fill_template import fill_template
from report import build_report, write_json_report, write_csv_report


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Census/PDF-invoice reconciliation pipeline")
    p.add_argument("--pdf", type=Path, nargs="+", default=None)
    p.add_argument("--census", type=Path, default=None)
    p.add_argument("--template", type=Path, default=config.DEFAULT_TEMPLATE_XLSX)
    p.add_argument("--output", type=Path, default=config.DEFAULT_FILLED_OUTPUT)
    p.add_argument("--report-json", type=Path, default=config.DEFAULT_RECONCILIATION_REPORT)
    p.add_argument("--report-csv", type=Path, default=config.DEFAULT_RECONCILIATION_CSV)
    p.add_argument("--pdf-extracted", type=Path, default=config.DEFAULT_PDF_EXTRACTED)
    p.add_argument("--census-extracted", type=Path, default=config.DEFAULT_CENSUS_EXTRACTED)
    return p.parse_args(argv)


def _prompt_path(label: str, extensions: list[str] | None = None) -> Path:
    """Always prompt the user to paste a file path."""
    ext_hint = f" ({', '.join(extensions)})" if extensions else ""
    while True:
        user_input = input(f"  -> Paste the full path for the {label}{ext_hint}: ").strip().strip('"').strip("'")
        if not user_input:
            continue
        new_path = Path(user_input)
        if new_path.exists():
            return new_path
        print(f"     File not found at: {new_path}. Please try again.")


def _prompt_paths(label: str) -> list[Path]:
    """Always prompt the user to paste PDF file path(s)."""
    while True:
        import shlex
        user_input = input(f"  -> Paste the full path(s) for the {label} (space separated, quote if spaces): ").strip()
        if not user_input:
            continue
        new_paths = []
        
        try:
            tokens = shlex.split(user_input, posix=False)
        except ValueError:
            tokens = [user_input]
            
        for token in tokens:
            p = Path(token.strip('"').strip("'"))
            if p.is_dir():
                new_paths.extend(list(p.glob("*.pdf")))
            elif p.exists():
                new_paths.append(p)
                
        # Fallback: if they pasted a single unquoted path containing spaces
        if not new_paths:
            p = Path(user_input.strip('"').strip("'"))
            if p.is_dir():
                new_paths.extend(list(p.glob("*.pdf")))
            elif p.exists():
                new_paths.append(p)

        if new_paths:
            return new_paths
        print(f"     No valid files found. Please try again.")


def _copy_input_file(source: Path, input_dir: Path) -> Path:
    """Copy source file into the processing/input/ directory."""
    input_dir.mkdir(parents=True, exist_ok=True)
    dest = input_dir / source.name
    if source.resolve() != dest.resolve():
        shutil.copy2(source, dest)
    return dest


def run(args: argparse.Namespace) -> dict:
    # Always prompt for input files if not provided via CLI
    print("\n=== Census Ingestion Automation ===")
    
    if args.pdf:
        pdf_paths = []
        for p in args.pdf:
            if p.is_dir():
                pdf_paths.extend(list(p.glob("*.pdf")))
            elif p.exists():
                pdf_paths.append(p)
        if not pdf_paths:
            print("\n  Invoice PDF(s):")
            pdf_paths = _prompt_paths("PDF invoice(s)")
    else:
        print("\n  Invoice PDF(s):")
        pdf_paths = _prompt_paths("PDF invoice(s)")
    
    if args.census and args.census.exists():
        census_path = args.census
    else:
        print("\n  Census file:")
        census_path = _prompt_path("Census workbook", [".xlsx", ".xls", ".csv"])
    
    template_path = args.template
    if not template_path.exists():
        print("\n  Template:")
        template_path = _prompt_path("Template", [".xlsx"])

    # Copy input files into processing/input/ for traceability
    print("\n[0/6] Setting up processing folder ...")
    for p in pdf_paths:
        _copy_input_file(p, config.INPUT_DIR)
    _copy_input_file(census_path, config.INPUT_DIR)
    _copy_input_file(template_path, config.INPUT_DIR)
    print(f"      -> Input files copied to {config.INPUT_DIR}")

    # Dynamically set output filenames if defaults are used
    first_pdf_name = pdf_paths[0].stem if pdf_paths else "Unknown_Invoice"
    prefix = f"{first_pdf_name}" if len(pdf_paths) == 1 else f"{first_pdf_name}_and_{len(pdf_paths)-1}_others"
    
    if args.output == config.DEFAULT_FILLED_OUTPUT:
        args.output = config.OUTPUT_DIR / f"{prefix}_Filled.xlsx"
        
    if args.pdf_extracted == config.DEFAULT_PDF_EXTRACTED:
        args.pdf_extracted = config.EXTRACTED_DIR / f"{prefix}_pdf_extracted.xlsx"
        
    if args.report_json == config.DEFAULT_RECONCILIATION_REPORT:
        args.report_json = config.OUTPUT_DIR / f"{prefix}_reconciliation_report.json"
        
    if args.report_csv == config.DEFAULT_RECONCILIATION_CSV:
        args.report_csv = config.OUTPUT_DIR / f"{prefix}_reconciliation_report.csv"
        
    if args.census_extracted == config.DEFAULT_CENSUS_EXTRACTED:
        args.census_extracted = config.EXTRACTED_DIR / f"{census_path.stem}_census_extracted.xlsx"
    # Step 1: Extract census
    print(f"\n[1/6] Extracting census demographics from {census_path.name} ...")
    census_rows = extract_census(census_path)
    print(f"      -> {len(census_rows)} census rows "
          f"({sum(1 for r in census_rows if not r.is_dependent)} employees, "
          f"{sum(1 for r in census_rows if r.is_dependent)} dependents)")

    # Save structured extraction
    save_census_to_excel(census_rows, args.census_extracted)
    print(f"      -> Saved structured extraction: {args.census_extracted}")

    print(f"\n[2/6] Extracting per-employee benefits from {len(pdf_paths)} invoice(s) ...")
    all_pdf_employees = []
    for p in pdf_paths:
        dump_raw = config.EXTRACTED_DIR / f"{p.stem}_raw_text.txt"
        emps = extract_employee_benefits(p, dump_raw_text_path=dump_raw)
        all_pdf_employees.append(emps)
        print(f"      -> Dumped raw extracted text for human validation: {dump_raw}")
            
    total_pdf_blocks = sum(len(e) for e in all_pdf_employees)
    print(f"      -> {total_pdf_blocks} employee blocks parsed from invoices")

    # Removed: The intermediate PDF extraction output to Excel is no longer required or generated.
    # Step 3: Match + reconcile
    print("\n[3/6] Matching + reconciling census rows against invoice data ...")
    merged_records, match_stats = match_employees(census_rows, all_pdf_employees)
    print(f"      -> exact matches: {match_stats['exact_matches']}, "
          f"fuzzy matches: {match_stats['fuzzy_matches']}, "
          f"unmatched census employees: {len(match_stats['unmatched_census_employees'])}")

    # Step 4: Fill template
    print(f"\n[4/6] Filling Prestige template -> {args.output}")
    fill_template(merged_records, template_path, args.output)

    # Step 5: Write reports
    print(f"\n[5/6] Writing reconciliation report -> {args.report_json} / {args.report_csv}")
    report = build_report(merged_records, match_stats)
    write_json_report(report, args.report_json)
    write_csv_report(report, args.report_csv)

    print("\n[6/6] Done!")
    print(f"  Processing folder : {config.PROCESSING_DIR}")
    print(f"  Filled template   : {args.output}")
    print(f"  Census extraction : {args.census_extracted}")
    print(f"  JSON report       : {args.report_json}")
    print(f"  CSV report        : {args.report_csv}")
    print(f"  Records with discrepancies: {report['records_with_discrepancies']} / {report['total_records']}")

    return report


if __name__ == "__main__":
    sys.exit(0 if run(parse_args()) else 1)
