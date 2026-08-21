"""
config.py
---------
Central configuration: file paths, template layout constants, and the
field <-> column mapping between extracted data and the Prestige template.

Everything here is deliberately declarative so that the pipeline can be
retargeted to a new plan year / new file names without touching logic code.
"""
from pathlib import Path
import warnings
import pandas as pd

# ---------------------------------------------------------------------------
# Paths (override via CLI args in main.py; these are sane local defaults)
# ---------------------------------------------------------------------------
PROCESSING_DIR = Path(__file__).resolve().parent / "processing"
INPUT_DIR = PROCESSING_DIR / "input"
OUTPUT_DIR = PROCESSING_DIR / "output"
EXTRACTED_DIR = PROCESSING_DIR / "extracted"

DEFAULT_PDF = INPUT_DIR / "Benefits_Invoice_-_May_2026.pdf"
DEFAULT_CENSUS_XLSX = INPUT_DIR / "Census.xlsx"
DEFAULT_TEMPLATE_XLSX = Path(__file__).resolve().parent / "Ingestion Census - Copy.xlsx"

DEFAULT_FILLED_OUTPUT = OUTPUT_DIR / "Prestige_Census_Filled.xlsx"
DEFAULT_RECONCILIATION_REPORT = OUTPUT_DIR / "reconciliation_report.json"
DEFAULT_RECONCILIATION_CSV = OUTPUT_DIR / "reconciliation_report.csv"

DEFAULT_PDF_EXTRACTED = EXTRACTED_DIR / "pdf_extracted.xlsx"
DEFAULT_CENSUS_EXTRACTED = EXTRACTED_DIR / "census_extracted.xlsx"

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
    ("discrepancies", "AG"),
]
FIELD_TO_COL = {name: col for name, col in TEMPLATE_COLUMNS}

# ---------------------------------------------------------------------------
# Census.xlsx (source demographic file) layout
# ---------------------------------------------------------------------------
CENSUS_SHEET_NAME = "Census"
CENSUS_HEADER_ROW = 24       # Fallback if auto-detect fails
CENSUS_FIRST_DATA_ROW = 26   # Fallback if auto-detect fails

