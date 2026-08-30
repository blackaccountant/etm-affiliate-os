"""Pure contracts and deterministic rules for M6.2B.1."""

import socket
from uuid import uuid4

import pytest

from app.audience.deterministic_signal_extractor import (
    ExtractionEvidenceFact,
    ExtractionObservationFact,
    extract,
)
from app.audience.normalization import signal_extraction_input_fingerprint
from app.audience.signal_extraction_mission_contracts import (
    AUDIENCE_SIGNAL_EXTRACTION_OPERATION_KIND,
    AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1,
    AudienceSignalExtractionContractError,
    AudienceSignalExtractionSnapshot,
    AudienceSignalExtractionWorkflowPayload,
    audience_signal_extraction_mission_idempotency_key,
)
from app.services.audience_signal_service import SignalCandidate


def ids():
    return str(uuid4()), str(uuid4()), str(uuid4())


@pytest.fixture(autouse=True)
def no_external_access(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("deterministic extraction must not use the network")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


def fingerprint(observation_id, evidence_ids, *, observation_key="a" * 64, evidence_fingerprints=None):
    if evidence_fingerprints is None:
        fingerprint_by_id = {
            evidence_id: chr(98 + index) * 64
            for index, evidence_id in enumerate(sorted(evidence_ids))
        }
        fingerprints = [fingerprint_by_id[evidence_id] for evidence_id in evidence_ids]
    else:
        fingerprints = evidence_fingerprints
    return signal_extraction_input_fingerprint(
        observation_id=observation_id,
        observation_key=observation_key,
        evidence=list(zip(evidence_ids, fingerprints, strict=True)),
    )


def facts(event, *, subject_type=None, evidence_order=None):
    observation_id, first, second = ids()
    evidence_ids = evidence_order or [first, second]
    return (
        ExtractionObservationFact({"event": event}, subject_type=subject_type),
        [ExtractionEvidenceFact(item, {"event": event}) for item in evidence_ids],
        observation_id,
    )


def test_snapshot_metadata_canonicalizes_order_and_round_trips():
    observation_id, first, second = ids()
    snapshot = AudienceSignalExtractionSnapshot(observation_id, AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1, fingerprint(observation_id, [first, second]), (second, first))
    assert snapshot.operation_kind == AUDIENCE_SIGNAL_EXTRACTION_OPERATION_KIND
    assert snapshot.evidence_ids == tuple(sorted((first, second)))
    assert AudienceSignalExtractionSnapshot.from_metadata(snapshot.to_metadata()) == snapshot


@pytest.mark.parametrize("metadata", [{}, {"operation_kind": AUDIENCE_SIGNAL_EXTRACTION_OPERATION_KIND, "observation_id": "bad", "ruleset_version": "v1", "input_fingerprint": "a" * 64, "evidence_ids": []}])
def test_malformed_snapshot_metadata_is_rejected(metadata):
    with pytest.raises(AudienceSignalExtractionContractError):
        AudienceSignalExtractionSnapshot.from_metadata(metadata)


def test_input_fingerprint_is_stable_order_independent_and_input_sensitive():
    observation_id, first, second = ids()
    base = fingerprint(observation_id, [first, second])
    assert base == fingerprint(observation_id, [second, first])
    assert base != fingerprint(observation_id, [first])
    assert base != fingerprint(observation_id, [first, second], observation_key="b" * 64)
    assert base != fingerprint(observation_id, [first, second], evidence_fingerprints=["d" * 64, "c" * 64])
    assert base != fingerprint(str(uuid4()), [first, second])
    with pytest.raises(ValueError, match="evidence entries"):
        signal_extraction_input_fingerprint(observation_id=observation_id, observation_key="a" * 64, evidence=[])


def test_mission_key_and_id_only_payload_are_deterministic():
    observation_id, first, _ = ids()
    value = fingerprint(observation_id, [first])
    key = audience_signal_extraction_mission_idempotency_key(observation_id, AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1, value)
    assert key == audience_signal_extraction_mission_idempotency_key(observation_id, AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1, value)
    assert key != audience_signal_extraction_mission_idempotency_key(observation_id, "audience-signal-extraction-v2", value)
    assert key != audience_signal_extraction_mission_idempotency_key(str(uuid4()), AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1, value)
    assert key != audience_signal_extraction_mission_idempotency_key(observation_id, AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1, "d" * 64)
    payload = AudienceSignalExtractionWorkflowPayload(observation_id)
    assert payload.to_dict() == {"audience_research_run_id": observation_id}
    assert AudienceSignalExtractionWorkflowPayload.from_payload(payload.to_dict()) == payload
    with pytest.raises(AudienceSignalExtractionContractError):
        AudienceSignalExtractionWorkflowPayload.from_payload({**payload.to_dict(), "ruleset_version": "leak"})


@pytest.mark.parametrize("event,signal_type,stage", [("pricing", "INTENT", "PRICING"), ("compare", "INTENT", "COMPARE"), ("purchase_request", "INTENT", "PURCHASE_REQUEST"), ("engagement", "ENGAGEMENT", None)])
def test_structured_events_emit_compatible_candidates(event, signal_type, stage):
    observation, evidence, _ = facts(event)
    candidates = extract(observation, evidence, ruleset_version=AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert isinstance(candidate, SignalCandidate)
    assert (candidate.signal_type, candidate.intent_stage, candidate.strength, candidate.confidence) == (signal_type, stage, 50, 60)
    assert candidate.evidence_ids == sorted(item.evidence_id for item in evidence)


def test_business_need_is_subject_aware_and_unknown_events_are_successful_zeroes():
    observation, evidence, _ = facts("business_need", subject_type="ORGANIZATION")
    assert extract(observation, evidence, ruleset_version=AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1)[0].signal_type == "BUSINESS_NEED"
    subjectless, subjectless_evidence, _ = facts("business_need")
    assert extract(subjectless, subjectless_evidence, ruleset_version=AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1)[0].signal_type == "BUSINESS_NEED"
    person, person_evidence, _ = facts("business_need", subject_type="PERSON")
    unknown, unknown_evidence, _ = facts("unrecognized")
    assert extract(person, person_evidence, ruleset_version=AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1) == []
    assert extract(unknown, unknown_evidence, ruleset_version=AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1) == []
    prose = ExtractionObservationFact({"summary": "Could you share the price?"})
    assert extract(prose, unknown_evidence, ruleset_version=AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1) == []


def test_evidence_order_and_duplicate_markers_do_not_duplicate_candidates():
    observation_id, first, second = ids()
    observation = ExtractionObservationFact({"event": "compare"})
    forward = [ExtractionEvidenceFact(first, {"event": "comparison"}), ExtractionEvidenceFact(second, {"event": "compare"})]
    reverse = list(reversed(forward))
    assert extract(observation, forward, ruleset_version=AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1) == extract(observation, reverse, ruleset_version=AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1)


def test_unknown_ruleset_is_a_typed_error_without_database_or_network_access():
    observation, evidence, _ = facts("pricing")
    with pytest.raises(AudienceSignalExtractionContractError, match="unsupported"):
        extract(observation, evidence, ruleset_version="audience-signal-extraction-v2")


def test_extractor_does_not_call_the_frozen_persistence_service(monkeypatch):
    from app.services.audience_signal_service import AudienceSignalService

    def blocked(*args, **kwargs):
        raise AssertionError("deterministic extraction must not persist")

    monkeypatch.setattr(AudienceSignalService, "persist", blocked)
    observation, evidence, _ = facts("pricing")
    assert extract(observation, evidence, ruleset_version=AUDIENCE_SIGNAL_EXTRACTION_RULESET_V1)
