from typing import List, Dict, Optional
from extractors.census_extractor import CensusRow
from extractors.invoice_extractor import InvoiceExtractionResult, EmployeeBenefits
from core.models import CensusRecord, SubscriberDependent, BenefitEnrollment, InvoiceRecord
from core.normalization import Normalizer

class ExtractionAdapter:
    @staticmethod
    def map_census(rows: List[CensusRow]) -> List[CensusRecord]:
        subscribers: Dict[str, CensusRecord] = {}
        dependents: List[CensusRow] = []

        # First pass: map subscribers
        for row in rows:
            if not row.is_dependent:
                rec = CensusRecord(
                    employee_id=str(row.row_no) if row.row_no else f"gen_{id(row)}",
                    first_name=row.first_name,
                    last_name=row.last_name,
                    normalized_name=Normalizer.normalize_name(f"{row.first_name} {row.last_name}"),
                    dob=str(row.dob) if row.dob else None,
                    zip_code=row.home_zip,
                    relationship=row.relationship or "Employee",
                    benefits=ExtractionAdapter._extract_benefits_from_row(row)
                )
                subscribers[rec.employee_id] = rec
            else:
                dependents.append(row)

        # Second pass: link dependents
        for dep_row in dependents:
            parent_id = str(dep_row.dependent_of_employee_number)
            if parent_id in subscribers:
                dep_rec = SubscriberDependent(
                    first_name=dep_row.first_name,
                    last_name=dep_row.last_name,
                    normalized_name=Normalizer.normalize_name(f"{dep_row.first_name} {dep_row.last_name}"),
                    dob=str(dep_row.dob) if dep_row.dob else None,
                    relationship=dep_row.relationship,
                    benefits=ExtractionAdapter._extract_benefits_from_row(dep_row)
                )
                subscribers[parent_id].dependents.append(dep_rec)
            else:
                # Orphaned dependent - might need to become a standalone record for visibility
                pass

        return list(subscribers.values())

    @staticmethod
    def _extract_benefits_from_row(row: CensusRow) -> Dict[str, BenefitEnrollment]:
        benefits = {}
        
        if row.medical_plan_enrolled or row.medical_coverage_tier:
            benefits["medical"] = BenefitEnrollment(
                benefit_type="medical",
                plan_name_raw=row.medical_plan_enrolled,
                coverage_tier_raw=row.medical_coverage_tier,
                premium=float(row.medical_plan_price) if row.medical_plan_price else None
            )
            
        if row.dental_plan_enrolled or row.dental_coverage_tier:
            benefits["dental"] = BenefitEnrollment(
                benefit_type="dental",
                plan_name_raw=row.dental_plan_enrolled,
                coverage_tier_raw=row.dental_coverage_tier,
                premium=float(row.dental_plan_price) if row.dental_plan_price else None
            )
            
        if row.vision_plan_enrolled or row.vision_coverage_tier:
            benefits["vision"] = BenefitEnrollment(
                benefit_type="vision",
                plan_name_raw=row.vision_plan_enrolled,
                coverage_tier_raw=row.vision_coverage_tier,
                premium=float(row.vision_plan_price) if row.vision_plan_price else None
            )
            
        if row.life_plan_name or row.life_benefit:
            benefits["life"] = BenefitEnrollment(
                benefit_type="life",
                plan_name_raw=row.life_plan_name,
                premium=float(row.life_rate) if row.life_rate else None
            )
            
        # Continue for STD, LTD if needed
        return benefits

    @staticmethod
    def map_invoice(result: InvoiceExtractionResult) -> List[InvoiceRecord]:
        records = []
        for emp in result.current_subscribers:
            rec = InvoiceRecord(
                first_name=emp.first_name,
                last_name=emp.last_name,
                normalized_name=Normalizer.normalize_name(f"{emp.first_name} {emp.last_name}"),
                employee_id=emp.employee_id,
                benefits={}
            )
            
            for plan in emp.plans:
                b_type = Normalizer.normalize_plan(plan.plan_name, [("medical", ["medical", "hmo", "ppo", "epo"])]) # Basic mapping
                # Fallback simple logic
                if "dental" in plan.plan_name.lower(): b_type = "dental"
                elif "vision" in plan.plan_name.lower(): b_type = "vision"
                elif "life" in plan.plan_name.lower(): b_type = "life"
                
                if b_type == "UNKNOWN":
                    b_type = "medical" # Default fallback for missing classification
                    
                rec.benefits[b_type] = BenefitEnrollment(
                    benefit_type=b_type,
                    plan_name_raw=plan.plan_name,
                    coverage_tier_raw=plan.coverage_tier,
                    premium=float(plan.total_monthly_due)
                )
                
            records.append(rec)
            
        return records