# Fallback field -> 1-based column index (used only if auto-detect fails)
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
# Census header aliases — used by census_extractor auto-detect.
# Each field maps to a list of possible header labels (case-insensitive).
# ---------------------------------------------------------------------------
CENSUS_HEADER_ALIASES = {
    "row_no":                       ["row", "row no", "#", "no", "number", "emp #", "employee #", "employee number"],
    "first_name":                   ["first name", "first", "fname", "given name"],
    "last_name":                    ["last name", "last", "lname", "surname", "family name", "employee last name"],
    "gender":                       ["gender", "sex"],
    "dob":                          ["date of birth", "dob", "birth date", "birthdate", "birth"],
    "home_zip":                     ["home zip", "zip code", "zip", "postal code", "home zip code"],
    "relationship":                 ["relationship", "relation", "relationship to employee", "type", "ee/dep",
                                     "enrollee type", "enrolleetype", "member type", "subscriber type"],
    "dependent_of_employee_number": ["dependent of", "dependent of employee number", "dependent of employee", "subscriber", "subscriber #"],
    "medical_coverage_tier":        ["medical coverage tier", "medical tier", "medical dep status", "med tier", "medical"],
    "cobra":                        ["cobra", "cobra status"],
    "medical_plan_enrolled":        ["medical plan enrolled", "medical plan", "med plan"],
    "medical_plan_price":           ["medical plan price", "medical price", "medical premium", "med price"],
    "dental_coverage_tier":         ["dental coverage tier", "dental tier", "dental dep status", "dental"],
    "dental_plan_enrolled":         ["dental plan enrolled", "dental plan"],
    "dental_plan_price":            ["dental plan price", "dental price", "dental premium"],
    "vision_coverage_tier":         ["vision coverage tier", "vision tier", "vision dep status", "vision"],
    "vision_plan_enrolled":         ["vision plan enrolled", "vision plan"],
    "vision_plan_price":            ["vision plan price", "vision price", "vision premium"],
    "life_plan_name":               ["life plan", "life", "life plan name", "basic life", "life insurance"],
    "life_benefit":                 ["life benefit", "life amount", "life vol", "life volume", "lifevolume"],
    "life_rate":                    ["life rate", "life premium", "life cost"],
    "ltd_plan":                     ["ltd plan", "ltd", "long term disability"],
    "ltd_benefit":                  ["ltd benefit", "ltd amount"],
    "ltd_rate":                     ["ltd rate", "ltd premium", "ltd cost"],
    "std_plan":                     ["std plan", "std", "short term disability"],
    "std_benefit":                  ["std benefit", "std amount"],
    "std_rate":                     ["std rate", "std premium", "std cost"],
    "work_state":                   ["work state", "state", "work location"],
    "job_title":                    ["job title", "title", "position", "job title or for disability only"],
    "workers_comp_code":            ["workers comp", "workers comp code", "wc code", "comp code"],
    "annual_salary":                ["annual salary", "salary", "annual", "annual compensation"],
    "ft_pt":                        ["ft/pt", "full time", "part time", "employment status", "employment type"],
    "elections":                    ["elections", "election"],

    # --- Pivoted-census generic columns (used by census_normalizer) ---
    "product_type":                 ["product type", "plan type", "benefit type", "coverage type",
                                     "line of coverage", "benefit category"],
    "plan_name_generic":            ["plan name", "benefit name", "benefit plan",
                                     "coverage name"],
    "carrier":                      ["carrier", "carrier name", "insurance company", "insurer",
                                     "insurance carrier", "vendor"],
    "tier_generic":                 ["tier", "coverage tier", "coverage level", "enrollment tier"],
    "volume":                       ["volume", "benefit amount", "coverage amount", "face amount"],
    "coverage_start_date":          ["coverage start date", "effective date", "start date",
                                     "enrollment date", "coverage effective date"],
    "coverage_stop_date":           ["coverage stop date", "termination date", "end date",
                                     "coverage end date"],
    "premium":                      ["premium", "monthly premium",
                                     "employee premium", "total premium"],
    "hire_date":                    ["hire date", "date of hire", "original hire date"],
    "family_id":                    ["family id", "family", "subscriber id", "member id",
                                     "group id"],
}

# ---------------------------------------------------------------------------
# Pivoted-census Product Type classification
# ---------------------------------------------------------------------------
# Maps raw Product Type strings (case-insensitive) to the internal category.
# Used by census_normalizer to route plan data to the correct CensusRow fields.
# "ignore" means the product type is not mapped to any template field.
PRODUCT_TYPE_CLASSIFICATION = {
    # Medical
    "medical":     "medical",
    "health":      "medical",
    "hmo":         "medical",
    "ppo":         "medical",
    "epo":         "medical",

    # Dental
    "dental":      "dental",

    # Vision
    "vision":      "vision",

    # Life / AD&D
    "life":        "life",
    "life/ad&d":   "life",
    "ad&d":        "life",
    "basic life":  "life",

    # LTD
    "ltd":         "ltd",
    "long term disability": "ltd",

    # STD
    "std":         "std",
    "short term disability": "std",

    # Ignored product types (no template field)
    "eap":         "ignore",
    "fsa":         "ignore",
    "hsa":         "ignore",
    "cobra":       "ignore",
    "401k":        "ignore",
    "retirement":  "ignore",
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
    ("medical", ["aet metro", "metro ntl", "epo", "mcp", "hmo", "ppo medical", "medical",
                 "pos", "chc", "hdhp", "copay"]),
    ("voluntary_other", []),  # catch-all: accident/critical/hospital/legal/etc.
]

# Minimum premium threshold — any unclassified plan with a charge >= this
# amount will be inferred as Medical (since Dental/Vision/Life are far cheaper)
MEDICAL_PREMIUM_INFERENCE_THRESHOLD = 200.0

