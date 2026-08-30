"""Deterministic normalization and fingerprint helpers for audience facts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone


def canonical_json(value: object) -> str:
    """Serialize JSON-safe values with a stable representation for fingerprints."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def required_text(value: object, field: str, *, lowercase: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized.lower() if lowercase else normalized


def aware_utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def normalize_identity_reference(identity_type: object, reference: object) -> str:
    """Normalize only identifier types whose casing/host semantics are stable."""
    kind = required_text(identity_type, "identity_type", lowercase=True)
    value = required_text(reference, "normalized_reference")
    if kind == "email":
        return value.lower()
    if kind == "domain":
        value = value.lower()
        return value.removeprefix("https://").removeprefix("http://").removeprefix("www.").rstrip("/")
    return value


def _fingerprint(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def observation_key(*, source_namespace: object, source_type: object,
                    external_observation_id: object | None, source_reference: object | None,
                    observed_at: datetime, normalized_fact: object) -> str:
    namespace = required_text(source_namespace, "source_namespace", lowercase=True)
    source_kind = required_text(source_type, "source_type", lowercase=True)
    observed = aware_utc(observed_at, "observed_at").isoformat()
    if external_observation_id is not None:
        external_id = required_text(external_observation_id, "external_observation_id")
        return _fingerprint("audience-observation-v1", namespace, "external", external_id)
    reference = required_text(source_reference, "source_reference")
    return _fingerprint(
        "audience-observation-v1", namespace, source_kind, "reference", reference,
        observed, canonical_json(normalized_fact),
    )


def evidence_fingerprint(*, observation_id: object, source_reference: object,
                         normalized_representation: object, content_fingerprint: object | None) -> str:
    return _fingerprint(
        "audience-evidence-v1",
        required_text(observation_id, "observation_id"),
        required_text(source_reference, "source_reference"),
        canonical_json(normalized_representation),
        "" if content_fingerprint is None else required_text(content_fingerprint, "content_fingerprint"),
    )


def normalize_topic(topic: object, topic_label: object) -> tuple[str, str]:
    label = required_text(topic_label, "topic_label")
    if len(label) > 256:
        raise ValueError("topic_label is too long")
    raw = required_text(topic, "topic", lowercase=True)
    slug = "-".join(part for part in raw.replace("_", " ").split() if part)
    if not slug or len(slug) > 128 or any(not (char.isalnum() or char == "-") for char in slug):
        raise ValueError("topic must normalize to a stable slug")
    return slug, label


def evidence_set_fingerprint(entries: list[tuple[str, str]]) -> str:
    if not entries:
        raise ValueError("evidence_ids are required")
    canonical = sorted(f"{required_text(item_id, 'evidence_id')}:{required_text(fingerprint, 'evidence_fingerprint')}" for item_id, fingerprint in entries)
    return _fingerprint("audience-evidence-set-v1", *canonical)


def signal_extraction_key(*, subject_id: str | None, signal_type: str, topic_slug: str,
                          intent_stage: str | None, evidence_set: str, ruleset_version: str) -> str:
    scope = f"subject:{subject_id}" if subject_id is not None else "subjectless"
    return _fingerprint("audience-signal-extraction-v1", scope, signal_type, topic_slug,
                        intent_stage or "", evidence_set, ruleset_version)
