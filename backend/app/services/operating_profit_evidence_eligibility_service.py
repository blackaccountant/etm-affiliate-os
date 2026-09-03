from datetime import timedelta
from app.optimization.operating_profit_evidence_eligibility_contracts import *
from app.optimization.operating_profit_evidence_contracts import OperatingProfitEvidenceRequest
from app.services.operating_profit_evidence_service import OperatingProfitEvidenceService
class OperatingProfitEvidenceEligibilityService:
 def __init__(self,db,*,evidence_service=None): self._evidence=OperatingProfitEvidenceService(db) if evidence_service is None else evidence_service
 def project(self,request):
  r=request.normalized(); rows=self._evidence.project(OperatingProfitEvidenceRequest(r.dimensions,r.currency)); out=[]; p=r.policy
  for e in rows:
   if any(x.tzinfo is None or x.utcoffset()!=timedelta() for x in (e.first_settlement_observed_at,e.latest_settlement_observed_at)) or e.first_settlement_observed_at>e.latest_settlement_observed_at or e.latest_settlement_observed_at>r.evaluated_at: raise ValueError("malformed evidence timestamps")
   reasons=[]
   for code,value,minimum in ((REASONS[0],e.settled_earning_count,p.minimum_settled_earning_count),(REASONS[1],e.settled_conversion_count,p.minimum_settled_conversion_count),(REASONS[2],e.settlement_link_count,p.minimum_settlement_link_count),(REASONS[3],e.attribution_click_count,p.minimum_attribution_click_count)):
    if minimum is not None and value<minimum: reasons.append(code)
   if p.maximum_settlement_observation_age is not None and r.evaluated_at-e.latest_settlement_observed_at>p.maximum_settlement_observation_age: reasons.append(REASONS[4])
   out.append(OperatingProfitEvidenceEligibilityRow(e.currency,e.dimensions,not reasons,tuple(reasons),r.evaluated_at,e.evidence_semantics,e.evidence_contract_version,p.policy_version,p.fingerprint()))
  return tuple(out)
