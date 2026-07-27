"""
normalize.py
------------
Normalization + alignment layer between the deterministic PDF/Excel
extractions.

This module intentionally separates two kinds of work:

1. DETERMINISTIC normalization (dates, money, whitespace, tier codes) --
   always done in plain Python; no ambiguity, so no LLM needed.

2. FUZZY alignment (matching "Acosta, Joseph" (PDF) to "Joseph Acosta"
   (Census) when spellings/suffixes/order differ, and classifying a raw
   plan-name string like "AET METRO NTL EPO 4000-80" into a template
   bucket like "medical") -- this is exactly the kind of ambiguous,
   language-shaped task an LLM is good at.

   `match_name()` and `classify_plan()` below implement a solid rule-based
   baseline (difflib + keyword rules) so the pipeline runs fully offline
   and deterministically for grading/repeatability. Each function has a
   documented seam -- `llm_client` parameter -- where you can swap in a
   real LLM call (see call_llm_for_ambiguous_matches() at the bottom) for
   the residual cases the rules can't resolve confidently. This keeps the
   *default* pipeline dependency-free while making the LLM-assisted upgrade
   a one-line change.
"""
from __future__ import annotations

import difflib
import re
from typing import Optional

from config import PLAN_CATEGORY_RULES, MEDICAL_TIER_MAP, MEDICAL_TIER_WAIVED


def normalize_name_key(first: str, last: str) -> str:
    """Lowercase, whitespace-collapsed 'first last' key for exact matching."""
    first = re.sub(r"\s+", " ", (first or "").strip().lower())
    last = re.sub(r"\s+", " ", (last or "").strip().lower())
    # Strip common suffixes that appear inconsistently between the two files
    # (e.g. "Acosta III" in the PDF vs "Acosta" in the census).
    last = re.sub(r"\b(jr|sr|ii|iii|iv)\.?$", "", last).strip()
    return f"{first} {last}"


def best_fuzzy_match(target_key: str, candidate_keys: list[str], cutoff: float = 0.82) -> Optional[str]:
    """
    Return the closest candidate key to `target_key` using sequence
    similarity, or None if nothing clears `cutoff`.

    This is the deterministic stand-in for an LLM-assisted match. Swap the
    body of this function for an LLM call (batched, with the full pair of
    candidate lists) if you need to handle harder cases such as transposed
    given/family names across cultures, nicknames, or transliteration
    differences that difflib can't see.
    """
    matches = difflib.get_close_matches(target_key, candidate_keys, n=1, cutoff=cutoff)
    return matches[0] if matches else None


def classify_plan(plan_name: str) -> str:
    """
    Map a raw PDF plan-name string to a template bucket:
    medical | dental | vision | life | ltd | std | voluntary_other

    Rule-based baseline; see module docstring re: LLM upgrade path.
    """
    name = plan_name.upper()
    for category, keywords in PLAN_CATEGORY_RULES:
        if not keywords:
            continue
        if any(kw.upper() in name for kw in keywords):
            return category
    return "voluntary_other"


def money(value) -> float:
    """Coerce a PDF/Excel money value (str, float, None) to a rounded float."""
    if value is None:
        return 0.0
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").strip()
        if value in ("", "-", "--"):
            return 0.0
        value = float(value)
    return round(float(value), 2)


def normalize_tier(tier: Optional[str], category: str = "") -> Optional[str]:
    if tier is None:
        return None
    tier = tier.strip().upper()
    
    # Handle composite tiers from OCR like "M1;V1;" or "M1; V1"
    if ";" in tier:
        parts = [p.strip() for p in tier.split(";") if p.strip()]
        for p in parts:
            if category == "medical" and p.startswith("M"):
                return p
            elif category == "vision" and p.startswith("V"):
                return p
            elif category == "dental" and p.startswith("D"):
                return p
        
        if parts:
            return parts[0]
            
    return tier


def _empty_summary() -> dict:
    return {
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
        "notes": [],
    }

