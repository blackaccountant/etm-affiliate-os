"""M11A4 in-memory candidate membership over frozen M11A3 assessments."""

from app.optimization.eligible_operating_profit_candidate_set_contracts import (
    EligibleOperatingProfitCandidateRow,
    EligibleOperatingProfitCandidateSetRequest,
    canonical_bucket_identity,
)
from app.optimization.operating_profit_evidence_eligibility_contracts import (
    OperatingProfitEvidenceEligibilityRequest,
)
from app.services.operating_profit_evidence_eligibility_service import (
    OperatingProfitEvidenceEligibilityService,
)


class EligibleOperatingProfitCandidateSetService:
    def __init__(self, db):
        self._eligibility = OperatingProfitEvidenceEligibilityService(db)

    def project(self, request):
        normalized = request.normalized()
        assessments = self._eligibility.project(OperatingProfitEvidenceEligibilityRequest(
            normalized.dimensions, normalized.currency, normalized.eligibility_policy, normalized.evaluated_at,
        ))
        candidates, identities = [], set()
        fingerprint = normalized.eligibility_policy.fingerprint()
        for row in assessments:
            if (
                row.currency != normalized.currency
                or row.evaluated_at != normalized.evaluated_at
                or row.policy_version != normalized.eligibility_policy.policy_version
                or row.policy_fingerprint != fingerprint
                or tuple(name for name, _ in row.dimensions) != normalized.dimensions
                or row.eligible != (row.reason_codes == ())
            ):
                raise ValueError("M11A3 assessment contradicts the M11A4 request")
            identity = canonical_bucket_identity(row.currency, row.dimensions)
            if identity in identities:
                raise ValueError("duplicate M11A3 bucket identity")
            identities.add(identity)
            if row.eligible:
                candidates.append(EligibleOperatingProfitCandidateRow(
                    row.currency, row.dimensions, row.evaluated_at, row.policy_version,
                    row.policy_fingerprint, row.source_evidence_semantics,
                    row.source_evidence_contract_version, row.assessment_semantics,
                    row.assessment_contract_version,
                ))
        return tuple(sorted(candidates, key=lambda row: canonical_bucket_identity(row.currency, row.dimensions)))
