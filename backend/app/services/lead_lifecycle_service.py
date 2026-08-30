"""Serialized, caller-owned M8C Lead lifecycle application service."""

from app.crm.contracts import CRMError, required_text
from app.crm.lifecycle_contracts import LifecycleTransitionRequest, LifecycleTransitionResult
from app.crm.lifecycle_transition_policy import validate_lifecycle_transition
from app.models.crm_relationships import LeadLifecycleEvent
from app.repositories.lead_lifecycle_repository import LeadLifecycleRepository
from app.repositories.lead_qualification_repository import LeadQualificationRepository


class LeadLifecycleService:
    def __init__(self, db):
        self.db = db
        self.lifecycle = LeadLifecycleRepository(db)
        self.qualifications = LeadQualificationRepository(db)

    def effective_state(self, lead_id: str) -> str | None:
        events = self.lifecycle.list_ordered(required_text(lead_id, "lead_id", 36))
        return events[-1].to_state if events else None

    def transition(
        self,
        lead_id: str,
        request: LifecycleTransitionRequest,
    ) -> LifecycleTransitionResult:
        lead_id = required_text(lead_id, "lead_id", 36)
        if not isinstance(request, LifecycleTransitionRequest):
            raise CRMError("INVALID_CONTRACT", "lifecycle transition request must be typed")
        lead = self.lifecycle.lock_lead(lead_id)
        if lead is None:
            raise CRMError("LEAD_NOT_FOUND", "Lead does not exist")

        fingerprint = request.fingerprint_for(lead.id)
        existing = self.lifecycle.by_source(request.source_namespace, request.source_event_key)
        if existing is not None:
            result = self.lifecycle.same_event_or_conflict(existing, fingerprint)
            return self._result(result)

        events = self.lifecycle.list_ordered(lead.id)
        latest = events[-1] if events else None
        current_state = latest.to_state if latest else None
        if latest is not None and request.occurred_at < latest.occurred_at:
            raise CRMError("BACKDATED_LIFECYCLE_EVENT", "lifecycle event cannot precede latest occurred_at")

        # Any historical immutable linked QUALIFIED/HIGH_INTENT assessment is
        # sufficient for the v1 ENRICHED -> QUALIFIED gate.
        has_qualifying = (
            self.qualifications.has_qualifying_assessment(lead.id)
            if request.to_state == "QUALIFIED"
            else False
        )
        decision = validate_lifecycle_transition(
            current_state,
            request.to_state,
            has_qualifying_assessment=has_qualifying,
        )
        event = LeadLifecycleEvent(
            lead_id=lead.id,
            sequence_number=1 if latest is None else latest.sequence_number + 1,
            from_state=decision.from_state,
            to_state=decision.to_state,
            occurred_at=request.occurred_at,
            source_namespace=request.source_namespace,
            source_event_key=request.source_event_key,
            event_fingerprint=fingerprint,
        )
        return self._result(self.lifecycle.append_or_reuse(event))

    @staticmethod
    def _result(value) -> LifecycleTransitionResult:
        return LifecycleTransitionResult(
            event_id=value.record.id,
            reused=value.reused,
            sequence_number=value.record.sequence_number,
            effective_state=value.record.to_state,
        )
