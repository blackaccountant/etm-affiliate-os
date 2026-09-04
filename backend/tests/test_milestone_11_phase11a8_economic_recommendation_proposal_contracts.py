from dataclasses import fields, FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal
import pytest
from app.optimization.economic_candidate_comparison_contracts import OperatingProfitComparisonPolicy
from app.optimization.eligible_economic_candidate_contracts import ELIGIBLE_ECONOMIC_CANDIDATE_CONTRACT_VERSION, ELIGIBLE_ECONOMIC_CANDIDATE_SEMANTICS
from app.optimization.eligible_operating_profit_candidate_set_contracts import EligibleOperatingProfitCandidateSetRequest
from app.optimization.operating_profit_evidence_eligibility_contracts import OperatingProfitEvidenceEligibilityPolicy
from app.optimization.ordered_economic_candidate_preference_contracts import *
from app.optimization.economic_recommendation_proposal_contracts import *
from app.services.economic_recommendation_proposal_service import EconomicRecommendationProposalService

WHEN=datetime(2026,1,1,tzinfo=timezone.utc); EL=OperatingProfitEvidenceEligibilityPolicy("e",1,1,1); CP=OperatingProfitComparisonPolicy("c")
def req(): return EconomicRecommendationProposalRequest(OrderedEconomicCandidatePreferenceRequest(EligibleOperatingProfitCandidateSetRequest(("affiliate_program",),"USD",EL,WHEN),CP),EconomicRecommendationPolicy("r"))
def row(i,t=1,p=Decimal("1"),**k):
    d=dict(currency="USD",dimensions=(("affiliate_program",i),),operating_profit=p,preference_tier=t,evaluated_at=WHEN,eligibility_policy_version="e",eligibility_policy_fingerprint=EL.fingerprint(),comparison_policy_version="c",source_economic_candidate_semantics=ELIGIBLE_ECONOMIC_CANDIDATE_SEMANTICS,source_economic_candidate_contract_version=ELIGIBLE_ECONOMIC_CANDIDATE_CONTRACT_VERSION,source_pairwise_comparison_semantics="read-only deterministic pairwise comparison of two distinct frozen M11A5B eligible economic candidates from one projection snapshot; higher exact operating_profit is preferred; exact Decimal equality is a tie; native currency/no FX; no monetary arithmetic or derived metric; no ranking, no recommendation, and no action",source_pairwise_comparison_contract_version="m11a6-economic-candidate-pairwise-comparison-v1",ordered_preference_semantics=ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_SEMANTICS,ordered_preference_contract_version=ORDERED_ECONOMIC_CANDIDATE_PREFERENCE_CONTRACT_VERSION); d.update(k); return OrderedEconomicCandidatePreferenceRow(**d)
class Source:
 def __init__(self,rows): self.rows,self.calls=rows,0
 def project(self,r): self.calls+=1; return self.rows
def service(*rows):
 s=Source(tuple(rows)); return EconomicRecommendationProposalService(None,ordered_preference_service=s),s
def test_contracts_and_manifests():
 assert ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION=="m11a8-economic-recommendation-proposal-v1"
 assert tuple(EconomicRecommendationPolicy.__dataclass_fields__)==("policy_version",)
 assert tuple(EconomicRecommendationProposalRequest.__dataclass_fields__)==("preference_request","recommendation_policy")
 assert len(fields(EconomicRecommendationProposalRow))==13
 with pytest.raises(FrozenInstanceError): EconomicRecommendationPolicy("x").policy_version="y"
@pytest.mark.parametrize("p",[EconomicRecommendationPolicy(""),EconomicRecommendationPolicy(" "),EconomicRecommendationPolicy(1)])
def test_invalid_policy(p):
 with pytest.raises(ValueError): EconomicRecommendationProposalRequest(req().preference_request,p).normalized()
def test_empty_singleton_ties_lower_tiers_and_decimal_identity():
 x,s=service(); assert x.project(req())==() and s.calls==1
 a,b,c=row(1,1,Decimal("9")),row(2,1,Decimal("9")),row(3,2,Decimal("1")); x,s=service(a,b,c); out=x.project(req()); assert [r.dimensions for r in out]==[a.dimensions,b.dimensions] and out[0].operating_profit is a.operating_profit and s.calls==1
def test_full_tuple_validation_and_structure_fail_closed():
 for rows in ((row(1,2),),(row(1,1),row(1,2)),(row(1,1),row(2,3)),(row(1,1,Decimal("1"),currency="EUR"),)):
  x,_=service(*rows)
  with pytest.raises(ValueError): x.project(req())
