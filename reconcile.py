"""
reconcile.py
------------
Matches Census.xlsx employee/dependent rows against the PDF's per-employee
benefit blocks, merges the two into one "MergedRecord" per template row,
and produces a structured discrepancy report.

Matching strategy
~~~~~~~~~~~~~~~~~
1. Only "EE" (employee, not dependent) rows in the census carry a name that
   should exist in the PDF (dependents are listed in the census but the PDF
   invoice is keyed by subscriber, so dependents inherit the subscriber's
   plan match rather than being matched independently).
2. Exact match on normalize_name_key(first, last).
3. Any census EE row left unmatched is retried with best_fuzzy_match()
   against the pool of unmatched PDF names.
4. Anything still unmatched is reported, not silently dropped.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional
import json
import openai
from dotenv import load_dotenv

load_dotenv()

from census_extractor import CensusRow
from normalize import normalize_name_key, best_fuzzy_match, build_employee_plan_summaries, money
from pdf_extractor import EmployeeBenefits


@dataclass
class MergedRecord:
    census_row: CensusRow
    pdf_employee: Optional[EmployeeBenefits]
    plan_summary: dict
    match_method: str  # "exact" | "fuzzy" | "dependent_inherits_subscriber" | "unmatched" | "pdf_only" | "llm"
    discrepancies: list[str] = field(default_factory=list)
    discrepancy_status: str = ""
    is_duplicate_name: bool = False


def match_employees(
    census_rows: list[CensusRow], pdf_employees_list: list[list[EmployeeBenefits]]
) -> tuple[list[MergedRecord], dict]:
    """
    Returns (merged_records, match_stats).

    merged_records has one entry per census row (employees AND dependents);
    dependents are linked to their subscriber's PDF match via
    dependent_of_employee_number where available, else via adjacency in the
    census sheet (dependents are listed directly under their subscriber).
    """
    census_ee_rows = [r for r in census_rows if not r.is_dependent]
    
    # Map from id(row) -> list[EmployeeBenefits]
    matched_pdfs_by_row: dict[int, list[EmployeeBenefits]] = {id(r): [] for r in census_ee_rows}
    all_unmatched_pdf_employees = []
    
    exact_matches_count = 0
    fuzzy_matches_count = 0
    llm_matches_count = 0

    census_name_counts = {}
    for row in census_ee_rows:
        k = normalize_name_key(row.first_name, row.last_name)
        if k:
            census_name_counts[k] = census_name_counts.get(k, 0) + 1

    for pdf_employees in pdf_employees_list:
        unmatched_pdf_employees = pdf_employees.copy()
        unmatched_census_rows: list[CensusRow] = []

        # Pass 1: Exact matches by normalized 'first last' key
        for row in census_ee_rows:
            key = normalize_name_key(row.first_name, row.last_name)
            match = next((p for p in unmatched_pdf_employees if normalize_name_key(p.first_name, p.last_name) == key), None)
            if match:
                matched_pdfs_by_row[id(row)].append(match)
                unmatched_pdf_employees.remove(match)
                exact_matches_count += 1
            else:
                unmatched_census_rows.append(row)

        # Pass 2: Fuzzy pass over what's left.
        still_unmatched_census: list[CensusRow] = []
        
        for row in unmatched_census_rows:
            key = normalize_name_key(row.first_name, row.last_name)
            pdf_keys = {id(p): normalize_name_key(p.first_name, p.last_name) for p in unmatched_pdf_employees}
            
            candidate_key = best_fuzzy_match(key, list(pdf_keys.values()))
            if candidate_key:
                # Find the actual employee object that yielded this key
                match = next((p for p in unmatched_pdf_employees if normalize_name_key(p.first_name, p.last_name) == candidate_key), None)
                if match:
                    matched_pdfs_by_row[id(row)].append(match)
                    unmatched_pdf_employees.remove(match)
                    fuzzy_matches_count += 1
                    continue
                    
            still_unmatched_census.append(row)

        # Pass 3: LLM pass over what's left.
        if still_unmatched_census and unmatched_pdf_employees:
            c_names = [f"{r.first_name} {r.last_name}" for r in still_unmatched_census]
            p_names = [f"{p.first_name} {p.last_name}" for p in unmatched_pdf_employees]
            llm_results = _llm_match(c_names, p_names)
            
            new_still_unmatched = []
            for row in still_unmatched_census:
                c_name = f"{row.first_name} {row.last_name}"
                if c_name in llm_results:
                    p_name = llm_results[c_name]
                    # Find the first pdf employee with this exact p_name
                    match = next((p for p in unmatched_pdf_employees if f"{p.first_name} {p.last_name}" == p_name), None)
                    if match:
                        matched_pdfs_by_row[id(row)].append(match)
                        unmatched_pdf_employees.remove(match)
                        # Remove from llm_results so we don't assign it again if another census row shares the same name
                        del llm_results[c_name]
                        llm_matches_count += 1
                        continue
                new_still_unmatched.append(row)
            still_unmatched_census = new_still_unmatched
            
        all_unmatched_pdf_employees.extend(unmatched_pdf_employees)

    # Track last-seen subscriber match while walking the census in original
    # order, so dependents can inherit it.
    merged: list[MergedRecord] = []
    last_subscriber_matches: list[EmployeeBenefits] = []
    last_subscriber_summaries: list[dict] = []
    subscriber_by_last_name = {}

    for row in census_rows:
        if not row.is_dependent:
            row_id = id(row)
            matched_pdfs = matched_pdfs_by_row[row_id]
            summaries = build_employee_plan_summaries(matched_pdfs)
            
            method = "matched" if matched_pdfs else "unmatched"
            last_subscriber_matches = matched_pdfs
            last_subscriber_summaries = summaries
            
            if row.last_name:
                subscriber_by_last_name[row.last_name.strip().lower()] = (matched_pdfs, summaries)
            
            for summary in summaries:
                if not summary.get("medical_plan_enrolled") and summary.get("medical_plan_price") is None:
                    summary["medical_coverage_tier"] = "WO"
                
                record = MergedRecord(
                    census_row=row,
                    pdf_employee=matched_pdfs[0] if matched_pdfs else None,
                    plan_summary=summary,
                    match_method=method,
                )
                k = normalize_name_key(row.first_name, row.last_name)
                if k and census_name_counts.get(k, 0) > 1:
                    record.is_duplicate_name = True
                _flag_discrepancies(record)
                merged.append(record)
        else:
            # Dependent: inherits medical/dental/vision tier context from the
            # subscriber. Try to match by last name first (if on a different sheet)
            dep_last = row.last_name.strip().lower() if row.last_name else ""
            if dep_last in subscriber_by_last_name:
                pdf_emps, base_summaries = subscriber_by_last_name[dep_last]
            else:
                pdf_emps = last_subscriber_matches
                base_summaries = last_subscriber_summaries
                
            method = "dependent_inherits_subscriber" if pdf_emps else "unmatched"
            summaries_to_use = base_summaries or [_empty_summary()]
            
            for summary in summaries_to_use:
                dep_summary = _dependent_summary(summary)
                record = MergedRecord(
                    census_row=row,
                    pdf_employee=pdf_emps[0] if pdf_emps else None,
                    plan_summary=dep_summary,
                    match_method=method,
                )
                _flag_discrepancies(record)
                merged.append(record)

    # Append PDF-only employees (Not on census)
    for pdf_emp in all_unmatched_pdf_employees:
        summaries = build_employee_plan_summaries([pdf_emp])
        for summary in summaries:
            dummy_row = CensusRow(
                row_no="",
                first_name=pdf_emp.first_name,
                last_name=pdf_emp.last_name,
                gender=None,
                dob=None,
                home_zip=None,
                relationship="EE",
                dependent_of_employee_number=None,
                medical_coverage_tier=None,
                cobra=None
            )
            record = MergedRecord(
                census_row=dummy_row,
                pdf_employee=pdf_emp,
                plan_summary=summary,
                match_method="pdf_only",
            )
            _flag_discrepancies(record)
            merged.append(record)

    # Determine final unmatched census employees (those that got no matches across all PDFs)
    final_unmatched_census_employees = [
        f"{r.first_name} {r.last_name}" for r in census_ee_rows if not matched_pdfs_by_row[id(r)]
    ]

    stats = {
        "census_employee_count": len(census_ee_rows),
        "pdf_employee_count": sum(len(p) for p in pdf_employees_list),
        "exact_matches": exact_matches_count,
        "fuzzy_matches": fuzzy_matches_count,
        "llm_matches": llm_matches_count,
        "unmatched_census_employees": final_unmatched_census_employees,
        "unmatched_pdf_employees": [f"{p.first_name} {p.last_name}" for p in all_unmatched_pdf_employees],
    }
    return merged, stats


def _llm_match(census_names: list[str], pdf_names: list[str]) -> dict[str, str]:
    if not census_names or not pdf_names:
        return {}
        
    client = openai.OpenAI()
    
    prompt = f"""
    You are an assistant that matches employee names from two different lists.
    List 1 (Census names): {json.dumps(census_names)}
    List 2 (Invoice names): {json.dumps(pdf_names)}
    
    Find the pairs that represent the same person despite variations in middle initials, nicknames, or hyphenated surnames.
    Only match if you are highly confident they are the same person.
    
    Return a JSON object where the keys are the exact strings from List 1, and the values are the exact strings from List 2.
    Output ONLY valid JSON.
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        if content:
            matches = json.loads(content)
            # Filter matches to ensure keys/values are actually in the lists
            return {k: v for k, v in matches.items() if k in census_names and v in pdf_names}
    except Exception as e:
        print(f"LLM match failed: {e}")
    return {}


