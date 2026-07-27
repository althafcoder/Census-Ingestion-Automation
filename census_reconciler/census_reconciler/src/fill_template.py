"""
fill_template.py
----------------
Writes merged census+PDF records into a copy of the Prestige template,
using the exact column layout declared in config.TEMPLATE_COLUMNS.

We open the *template* workbook itself (not a blank one) so all existing
formatting, merged header cells, and the "Census" sheet name are preserved
untouched -- only the data rows are populated.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import openpyxl

from config import (
    FIELD_TO_COL,
    TEMPLATE_FIRST_DATA_ROW,
    TEMPLATE_SHEET_NAME,
)
from reconcile import MergedRecord


def _col_letter_to_index(letter: str) -> int:
    return openpyxl.utils.column_index_from_string(letter)


def _record_to_row_values(record: MergedRecord, row_no: int) -> dict:
    row = record.census_row
    summary = record.plan_summary
    return {
        "row_no": row_no,
        "first_name": row.first_name,
        "last_name": row.last_name,
        "gender": row.gender,
        "dob": row.dob,
        "home_zip": row.home_zip,
        "relationship": row.relationship,
        "dependent_of_employee_number": row.dependent_of_employee_number,
        "medical_coverage_tier": summary.get("medical_coverage_tier") or row.medical_coverage_tier,
        "cobra": row.cobra,
        "medical_plan_enrolled": summary.get("medical_plan_enrolled"),
        "medical_plan_price": summary.get("medical_plan_price"),
        "dental_coverage_tier": summary.get("dental_coverage_tier") or row.dental_coverage_tier,
        "dental_plan_enrolled": summary.get("dental_plan_enrolled") or row.dental_plan_enrolled,
        "dental_plan_price": summary.get("dental_plan_price") or row.dental_plan_price,
        "vision_coverage_tier": summary.get("vision_coverage_tier") or row.vision_coverage_tier,
        "vision_plan_enrolled": summary.get("vision_plan_enrolled") or row.vision_plan_enrolled,
        "vision_plan_price": summary.get("vision_plan_price") or row.vision_plan_price,
        "life_plan_name": summary.get("life_plan_name") or row.life_plan_name,
        "life_benefit": row.life_benefit,
        "life_rate": summary.get("life_rate") or row.life_rate,
        "ltd_plan": summary.get("ltd_plan") or row.ltd_plan,
        "ltd_benefit": row.ltd_benefit,
        "ltd_rate": summary.get("ltd_rate") or row.ltd_rate,
        "std_plan": summary.get("std_plan") or row.std_plan,
        "std_benefit": row.std_benefit,
        "std_rate": summary.get("std_rate") or row.std_rate,
        "work_state": row.work_state,
        "job_title": row.job_title,
        "workers_comp_code": row.workers_comp_code,
        "annual_salary": row.annual_salary,
        "ft_pt": row.ft_pt,
    }


def fill_template(
    records: list[MergedRecord],
    template_path: Path,
    output_path: Path,
) -> Path:
    """
    Copy `template_path` to `output_path`, then populate the Census sheet's
    data rows (starting at TEMPLATE_FIRST_DATA_ROW) from `records`.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(template_path, output_path)

    wb = openpyxl.load_workbook(str(output_path))
    ws = wb[TEMPLATE_SHEET_NAME]

    for i, record in enumerate(records):
        target_row = TEMPLATE_FIRST_DATA_ROW + i
        values = _record_to_row_values(record, row_no=i + 1)
        for field_name, value in values.items():
            col_letter = FIELD_TO_COL[field_name]
            col_idx = _col_letter_to_index(col_letter)
            ws.cell(row=target_row, column=col_idx, value=value)

    wb.save(str(output_path))
    return output_path
