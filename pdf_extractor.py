"""
pdf_extractor.py
----------------
Universal, LLM-powered parser for benefits invoice PDFs from ANY carrier
(Paychex, Aetna, MetLife, UHC, BCBS, Cigna, etc.).

Design notes
~~~~~~~~~~~~
Instead of hardcoded regex patterns tied to one carrier's format, this module
uses Docling (RapidOCR + TableFormer) to extract markdown from the PDF, which
is then parsed into structured JSON by GPT-4o-mini.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import openai
from dotenv import load_dotenv

load_dotenv()


@dataclass
class PlanLine:
    plan_name: str
    coverage_tier: str
    month: str
    line_type: str | None
    total_monthly_due: float
    employee_contribution: float
    employer_contribution: float
    adjusted_amount_due: float


@dataclass
class EmployeeBenefits:
    last_name: str
    first_name: str
    employee_id: str
    status: str | None
    plans: list[PlanLine] = field(default_factory=list)

    @property
    def full_name_key(self) -> str:
        """Normalized 'first last' key used for cross-file matching."""
        return f"{self.first_name.strip().lower()} {self.last_name.strip().lower()}"


# ---------------------------------------------------------------------------
# LLM-powered extraction
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT_BASE = """Your job is to extract EVERY employee and their benefit plan lines from this content.

For each employee, extract:
- "first_name": The employee's first name (given name). Split carefully from last name.
- "last_name": The employee's last name (surname/family name). Split carefully from first name.
- "employee_id": Any employee ID or number shown (use "" if not present).
- "status": Any status like "Termination", "Newly Eligible", "New Hire" etc. (use null if not present).
- "plans": An array of plan lines, where each plan has:
  - "plan_name": The full plan/product name as shown (e.g. "AET DENTAL MID PPO", "METL ER LTD 180D 2K", "Medical HMO Gold")
  - "coverage_tier": The coverage tier code (e.g. "EE", "FAM", "EE+CH", "EE+SP", "EE+S/D", "EC", "ES", "SINGLE", "FAMILY", "EMPLOYEE", "EMP+SPOUSE", "EMP+CHILD"). Use "" if not shown.
  - "total_due": The base monthly premium/charge amount for the current period as a number (e.g. 45.00). Extract this from columns labeled "Charge Amount", "Current", "Premium Amount", or "Renewal Amount". Do NOT use the "Total" column if adjustments are present. Use 0.0 if not shown.
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
10. IGNORE "Prior Period Coverage Adjustments", retro adjustments, credits, and combined "Total" columns. You must extract ONLY the base charge amount for the current period (from "Charge Amount", "Current Detail", or "Premium Amount"). If an invoice has a "Totals" column and a "Charge Amount" column, always use the "Charge Amount" for `total_due`. NEVER extract negative numbers (e.g. -546.01). If you see a negative number, it is an adjustment or credit and MUST be ignored. ONLY extract the positive base premium amount for the current period.
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

CRITICAL PLAN NAME RULES — YOU MUST FOLLOW THESE EXACTLY:
12. Extract the COMPLETE plan name exactly as written in the source document. NEVER truncate, abbreviate, or partially extract a plan name.
13. Plan names often contain multiple segments separated by spaces, including codes, numbers, suffixes, prefixes, deductible amounts, copay amounts, HSA/HRA designations, network identifiers, tiers, options, and version codes. You MUST include ALL of them.
    - "CO S CHC NG 40/80/2500/70 EPO 25 DXG5" must NOT become "CO S CHC NG 40/80/2500/70 EPO" — the "25 DXG5" suffix is mandatory.
    - "CO B CHC + NG 6500/90 POS HSA 25 DXFG" must NOT become "CO B CHC" or omit any part.
    - "DENTAL Voluntary B3303" must NOT become "DENTAL" or "DENTAL Voluntary" — include "B3303".
    - "Vision 100% Voluntary S1043" must NOT become "Vision" or "Vision 100%" — include "Voluntary S1043".
    - "CO S DR P NG 125/3000/65 HMO 25 DXFA" must be extracted in full.
14. If a plan name is split across multiple lines or cells in the table, concatenate ALL parts into one complete name.
15. When a single table cell contains multiple plan names concatenated together (e.g., "Vision 100% Voluntary S1043 DENTAL Voluntary B3303 CO S CHC NG 40/80/2500/70 EPO 25 DXG5"), you MUST split them into SEPARATE plan entries. Each recognized plan gets its own plan object. Identify plan boundaries by looking for known plan type keywords (Vision, DENTAL, CO S, CO B, etc.).
16. When a row has multiple employees or plans stacked (names repeated 2-3 times, plan names listed sequentially, IDs repeated), each plan-employee-charge tuple must be extracted separately. Match plans to their corresponding charge amounts in order.

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

