from datetime import datetime,timezone
from decimal import Decimal
import pytest
from app.optimization.economic_recommendation_approval_contracts import *
from app.optimization.economic_recommendation_proposal_contracts import *
from app.services.economic_recommendation_approval_service import EconomicRecommendationApprovalService
from app.optimization.ordered_economic_candidate_preference_contracts import OrderedEconomicCandidatePreferenceRequest
from app.optimization.eligible_operating_profit_candidate_set_contracts import EligibleOperatingProfitCandidateSetRequest
from app.optimization.operating_profit_evidence_eligibility_contracts import OperatingProfitEvidenceEligibilityPolicy
from app.optimization.economic_candidate_comparison_contracts import OperatingProfitComparisonPolicy
W=datetime(2026,1,1,tzinfo=timezone.utc)
def request(state=EconomicRecommendationApprovalState.APPROVED,selected=((("affiliate_program",1),),)):
 p=EconomicRecommendationProposalRequest(OrderedEconomicCandidatePreferenceRequest(EligibleOperatingProfitCandidateSetRequest(("affiliate_program",),"USD",OperatingProfitEvidenceEligibilityPolicy("e",1,1,1),W),OperatingProfitComparisonPolicy("c")),EconomicRecommendationPolicy("r")); return EconomicRecommendationApprovalRequest(p,EconomicRecommendationApprovalDecision(state,selected,"actor","ref",W),EconomicRecommendationApprovalPolicy("a"))
def row(i): return EconomicRecommendationProposalRow("USD",(("affiliate_program",i),),Decimal("1"),1,W,"e",request().proposal_request.preference_request.candidate_request.eligibility_policy.fingerprint(),"c","r",ECONOMIC_RECOMMENDATION_PROPOSAL_SEMANTICS,ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION)
class Source:
 def __init__(self,*rows):self.rows=rows;self.calls=0
 def project(self,r):self.calls+=1;return tuple(self.rows)
def test_manifest_and_one_external_selection():
 s=Source(row(1),row(2)); out=EconomicRecommendationApprovalService(None,recommendation_proposal_service=s).project(request(selected=((("affiliate_program",2),),))); assert s.calls==1 and out.approved_rows==(s.rows[1],) and out.decision_state is EconomicRecommendationApprovalState.APPROVED
def test_rejected_empty_and_foreign_fails():
 s=Source(); assert EconomicRecommendationApprovalService(None,recommendation_proposal_service=s).project(request(EconomicRecommendationApprovalState.REJECTED,())).approved_rows==()
 with pytest.raises(ValueError): EconomicRecommendationApprovalService(None,recommendation_proposal_service=Source(row(1))).project(request(selected=((("affiliate_program",2),),)))
