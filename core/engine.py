from pathlib import Path
from extractors.census_extractor import extract_census
from extractors.invoice_extractor import extract_employee_benefits
from extractors.adapters import ExtractionAdapter
from core.models import IdentityMatch
from reconciliation.reconciler import BenefitReconciler
from core.normalization import Normalizer
from reconcile import _llm_match  # Import LLM fallback logic
from reports.reconciliation_report import ReconciliationReportGenerator

class NewEnginePipeline:
    @staticmethod
    def run(census_path: Path, pdf_paths: list[Path], output_json: Path, output_csv: Path, output_excel: Path = None, template_path: Path = None):
        print("--- Running New Engine Pipeline ---")
        
        # 1. Extraction
        print("[1/4] Extracting Census...")
        census_rows = extract_census(census_path)
        census_records = ExtractionAdapter.map_census(census_rows)
        print(f"      -> {len(census_records)} Canonical Census Records created")

        print("[2/4] Extracting Invoices...")
        all_invoice_records = []
        for pdf in pdf_paths:
            result = extract_employee_benefits(pdf)
            invoice_records = ExtractionAdapter.map_invoice(result)
            all_invoice_records.extend(invoice_records)
        print(f"      -> {len(all_invoice_records)} Canonical Invoice Records created")

        # 2. Matching (Simplified for integration)
        print("[3/4] Primary Identity Matching...")
        matches = []
        unmatched_census = []
        unmatched_invoice = list(all_invoice_records)

        # Pass 1: Exact Name
        for c_rec in census_records:
            match_found = False
            for i_rec in unmatched_invoice:
                if c_rec.normalized_name == i_rec.normalized_name:
                    matches.append(IdentityMatch(
                        status="MATCHED",
                        confidence=1.0,
                        census_record=c_rec,
                        invoice_record=i_rec,
                        method="EXACT_NAME"
                    ))
                    unmatched_invoice.remove(i_rec)
                    match_found = True
                    break
            if not match_found:
                unmatched_census.append(c_rec)

        # Pass 2: Fuzzy Match
        still_unmatched_census = []
        for c_rec in unmatched_census:
            match_found = False
            best_score = 0
            best_match = None
            
            # Simple fuzzy implementation matching reconcile.py's best_fuzzy_match
            from normalize import best_fuzzy_match
            
            if unmatched_invoice:
                pdf_keys = {id(i): i.normalized_name for i in unmatched_invoice}
                candidate_key = best_fuzzy_match(c_rec.normalized_name, list(pdf_keys.values()))
                if candidate_key:
                    for i_rec in unmatched_invoice:
                        if i_rec.normalized_name == candidate_key:
                            best_match = i_rec
                            break
            
            if best_match:
                matches.append(IdentityMatch(
                    status="MATCHED",
                    confidence=0.8,
                    census_record=c_rec,
                    invoice_record=best_match,
                    method="FUZZY_NAME"
                ))
                unmatched_invoice.remove(best_match)
                match_found = True
                
            if not match_found:
                still_unmatched_census.append(c_rec)
                
        # Pass 3: LLM Match
        if still_unmatched_census and unmatched_invoice:
            c_names = [c.normalized_name for c in still_unmatched_census]
            p_names = [i.normalized_name for i in unmatched_invoice]
            llm_results = _llm_match(c_names, p_names)
            
            final_unmatched_census = []
            for c_rec in still_unmatched_census:
                if c_rec.normalized_name in llm_results:
                    p_name = llm_results[c_rec.normalized_name]
                    # Find matching invoice
                    best_match = next((i for i in unmatched_invoice if i.normalized_name == p_name), None)
                    if best_match:
                        matches.append(IdentityMatch(
                            status="MATCHED",
                            confidence=0.7,
                            census_record=c_rec,
                            invoice_record=best_match,
                            method="LLM_FALLBACK"
                        ))
                        unmatched_invoice.remove(best_match)
                        del llm_results[c_rec.normalized_name] # Prevent double-assign
                        continue
                final_unmatched_census.append(c_rec)
        else:
            final_unmatched_census = still_unmatched_census

        for c_rec in final_unmatched_census:
            matches.append(IdentityMatch(
                status="UNMATCHED",
                confidence=0.0,
                census_record=c_rec,
                invoice_record=None,
                method="NO_MATCH_FOUND"
            ))

        for i_rec in unmatched_invoice:
            matches.append(IdentityMatch(
                status="UNMATCHED",
                confidence=0.0,
                census_record=None,
                invoice_record=i_rec,
                method="NO_MATCH_FOUND"
            ))

        # 3. Reconciliation
        print("[4/4] Benefit Reconciliation...")
        reconciliation_results = []
        for match in matches:
            if match.status == "MATCHED":
                result = BenefitReconciler.reconcile(match)
                reconciliation_results.append(result)
            else:
                from core.models import ReconciliationResult
                reconciliation_results.append(ReconciliationResult(identity_match=match))

        # 4. Outputs
        print("Generating Output Reports...")
        ReconciliationReportGenerator.generate_json(reconciliation_results, str(output_json))
        ReconciliationReportGenerator.generate_csv(reconciliation_results, str(output_csv))
        
        # 5. Generate Excel
        if output_excel and template_path:
            print(f"Generating Filled Excel -> {output_excel}")
            try:
                # Convert ReconciliationResult to legacy MergedRecord format for the excel generator
                from reconcile import MergedRecord
                from output.excel_generator import fill_template
                from extractors.census_extractor import CensusRow
                
                legacy_records = []
                for res in reconciliation_results:
                    # Construct a dummy CensusRow and plan_summary to satisfy fill_template
                    c_rec = res.identity_match.census_record
                    i_rec = res.identity_match.invoice_record
                    
                    if c_rec:
                        def get_cb(b_type):
                            if b_type not in c_rec.benefits: return None, None, None
                            b = c_rec.benefits[b_type]
                            return b.normalized_plan_name or b.plan_name_raw, b.coverage_tier_raw or b.coverage_tier, b.premium

                        c_med_p, c_med_t, c_med_r = get_cb("medical")
                        c_den_p, c_den_t, c_den_r = get_cb("dental")
                        c_vis_p, c_vis_t, c_vis_r = get_cb("vision")
                        c_life_p, _, c_life_r = get_cb("life")
                        c_std_p, _, c_std_r = get_cb("std")
                        c_ltd_p, _, c_ltd_r = get_cb("ltd")

                        row_no = 0
                        if c_rec.source_refs:
                            ref = next(iter(c_rec.source_refs.values()))
                            row_no = ref.row or 0

                        c_row = CensusRow(
                            row_no=row_no,
                            first_name=c_rec.first_name,
                            last_name=c_rec.last_name,
                            gender="", dob="", home_zip="", relationship="EE",
                            dependent_of_employee_number="",
                            medical_coverage_tier=c_med_t, cobra="",
                            medical_plan_enrolled=c_med_p, medical_plan_price=c_med_r,
                            dental_coverage_tier=c_den_t, dental_plan_enrolled=c_den_p, dental_plan_price=c_den_r,
                            vision_coverage_tier=c_vis_t, vision_plan_enrolled=c_vis_p, vision_plan_price=c_vis_r,
                            life_plan_name=c_life_p, life_benefit="", life_rate=c_life_r,
                            std_plan=c_std_p, std_benefit="", std_rate=c_std_r,
                            ltd_plan=c_ltd_p, ltd_benefit="", ltd_rate=c_ltd_r,
                            work_state="", job_title="", workers_comp_code="", annual_salary="", ft_pt=""
                        )
                    else:
                        c_row = CensusRow(
                            row_no=0, first_name=i_rec.first_name if i_rec else "", last_name=i_rec.last_name if i_rec else "",
                            gender="", dob="", home_zip="", relationship="EE", dependent_of_employee_number="", medical_coverage_tier="", cobra=""
                        )

                    def get_ib(b_type):
                        if not i_rec or b_type not in i_rec.benefits: return None, None, None
                        b = i_rec.benefits[b_type]
                        return b.normalized_plan_name or b.plan_name_raw, b.coverage_tier_raw or b.coverage_tier, b.premium

                    i_med_p, i_med_t, i_med_r = get_ib("medical")
                    i_den_p, i_den_t, i_den_r = get_ib("dental")
                    i_vis_p, i_vis_t, i_vis_r = get_ib("vision")
                    i_life_p, _, i_life_r = get_ib("life")
                    i_std_p, _, i_std_r = get_ib("std")
                    i_ltd_p, _, i_ltd_r = get_ib("ltd")

                    plan_summary = {
                        "medical_coverage_tier": i_med_t,
                        "medical_plan_enrolled": i_med_p,
                        "medical_plan_price": i_med_r,
                        "dental_coverage_tier": i_den_t,
                        "dental_plan_enrolled": i_den_p,
                        "dental_plan_price": i_den_r,
                        "vision_coverage_tier": i_vis_t,
                        "vision_plan_enrolled": i_vis_p,
                        "vision_plan_price": i_vis_r,
                        "life_plan_name": i_life_p,
                        "life_benefit": None,
                        "life_rate": i_life_r,
                        "std_plan": i_std_p,
                        "std_benefit": None,
                        "std_rate": i_std_r,
                        "ltd_plan": i_ltd_p,
                        "ltd_benefit": None,
                        "ltd_rate": i_ltd_r,
                        "notes": []
                    }

                    status = res.identity_match.status
                    if status == "MATCHED":
                        method = "exact" if res.identity_match.method == "EXACT_NAME" else ("fuzzy" if res.identity_match.method == "FUZZY_NAME" else "llm")
                        discrepancy_status = "Review" if res.discrepancies else "Correct"
                    elif status == "UNMATCHED":
                        if c_rec:
                            method = "unmatched"
                            discrepancy_status = "not available on invoice"
                        else:
                            method = "pdf_only"
                            discrepancy_status = "Not on census"

                    merged = MergedRecord(
                        census_row=c_row,
                        pdf_employee=None,
                        plan_summary=plan_summary,
                        match_method=method,
                        discrepancies=[d.message for d in res.discrepancies],
                        discrepancy_status=discrepancy_status
                    )
                    legacy_records.append(merged)
                    
                    # Add dependents
                    seen_deps = set()
                    dep_list = (c_rec.dependents if c_rec else []) + (i_rec.dependents if i_rec else [])
                    for dep in dep_list:
                        dep_key = f"{dep.first_name or ''} {dep.last_name or ''}".strip().lower()
                        if dep_key in seen_deps: continue
                        seen_deps.add(dep_key)
                        
                        # Populate dependent plan data if they had any on census
                        d_med_p, d_med_t, d_med_r = None, None, None
                        d_den_p, d_den_t, d_den_r = None, None, None
                        d_vis_p, d_vis_t, d_vis_r = None, None, None
                        
                        def get_dep_b(b_type):
                            if b_type not in dep.benefits: return None, None, None
                            b = dep.benefits[b_type]
                            return b.normalized_plan_name or b.plan_name_raw, b.coverage_tier_raw or b.coverage_tier, b.premium
                            
                        d_med_p, d_med_t, d_med_r = get_dep_b("medical")
                        d_den_p, d_den_t, d_den_r = get_dep_b("dental")
                        d_vis_p, d_vis_t, d_vis_r = get_dep_b("vision")
                        
                        d_row = CensusRow(
                            row_no=0, first_name=dep.first_name, last_name=dep.last_name,
                            gender="", dob="", home_zip="", relationship=dep.relationship,
                            dependent_of_employee_number=c_row.row_no,
                            medical_coverage_tier=d_med_t, medical_plan_enrolled=d_med_p, medical_plan_price=d_med_r,
                            dental_coverage_tier=d_den_t, dental_plan_enrolled=d_den_p, dental_plan_price=d_den_r,
                            vision_coverage_tier=d_vis_t, vision_plan_enrolled=d_vis_p, vision_plan_price=d_vis_r,
                            cobra=""
                        )
                        legacy_records.append(MergedRecord(
                            census_row=d_row,
                            pdf_employee=None,
                            plan_summary=plan_summary,
                            match_method=method,
                            discrepancies=[],
                            discrepancy_status=""
                        ))
                
                fill_template(legacy_records, template_path, output_excel)
            except Exception as e:
                print(f"Warning: Failed to generate filled Excel in New Engine: {e}")
        
        print("--- New Engine Pipeline Complete ---")
        return {
            "total_records": len(reconciliation_results),
            "matches": len([m for m in matches if m.status == "MATCHED"])
        }