from config import MEDICAL_TIER_WAIVED, MEDICAL_TIER_MAP


def _normalize_census_tier(tier_str: str) -> str:
    """Normalize census tier strings like 'EE - Single' or 'ES - Employee/Spouse' 
    to their standard code for comparison.
    
    Census tiers often include descriptive text after a dash, e.g.:
      'EE - Single' -> 'EE'
      'ES - Employee/Spouse' -> 'ES'
      'EF - Employee/Family' -> 'ESC'  (mapped via MEDICAL_TIER_MAP)
      'EC - Employee/Children' -> 'EC'
    """
    if not tier_str:
        return ""
    raw = tier_str.strip().upper()
    
    # Strip descriptive text after " - " (e.g. "EE - Single" -> "EE")
    if " - " in raw:
        raw = raw.split(" - ")[0].strip()
    
    # Also handle "WAIVE" / "Waived"
    if raw in ("WAIVE", "WAIVED"):
        return "WO"
    
    # Map through MEDICAL_TIER_MAP to get the canonical numeric form
    mapped = MEDICAL_TIER_MAP.get(raw, raw)
    return mapped


def _empty_summary() -> dict:
    return {
        "medical_coverage_tier": None, "medical_plan_enrolled": None, "medical_plan_price": None,
        "dental_coverage_tier": None, "dental_plan_enrolled": None, "dental_plan_price": None,
        "vision_coverage_tier": None, "vision_plan_enrolled": None, "vision_plan_price": None,
        "life_plan_name": None, "life_benefit": None, "life_rate": None,
        "ltd_plan": None, "ltd_benefit": None, "ltd_rate": None,
        "std_plan": None, "std_benefit": None, "std_rate": None,
        "notes": [],
    }


