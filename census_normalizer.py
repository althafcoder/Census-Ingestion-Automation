"""
census_normalizer.py
--------------------
Pre-processing layer for census files that use a pivoted/tall layout where
each row represents one plan enrollment per person (Product Type + Plan Name
+ Carrier columns) rather than the flat/wide layout where each person has
one row with separate columns for each plan type.

This module:
  1. Detects whether a census worksheet uses a flat or pivoted layout.
  2. If pivoted, groups rows by person, classifies each plan row by
     Product Type, and emits one flat CensusRow per unique person
     with all plan slots populated.

Dependents get their own individual plan data read from their rows
(not inherited from the subscriber), since dependents can have different
coverages.

EAP and other non-template product types are silently ignored.

Design principle: all pivoting logic is deterministic (no LLM). The LLM
is only invoked as a fallback when Product Type is missing or unrecognizable.
"""
from __future__ import annotations

import json
import warnings
from collections import defaultdict
from typing import Optional

from config import (
    PRODUCT_TYPE_CLASSIFICATION,
    MEDICAL_TIER_MAP,
)

# Avoid circular import: CensusRow is imported lazily or from census_extractor.
# We define the function signatures here so census_extractor can call us.


# ---------------------------------------------------------------------------
# Layout detection
# ---------------------------------------------------------------------------

# The pivoted-census marker fields: if these appear in the auto-detected
# column mapping AND the flat plan-specific columns do NOT, the layout is
# pivoted.
_PIVOTED_MARKER_FIELDS = {"product_type", "plan_name_generic"}
_FLAT_PLAN_FIELDS = {
    "medical_plan_enrolled", "dental_plan_enrolled", "vision_plan_enrolled",
    "life_plan_name", "dental_coverage_tier", "vision_coverage_tier",
}


def detect_census_layout(field_cols: dict[str, int]) -> str:
    """
    Determine census layout type from auto-detected column mapping.

    Returns:
        "pivoted" — if the census has Product Type / Plan Name columns
                     but no separate plan-specific columns.
        "flat"    — standard one-row-per-person layout (existing behavior).
    """
    has_pivoted_markers = _PIVOTED_MARKER_FIELDS.issubset(field_cols.keys())
    has_flat_plan_cols = bool(_FLAT_PLAN_FIELDS & field_cols.keys())

    if has_pivoted_markers and not has_flat_plan_cols:
        return "pivoted"
    return "flat"


# ---------------------------------------------------------------------------
# Product Type classification
# ---------------------------------------------------------------------------

def _classify_product_type(
    product_type: str | None,
    plan_name: str | None = None,
    carrier: str | None = None,
) -> str:
    """
    Classify a raw Product Type value into a template category.

    Returns one of: "medical", "dental", "vision", "life", "ltd", "std",
    "ignore", or "unknown".

    Uses deterministic rules from PRODUCT_TYPE_CLASSIFICATION first.
    Falls back to keyword matching on plan_name/carrier if product_type
    doesn't match. Returns "unknown" if nothing matches (caller can
    optionally route to LLM).
    """
    if product_type:
        pt_lower = product_type.strip().lower()

        # Direct lookup
        if pt_lower in PRODUCT_TYPE_CLASSIFICATION:
            return PRODUCT_TYPE_CLASSIFICATION[pt_lower]

        # Substring match against known keys
        for key, category in PRODUCT_TYPE_CLASSIFICATION.items():
            if key in pt_lower:
                return category

    # Fallback: infer from plan_name or carrier text
    combined = " ".join(filter(None, [plan_name, carrier])).lower()
    if not combined.strip():
        return "unknown"

    # Order matters: more specific first
    _keyword_rules = [
        ("dental", ["dental"]),
        ("vision", ["vision", "vsp"]),
        ("life",   ["life", "ad&d", "ad & d"]),
        ("ltd",    ["ltd", "long term disability"]),
        ("std",    ["std", "short term disability"]),
        ("medical", ["medical", "hmo", "ppo", "epo", "hsa", "blue cross",
                     "aetna", "cigna", "united health", "anthem"]),
    ]
    for category, keywords in _keyword_rules:
        if any(kw in combined for kw in keywords):
            return category

    # EAP / FSA etc. in plan name
    for ignored in ("eap", "fsa", "hsa", "cobra", "401k", "retirement"):
        if ignored in combined:
            return "ignore"

    return "unknown"