If no employee data is found, return {"employees": []}.
"""

_EXTRACTION_PROMPT_TEXT = (
    "You are an expert benefits invoice data extractor. You will receive the extracted markdown text and layout of a benefits/insurance invoice PDF.\n\n"
    + _EXTRACTION_PROMPT_BASE
)


def _extract_known_plans_from_summary(raw_text: str) -> list[str]:
    """Extract known plan names from the invoice Summary section ONLY.
    
    Looks for 'Subtotal,' lines in the Summary section (page 2) which list
    individual plan names like 'CO B CHC + NG 6500/90 POS HSA 25 DXFG'.
    
    Filters out:
    - Non-plan entries like 'Adjustments', 'Plan Charges'
    - Concatenated multi-plan strings (which appear in the Details pages)
    """
    import re
    known_plans = []
    
    # Restrict to the Summary section only (between "## Summary" and the next page break)
    summary_match = re.search(r'## Summary\s*\n(.*?)(?=--- PAGE \d|$)', raw_text, re.DOTALL)
    summary_text = summary_match.group(1) if summary_match else ""
    
    if not summary_text:
        # Fallback: use the full text but only Subtotal lines
        summary_text = raw_text
    
    # Match plan names from Subtotal lines in the Summary:
    # e.g. "Subtotal, CO S CHC NG 40/80/2500/70 EPO 25 DXG5"
    subtotal_pattern = re.compile(r'Subtotal,\s+(.+?)\s*\|', re.IGNORECASE)
    for m in subtotal_pattern.finditer(summary_text):
        plan_name = m.group(1).strip()
        # Filter out non-plan entries
        if not plan_name:
            continue
        plan_upper = plan_name.upper()
        if any(skip in plan_upper for skip in ('ADJUSTMENT', 'PLAN CHARGES', 'GRAND TOTAL', 
                                                 'SUBTOTAL', '1137136')):
            continue
        if plan_name not in known_plans:
            known_plans.append(plan_name)
    
    # Remove any "known plan" that is actually a concatenation of other known plans
    # (e.g., "Vision 100% Voluntary S1043 DENTAL Voluntary B3303 CO S CHC NG...")
    atomic_plans = []
    for plan in known_plans:
        plan_upper = plan.upper()
        # Check if this plan contains any OTHER known plan as a substring
        contains_other = False
        for other in known_plans:
            if other == plan:
                continue
            if other.upper() in plan_upper:
                contains_other = True
                break
        if not contains_other:
            atomic_plans.append(plan)
    
    return atomic_plans


def _fix_truncated_plan_name(plan_name: str, known_plans: list[str]) -> str:
    """If plan_name is a truncated prefix of a known plan, return the full known plan.
    
    Picks the SHORTEST matching known plan (closest to the truncated version)
    to avoid expanding to concatenated multi-plan strings.
    """
    if not plan_name or not known_plans:
        return plan_name
    
    name_upper = plan_name.strip().upper()
    
    # Direct exact match
    for known in known_plans:
        if known.upper() == name_upper:
            return known
    
    # Check if plan_name is a prefix of a known plan (truncation)
    # Pick the SHORTEST match (closest to the truncated version)
    best_match = None
    best_len = float('inf')
    for known in known_plans:
        known_upper = known.upper()
        if known_upper.startswith(name_upper) and len(known) > len(plan_name):
            if len(known) < best_len:
                best_match = known
                best_len = len(known)
    
    if best_match:
        return best_match
    
    # Check if plan_name is a significant substring of a known plan
    best_match = None
    best_len = float('inf')
    for known in known_plans:
        if name_upper in known.upper() and len(name_upper) >= 10:
            if len(known) < best_len:
                best_match = known
                best_len = len(known)
    
    if best_match:
        return best_match
    
    return plan_name


def _try_split_merged_plans(plan_name: str, known_plans: list[str]) -> list[str] | None:
    """If plan_name contains multiple known plans merged together, split them.
    
    Returns a list of individual plan names, or None if no split was needed.
    Only uses atomic (non-concatenated) known plans for splitting.
    """
    if not plan_name or not known_plans:
        return None
    
    name_upper = plan_name.strip().upper()
    
    # Check if this single plan_name contains more than one known plan
    found_plans = []
    for known in known_plans:
        known_upper = known.upper()
        if known_upper in name_upper:
            found_plans.append((name_upper.index(known_upper), known))
    
    # Remove overlapping matches (keep longer ones)
    if len(found_plans) > 1:
        found_plans.sort(key=lambda x: x[0])
        non_overlapping = [found_plans[0]]
        for pos, plan in found_plans[1:]:
            prev_pos, prev_plan = non_overlapping[-1]
            if pos >= prev_pos + len(prev_plan):
                non_overlapping.append((pos, plan))
            elif len(plan) > len(prev_plan):
                non_overlapping[-1] = (pos, plan)
        found_plans = non_overlapping
    
    if len(found_plans) > 1:
        return [p[1] for p in found_plans]
    
    return None


def _advanced_split_merged_plans(plan_name: str, known_plans: list[str]) -> list[str] | None:
    """Add-on logic: Fallback to split merged plans using partial fuzzy matches and gaps."""
    if not plan_name or not known_plans:
        return None
    
    name_upper = plan_name.upper()
    found_exact = []
    
    for known in known_plans:
        if known.upper() in name_upper:
            found_exact.append(known)
            
    if not found_exact:
        return None
        
    found_exact.sort(key=len, reverse=True)
    
    import re
    current_str = plan_name
    placeholder = ' ||| '
    for known in found_exact:
        pattern = re.compile(re.escape(known), re.IGNORECASE)
        current_str = pattern.sub(placeholder, current_str)
        
    parts = current_str.split('|||')
    
    result_plans = list(found_exact)
    added_new = False
    
    for part in parts:
        part = part.strip()
        if len(part) >= 5: 
            fixed = _fix_truncated_plan_name(part, known_plans)
            if fixed != part and fixed in known_plans:
                result_plans.append(fixed)
                added_new = True
                
    if added_new:
        return result_plans
    return None


def _validate_and_fix_plan_names(employees: list[dict], raw_text: str) -> list[dict]:
    """Post-process LLM output to fix truncated/merged plan names.
    
    Uses known plan names extracted from the invoice Summary section.
    """
    known_plans = _extract_known_plans_from_summary(raw_text)
    if not known_plans:
        return employees
    
    print(f"      -> Post-processing: found {len(known_plans)} known plans: {known_plans}")
    
    # Add-on: dynamically add all fully-extracted plan names from the PDF body 
    # so we can use them to fix truncated ones (like "Plan - " -> "Plan - Admin/Excess Loss")
    original_known = list(known_plans)
    all_raw_names = set(str(p.get("plan_name", "")).strip() for emp in employees for p in emp.get("plans", []))
    for raw in all_raw_names:
        if raw and raw not in known_plans and not raw.endswith("-"):
            # Avoid adding merged plans that happen to start with a known plan
            if _try_split_merged_plans(raw, original_known) or _advanced_split_merged_plans(raw, original_known):
                continue
                
            for k in original_known:
                if raw.startswith(k) and len(raw) > len(k):
                    known_plans.append(raw)
                    break
            
    for emp in employees:
        fixed_plans = []
        for plan in emp.get("plans", []):
            name = str(plan.get("plan_name", "")).strip()
            
            # First check if this is a merged multi-plan string
            splits = _try_split_merged_plans(name, known_plans)
            
            # Add-on logic: fallback to advanced fuzzy split if standard split fails
            if not splits:
                splits = _advanced_split_merged_plans(name, known_plans)
                
            if splits:
                # Create separate plan entries for each split plan
                for split_name in splits:
                    new_plan = dict(plan)
                    new_plan["plan_name"] = split_name
                    fixed_plans.append(new_plan)
                print(f"      -> Split merged plans for {emp.get('first_name', '')} {emp.get('last_name', '')}: '{name}' -> {splits}")
            else:
                # Try fixing truncation
                fixed_name = _fix_truncated_plan_name(name, known_plans)
                if fixed_name != name:
                    print(f"      -> Fixed truncated plan for {emp.get('first_name', '')} {emp.get('last_name', '')}: '{name}' -> '{fixed_name}'")
                plan["plan_name"] = fixed_name
                fixed_plans.append(plan)
        
        emp["plans"] = fixed_plans
    
    return employees


def _process_llm_response(content: str) -> list[dict]:
    if not content:
        return []
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


def _extract_via_llm_text(text_content: str, label: str) -> list[dict]:
    """Send OCR text to GPT-4o-mini and parse the structured JSON response."""
    client = openai.OpenAI()
    
    user_content = f"Extract all employee benefit data from this invoice content ({label}).\n\nMARKDOWN CONTENT:\n{text_content}"
        
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _EXTRACTION_PROMPT_TEXT},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        return _process_llm_response(response.choices[0].message.content)
    except Exception as e:
        print(f"      -> Text LLM extraction failed for {label}: {e}")
    
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
    Parse the invoice into a list of EmployeeBenefits records using Docling layout/OCR,
    with a dynamic fallback to Rostaing OCR if the PDF text layer is corrupted.
    """
    import fitz
    
    # Fast pre-check for corrupted text layer
    print(f"      -> Checking text layer integrity for {pdf_path.name}...")
    try:
        doc_fitz = fitz.open(pdf_path)
        first_page_text = doc_fitz[0].get_text("text")
        doc_fitz.close()
        unprintable = sum(1 for c in first_page_text if not c.isprintable() and c not in '\n\r\t')
        is_corrupted = unprintable > 50 or first_page_text.count(".notdef") > 10 or len(first_page_text.strip()) < 10
    except Exception as e:
        print(f"      -> Warning: PyMuPDF check failed: {e}")
        is_corrupted = False

    all_employee_dicts = []
    
    if is_corrupted:
        print(f"      -> Corrupted text layer detected (missing ToUnicode mappings).")
        print(f"      -> Falling back to Rostaing OCR for {pdf_path.name}...")
        try:
            import subprocess
            
            out_file = dump_raw_text_path if dump_raw_text_path else (pdf_path.parent / (pdf_path.stem + "_rostaing.txt"))
            out_file.parent.mkdir(parents=True, exist_ok=True)
            
            cmd = [
                "python", "-c",
                f'from rostaing_ocr import ocr_extractor; ocr_extractor(r"""{pdf_path.absolute()}""", r"""{out_file.absolute()}""", save_file=True)'
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            
            full_raw_text = out_file.read_text(encoding="utf-8")
        except Exception as e:
            print(f"      -> Error running Rostaing OCR: {e}")
            full_raw_text = ""
            
        # Split by page markers (e.g. "--- Page 5 ---") to keep LLM context size manageable
        import re
        pages = re.split(r'(?=\n--- Page \d+ ---)', full_raw_text)
        
        for i, page_text in enumerate(pages, start=1):
            if not page_text.strip():
                continue
            print(f"      -> Processing OCR page chunk {i}/{len(pages)}...")
            emp_dicts = _extract_via_llm_text(page_text, f"chunk {i}")
            all_employee_dicts.extend(emp_dicts)
            print(f"      -> Chunk {i}: extracted {len(emp_dicts)} employees")
            
    else:
        print(f"      -> Initializing Docling (RapidOCR + TableFormer) for {pdf_path.name}")
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
        
        pipeline_options = PdfPipelineOptions(do_ocr=True, do_table_structure=True)
        pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE
        
        try:
            from docling.datamodel.pipeline_options import RapidOcrOptions
            pipeline_options.ocr_options = RapidOcrOptions()
        except ImportError:
            pass
            
        doc_converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF],
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            },
        )
    
        print(f"      -> Extracting Document...")
        conv_res = doc_converter.convert(pdf_path)
        doc = conv_res.document
        
        num_pages = len(doc.pages)
        print(f"      -> {num_pages} pages parsed. Starting LLM extraction...")
        
        if dump_raw_text_path:
            dump_raw_text_path.parent.mkdir(parents=True, exist_ok=True)
            dump_raw_text_path.write_text("Extracted markdown will be saved here.\n", encoding="utf-8")
        
        for i in range(1, num_pages + 1):
            print(f"      -> Processing page {i}/{num_pages}...")
            try:
                page_md = doc.export_to_markdown(page_no=i)
            except Exception:
                # If docling doesn't support page_no in this version, fallback to full text
                if i == 1:
                    page_md = doc.export_to_markdown()
                else:
                    break
                    
            if dump_raw_text_path and page_md.strip():
                with dump_raw_text_path.open("a", encoding="utf-8") as f:
                    f.write(f"\n--- PAGE {i} MARKDOWN ---\n{page_md}\n")
                    
            if not page_md.strip():
                continue
                
            emp_dicts = _extract_via_llm_text(page_md, f"page {i}")
            all_employee_dicts.extend(emp_dicts)
            print(f"      -> Page {i}/{num_pages}: extracted {len(emp_dicts)} employees")
    
    # Merge duplicates (employees spanning page breaks)
    merged_dicts = _merge_duplicate_employees(all_employee_dicts)
    
    # Post-process: validate and fix plan names against known plans from Summary
    full_raw_text = ""
    if dump_raw_text_path and dump_raw_text_path.exists():
        full_raw_text = dump_raw_text_path.read_text(encoding="utf-8")
    if full_raw_text:
        merged_dicts = _validate_and_fix_plan_names(merged_dicts, full_raw_text)
    
    # Convert to EmployeeBenefits dataclasses
    employees = [_dict_to_employee_benefits(d) for d in merged_dicts]
    
    # Filter out entries with no name
    employees = [e for e in employees if e.first_name or e.last_name]
    
    return employees
