"""M9C2B cold-delivery persistence contracts; no providers, webhooks, or workflow execution."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.models.cold_delivery import ColdDeliveryEvent, ColdDeliveryOperation, ColdDeliveryOperationState, ColdMessageContent, ColdProviderDispatch, ColdProviderFeedbackReceipt
from app.models.cold_prospecting import ColdProspectingAuthorization
from app.outreach.cold_delivery_contracts import ColdDeliveryState, ColdMessageContentContract, ColdT3DecisionContract, CreateColdDeliveryOperationRequest, pii_bounded_payload, validate_cold_delivery_transition
from app.outreach.contracts import OutreachError, PreparedOutreachMessage, sha256_fingerprint
from app.repositories.cold_delivery_event_repository import ColdDeliveryEventRepository


NOW = datetime(2031, 1, 1, tzinfo=timezone.utc)
FP = "a" * 64


def _authorization(db, suffix="one"):
    value = ColdProspectingAuthorization(id=(suffix * 36)[:36], lead_id=("l" + suffix * 36)[:36], contact_point_id=("c" + suffix * 36)[:36], organization_evidence_id=None, policy_selection_id=None, channel="EMAIL", purpose_key="cold_b2b:platform", purpose_family="platform", requested_action="INITIAL", source_namespace="cold-test", source_event_key=sha256_fingerprint({"auth": suffix}), request_fingerprint="b" * 64, authorization_state="ELIGIBLE", reason_codes=["ELIGIBLE"], eligibility_policy_version="v1", frequency_policy_version="v1", policy_profile_key="profile", decision_fingerprint="c" * 64, evidence={}, evaluated_at=NOW)
    db.add(value); db.flush(); return value


def _operation(db, suffix="one", *, action="INITIAL", message_fp=FP):
    auth = _authorization(db, suffix)
    value = ColdDeliveryOperation(cold_authorization_id=auth.id, lead_id=auth.lead_id, contact_point_id=auth.contact_point_id, action=action, purpose_key="cold_b2b:platform", purpose_family="platform", source_namespace="cold-delivery", source_event_key=sha256_fingerprint({"operation": suffix}), message_content_fingerprint=message_fp, operation_schema_version="cold-delivery-operation-v1", created_at=NOW)
    db.add(value); db.flush(); db.add(ColdDeliveryOperationState(operation_id=value.id, current_state="CREATED", revision=1, next_event_sequence=1, updated_at=NOW)); db.flush(); return value, auth


def test_operation_identity_is_immutable_and_actions_are_commercial_identity(db_session):
    request = CreateColdDeliveryOperationRequest("a" * 36, "b" * 36, "c" * 36, "INITIAL", "cold_b2b:platform", "cold-source", FP, FP, NOW)
    follow = CreateColdDeliveryOperationRequest("a" * 36, "b" * 36, "c" * 36, "FOLLOW_UP", "cold_b2b:platform", "cold-source", FP, FP, NOW)
    assert request.request_fingerprint != follow.request_fingerprint and request.action == "INITIAL" and follow.action == "FOLLOW_UP"
    operation, _ = _operation(db_session)
    with pytest.raises(IntegrityError):
        db_session.add(ColdDeliveryOperation(cold_authorization_id=operation.cold_authorization_id, lead_id=operation.lead_id, contact_point_id=operation.contact_point_id, action="INITIAL", purpose_key="cold_b2b:platform", purpose_family="platform", source_namespace="other", source_event_key=sha256_fingerprint({"second": 1}), message_content_fingerprint=FP, operation_schema_version="v1", created_at=NOW)); db_session.flush()


def test_technical_retry_is_state_not_a_second_commercial_operation(db_session):
    operation, _ = _operation(db_session)
    state = db_session.get(ColdDeliveryOperationState, operation.id); state.current_state = "TECHNICAL_RETRY_DUE"; state.next_technical_retry_at = NOW; state.revision += 1; db_session.flush()
    assert db_session.query(ColdDeliveryOperation).filter_by(cold_authorization_id=operation.cold_authorization_id).count() == 1


def test_message_artifact_is_separate_and_fingerprint_bound_to_operation(db_session):
    operation, _ = _operation(db_session)
    message = PreparedOutreachMessage("A bounded body", subject="Subject")
    contract = ColdMessageContentContract(message)
    assert contract.content_fingerprint == message.content_fingerprint
    matching, _ = _operation(db_session, "two", message_fp=message.content_fingerprint)
    db_session.add(ColdMessageContent(operation_id=matching.id, content_fingerprint=message.content_fingerprint, subject=message.subject, body=message.body, content_format=message.content_format, content_schema_version="cold-message-content-v1", created_at=NOW)); db_session.flush()
    pairs = {(tuple(item["constrained_columns"]), tuple(item["referred_columns"])) for item in inspect(db_session.bind).get_foreign_keys("cold_message_contents")}
    assert (("operation_id", "content_fingerprint"), ("id", "message_content_fingerprint")) in pairs


@pytest.mark.parametrize("message", [
    PreparedOutreachMessage("Email person@example.com"),
    PreparedOutreachMessage("Call +1 415 555 1212"),
    PreparedOutreachMessage("Hello {{recipient_name}}"),
    PreparedOutreachMessage("token", channel_metadata={"campaign": "x"}),
    PreparedOutreachMessage("api_key=private"),
])
def test_cold_message_content_rejects_routing_personalization_and_secrets(message):
    with pytest.raises(OutreachError, match="cold message content"):
        ColdMessageContentContract(message)


def test_event_sequence_uses_locked_control_row_and_source_idempotency(db_session):
    operation, _ = _operation(db_session); repo = ColdDeliveryEventRepository(db_session)
    first, reused = repo.append_or_reuse(operation_id=operation.id, event_type="CREATED", occurred_at=NOW, source_namespace="cold-event", source_event_key=FP, event_fingerprint="b" * 64, safe_payload={"reason_codes": ["CREATED"]})
    replay, again = repo.append_or_reuse(operation_id=operation.id, event_type="CREATED", occurred_at=NOW, source_namespace="cold-event", source_event_key=FP, event_fingerprint="b" * 64, safe_payload={"reason_codes": ["CREATED"]})
    second, _ = repo.append_or_reuse(operation_id=operation.id, event_type="READY", occurred_at=NOW, source_namespace="cold-event", source_event_key="c" * 64, event_fingerprint="d" * 64, safe_payload={"reason_codes": ["READY"]})
    assert (first.sequence_number, replay.id, reused, again, second.sequence_number) == (1, first.id, False, True, 2)
    assert db_session.get(ColdDeliveryOperationState, operation.id).next_event_sequence == 3


def test_persistence_boundary_has_no_raw_recipient_or_message_outside_content_artifact():
    for model in (ColdDeliveryOperation, ColdDeliveryEvent, ColdProviderDispatch, ColdT3DecisionContract):
        columns = set(getattr(model, "__table__", type("x", (), {"columns": {}})).columns.keys())
        assert not {"recipient", "recipient_email", "normalized_value", "body", "secret", "api_key"}.intersection(columns)
    with pytest.raises(OutreachError): pii_bounded_payload({"recipient_email": "person@example.com"})
    with pytest.raises(OutreachError): pii_bounded_payload({"reason": "person@example.com"})


def test_state_machine_accepts_only_approved_transitions():
    assert validate_cold_delivery_transition("CREATED", "READY") == "READY"
    assert validate_cold_delivery_transition("TECHNICAL_RETRY_DUE", "DISPATCH_PLANNED") == "DISPATCH_PLANNED"
    for before, after in (("CREATED", "ACCEPTED"), ("ACCEPTED", "READY"), ("T3_BLOCKED", "READY")):
        with pytest.raises(OutreachError, match="cannot transition"): validate_cold_delivery_transition(before, after)
    assert ColdDeliveryState.RECONCILIATION_REQUIRED.value == "RECONCILIATION_REQUIRED"


def test_t3_contract_is_a_revalidation_record_not_a_new_authorization():
    decision = ColdT3DecisionContract("a" * 36, "b" * 36, FP, NOW, "b" * 64, "c" * 64, ("d" * 36,), "e" * 64, "ALLOWED", ("CONTACTABLE",))
    assert decision.decision == "ALLOWED" and decision.crm_evidence_ids == ("d" * 36,)


def test_one_state_dispatch_provider_identity_and_feedback_dedupe_constraints(db_session):
    operation, _ = _operation(db_session)
    with pytest.raises(IntegrityError):
        db_session.add(ColdDeliveryOperationState(operation_id=operation.id, current_state="CREATED", revision=1, next_event_sequence=1, updated_at=NOW)); db_session.flush()
    db_session.rollback(); operation, _ = _operation(db_session, "after-state")
    dispatch = ColdProviderDispatch(operation_id=operation.id, provider_key="provider", provider_contract_version="v1", provider_operation_key="opaque-key", payload_fingerprint=FP, sender_fingerprint="b" * 64, recipient_fingerprint="c" * 64, dispatch_status="PLANNED", planned_at=NOW)
    db_session.add(dispatch); db_session.flush()
    db_session.add(ColdProviderFeedbackReceipt(provider_dispatch_id=dispatch.id, provider_key="provider", provider_event_key="event-1", event_fingerprint="d" * 64, received_at=NOW, interpretation_version="v1", interpretation_metadata={"event_type": "ACCEPTED"})); db_session.flush()
    with pytest.raises(IntegrityError):
        db_session.add(ColdProviderFeedbackReceipt(provider_dispatch_id=dispatch.id, provider_key="provider", provider_event_key="event-1", event_fingerprint="e" * 64, received_at=NOW, interpretation_version="v1", interpretation_metadata={})); db_session.flush()
