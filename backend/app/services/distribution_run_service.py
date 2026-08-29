"""Domain validation and durable creation of distribution intent only."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.distribution.contracts import (
    CreateDistributionRunRequest,
    DistributionRunStatus,
    canonicalize_prepared_content_body,
    payload_fingerprint_for_body,
)
from app.models.content_evaluation import ContentEvaluation
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.repositories.distribution_run_repository import DistributionRunRepository


class DistributionRunService:
    def __init__(self, db: Session):
        self.db = db
        self.runs = DistributionRunRepository(db)

    @staticmethod
    def _text(value: object, field: str, *, lowercase: bool = False) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field} must be text")
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError(f"{field} is required")
        return normalized.lower() if lowercase else normalized

    @staticmethod
    def _scheduled_for(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scheduled_for must be timezone-aware")
        return value.astimezone(timezone.utc)

    @staticmethod
    def payload_fingerprint(prepared_content_body: object) -> str:
        return payload_fingerprint_for_body(prepared_content_body)

    @staticmethod
    def idempotency_key(*, artifact_id: str, evaluation_id: str, platform: str, account_reference: str, destination: str, payload_fingerprint: str) -> str:
        material = {
            "account_reference": account_reference,
            "content_evaluation_id": evaluation_id,
            "destination": destination,
            "generated_content_artifact_id": artifact_id,
            "payload_fingerprint": payload_fingerprint,
            "platform": platform,
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return f"distribution-run:{hashlib.sha256(encoded).hexdigest()}"

    def create(self, request: CreateDistributionRunRequest):
        artifact_id = self._text(request.generated_content_artifact_id, "generated_content_artifact_id")
        evaluation_id = self._text(request.content_evaluation_id, "content_evaluation_id")
        platform = self._text(request.platform, "platform", lowercase=True)
        account_reference = self._text(request.account_reference, "account_reference")
        destination = self._text(request.destination, "destination")
        scheduled_for = self._scheduled_for(request.scheduled_for)
        artifact = self.db.get(GeneratedContentArtifact, artifact_id)
        if artifact is None:
            raise ValueError("generated content artifact does not exist")
        evaluation = self.db.get(ContentEvaluation, evaluation_id)
        if evaluation is None:
            raise ValueError("content evaluation does not exist")
        if (
            evaluation.artifact_id != artifact.id
            or evaluation.generation_run_id != artifact.generation_run_id
            or evaluation.content_brief_id != artifact.content_brief_id
        ):
            raise ValueError("content evaluation does not match artifact lineage")
        if evaluation.decision != "APPROVED" or evaluation.approved is not True:
            raise ValueError("content evaluation is not approved for distribution")
        prepared_body = canonicalize_prepared_content_body(
            artifact.body if request.prepared_content_body is None else request.prepared_content_body
        )
        fingerprint = self.payload_fingerprint(prepared_body)
        key = self.idempotency_key(
            artifact_id=artifact_id,
            evaluation_id=evaluation_id,
            platform=platform,
            account_reference=account_reference,
            destination=destination,
            payload_fingerprint=fingerprint,
        )
        existing = self.runs.get_by_idempotency_key(key)
        if existing is not None:
            return existing

        status = (
            DistributionRunStatus.SCHEDULED.value
            if scheduled_for is not None and scheduled_for > datetime.now(timezone.utc)
            else DistributionRunStatus.CREATED.value
        )
        return self.runs.create(
            generated_content_artifact_id=artifact.id,
            content_evaluation_id=evaluation.id,
            platform=platform,
            account_reference=account_reference,
            destination=destination,
            status=status,
            idempotency_key=key,
            prepared_content_body=prepared_body,
            payload_fingerprint=fingerprint,
            scheduled_for=scheduled_for,
        )
