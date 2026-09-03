"""Associate frozen eligible buckets with captured M11A1 operating profit."""

from app.optimization.eligible_economic_candidate_contracts import EligibleEconomicCandidateRow
from app.optimization.eligible_operating_profit_candidate_set_contracts import (
    EligibleOperatingProfitCandidateSetRequest,
    canonical_bucket_identity,
)
from app.services.eligible_operating_profit_candidate_set_service import (
    EligibleOperatingProfitCandidateSetService,
)
from app.services.operating_profit_evidence_eligibility_service import (
    OperatingProfitEvidenceEligibilityService,
)
from app.services.operating_profit_evidence_service import OperatingProfitEvidenceService
from app.services.operating_profit_signal_service import OperatingProfitSignalService


class _CapturingOperatingProfitSignalService:
    """Request-cycle capture around one transparent M11A1 delegate."""

    def __init__(self, delegate):
        self._delegate = delegate
        self._active = False
        self._calls = 0
        self._rows = None

    def begin_capture(self):
        if self._active:
            raise RuntimeError("M11A5B capture cycle is already active")
        self._active, self._calls, self._rows = True, 0, None

    def project(self, request):
        if not self._active:
            raise RuntimeError("M11A5B signal projection requires an active capture cycle")
        self._calls += 1
        if self._calls != 1:
            raise ValueError("M11A5B requires exactly one M11A1 traversal per projection")
        self._rows = self._delegate.project(request)
        return self._rows

    def finish_capture(self):
        if not self._active or self._calls != 1 or self._rows is None:
            raise ValueError("M11A5B capture is absent or incomplete")
        rows = self._rows
        self._active, self._calls, self._rows = False, 0, None
        return rows

    def abort_capture(self):
        self._active, self._calls, self._rows = False, 0, None


class EligibleEconomicCandidateService:
    """One-pass, in-memory association over one caller-owned upstream graph."""

    def __init__(self, db):
        self._capture = _CapturingOperatingProfitSignalService(OperatingProfitSignalService(db))
        evidence = OperatingProfitEvidenceService(db, signal_service=self._capture)
        eligibility = OperatingProfitEvidenceEligibilityService(db, evidence_service=evidence)
        self._candidates = EligibleOperatingProfitCandidateSetService(
            db, eligibility_service=eligibility,
        )

    @staticmethod
    def _signal_index(signals, normalized):
        index = {}
        for signal in signals:
            if (
                signal.currency != normalized.currency
                or tuple(name for name, _ in signal.dimensions) != normalized.dimensions
            ):
                raise ValueError("M11A1 signal contradicts the M11A5B request")
            identity = canonical_bucket_identity(signal.currency, signal.dimensions)
            if identity in index:
                raise ValueError("duplicate captured M11A1 bucket identity")
            index[identity] = signal
        return index

    @staticmethod
    def _validate_candidate(candidate, normalized, fingerprint):
        if (
            candidate.currency != normalized.currency
            or tuple(name for name, _ in candidate.dimensions) != normalized.dimensions
            or candidate.evaluated_at != normalized.evaluated_at
            or candidate.policy_version != normalized.eligibility_policy.policy_version
            or candidate.policy_fingerprint != fingerprint
        ):
            raise ValueError("M11A4 candidate contradicts the M11A5B request")

    @classmethod
    def _associate(cls, candidates, signals, normalized):
        index = cls._signal_index(signals, normalized)
        fingerprint = normalized.eligibility_policy.fingerprint()
        rows = []
        for candidate in candidates:
            cls._validate_candidate(candidate, normalized, fingerprint)
            signal = index.get(canonical_bucket_identity(candidate.currency, candidate.dimensions))
            if signal is None:
                raise ValueError("M11A4 candidate has no captured M11A1 signal")
            if signal.currency != candidate.currency or signal.dimensions != candidate.dimensions:
                raise ValueError("M11A1 signal does not exactly match its M11A4 candidate")
            rows.append(EligibleEconomicCandidateRow(
                currency=candidate.currency,
                dimensions=candidate.dimensions,
                operating_profit=signal.operating_profit,
                evaluated_at=candidate.evaluated_at,
                policy_version=candidate.policy_version,
                policy_fingerprint=candidate.policy_fingerprint,
                source_operating_profit_semantics=signal.source_semantics,
                source_signal_semantics=signal.signal_semantics,
                source_signal_contract_version=signal.signal_contract_version,
                source_evidence_semantics=candidate.source_evidence_semantics,
                source_evidence_contract_version=candidate.source_evidence_contract_version,
                source_eligibility_semantics=candidate.source_eligibility_semantics,
                source_eligibility_contract_version=candidate.source_eligibility_contract_version,
                source_candidate_set_semantics=candidate.candidate_set_semantics,
                source_candidate_set_contract_version=candidate.candidate_set_contract_version,
            ))
        return tuple(rows)

    def project(self, request: EligibleOperatingProfitCandidateSetRequest):
        normalized = request.normalized()
        self._capture.begin_capture()
        try:
            candidates = self._candidates.project(normalized)
            signals = self._capture.finish_capture()
        except Exception:
            self._capture.abort_capture()
            raise
        return self._associate(candidates, signals, normalized)
