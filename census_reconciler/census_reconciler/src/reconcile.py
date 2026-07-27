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

from census_extractor import CensusRow
from normalize import normalize_name_key, best_fuzzy_match, build_employee_plan_summary, money
from pdf_extractor import EmployeeBenefits


@dataclass
class MergedRecord:
    census_row: CensusRow
    pdf_employee: Optional[EmployeeBenefits]
    plan_summary: dict
    match_method: str  # "exact" | "fuzzy" | "dependent_inherits_subscriber" | "unmatched"
    discrepancies: list[str] = field(default_factory=list)


def _index_census_employees(census_rows: list[CensusRow]) -> dict[str, CensusRow]:
    return {
        normalize_name_key(r.first_name, r.last_name): r
        for r in census_rows
        if not r.is_dependent
    }


def _index_pdf_employees(pdf_employees: list[EmployeeBenefits]) -> dict[str, EmployeeBenefits]:
    return {normalize_name_key(e.first_name, e.last_name): e for e in pdf_employees}


def match_employees(
    census_rows: list[CensusRow], pdf_employees: list[EmployeeBenefits]
) -> tuple[list[MergedRecord], dict]:
    """
    Returns (merged_records, match_stats).

    merged_records has one entry per census row (employees AND dependents);
    dependents are linked to their subscriber's PDF match via
    dependent_of_employee_number where available, else via adjacency in the
    census sheet (dependents are listed directly under their subscriber).
    """
    census_ee_index = _index_census_employees(census_rows)
    pdf_index = _index_pdf_employees(pdf_employees)

    exact_matches: dict[str, EmployeeBenefits] = {}
    unmatched_census_keys: list[str] = []

    for key in census_ee_index:
        if key in pdf_index:
            exact_matches[key] = pdf_index[key]
        else:
            unmatched_census_keys.append(key)

    # Fuzzy pass over what's left.
    unmatched_pdf_keys = [k for k in pdf_index if pdf_index[k] not in exact_matches.values()]
    fuzzy_matches: dict[str, EmployeeBenefits] = {}
    still_unmatched_census: list[str] = []
    for key in unmatched_census_keys:
        candidate = best_fuzzy_match(key, unmatched_pdf_keys)
        if candidate:
            fuzzy_matches[key] = pdf_index[candidate]
            unmatched_pdf_keys.remove(candidate)
        else:
            still_unmatched_census.append(key)

    # Track last-seen subscriber match while walking the census in original
    # order, so dependents can inherit it.
    merged: list[MergedRecord] = []
    last_subscriber_match: Optional[EmployeeBenefits] = None
    last_subscriber_summary: dict = {}

    for row in census_rows:
        if not row.is_dependent:
            key = normalize_name_key(row.first_name, row.last_name)
            pdf_emp = exact_matches.get(key) or fuzzy_matches.get(key)
            method = "exact" if key in exact_matches else ("fuzzy" if key in fuzzy_matches else "unmatched")
            summary = build_employee_plan_summary(pdf_emp) if pdf_emp else _empty_summary()
            last_subscriber_match, last_subscriber_summary = pdf_emp, summary
        else:
            # Dependent: inherits medical/dental/vision tier context from the
            # subscriber but typically has no independent price line in the
            # PDF (dependents ride on the subscriber's premium).
            pdf_emp = last_subscriber_match
            method = "dependent_inherits_subscriber" if pdf_emp else "unmatched"
            summary = _dependent_summary(last_subscriber_summary)

        record = MergedRecord(
            census_row=row,
            pdf_employee=pdf_emp,
            plan_summary=summary,
            match_method=method,
        )
        _flag_discrepancies(record)
        merged.append(record)

    stats = {
        "census_employee_count": len(census_ee_index),
        "pdf_employee_count": len(pdf_index),
        "exact_matches": len(exact_matches),
        "fuzzy_matches": len(fuzzy_matches),
        "unmatched_census_employees": still_unmatched_census,
        "unmatched_pdf_employees": [k for k in unmatched_pdf_keys],
    }
    return merged, stats


def _empty_summary() -> dict:
    return {
        "medical_coverage_tier": None, "medical_plan_enrolled": None, "medical_plan_price": None,
        "dental_coverage_tier": None, "dental_plan_enrolled": None, "dental_plan_price": None,
        "vision_coverage_tier": None, "vision_plan_enrolled": None, "vision_plan_price": None,
        "life_plan_name": None, "life_rate": None,
        "ltd_plan": None, "ltd_rate": None,
        "std_plan": None, "std_rate": None,
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

    if record.match_method == "unmatched":
        record.discrepancies.append(
            f"No PDF invoice match found for '{row.first_name} {row.last_name}' "
            f"(census row {row.row_no})."
        )
        return

    if record.match_method == "fuzzy":
        record.discrepancies.append(
            f"Matched via fuzzy name matching, not exact: "
            f"'{row.first_name} {row.last_name}' (census row {row.row_no})."
        )

    if row.is_dependent:
        return  # tier-only comparison already handled; no price to compare

    # Compare census pre-existing medical tier (if any) vs PDF-derived tier.
    census_tier = (row.medical_coverage_tier or "").strip().upper() or None
    pdf_tier = summary.get("medical_coverage_tier")
    if census_tier and pdf_tier and census_tier != pdf_tier:
        record.discrepancies.append(
            f"Medical coverage tier mismatch: census='{census_tier}' vs pdf='{pdf_tier}'."
        )

    if not summary.get("medical_plan_enrolled") and (row.medical_coverage_tier or "").strip().upper() not in (None, "", "WO"):
        record.discrepancies.append(
            "Census indicates active medical coverage tier but no medical plan line "
            "was found on the PDF invoice for this employee."
        )
