"""
pdf_extractor.py
----------------
Universal, LLM-powered parser for benefits invoice PDFs from ANY carrier
(Paychex, Aetna, MetLife, UHC, BCBS, Cigna, etc.).

Design notes
~~~~~~~~~~~~
Instead of hardcoded regex patterns tied to one carrier's format, this module
sends raw PDF text to GPT-4o-mini in page-batches and asks the LLM to extract
structured employee benefit data as JSON. This makes the extractor completely
carrier-agnostic.

The extraction pipeline is:
    PDF → pdfplumber (raw text) → chunk pages → GPT-4o-mini → EmployeeBenefits[]

The _read_pages() function handles both digital-text PDFs and scanned PDFs
(via OCR fallback). The rest of the module is backend-agnostic.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import openai
from dotenv import load_dotenv

load_dotenv()

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
    import base64
    if fitz is None:
        raise ImportError("PyMuPDF (fitz) is required for PDF extraction.")
    
    print("      -> Extracting PDF pages as images for Vision API...")
    doc = fitz.open(pdf_path)
    for page in doc:
        pix = page.get_pixmap(dpi=150)
        img = base64.b64encode(pix.tobytes("jpeg")).decode("utf-8")
        yield img

# ---------------------------------------------------------------------------
# LLM-powered extraction
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = """You are an expert benefits invoice data extractor. You will receive images of a benefits/insurance invoice PDF.

Your job is to extract EVERY employee and their benefit plan lines from this text.

For each employee, extract:
- "first_name": The employee's first name (given name). Split carefully from last name.
- "last_name": The employee's last name (surname/family name). Split carefully from first name.
- "employee_id": Any employee ID or number shown (use "" if not present).
- "status": Any status like "Termination", "Newly Eligible", "New Hire" etc. (use null if not present).
- "plans": An array of plan lines, where each plan has:
  - "plan_name": The full plan/product name as shown (e.g. "AET DENTAL MID PPO", "METL ER LTD 180D 2K", "Medical HMO Gold")
  - "coverage_tier": The coverage tier code (e.g. "EE", "FAM", "EE+CH", "EE+SP", "EE+S/D", "EC", "ES", "SINGLE", "FAMILY", "EMPLOYEE", "EMP+SPOUSE", "EMP+CHILD"). Use "" if not shown.
  - "total_due": The total monthly premium/amount due as a number (e.g. 45.00). Use 0.0 if not shown.
  - "ee_contribution": The employee contribution amount as a number. Use 0.0 if not shown.
  - "er_contribution": The employer contribution amount as a number. Use 0.0 if not shown.

IMPORTANT RULES:
1. Extract ALL employees you can find, not just a sample.
2. If names appear as "LAST, FIRST" or "LAST FIRST", split them correctly into first_name and last_name.
3. If names appear as "FIRST LAST", split them correctly.
4. Do NOT skip any employees even if they have no plan lines.
5. Ignore page headers, footers, totals lines, and other boilerplate.
6. If the same employee appears multiple times (e.g. across page breaks), combine their plan lines.
7. Be precise with dollar amounts — extract exact values from the text.
8. If the invoice is formatted as a wide table (like Markdown) where column headers represent plan categories (e.g., "Medical", "Vision", "Life & ADD"): You MUST create a SEPARATE plan object in the `plans` array for EVERY amount found across the columns. Use the column header as the `plan_name` and the amount as the `total_due`. Do NOT combine different plans into a single plan object by putting the amounts into `ee_contribution` or `er_contribution`. DO NOT create a plan object if the cell for that plan category is empty. VERY IMPORTANT: OCR often misses empty cells, causing the remaining amounts to shift left into the wrong columns. If a row has an amount like "2.98", look at the table headers. Medical premiums are typically >$100, while Life/AD&D premiums are typically <$10. If an amount is clearly for Life/AD&D (e.g. 2.98) but it shifted into the "Medical" or "Elections" column due to a missing pipe/cell, you MUST correctly assign it to the "Life & ADD" plan_name, NOT "Medical" or "Elections".
9. If there is an 'Elections' column containing multiple tier codes (e.g., "M1;V1;" or "M1; V1"), split them up and map them strictly to their respective plans. For example, assign "M1" to the Medical plan's `coverage_tier`, and "V1" to the Vision plan's `coverage_tier`. Do not dump the entire string into a single plan's tier.
10. DO NOT ignore "Prior Period Coverage Adjustments" or retro adjustments. Extract these lines just like normal active plans, and if the amount is negative (e.g. -546.01), extract the absolute positive value (e.g. 546.01) as the total_due so we can capture the standard premium rate.
11. Use the following coverage type definitions as a reference when interpreting tier codes:
    - EE: Employee Only
    - ES: Employee and Spouse
    - ESC: Employee and Family
    - EC: Employee and Child(ren)
    - E1D: Employee and One Dependent
    - E2D: Employee and Two Dependents
    - E4D: Employee and Four Dependents
    - E5D: Employee & One or More Dependent
    - E6D: Employee & Two or More Dependents
    - E7D: Employee & Three or More Dependents
    - E8D: Employee & Four or More Dependents
    - E9D: Employee & Five or More Dependents

