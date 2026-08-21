"""
test_pipeline.py
-----------------
Lightweight smoke tests (no pytest dependency required beyond pytest itself)
that exercise each module against the sample files in input/.

Run with:
    pytest tests/ -v
or directly:
    python tests/test_pipeline.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config
from census_extractor import extract_census
from pdf_extractor import extract_employee_benefits
from normalize import classify_plan, money, normalize_name_key, best_fuzzy_match
from reconcile import match_employees
from fill_template import fill_template
from report import build_report


def test_census_extraction_row_count():
    rows = extract_census(config.DEFAULT_CENSUS_XLSX)
    assert len(rows) > 0
    assert rows[0].first_name is not None
    assert rows[0].last_name is not None


def test_pdf_extraction_finds_employees():
    employees = extract_employee_benefits(config.DEFAULT_PDF)
    assert len(employees) > 200  # invoice has ~290 employee blocks
    first = employees[0]
    assert first.first_name and first.last_name
    assert len(first.plans) > 0





def test_plan_classification():
    assert classify_plan("AET METRO NTL EPO 4000-80") == "medical"
    assert classify_plan("AET DENTAL MID PPO") == "dental"
    assert classify_plan("AETNA VISION CORE") == "vision"
    assert classify_plan("METL LIFE INS $15,000") == "life"
    assert classify_plan("METL ER LTD 180D 2K") == "ltd"
    assert classify_plan("METL ER STD 26 WKS 14D 500") == "std"
    assert classify_plan("METV ACCIDENT HI PLAN") == "voluntary_other"


def test_money_parsing():
    assert money("$ 1,236.16") == 1236.16
    assert money(None) == 0.0
    assert money(45.0) == 45.0


def test_name_matching_helpers():
    key = normalize_name_key("Joseph", "Acosta III")
    assert key == "joseph acosta"
    matches = best_fuzzy_match("jose acosta", ["joseph acosta", "maria lopez"])
    assert matches == "joseph acosta"


def test_end_to_end_pipeline(tmp_path):
    census_rows = extract_census(config.DEFAULT_CENSUS_XLSX)
    pdf_employees = extract_employee_benefits(config.DEFAULT_PDF)

    merged, stats = match_employees(census_rows, [pdf_employees])
    assert len(merged) == len(census_rows)
    assert stats["exact_matches"] > 0

    output_path = tmp_path / "filled.xlsx"
    fill_template(merged, config.DEFAULT_TEMPLATE_XLSX, output_path)
    assert output_path.exists()

    report = build_report(merged, stats)
    assert report["total_records"] == len(census_rows)
    assert "records_with_discrepancies" in report


if __name__ == "__main__":
    # Allow `python tests/test_pipeline.py` without pytest installed.
    import inspect
    tests = [f for name, f in globals().items() if name.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            if "tmp_path" in inspect.signature(t).parameters:
                import tempfile
                with tempfile.TemporaryDirectory() as d:
                    t(Path(d))
            else:
                t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL: {t.__name__} -> {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
