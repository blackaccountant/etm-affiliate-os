import re
from app.content_intelligence.evaluation_contracts import ComplianceFlag, ContentEvaluationResult, EvaluationDecision, EVALUATOR_VERSION, POLICY_VERSION
from app.models.content_brief import ContentBrief
from app.models.content_brief_evidence import ContentBriefEvidence
from app.models.discovery import EvidenceObservation
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.repositories.content_evaluation_repository import ContentEvaluationRepository

class ContentEvaluator:
    def __init__(self, db): self.db=db; self.repo=ContentEvaluationRepository(db)
    def evaluate(self, artifact_id, evaluator_version=EVALUATOR_VERSION, policy_version=POLICY_VERSION):
        artifact=self.db.get(GeneratedContentArtifact, artifact_id)
        if not artifact: raise ValueError("generated content artifact not found")
        if artifact.status != "GENERATED": raise ValueError("artifact is not GENERATED")
        existing=self.repo.get_by_identity(artifact.id,evaluator_version,policy_version)
        if existing: return ContentEvaluationResult(existing.id,existing.decision,existing.approved,existing.overall_score)
        brief=self.db.get(ContentBrief,artifact.content_brief_id); links=self.db.query(ContentBriefEvidence).filter_by(content_brief_id=brief.id).all(); allowed={x.evidence_observation_id for x in links}
        flags=[]; rejection=[]; revision=[]; missing=[]; claim_results=[]
        def add(flag, severity, reason):
            if flag not in flags: flags.append(flag)
            (rejection if severity=="REJECT" else revision).append(reason)
        disclosure=(artifact.affiliate_disclosure+" "+artifact.body).lower()
        if "affiliate" not in disclosure or not ("link" in disclosure or "commission" in disclosure): add(ComplianceFlag.MISSING_DISCLOSURE.value,"REVISION","Substantive affiliate disclosure is required")
        if artifact.call_to_action != brief.call_to_action: add(ComplianceFlag.UNSAFE_CTA.value,"REVISION","CTA does not match the brief")
        text=" ".join((artifact.title,artifact.hook,artifact.body,artifact.call_to_action)).lower()
        for pattern,flag,severity in [(r"\bdiscount\b",ComplianceFlag.FABRICATED_DISCOUNT,"REJECT"),(r"\bguaranteed (income|earnings)\b",ComplianceFlag.GUARANTEED_INCOME,"REJECT"),(r"\bguaranteed results?\b",ComplianceFlag.GUARANTEED_RESULTS,"REJECT"),(r"\b(testimonial|customer says)\b",ComplianceFlag.FAKE_TESTIMONIAL,"REJECT"),(r"\b(limited time|act now)\b",ComplianceFlag.MISLEADING_URGENCY,"REVISION"),(r"\b(only \d+ left|scarcity)\b",ComplianceFlag.SCARCITY_CLAIM,"REVISION"),(r"\b(product feature|capability)\b",ComplianceFlag.UNSUPPORTED_CAPABILITY,"REJECT"),(r"\b(price|pricing|\$\d+)\b",ComplianceFlag.UNSUPPORTED_PRICE,"REJECT"),(r"\bfree trial\b",ComplianceFlag.UNSUPPORTED_TRIAL,"REJECT")]:
            if re.search(pattern,text): add(flag.value,severity,flag.value)
        evidence_ids={i for c in artifact.claims for i in c.get("source_evidence_ids",[])}; observed={x.id:x for x in self.db.query(EvidenceObservation).filter(EvidenceObservation.id.in_(evidence_ids)).all()} if evidence_ids else {}
        for claim in artifact.claims:
            ids=tuple(claim.get("source_evidence_ids") or ()); local=[]; severity="INFO"; reason="grounded"
            if not ids: local.append(ComplianceFlag.UNGROUNDED_CLAIM.value); severity="REJECT"; reason="claim has no evidence IDs"; add(local[-1],severity,reason)
            for evidence_id in ids:
                evidence=observed.get(evidence_id)
                if not evidence: local.append(ComplianceFlag.UNKNOWN_EVIDENCE.value); severity="REJECT"; reason="unknown evidence ID"; missing.append(evidence_id); add(local[-1],severity,reason)
                elif evidence_id not in allowed: local.append(ComplianceFlag.CROSS_BRIEF_EVIDENCE.value); severity="REJECT"; reason="evidence is not linked to brief"; add(local[-1],severity,reason)
                elif evidence.candidate_id != brief.discovery_candidate_id: local.append(ComplianceFlag.CROSS_CANDIDATE_EVIDENCE.value); severity="REJECT"; reason="evidence belongs to another candidate"; add(local[-1],severity,reason)
            claim_results.append({"claim_text":claim.get("text", ""),"source_evidence_ids":list(ids),"grounded":not local,"flags":local,"severity":severity,"reason":reason})
        values={x.claim_type:x.observed_value for x in observed.values() if x.id in allowed}
        for value in re.findall(r"(\d+(?:\.\d+)?)\s*%",text):
            if "commission_percent" not in values or float(value)!=float(values["commission_percent"]): add(ComplianceFlag.UNSUPPORTED_ECONOMICS.value,"REJECT","commission percentage conflicts with evidence")
        for value in re.findall(r"(\d+)[- ]day cookie",text):
            if "cookie_days" not in values or int(value)!=int(values["cookie_days"]): add(ComplianceFlag.UNSUPPORTED_ECONOMICS.value,"REJECT","cookie duration conflicts with evidence")
        grounding=0 if rejection else 100; compliance=0 if rejection else max(0,100-25*len(revision)); offer=100 if artifact.call_to_action==brief.call_to_action else 60; intent=100 if artifact.content_type==brief.content_type else 60; clarity=100 if len(artifact.body.strip())>=20 else 60; overall=int(compliance*.4+grounding*.3+offer*.15+offer*.1+clarity*.05)
        decision=EvaluationDecision.REJECTED.value if rejection or overall<60 else EvaluationDecision.APPROVED.value if overall>=85 and not revision else EvaluationDecision.REVISION_REQUIRED.value
        row=self.repo.create(artifact_id=artifact.id,content_brief_id=brief.id,generation_run_id=artifact.generation_run_id,factual_grounding_score=grounding,offer_alignment_score=offer,intent_alignment_score=intent,clarity_score=clarity,cta_score=offer,compliance_score=compliance,overall_score=overall,decision=decision,approved=decision==EvaluationDecision.APPROVED.value,evaluator_version=evaluator_version,policy_version=policy_version,claim_results=claim_results,compliance_flags=flags,unsupported_claims=[x for x in flags if x not in {ComplianceFlag.MISSING_DISCLOSURE.value,ComplianceFlag.UNSAFE_CTA.value,ComplianceFlag.MISLEADING_URGENCY.value,ComplianceFlag.SCARCITY_CLAIM.value}],missing_evidence_ids=sorted(set(missing)),revision_reasons=revision,rejection_reasons=rejection)
        self.db.commit(); self.db.refresh(row); return ContentEvaluationResult(row.id,row.decision,row.approved,row.overall_score)
