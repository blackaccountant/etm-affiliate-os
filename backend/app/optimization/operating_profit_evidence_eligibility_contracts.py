"""Pure M11A3 evidence-adequacy eligibility contracts."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib, json
from app.optimization.operating_profit_evidence_contracts import OperatingProfitEvidenceRequest

OPERATING_PROFIT_EVIDENCE_ELIGIBILITY_CONTRACT_VERSION="m11a3-evidence-eligibility-v1"
OPERATING_PROFIT_EVIDENCE_ELIGIBILITY_SEMANTICS="deterministic evidence-adequacy assessment only; no financial quality, confidence, ranking, recommendation, or action"
REASONS=("INSUFFICIENT_SETTLED_EARNINGS","INSUFFICIENT_SETTLED_CONVERSIONS","INSUFFICIENT_SETTLEMENT_LINKS","INSUFFICIENT_ATTRIBUTION_CLICKS","STALE_SETTLEMENT_OBSERVATION")
@dataclass(frozen=True)
class OperatingProfitEvidenceEligibilityPolicy:
 policy_version:str; minimum_settled_earning_count:int; minimum_settled_conversion_count:int; minimum_settlement_link_count:int; minimum_attribution_click_count:int|None=None; maximum_settlement_observation_age:timedelta|None=None
 def normalized(self):
  v=self.policy_version.strip() if isinstance(self.policy_version,str) else ""
  values=(self.minimum_settled_earning_count,self.minimum_settled_conversion_count,self.minimum_settlement_link_count,self.minimum_attribution_click_count)
  if not v or any(x is not None and (type(x) is not int or x<0) for x in values) or (self.maximum_settlement_observation_age is not None and (not isinstance(self.maximum_settlement_observation_age,timedelta) or self.maximum_settlement_observation_age<timedelta())): raise ValueError("invalid evidence eligibility policy")
  return OperatingProfitEvidenceEligibilityPolicy(v,*values,self.maximum_settlement_observation_age)
 def fingerprint(self):
  p=self.normalized(); d={"policy_version":p.policy_version,"minimum_settled_earning_count":p.minimum_settled_earning_count,"minimum_settled_conversion_count":p.minimum_settled_conversion_count,"minimum_settlement_link_count":p.minimum_settlement_link_count,"minimum_attribution_click_count":p.minimum_attribution_click_count,"maximum_settlement_observation_age_microseconds":None if p.maximum_settlement_observation_age is None else p.maximum_settlement_observation_age.days*86400000000+p.maximum_settlement_observation_age.seconds*1000000+p.maximum_settlement_observation_age.microseconds}; return hashlib.sha256(json.dumps(d,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
@dataclass(frozen=True)
class OperatingProfitEvidenceEligibilityRequest:
 dimensions:tuple[str,...]=(); currency:str|None=None; policy:OperatingProfitEvidenceEligibilityPolicy|None=None; evaluated_at:datetime|None=None
 def normalized(self):
  r=OperatingProfitEvidenceRequest(self.dimensions,self.currency).normalized()
  if self.policy is None or self.evaluated_at is None or self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset()!=timedelta() : raise ValueError("policy and UTC evaluated_at required")
  return OperatingProfitEvidenceEligibilityRequest(r.dimensions,r.currency,self.policy.normalized(),self.evaluated_at)
@dataclass(frozen=True)
class OperatingProfitEvidenceEligibilityRow:
 currency:str; dimensions:tuple; eligible:bool; reason_codes:tuple[str,...]; evaluated_at:datetime; source_evidence_semantics:str; source_evidence_contract_version:str; policy_version:str; policy_fingerprint:str; assessment_semantics:str=OPERATING_PROFIT_EVIDENCE_ELIGIBILITY_SEMANTICS; assessment_contract_version:str=OPERATING_PROFIT_EVIDENCE_ELIGIBILITY_CONTRACT_VERSION