# Standardized tier map used by both census and pdf normalizers
MEDICAL_TIER_MAP = {
    # Employee Only
    'EE': 'EE',
    'EMPLOYEE ONLY': 'EE',
    'SINGLE': 'EE',
    'SUBSCRIBER ONLY': 'EE',
    'SUBSCRIBER': 'EE',
    'EMPLOYEE': 'EE',
    'OWNER': 'EE',
    'EMP ONLY': 'EE',
    'INDIVIDUAL': 'EE',
    'IND': 'EE',
    'INDIVIDUAL AND CHILDREN': 'EC',
    'INDIVIDUAL AND CHILD': 'EC',
    'INDIVIDUAL & CHILDREN': 'EC',
    'IND AND CHILDREN': 'EC',
    'E': 'EE',
    'PARTICIPANT': 'EE',
    'PPT': 'EE',
    'EO': 'EE',
    'M1': 'EE',
    'V1': 'EE',
    'D1': 'EE',
    '1': 'EE',
    
    # Employee & Spouse
    'ES': 'ES',
    'EMPLOYEE & SPOUSE': 'ES',
    'EMPLOYEE AND SPOUSE': 'ES',
    'SPOUSE': 'ES',
    'DOMESTIC PARTNER': 'ES',
    'EE+SP': 'ES',
    'EE/SP': 'ES',
    'EMP+SPOUSE': 'ES',
    'DEP': 'ES',
    'S': 'ES',
    'M2': 'ES',
    'V2': 'ES',
    'D2': 'ES',
    '2': 'ES',
    '2P': 'ES',
    '2A': 'ES',
    
    # Employee & Child(ren)
    'EC': 'EC',
    'EMPLOYEE & CHILD': 'EC',
    'EMPLOYEE & CHILD(REN)': 'EC',
    'EMPLOYEE AND CHILD': 'EC',
    'EMPLOYEE + CHILD': 'EC',
    'E1D': 'EC',
    'E2D': 'EC',
    'E3D': 'EC',
    'EE+CH': 'EC',
    'EE/CH': 'EC',
    'EMP+CHILD': 'EC',
    'EMPLOYEE/CHILD': 'EC',
    'EMPLOYEE/CHILDREN': 'EC',
    'EMP/CHILD': 'EC',
    'FPC': 'EC',
    'C': 'EC',
    'CHILD': 'EC',
    'M4': 'EC',
    'V4': 'EC',
    'D4': 'EC',
    '4': 'EC',
    
    # Employee & Family
    'EF': 'EF',
    'EMPLOYEE & FAMILY': 'EF',
    'EMPLOYEE AND FAMILY': 'EF',
    'FAMILY': 'EF',
    'EMPLOYEE + FAMILY': 'EF',
    'ESC': 'EF',
    'ESD': 'EF',
    'E4D': 'EF',
    'E5D': 'EF',
    'E6D': 'EF',
    'E7D': 'EF',
    'E8D': 'EF',
    'E9D': 'EF',
    'FAM': 'EF',
    'EMPLOYEE, SPOUSE & CHILDREN': 'EF',
    'F': 'EF',
    'M3': 'EF',
    'V3': 'EF',
    'D3': 'EF',
    '3': 'EF',
    
    # Waived / Other
    'WO': 'WO',
    'WAIVE': 'WO',
    'WAIVED': 'WO',
    'NE': 'WO',
    'RC': 'WO',
    'WP': 'WO'
}

MEDICAL_TIER_WAIVED = 'WO'

DEPENDENT_RELATIONSHIP_MAP = {
    'SUBSCRIBER': 'EE',
    'EMPLOYEE': 'EE',
    'OWNER': 'EE',
    'SPOUSE': 'SP',
    'DOMESTIC PARTNER': 'SP',
    'WIFE': 'SP',
    'HUSBAND': 'SP',
    'CHILD': 'CH',
    'SON': 'CH',
    'DAUGHTER': 'CH',
    'LEGAL DEPENDENT': 'CH',
    'DP': 'SP',
    # Verbose census values (e.g. "Enrollee Type" column)
    'SPOUSE OF EMPLOYEE': 'SP',
    'CHILD OF EMPLOYEE': 'CH',
    'DOMESTIC PARTNER OF EMPLOYEE': 'SP',
}