Return a JSON object with this exact structure:
{
  "employees": [
    {
      "first_name": "John",
      "last_name": "Doe",
      "employee_id": "123",
      "status": null,
      "plans": [
        {
          "plan_name": "Medical HMO Gold",
          "coverage_tier": "FAM",
          "total_due": 450.00,
          "ee_contribution": 100.00,
          "er_contribution": 350.00
        }
      ]
    }
  ]
}

If no employee data is found in the images, return {"employees": []}.
"""


def _chunk_pages(pages: list[str], chunk_size: int = 4) -> list[list[str]]:
    """Group base64 images into chunks for batched LLM calls."""
    chunks = []
    for i in range(0, len(pages), chunk_size):
        chunks.append(pages[i:i + chunk_size])
    return chunks


def _extract_via_llm(image_chunk: list[str], chunk_index: int, total_chunks: int) -> list[dict]:
    """Send a chunk of images to GPT-4o-mini Vision and parse the structured JSON response."""
    client = openai.OpenAI()
    
    user_content = [
        {"type": "text", "text": f"Extract all employee benefit data from these invoice pages (chunk {chunk_index + 1} of {total_chunks})."}
    ]
    for b64_img in image_chunk:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}
        })
        
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _EXTRACTION_PROMPT},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        content = response.choices[0].message.content
        if content:
            result = json.loads(content)
            employees = result.get("employees", [])
            
            # Post-process to fix OCR column-shift hallucinations
            for emp in employees:
                for plan in emp.get("plans", []):
                    p_name = str(plan.get("plan_name", "")).strip().lower()
                    due = float(plan.get("total_due") or 0.0)
                    
                    # If it's a Medical plan with an impossibly small premium (< $10),
                    # it's almost certainly an OCR alignment hallucination where a Life/AD&D
                    # amount shifted left into the Medical column.
                    if "medical" in p_name and 0 < due < 10.0:
                        plan["plan_name"] = "Life & ADD"
            
            return employees
    except Exception as e:
        print(f"      -> LLM extraction failed for chunk {chunk_index + 1}: {e}")
    
    return []


def _merge_duplicate_employees(all_employee_dicts: list[dict]) -> list[dict]:
    """Merge employees that appear in multiple chunks (same name)."""
    merged = {}
    
    for emp in all_employee_dicts:
        first = (emp.get("first_name") or "").strip().lower()
        last = (emp.get("last_name") or "").strip().lower()
        emp_id = (emp.get("employee_id") or "").strip()
        
        # Use employee_id if available, otherwise use name as key
        if emp_id:
            key = emp_id
        else:
            key = f"{first}|{last}"
        
        if key in merged:
            # Append plan lines to existing employee
            existing_plans = merged[key].get("plans", [])
            new_plans = emp.get("plans", [])
            existing_plans.extend(new_plans)
            merged[key]["plans"] = existing_plans
            # Keep the richer version of name/status
            if not merged[key].get("status") and emp.get("status"):
                merged[key]["status"] = emp["status"]
        else:
            merged[key] = emp
    
    return list(merged.values())


def _dict_to_employee_benefits(emp_dict: dict) -> EmployeeBenefits:
    """Convert a raw LLM-extracted dict into an EmployeeBenefits dataclass."""
    plans = []
    for plan_dict in emp_dict.get("plans", []):
        plans.append(PlanLine(
            plan_name=str(plan_dict.get("plan_name", "")).strip(),
            coverage_tier=str(plan_dict.get("coverage_tier", "")).strip() or None,
            month="",  # LLM may not always extract month; not critical
            line_type=None,
            total_monthly_due=float(plan_dict.get("total_due", 0.0)),
            employee_contribution=float(plan_dict.get("ee_contribution", 0.0)),
            employer_contribution=float(plan_dict.get("er_contribution", 0.0)),
            adjusted_amount_due=float(plan_dict.get("total_due", 0.0)),
        ))
    
    return EmployeeBenefits(
        last_name=str(emp_dict.get("last_name", "")).strip(),
        first_name=str(emp_dict.get("first_name", "")).strip(),
        employee_id=str(emp_dict.get("employee_id", "")).strip(),
        status=emp_dict.get("status"),
        plans=plans,
    )


def extract_employee_benefits(pdf_path: Path, dump_raw_text_path: Path | None = None) -> list[EmployeeBenefits]:
    """
    Parse the invoice into a list of EmployeeBenefits records using LLM extraction.
    Works with ANY carrier's invoice format.
    """
    # Step 1: Extract images from all pages
    pages = list(_read_pages(pdf_path))
    
    if dump_raw_text_path:
        dump_raw_text_path.parent.mkdir(parents=True, exist_ok=True)
        with dump_raw_text_path.open("w", encoding="utf-8") as f:
            f.write("Vision mode active. Raw text dump is disabled since images are sent directly to the LLM.\n")
    
    if not pages:
        print("      -> No pages found in PDF")
        return []
    
    # Step 2: Chunk pages for batched LLM calls
    chunks = _chunk_pages(pages, chunk_size=4)
    print(f"      -> {len(pages)} pages, {len(chunks)} LLM batch(es)")
    
    # Step 3: Send each chunk to GPT-4o-mini
    all_employee_dicts = []
    for i, chunk in enumerate(chunks):
        emp_dicts = _extract_via_llm(chunk, i, len(chunks))
        all_employee_dicts.extend(emp_dicts)
        print(f"      -> Chunk {i + 1}/{len(chunks)}: extracted {len(emp_dicts)} employees")
    
    # Step 4: Merge duplicates (employees spanning page breaks)
    merged_dicts = _merge_duplicate_employees(all_employee_dicts)
    
    # Step 5: Convert to EmployeeBenefits dataclasses
    employees = [_dict_to_employee_benefits(d) for d in merged_dicts]
    
    # Filter out entries with no name
    employees = [e for e in employees if e.first_name or e.last_name]
    
    return employees


def save_pdf_to_excel(employees: list[EmployeeBenefits], invoice_summary: dict, path: Path) -> None:
    """Save extracted PDF plan lines and invoice summary as a structured Excel file."""
    import openpyxl
    wb = openpyxl.Workbook()
    
    # Write the invoice summary to the first sheet
    ws_summary = wb.active
    ws_summary.title = "Invoice Summary"
    ws_summary.append(["Field", "Value"])
    for key, val in invoice_summary.items():
        ws_summary.append([key, val])
        
    # Write the employee plan data to a second sheet
    ws_plans = wb.create_sheet(title="PDF Extracted")
    headers = ["Employee Name", "Employee ID", "Status", "Plan Name",
               "Coverage Tier", "Month", "Line Type", "Total Due",
               "EE Contribution", "ER Contribution", "Adjusted Due"]
    ws_plans.append(headers)
    for emp in employees:
        for plan in emp.plans:
            ws_plans.append([
                f"{emp.first_name} {emp.last_name}",
                emp.employee_id,
                emp.status,
                plan.plan_name,
                plan.coverage_tier,
                plan.month,
                plan.line_type,
                plan.total_monthly_due,
                plan.employee_contribution,
                plan.employer_contribution,
                plan.adjusted_amount_due,
            ])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))
