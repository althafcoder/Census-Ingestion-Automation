"""
config.py
---------
Central configuration: file paths, template layout constants, and the
field <-> column mapping between extracted data and the Prestige template.

Everything here is deliberately declarative so that the pipeline can be
retargeted to a new plan year / new file names without touching logic code.
"""
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (override via CLI args in main.py; these are sane local defaults)
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"

DEFAULT_PDF = INPUT_DIR / "Benefits_Invoice_-_May_2026.pdf"
DEFAULT_CENSUS_XLSX = INPUT_DIR / "Census.xlsx"
DEFAULT_TEMPLATE_XLSX = INPUT_DIR / "prestige_templet_-_Format.xlsx"

DEFAULT_FILLED_OUTPUT = OUTPUT_DIR / "Prestige_Census_Filled.xlsx"
DEFAULT_RECONCILIATION_REPORT = OUTPUT_DIR / "reconciliation_report.json"
DEFAULT_RECONCILIATION_CSV = OUTPUT_DIR / "reconciliation_report.csv"

# ---------------------------------------------------------------------------
# Prestige template layout
# ---------------------------------------------------------------------------
# The template's header row (with column titles) and the first data row are
# fixed by the vendor's format -- verified against the sample file.
TEMPLATE_SHEET_NAME = "Census"
TEMPLATE_HEADER_ROW = 24
TEMPLATE_FIRST_DATA_ROW = 26
TEMPLATE_FIRST_DATA_COL = 1  # column A holds the row index / employee no.

# Column letters -> logical field name, in template order (col A = 1).
# This is the authoritative "data model" for one output row.
TEMPLATE_COLUMNS = [
    ("row_no", "A"),
    ("first_name", "B"),
    ("last_name", "C"),
    ("gender", "D"),
    ("dob", "E"),
    ("home_zip", "F"),
    ("relationship", "G"),
    ("dependent_of_employee_number", "H"),
    ("medical_coverage_tier", "I"),
    ("cobra", "J"),
    ("medical_plan_enrolled", "K"),
    ("medical_plan_price", "L"),
    ("dental_coverage_tier", "M"),
    ("dental_plan_enrolled", "N"),
    ("dental_plan_price", "O"),
    ("vision_coverage_tier", "P"),
    ("vision_plan_enrolled", "Q"),
    ("vision_plan_price", "R"),
    ("life_plan_name", "S"),
    ("life_benefit", "T"),
    ("life_rate", "U"),
    ("ltd_plan", "V"),
    ("ltd_benefit", "W"),
    ("ltd_rate", "X"),
    ("std_plan", "Y"),
    ("std_benefit", "Z"),
    ("std_rate", "AA"),
    ("work_state", "AB"),
    ("job_title", "AC"),
    ("workers_comp_code", "AD"),
    ("annual_salary", "AE"),
    ("ft_pt", "AF"),
]
FIELD_TO_COL = {name: col for name, col in TEMPLATE_COLUMNS}

# ---------------------------------------------------------------------------
# Census.xlsx (source demographic file) layout
# ---------------------------------------------------------------------------
CENSUS_SHEET_NAME = "Census"
CENSUS_HEADER_ROW = 24
CENSUS_FIRST_DATA_ROW = 26

# Field name -> 1-based column index in Census.xlsx (verified against sample)
CENSUS_FIELD_COLS = {
    "row_no": 1,
    "first_name": 2,
    "last_name": 3,
    "gender": 4,
    "dob": 5,
    "home_zip": 6,
    "relationship": 7,
    "dependent_of_employee_number": 8,
    "medical_coverage_tier": 9,
    "cobra": 10,
    # 11, 12 unused in raw census (medical plan/price not yet known)
    "dental_coverage_tier": 13,
    "dental_plan_enrolled": 14,
    "dental_plan_price": 15,
    "vision_coverage_tier": 16,
    "vision_plan_enrolled": 17,
    "vision_plan_price": 18,
    "life_plan_name": 19,
    "life_benefit": 20,
    "life_rate": 21,
    "ltd_plan": 22,
    "ltd_benefit": 23,
    "ltd_rate": 24,
    "std_plan": 25,
    "std_benefit": 26,
    "std_rate": 27,
    "work_state": 28,
    "job_title": 29,
    "workers_comp_code": 30,
    "annual_salary": 31,
    "ft_pt": 32,
}

# ---------------------------------------------------------------------------
# PDF plan-name classification rules
# ---------------------------------------------------------------------------
# Each PEO benefits admin line item is classified into one of these buckets
# by matching (case-insensitive) substrings against the plan name.
# Order matters: first match wins.
PLAN_CATEGORY_RULES = [
    ("dental", ["dental"]),
    ("vision", ["vision"]),
    ("life", ["life", "ltc rider", "whole life"]),
    ("ltd", ["ltd"]),
    ("std", ["std"]),
    ("medical", ["aet metro", "metro ntl", "epo", "mcp", "hmo", "ppo medical"]),
    ("voluntary_other", []),  # catch-all: accident/critical/hospital/legal/etc.
]

# Coverage-tier codes seen in the PDF "COVERAGE" column and how they map to
# the census "tier" vocabulary (EE / EE+CH / EE+S/D / FAM).
COVERAGE_TIER_NORMALIZATION = {
    "EE": "EE",
    "EE+CH": "EE+CH",
    "EE+S/D": "EE+S/D",
    "FAM": "FAM",
}
