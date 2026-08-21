from typing import List, Tuple
from .models import CensusRecord, InvoiceRecord

class ExtractionValidator:
    @staticmethod
    def validate_census(records: List[CensusRecord]) -> Tuple[bool, List[str]]:
        errors = []
        if not records:
            errors.append("Census extraction returned no records.")
        # Basic validation: ensure at least some employees have benefits
        has_benefits = any(rec.benefits for rec in records)
        if not has_benefits:
            errors.append("No benefits found in census extraction.")
        return len(errors) == 0, errors

    @staticmethod
    def validate_invoice(records: List[InvoiceRecord]) -> Tuple[bool, List[str]]:
        errors = []
        if not records:
            errors.append("Invoice extraction returned no records.")
        has_benefits = any(rec.benefits for rec in records)
        if not has_benefits:
            errors.append("No benefits found in invoice extraction.")
        return len(errors) == 0, errors

class FinancialValidator:
    @staticmethod
    def validate_invoice_totals(records: List[InvoiceRecord], reported_total: float = None) -> Tuple[str, str]:
        # Calculate sum of all premiums
        calculated_total = 0.0
        for rec in records:
            for b in rec.benefits.values():
                if b.premium:
                    calculated_total += b.premium
            for d in rec.dependents:
                for b in d.benefits.values():
                    if b.premium:
                        calculated_total += b.premium

        if reported_total is None:
            return "NOT_APPLICABLE", "Reported invoice grand total was not available"
        
        if abs(calculated_total - reported_total) < 1.0: # allow rounding differences
            return "PASS", "Calculated total matches reported total."
        
        return "WARNING", f"Calculated total {calculated_total} differs from reported total {reported_total}."
