"""
pdf_extractor.py
----------------
Deterministic parser for the Paychex "PEO Benefits Administration Per
Employee" invoice pages.

Design notes
~~~~~~~~~~~~
The invoice is plain, monospaced-ish text (not a scanned image), so a
regex/line-based parser is far more reliable and repeatable than an LLM
here -- LLMs are reserved for *fuzzy* work (name matching, plan
classification, discrepancy narration), not for pulling exact dollar
figures out of a table. This keeps the pipeline deterministic where it
matters most (money) and only invokes the LLM-assisted layer downstream.

Any PDF text-extraction library works as the extraction backend; this
module defaults to `pdfplumber` (confirmed available in this
environment). If you prefer PyMuPDF (`fitz`), swap out `_read_pages()`
only -- the rest of the module is backend-agnostic because it works on
plain strings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

try:
    import pdfplumber
    _BACKEND = "pdfplumber"
except ImportError:  # pragma: no cover - fallback path
    pdfplumber = None
    _BACKEND = None

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


# Matches an employee header line, e.g.:
#   "Abraham, Luis - 728"
#   "Candelora, Kari M - 1060 (Termination)"
#   "Caranqui Taday, Gisela Y - 1087 (Newly Eligible)"
EMPLOYEE_HEADER_RE = re.compile(
    r"^(?P<last>[A-Za-z' \-\.]+?),\s*(?P<first>[A-Za-z' \-\.]+?)\s*-\s*"
    r"(?P<emp_id>\d+)\s*(?:\((?P<status>[^)]+)\))?\s*$"
)

# Matches a plan line, e.g.:
#   "AET DENTAL MID PPO EE MAY 2026 $ 45.00 $ 0.00 $ 45.00 $ 0.00"
#   "METL ER LTD 180D 2K EE MAY 2026 PREMIUM DUE $ 4.28 $ 0.00 $ 3.21 $ 1.07"
PLAN_LINE_RE = re.compile(
    r"^(?P<plan_name>.+?)\s+"
    r"(?P<coverage>EE\+CH|EE\+S/D|EE|FAM)\s+"
    r"(?P<month>[A-Z]{3}\s?\d{4})\s*"
    r"(?P<line_type>PREMIUM DUE|PREMIUM CREDIT)?\s*"
    r"\$\s*(?P<total_due>-?[\d,]+\.\d{2})\s*"
    r"\$\s*(?P<ee_contrib>-?[\d,]+\.\d{2})\s*"
    r"\$\s*(?P<er_contrib>-?[\d,]+\.\d{2})\s*"
    r"\$\s*(?P<adjusted_due>-?[\d,]+\.\d{2})\s*$"
)

# Lines that are boilerplate / headers we should ignore while scanning.
SKIP_PATTERNS = (
    "PAGE ", "HUMAN RESOURCE SERVICES", "CLIENT NUMBER", "STATEMENT DATE",
    "STATEMENT NUMBER", "CUSTOMER SERVICE", "PEO BENEFITS ADMINISTRATION",
    "TOTAL PAYROLL", "NAME/PLAN", "AMOUNT DUE", "AMOUNTDUE", "TOTAL PEO",
    "PROFESSIONAL EMPLOYER", "NUOVO PASTA", "HONEYSPOT", "STRATFORD",
)


@dataclass
class PlanLine:
    plan_name: str
    coverage_tier: str
    month: str
    line_type: str | None  # None | "PREMIUM DUE" | "PREMIUM CREDIT"
    total_monthly_due: float
    employee_contribution: float
    employer_contribution: float
    adjusted_amount_due: float


@dataclass
class EmployeeBenefits:
    last_name: str
    first_name: str
    employee_id: str
    status: str | None  # e.g. "Termination", "Newly Eligible"
    plans: list[PlanLine] = field(default_factory=list)

    @property
    def full_name_key(self) -> str:
        """Normalized 'first last' key used for cross-file matching."""
        return f"{self.first_name.strip().lower()} {self.last_name.strip().lower()}"


def _read_pages(pdf_path: Path) -> Iterable[str]:
    """Yield page text. Backend-agnostic entry point."""
    if _BACKEND == "pdfplumber":
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                yield page.extract_text() or ""
    elif fitz is not None:
        doc = fitz.open(str(pdf_path))
        for page in doc:
            yield page.get_text()
    else:
        raise RuntimeError(
            "No PDF backend available. Install pdfplumber (preferred) or "
            "PyMuPDF: pip install pdfplumber"
        )


def _is_boilerplate(line: str) -> bool:
    upper = line.strip().upper()
    if not upper:
        return True
    return any(pat in upper for pat in SKIP_PATTERNS)


def _clean_amount(raw: str) -> float:
    return float(raw.replace(",", ""))


def extract_employee_benefits(pdf_path: Path) -> list[EmployeeBenefits]:
    """
    Parse the invoice into a list of EmployeeBenefits records.

    Returns one record per unique (employee_id) encountered; if the same
    employee's block is split across a page boundary (as happens in this
    invoice), lines are appended to the same record.
    """
    employees: dict[str, EmployeeBenefits] = {}
    current: EmployeeBenefits | None = None

    for page_text in _read_pages(pdf_path):
        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            if _is_boilerplate(line):
                continue

            header_match = EMPLOYEE_HEADER_RE.match(line)
            if header_match:
                emp_id = header_match.group("emp_id")
                if emp_id in employees:
                    current = employees[emp_id]
                else:
                    current = EmployeeBenefits(
                        last_name=header_match.group("last").strip(),
                        first_name=header_match.group("first").strip(),
                        employee_id=emp_id,
                        status=header_match.group("status"),
                    )
                    employees[emp_id] = current
                continue

            plan_match = PLAN_LINE_RE.match(line)
            if plan_match and current is not None:
                current.plans.append(
                    PlanLine(
                        plan_name=re.sub(r"\s+", " ", plan_match.group("plan_name")).strip(),
                        coverage_tier=plan_match.group("coverage"),
                        month=plan_match.group("month"),
                        line_type=plan_match.group("line_type"),
                        total_monthly_due=_clean_amount(plan_match.group("total_due")),
                        employee_contribution=_clean_amount(plan_match.group("ee_contrib")),
                        employer_contribution=_clean_amount(plan_match.group("er_contrib")),
                        adjusted_amount_due=_clean_amount(plan_match.group("adjusted_due")),
                    )
                )
                continue
            # else: line didn't match either pattern (wrapped text, totals
            # footer, etc.) -- intentionally ignored; see reconciliation
            # report's `unparsed_line_count` for visibility into this.

    return list(employees.values())


def extract_invoice_summary(pdf_path: Path) -> dict:
    """
    Pull the page-1 account summary totals (grand total, statement date,
    client number) for the reconciliation report's header.
    """
    summary = {}
    first_page = next(iter(_read_pages(pdf_path)), "")
    patterns = {
        "client_number": r"CLIENT NUMBER:\s*([\d\-]+)",
        "statement_date": r"STATEMENT DATE:\s*([\d/]+)",
        "statement_number": r"STATEMENT NUMBER:\s*(\d+)",
        "grand_total": r"GRAND TOTAL:\s*\$\s*([\d,]+\.\d{2})",
    }
    for key, pat in patterns.items():
        m = re.search(pat, first_page)
        if m:
            summary[key] = m.group(1)
    return summary