def _classify_with_llm_fallback(
    unclassified: list[dict],
) -> dict[int, str]:
    """
    For rows where _classify_product_type returned 'unknown', ask the LLM.

    Args:
        unclassified: list of dicts with keys 'index', 'product_type',
                      'plan_name', 'carrier'.

    Returns:
        dict mapping index -> category string.
    """
    if not unclassified:
        return {}

    try:
        import openai
        from dotenv import load_dotenv
        load_dotenv()

        client = openai.OpenAI()

        items_desc = "\n".join(
            f"  {i+1}. Product Type: \"{item['product_type']}\", "
            f"Plan Name: \"{item['plan_name']}\", "
            f"Carrier: \"{item['carrier']}\""
            for i, item in enumerate(unclassified)
        )

        prompt = f"""You are classifying employee benefit plan lines into categories.

For each plan line below, classify it into exactly ONE of these categories:
  medical, dental, vision, life, ltd, std, ignore

Use "ignore" for plans that don't fit any category (EAP, FSA, HSA, 401k, etc.).

Plan lines:
{items_desc}

Return a JSON object where keys are the line numbers (1-based) as strings,
and values are the category. Example: {{"1": "medical", "2": "ignore"}}
Output ONLY valid JSON."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if content:
            raw = json.loads(content)
            valid_categories = {"medical", "dental", "vision", "life",
                                "ltd", "std", "ignore"}
            result = {}
            for i, item in enumerate(unclassified):
                cat = raw.get(str(i + 1), "ignore")
                result[item["index"]] = cat if cat in valid_categories else "ignore"
            return result
    except Exception as e:
        warnings.warn(f"LLM product-type classification failed: {e}")

    # If LLM fails, default everything to "ignore"
    return {item["index"]: "ignore" for item in unclassified}


# ---------------------------------------------------------------------------
# Person key for grouping rows
# ---------------------------------------------------------------------------

def _person_key(first_name: str | None, last_name: str | None,
                dob: object = None) -> str:
    """
    Build a grouping key for a person. Uses first+last+DOB to handle
    cases where multiple family members share a last name.
    """
    fn = (first_name or "").strip().lower()
    ln = (last_name or "").strip().lower()
    dob_str = ""
    if dob is not None:
        dob_str = str(dob).strip().lower()
    return f"{fn}|{ln}|{dob_str}"


# ---------------------------------------------------------------------------
# Core pivot logic
# ---------------------------------------------------------------------------

def normalize_pivoted_census(
    ws,
    header_row: int,
    first_data_row: int,
    field_cols: dict[str, int],
) -> "list[CensusRow]":
    """
    Read a pivoted census worksheet and return flat CensusRow objects.

    Each person may have multiple rows (one per plan). We group by person,
    classify each plan row, and merge them into a single CensusRow with
    all plan slots populated.

    Dependents get their own CensusRow with their individual plan data.

    Args:
        ws: openpyxl worksheet.
        header_row: 1-based row index of the header.
        first_data_row: 1-based row index of the first data row.
        field_cols: dict mapping field names to 1-based column indices
                    (from auto-detect).

    Returns:
        list[CensusRow] in the order they appear (employees first, then
        their dependents, grouped).
    """
    # Lazy import to avoid circular dependency
    from census_extractor import CensusRow

    def _clean(value):
        if isinstance(value, str):
            value = value.strip()
            return value if value else None
        return value

    def get(row_idx: int, field_name: str, default=None):
        col = field_cols.get(field_name)
        if col is None:
            return default
        return _clean(ws.cell(row=row_idx, column=col).value)

    # --- Pass 1: Read all raw rows and group by person ---
    # Each raw_row is a dict of field_name -> value, plus the Excel row index.
    raw_rows = []
    r = first_data_row

    while r <= (ws.max_row or r):
        first_name = get(r, "first_name")
        last_name = get(r, "last_name")

        if first_name is None and last_name is None:
            # Check next row too (two consecutive empties = end of data)
            next_first = get(r + 1, "first_name") if r + 1 <= (ws.max_row or r) else None
            next_last = get(r + 1, "last_name") if r + 1 <= (ws.max_row or r) else None
            if next_first is None and next_last is None:
                break
            r += 1
            continue

        raw_row = {
            "excel_row": r,
            "first_name": first_name,
            "last_name": last_name,
            "gender": get(r, "gender"),
            "dob": get(r, "dob"),
            "home_zip": get(r, "home_zip"),
            "relationship": get(r, "relationship"),
            "dependent_of_employee_number": get(r, "dependent_of_employee_number"),
            "cobra": get(r, "cobra"),
            "work_state": get(r, "work_state"),
            "job_title": get(r, "job_title"),
            "workers_comp_code": get(r, "workers_comp_code"),
            "annual_salary": get(r, "annual_salary"),
            "ft_pt": get(r, "ft_pt"),
            # Pivoted-specific columns
            "product_type": get(r, "product_type"),
            "plan_name_generic": get(r, "plan_name_generic"),
            "carrier": get(r, "carrier"),
            "tier_generic": get(r, "tier_generic"),
            "volume": get(r, "volume"),
            "premium": get(r, "premium"),
            "family_id": get(r, "family_id"),
        }
        raw_rows.append(raw_row)
        r += 1

    if not raw_rows:
        return []

    # --- Pass 2: Classify product types ---
    unclassified_for_llm = []
    for i, row in enumerate(raw_rows):
        category = _classify_product_type(
            row["product_type"], row["plan_name_generic"], row["carrier"]
        )
        row["_category"] = category
        if category == "unknown":
            unclassified_for_llm.append({
                "index": i,
                "product_type": row["product_type"] or "",
                "plan_name": row["plan_name_generic"] or "",
                "carrier": row["carrier"] or "",
            })

    # LLM fallback for unknowns
    if unclassified_for_llm:
        llm_results = _classify_with_llm_fallback(unclassified_for_llm)
        for idx, category in llm_results.items():
            raw_rows[idx]["_category"] = category
        classified_count = sum(1 for c in llm_results.values() if c != "ignore")
        if classified_count:
            print(f"      -> LLM classified {classified_count} unknown product types")

    # --- Pass 3: Group rows by person ---
    # Maintain insertion order so employees appear before their dependents.
    person_groups: dict[str, list[dict]] = defaultdict(list)
    person_order: list[str] = []

    for row in raw_rows:
        key = _person_key(row["first_name"], row["last_name"], row["dob"])
        if key not in person_groups:
            person_order.append(key)
        person_groups[key].append(row)

    # --- Pass 4: Build CensusRow objects ---
    # Determine relationship mapping for Self vs dependent
    _self_values = {"self", "ee", "employee", "subscriber", "member"}

    census_rows: list[CensusRow] = []
    # Track employees vs dependents for ordering
    employees = []
    dependents_by_subscriber = defaultdict(list)

    for pkey in person_order:
        rows = person_groups[pkey]
        # Use the first row for demographic data (all rows for the same
        # person share the same demographic info).
        demo = rows[0]

        # Initialize plan fields as None
        plan_data = {
            "medical_coverage_tier": None,
            "medical_plan_enrolled": None,
            "medical_plan_price": None,
            "dental_coverage_tier": None,
            "dental_plan_enrolled": None,
            "dental_plan_price": None,
            "vision_coverage_tier": None,
            "vision_plan_enrolled": None,
            "vision_plan_price": None,
            "life_plan_name": None,
            "life_benefit": None,
            "life_rate": None,
            "ltd_plan": None,
            "ltd_benefit": None,
            "ltd_rate": None,
            "std_plan": None,
            "std_benefit": None,
            "std_rate": None,
        }

        # Route each plan row to the correct fields
        for row in rows:
            category = row["_category"]
            plan_name = row["plan_name_generic"]
            tier = row["tier_generic"]
            premium = row["premium"]
            volume = row["volume"]
            carrier = row["carrier"]

            # Build a descriptive plan name including carrier if available
            full_plan_name = plan_name
            if carrier and plan_name:
                # Don't duplicate if carrier is already in plan name
                if carrier.lower() not in (plan_name or "").lower():
                    full_plan_name = f"{plan_name} ({carrier})"

            if category == "medical":
                if plan_data["medical_plan_enrolled"] is None:
                    # Map tier through MEDICAL_TIER_MAP
                    raw_tier = (tier or "").strip().upper()
                    plan_data["medical_coverage_tier"] = MEDICAL_TIER_MAP.get(raw_tier, raw_tier) or None
                    plan_data["medical_plan_enrolled"] = full_plan_name
                    plan_data["medical_plan_price"] = premium

            elif category == "dental":
                if plan_data["dental_plan_enrolled"] is None:
                    plan_data["dental_coverage_tier"] = (tier or "").strip().upper() or None
                    plan_data["dental_plan_enrolled"] = full_plan_name
                    plan_data["dental_plan_price"] = premium

            elif category == "vision":
                if plan_data["vision_plan_enrolled"] is None:
                    plan_data["vision_coverage_tier"] = (tier or "").strip().upper() or None
                    plan_data["vision_plan_enrolled"] = full_plan_name
                    plan_data["vision_plan_price"] = premium

            elif category == "life":
                if plan_data["life_plan_name"] is None:
                    plan_data["life_plan_name"] = full_plan_name
                    plan_data["life_benefit"] = volume
                    plan_data["life_rate"] = premium

            elif category == "ltd":
                if plan_data["ltd_plan"] is None:
                    plan_data["ltd_plan"] = full_plan_name
                    plan_data["ltd_benefit"] = volume
                    plan_data["ltd_rate"] = premium

            elif category == "std":
                if plan_data["std_plan"] is None:
                    plan_data["std_plan"] = full_plan_name
                    plan_data["std_benefit"] = volume
                    plan_data["std_rate"] = premium

            # "ignore" and "unknown" are silently skipped

        # Determine relationship
        rel_raw = (demo.get("relationship") or "").strip().lower()
        is_self = rel_raw in _self_values or rel_raw == ""

        # Map relationship value to the format expected by the template
        relationship = "EE" if is_self else (demo.get("relationship") or "").strip()

        census_row = CensusRow(
            row_no=demo.get("family_id"),
            first_name=demo["first_name"],
            last_name=demo["last_name"],
            gender=demo["gender"],
            dob=demo["dob"],
            home_zip=demo["home_zip"],
            relationship=relationship,
            dependent_of_employee_number=demo["dependent_of_employee_number"],
            medical_coverage_tier=plan_data["medical_coverage_tier"],
            medical_plan_enrolled=plan_data["medical_plan_enrolled"],
            medical_plan_price=plan_data["medical_plan_price"],
            cobra=demo["cobra"],
            dental_coverage_tier=plan_data["dental_coverage_tier"],
            dental_plan_enrolled=plan_data["dental_plan_enrolled"],
            dental_plan_price=plan_data["dental_plan_price"],
            vision_coverage_tier=plan_data["vision_coverage_tier"],
            vision_plan_enrolled=plan_data["vision_plan_enrolled"],
            vision_plan_price=plan_data["vision_plan_price"],
            life_plan_name=plan_data["life_plan_name"],
            life_benefit=plan_data["life_benefit"],
            life_rate=plan_data["life_rate"],
            ltd_plan=plan_data["ltd_plan"],
            ltd_benefit=plan_data["ltd_benefit"],
            ltd_rate=plan_data["ltd_rate"],
            std_plan=plan_data["std_plan"],
            std_benefit=plan_data["std_benefit"],
            std_rate=plan_data["std_rate"],
            work_state=demo["work_state"],
            job_title=demo["job_title"],
            workers_comp_code=demo["workers_comp_code"],
            annual_salary=demo["annual_salary"],
            ft_pt=demo["ft_pt"],
        )

        if is_self:
            employees.append(census_row)
        else:
            # Link dependent to their subscriber. We use last_name as a
            # rough heuristic since Family ID is often empty in pivoted
            # census files. The fill_template step will fix up the
            # dependent_of_employee_number based on row ordering.
            dependents_by_subscriber[demo["last_name"] or ""].append(census_row)

    # --- Pass 5: Order output (employee followed by their dependents) ---
    for emp in employees:
        census_rows.append(emp)
        # Find dependents sharing the same last name
        last = (emp.last_name or "").strip()
        if last in dependents_by_subscriber:
            for dep in dependents_by_subscriber[last]:
                census_rows.append(dep)
            del dependents_by_subscriber[last]

    # Append any remaining dependents whose subscriber wasn't found
    for deps in dependents_by_subscriber.values():
        census_rows.extend(deps)

    return census_rows