def build_employee_plan_summaries(employee_benefits_list) -> list[dict]:
    """
    Collapse a list of EmployeeBenefits records' raw plan lines (from pdf_extractor)
    into field-per-category summaries matching the template's column groups.

    If multiple plans of the same core category are found (e.g. two basic life plans),
    they will spill over into a new overflow summary, which results in the employee
    getting an additional row in the output template.
    """
    summaries = [_empty_summary()]
    seen_category_prices = [{}]
    
    all_plans = []
    for emp in employee_benefits_list:
        all_plans.extend(emp.plans)

    for plan in all_plans:
        category = classify_plan(plan.plan_name)
        price = money(plan.total_monthly_due)

        placed = False
        for i, summary in enumerate(summaries):
            if category == "medical":
                if summary["medical_plan_enrolled"] is None:
                    raw_tier = normalize_tier(plan.coverage_tier, category)
                    summary["medical_coverage_tier"] = MEDICAL_TIER_MAP.get(raw_tier, raw_tier)
                    summary["medical_plan_enrolled"] = plan.plan_name
                    summary["medical_plan_price"] = price
                    seen_category_prices[i]["medical"] = price
                    placed = True
                    break
                elif price <= seen_category_prices[i].get("medical", -1):
                    summary["notes"].append(f"Duplicate medical line ignored: {plan.plan_name}")
                    placed = True
                    break

            elif category == "dental":
                if summary["dental_plan_enrolled"] is None:
                    summary["dental_coverage_tier"] = normalize_tier(plan.coverage_tier, category)
                    summary["dental_plan_enrolled"] = plan.plan_name
                    summary["dental_plan_price"] = price
                    seen_category_prices[i]["dental"] = price
                    placed = True
                    break
                elif price <= seen_category_prices[i].get("dental", -1):
                    summary["notes"].append(f"Duplicate dental line ignored: {plan.plan_name}")
                    placed = True
                    break

            elif category == "vision":
                if summary["vision_plan_enrolled"] is None:
                    summary["vision_coverage_tier"] = normalize_tier(plan.coverage_tier, category)
                    summary["vision_plan_enrolled"] = plan.plan_name
                    summary["vision_plan_price"] = price
                    seen_category_prices[i]["vision"] = price
                    placed = True
                    break
                elif price <= seen_category_prices[i].get("vision", -1):
                    summary["notes"].append(f"Duplicate vision line ignored: {plan.plan_name}")
                    placed = True
                    break

            elif category == "life":
                # Prefer the base "METL LIFE INS $x,xxx" line over voluntary/whole-life riders.
                is_base_life = "VOLUNTARY" not in plan.plan_name.upper() and "WHOLE LIFE" not in plan.plan_name.upper()
                if not is_base_life:
                    summary["notes"].append(f"Additional life line noted only: {plan.plan_name}")
                    placed = True
                    break
                    
                if summary["life_plan_name"] is None:
                    summary["life_plan_name"] = plan.plan_name
                    summary["life_benefit"] = normalize_tier(plan.coverage_tier, category)
                    summary["life_rate"] = price
                    placed = True
                    break

            elif category == "ltd":
                if summary["ltd_plan"] is None:
                    summary["ltd_plan"] = plan.plan_name
                    summary["ltd_benefit"] = normalize_tier(plan.coverage_tier, category)
                    summary["ltd_rate"] = price
                    placed = True
                    break

            elif category == "std":
                if summary["std_plan"] is None:
                    summary["std_plan"] = plan.plan_name
                    summary["std_benefit"] = normalize_tier(plan.coverage_tier, category)
                    summary["std_rate"] = price
                    placed = True
                    break

            else:
                summary["notes"].append(f"Voluntary/other line not mapped to template column: {plan.plan_name} (${price})")
                placed = True
                break

        if not placed:
            # Create a new overflow summary for this extra plan
            new_summary = _empty_summary()
            seen_category_prices.append({})
            
            if category == "medical":
                raw_tier = normalize_tier(plan.coverage_tier, category)
                new_summary["medical_coverage_tier"] = MEDICAL_TIER_MAP.get(raw_tier, raw_tier)
                new_summary["medical_plan_enrolled"] = plan.plan_name
                new_summary["medical_plan_price"] = price
                seen_category_prices[-1]["medical"] = price
            elif category == "dental":
                new_summary["dental_coverage_tier"] = normalize_tier(plan.coverage_tier, category)
                new_summary["dental_plan_enrolled"] = plan.plan_name
                new_summary["dental_plan_price"] = price
                seen_category_prices[-1]["dental"] = price
            elif category == "vision":
                new_summary["vision_coverage_tier"] = normalize_tier(plan.coverage_tier, category)
                new_summary["vision_plan_enrolled"] = plan.plan_name
                new_summary["vision_plan_price"] = price
                seen_category_prices[-1]["vision"] = price
            elif category == "life":
                new_summary["life_plan_name"] = plan.plan_name
                new_summary["life_benefit"] = normalize_tier(plan.coverage_tier, category)
                new_summary["life_rate"] = price
            elif category == "ltd":
                new_summary["ltd_plan"] = plan.plan_name
                new_summary["ltd_benefit"] = normalize_tier(plan.coverage_tier, category)
                new_summary["ltd_rate"] = price
            elif category == "std":
                new_summary["std_plan"] = plan.plan_name
                new_summary["std_benefit"] = normalize_tier(plan.coverage_tier, category)
                new_summary["std_rate"] = price
            
            summaries.append(new_summary)

    return summaries


def call_llm_for_ambiguous_matches(unmatched_pdf_names, unmatched_census_names, llm_client=None):
    """
    Optional LLM-assisted resolution step for names that the deterministic
    fuzzy matcher (best_fuzzy_match) could not confidently pair.

    This is a documented seam, not wired into main.py by default, so the
    pipeline stays runnable with zero external API dependencies. To enable:

        from anthropic import Anthropic
        client = Anthropic()
        pairs = call_llm_for_ambiguous_matches(unmatched_pdf, unmatched_census, client)

    and implement the prompt/parse logic below to taste. The prompt should:
      - list both unmatched-name lists,
      - ask the model to return JSON pairs {"pdf_name": ..., "census_name": ...}
        only where it is confident, and
      - explicitly allow "no match" so the model doesn't force pairings.
    """
    if llm_client is None:
        return {}
    raise NotImplementedError(
        "Wire up your LLM client's prompt/response handling here. "
        "Left unimplemented intentionally -- see docstring."
    )