EMPLOYMENT_STATUS_MAP = {
    'FULL TIME': 'FT',
    'FT': 'FT',
    'PART TIME': 'PT',
    'PT': 'PT',
}

# ---------------------------------------------------------------------------
# Dynamic Loading of Census Header Aliases from Excel Mapping
# ---------------------------------------------------------------------------
def _load_dynamic_header_aliases():
    mappings_dir = PROCESSING_DIR / "mappings"
    if not mappings_dir.exists():
        return

    # Map Validation Template exact strings to the internal field keys
    val_to_key = {
        'First Name (EEscriber / Dependent)': 'first_name',
        'Employee First Name (EEscriber / Dependent)': 'first_name',
        'Employee Last Name (EEscriber / Dependent)': 'last_name',
        'Gender': 'gender',
        'Date of Birth': 'dob',
        'Home Zip Code': 'home_zip',
        'Relationship to Employee': 'relationship',
        'Dependent of Employee number': 'dependent_of_employee_number',
        'Medical Coverage Tier': 'medical_coverage_tier',
        'Cobra': 'cobra',
        'Medical Plan Enrolled': 'medical_plan_enrolled',
        'Medical Plan Price': 'medical_plan_price',
        'Dental Coverage Tier': 'dental_coverage_tier',
        'Dental Plan Enrolled': 'dental_plan_enrolled',
        'Dental Plan Price': 'dental_plan_price',
        'Vision Coverage Tier': 'vision_coverage_tier',
        'Vision Plan Enrolled': 'vision_plan_enrolled',
        'Vision Plan Price': 'vision_plan_price',
        'Life Plan Name': 'life_plan_name',
        'Life Benefit': 'life_benefit',
        'Life Rate': 'life_rate',
        'LTD Plan': 'ltd_plan',
        'LTD Benefit': 'ltd_benefit',
        'LTD Rate': 'ltd_rate',
        'STD Plan': 'std_plan',
        'STD Benefit': 'std_benefit',
        'STD Rate': 'std_rate',
        'Work State': 'work_state',
        'Job Title': 'job_title',
        'Workers Comp Code': 'workers_comp_code',
        'Annual Salary': 'annual_salary',
        'FT/PT': 'ft_pt'
    }

    import re
    def normalize_val(v):
        return re.sub(r'[^a-zA-Z0-9]', '', str(v)).lower()
        
    val_to_key_norm = {normalize_val(k): v for k, v in val_to_key.items()}

    for mapping_file in mappings_dir.glob("*.xlsx"):
        try:
            df = pd.read_excel(mapping_file)
            
            # We look for all columns that might contain excel mappings
            # (e.g. 'EXCEL', 'excel ', 'ADP', 'adp ')
            mapping_cols = [c for c in df.columns if str(c).strip().lower() in ('excel', 'adp')]
            
            for _, row in df.iterrows():
                val_template = normalize_val(row.get('Validation Template (Personl Info)', ''))
                if val_template in val_to_key_norm:
                    key = val_to_key_norm[val_template]
                    
                    # Extract all possible mappings from the mapping columns
                    new_aliases = []
                    for col in mapping_cols:
                        val = str(row.get(col, '')).strip()
                        if val and val.lower() != 'nan':
                            # Split by '/' to get individual aliases
                            for alias in val.split('/'):
                                alias = alias.strip().lower()
                                if alias and alias not in new_aliases:
                                    new_aliases.append(alias)
                    
                    if key in CENSUS_HEADER_ALIASES:
                        # Prepend new aliases so they take precedence in exact match
                        for a in reversed(new_aliases):
                            if a in CENSUS_HEADER_ALIASES[key]:
                                CENSUS_HEADER_ALIASES[key].remove(a)
                            CENSUS_HEADER_ALIASES[key].insert(0, a)
                    else:
                        CENSUS_HEADER_ALIASES[key] = new_aliases
                        
        except Exception as e:
            warnings.warn(f"Failed to load dynamic header aliases from {mapping_file}: {e}")

_load_dynamic_header_aliases()