def _dependent_summary(subscriber_summary: dict) -> dict:
    """Dependents show coverage tier context but no independent price."""
    s = _empty_summary()
    for tier_field in ("medical_coverage_tier", "dental_coverage_tier", "vision_coverage_tier"):
        s[tier_field] = subscriber_summary.get(tier_field)
    return s


def _flag_discrepancies(record: MergedRecord) -> None:
    row = record.census_row
    summary = record.plan_summary

    if record.match_method == "pdf_only":
        record.discrepancy_status = "Not on census"
        record.discrepancies.append("not in the census listed in the invoice")
        return

    if record.is_duplicate_name:
        record.discrepancies.append("Duplicate names listed in the census")
        record.discrepancy_status = "Duplicate names listed in the census"

    if record.match_method == "unmatched":
        record.discrepancy_status = "not available on invoice"
        record.discrepancies.append(
            f"No PDF invoice match found for '{row.first_name} {row.last_name}' "
            f"(census row {row.row_no})."
        )
        return

    name_mismatch = (record.match_method == "fuzzy")

    if record.match_method == "fuzzy":
        record.discrepancies.append(
            f"Matched via fuzzy name matching, not exact: "
            f"'{row.first_name} {row.last_name}' (census row {row.row_no})."
        )
        
    if record.match_method == "llm":
        record.discrepancies.append(
            f"Matched via AI fallback: "
            f"'{row.first_name} {row.last_name}' (census row {row.row_no})."
        )

    if row.is_dependent:
        record.discrepancy_status = ""
        return  # tier-only comparison already handled; no price to compare

    # Normalize both census and PDF tiers through MEDICAL_TIER_MAP for apples-to-apples comparison
    census_tier_raw = (row.medical_coverage_tier or "").strip().upper()
    census_tier = _normalize_census_tier(census_tier_raw) if census_tier_raw else "WO"
    
    pdf_tier = (summary.get("medical_coverage_tier") or "").strip().upper()
    pdf_tier_normalized = MEDICAL_TIER_MAP.get(pdf_tier, pdf_tier) if pdf_tier else "WO"
        
    if not census_tier_raw:
        tier_mismatch = False
    else:
        tier_mismatch = (census_tier != pdf_tier_normalized)

    if name_mismatch and tier_mismatch:
        record.discrepancy_status = "mismatch employee name & mismatch coverage name"
    elif name_mismatch:
        record.discrepancy_status = "mismatch employee name"
    elif tier_mismatch:
        record.discrepancy_status = "mismatch coverage name"
    else:
        record.discrepancy_status = "Correct"

    # Compare census pre-existing medical tier (if any) vs PDF-derived tier.
    if census_tier_raw and census_tier_raw not in ("", "WO", "WAIVE", "WAIVED"):
        if pdf_tier and pdf_tier not in ("", "WO") and census_tier != pdf_tier_normalized:
            record.discrepancies.append(
                f"Medical coverage tier mismatch: census='{census_tier_raw}' (normalized='{census_tier}') vs pdf='{pdf_tier}' (normalized='{pdf_tier_normalized}')."
            )

    if not summary.get("medical_plan_enrolled") and summary.get("medical_plan_price") is None and (row.medical_coverage_tier or "").strip().upper() not in (None, "", "WO"):
        record.discrepancies.append(
            "Census indicates active medical coverage tier but no medical plan line "
            "was found on the PDF invoice for this employee."
        )
    if not summary.get("dental_plan_enrolled") and summary.get("dental_plan_price") is None and (row.dental_coverage_tier or "").strip().upper() not in (None, "", "WO"):
        record.discrepancies.append(
            "Census indicates active dental coverage tier but no dental plan line "
            "was found on the PDF invoice for this employee."
        )
    if not summary.get("vision_plan_enrolled") and summary.get("vision_plan_price") is None and (row.vision_coverage_tier or "").strip().upper() not in (None, "", "WO"):
        record.discrepancies.append(
            "Census indicates active vision coverage tier but no vision plan line "
            "was found on the PDF invoice for this employee."
        )
    life_rate = getattr(row, "life_rate", None)
    try:
        life_rate_val = float(life_rate) if life_rate else 0.0
    except (ValueError, TypeError):
        life_rate_val = 0.0
    if not summary.get("life_rate") and life_rate_val > 0:
        record.discrepancies.append(
            "Census indicates active life plan (has rate) but no life plan line "
            "was found on the PDF invoice for this employee."
        )
