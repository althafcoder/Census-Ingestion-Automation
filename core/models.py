from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

@dataclass
class SourceReference:
    source_file: str
    extraction_method: str
    page: Optional[int] = None
    sheet: Optional[str] = None
    row: Optional[int] = None
    column: Optional[str] = None

@dataclass
class BenefitEnrollment:
    benefit_type: str
    plan_name_raw: Optional[str] = None
    normalized_plan_name: Optional[str] = None
    coverage_tier_raw: Optional[str] = None
    coverage_tier: Optional[str] = None
    premium: Optional[float] = None
    enrollment_status: Optional[str] = None
    effective_date: Optional[str] = None
    termination_date: Optional[str] = None
    source_refs: Dict[str, SourceReference] = field(default_factory=dict)

@dataclass
class SubscriberDependent:
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    normalized_name: Optional[str] = None
    dob: Optional[str] = None
    relationship: Optional[str] = None
    benefits: Dict[str, BenefitEnrollment] = field(default_factory=dict)
    source_refs: Dict[str, SourceReference] = field(default_factory=dict)

@dataclass
class CensusRecord:
    employee_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    normalized_name: Optional[str] = None
    dob: Optional[str] = None
    zip_code: Optional[str] = None
    relationship: str = "Employee"
    benefits: Dict[str, BenefitEnrollment] = field(default_factory=dict)
    dependents: List[SubscriberDependent] = field(default_factory=list)
    source_refs: Dict[str, SourceReference] = field(default_factory=dict)

@dataclass
class InvoiceRecord:
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    normalized_name: Optional[str] = None
    employee_id: Optional[str] = None
    dob: Optional[str] = None
    benefits: Dict[str, BenefitEnrollment] = field(default_factory=dict)
    dependents: List[SubscriberDependent] = field(default_factory=list)
    source_refs: Dict[str, SourceReference] = field(default_factory=dict)

@dataclass
class IdentityEvidence:
    result: str
    score: float
    details: Optional[str] = None

@dataclass
class IdentityMatch:
    status: str
    method: str
    confidence: float
    evidence: Dict[str, IdentityEvidence] = field(default_factory=dict)
    census_record: Optional[CensusRecord] = None
    invoice_record: Optional[InvoiceRecord] = None

@dataclass
class Discrepancy:
    rule_id: str
    status: str
    severity: str
    message: str
    benefit_type: Optional[str] = None
    census_value: Any = None
    invoice_value: Any = None

@dataclass
class ReconciliationResult:
    identity_match: IdentityMatch
    discrepancies: List[Discrepancy] = field(default_factory=list)

@dataclass
class AuditRun:
    run_id: str
    client: str
    engine_version: str
    config_version: str
    plan_mapping_version: str
    coverage_mapping_version: str
    matching_threshold_version: str
    timestamp: Optional[str] = None
