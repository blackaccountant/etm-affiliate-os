"""Durable content brief service for the upstream intelligence ledger."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.content_intelligence.contracts import ContentBriefStatus, ContentGenerationRunStatus, EvidenceUsageRole
from app.models.content_brief import ContentBrief
from app.models.content_brief_evidence import ContentBriefEvidence
from app.models.content_generation_run import ContentGenerationRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun, EvidenceObservation


class ContentBriefService:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _canonical_json(value) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _normalize_value(value):
        if value is None:
            return None
        if isinstance(value, (list, tuple, set)):
            return sorted(str(item).strip() for item in value if str(item).strip())
        if isinstance(value, str):
            return value.strip()
        return str(value)

    def _brief_identity(self, *, discovery_candidate_id: str, content_type: str, channel_intent: str, objective: str,
                        audience_intent: str | None, audience_problem: str | None, angle: str | None,
                        call_to_action: str | None, tone: str | None, required_disclosure: str | None,
                        key_benefits: object | None, proof_points: object | None, target_keywords: object | None,
                        constraints: object | None) -> str:
        payload = {
            "discovery_candidate_id": discovery_candidate_id,
            "content_type": content_type,
            "channel_intent": channel_intent,
            "objective": objective,
            "audience_intent": audience_intent,
            "audience_problem": audience_problem,
            "angle": angle,
            "call_to_action": call_to_action,
            "tone": tone,
            "required_disclosure": required_disclosure,
            "key_benefits": self._normalize_value(key_benefits),
            "proof_points": self._normalize_value(proof_points),
            "target_keywords": self._normalize_value(target_keywords),
            "constraints": self._normalize_value(constraints),
        }
        return self._canonical_json(payload)

    def _candidate_eligible(self, candidate: DiscoveryCandidate | None) -> bool:
        return candidate is not None and candidate.disposition == "SELECTED" and candidate.verification_status == "VERIFIED"

    def _validate_run_and_candidate(self, run_id: str, candidate_id: str) -> tuple[DiscoveryRun, DiscoveryCandidate]:
        run = self.db.get(DiscoveryRun, run_id)
        if run is None:
            raise ValueError("discovery run not found")
        candidate = self.db.get(DiscoveryCandidate, candidate_id)
        if candidate is None:
            raise ValueError("discovery candidate not found")
        if candidate.run_id != run.id:
            raise ValueError("candidate does not belong to this run")
        if candidate.disposition != "SELECTED":
            raise ValueError("candidate is not selected")
        if candidate.verification_status != "VERIFIED":
            raise ValueError("candidate is not verified")
        return run, candidate

    def _validate_evidence_chain(self, candidate: DiscoveryCandidate, evidence_observation_ids: list[str]) -> None:
        if not evidence_observation_ids:
            return
        valid_ids = {item.id for item in self.db.query(EvidenceObservation).filter(EvidenceObservation.candidate_id == candidate.id).all()}
        for evidence_id in evidence_observation_ids:
            if evidence_id not in valid_ids:
                raise ValueError("evidence does not belong to the valid discovery provenance chain")
            evidence = self.db.get(EvidenceObservation, evidence_id)
            if evidence is None or evidence.candidate_id != candidate.id:
                raise ValueError("evidence provenance is invalid for this brief")

    @staticmethod
    def _evidence_links(
        evidence_observation_ids: list[str] | None,
        usage_role: str,
        evidence_links: list[dict[str, str]] | None,
    ) -> list[dict[str, str]]:
        """Normalize legacy single-role input and Phase 4C role-aware links."""
        links = list(evidence_links or [])
        if evidence_observation_ids:
            links.extend(
                {
                    "evidence_observation_id": evidence_id,
                    "usage_role": usage_role,
                }
                for evidence_id in evidence_observation_ids
            )

        allowed_roles = {item.value for item in EvidenceUsageRole}
        normalized: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for link in links:
            evidence_id = str(link.get("evidence_observation_id") or "").strip()
            role = str(link.get("usage_role") or "").strip()
            if not evidence_id or role not in allowed_roles:
                raise ValueError("evidence links require a valid evidence_observation_id and usage_role")
            key = (evidence_id, role)
            if key not in seen:
                seen.add(key)
                normalized.append({"evidence_observation_id": evidence_id, "usage_role": role})
        return normalized

    def _reconcile_evidence_links(
        self,
        brief: ContentBrief,
        candidate: DiscoveryCandidate,
        evidence_links: list[dict[str, str]],
    ) -> None:
        evidence_ids = [item["evidence_observation_id"] for item in evidence_links]
        self._validate_evidence_chain(candidate, evidence_ids)
        existing = {
            (link.evidence_observation_id, link.usage_role)
            for link in self.db.query(ContentBriefEvidence).filter(ContentBriefEvidence.content_brief_id == brief.id).all()
        }
        for link in evidence_links:
            key = (link["evidence_observation_id"], link["usage_role"])
            if key not in existing:
                self.db.add(
                    ContentBriefEvidence(
                        id=str(uuid4()),
                        content_brief_id=brief.id,
                        evidence_observation_id=key[0],
                        usage_role=key[1],
                        created_at=self._utc_now(),
                    )
                )
                existing.add(key)

    def create_brief(self, *, discovery_run_id: str, discovery_candidate_id: str, content_type: str, channel_intent: str,
                     objective: str, audience_intent: str | None = None, audience_problem: str | None = None,
                     angle: str | None = None, call_to_action: str | None = None, tone: str | None = None,
                     required_disclosure: str | None = None, key_benefits: object | None = None,
                     proof_points: object | None = None, target_keywords: object | None = None,
                     constraints: object | None = None, evidence_observation_ids: list[str] | None = None,
                     usage_role: str = EvidenceUsageRole.PRIMARY.value, evidence_links: list[dict[str, str]] | None = None,
                     status: str = ContentBriefStatus.CREATED.value,
                     identity_proof_points: object | None = None) -> ContentBrief:
        run, candidate = self._validate_run_and_candidate(discovery_run_id, discovery_candidate_id)
        normalized_evidence_links = self._evidence_links(evidence_observation_ids, usage_role, evidence_links)
        self._validate_evidence_chain(
            candidate,
            [item["evidence_observation_id"] for item in normalized_evidence_links],
        )
        identity = self._brief_identity(
            discovery_candidate_id=candidate.id,
            content_type=content_type,
            channel_intent=channel_intent,
            objective=objective,
            audience_intent=audience_intent,
            audience_problem=audience_problem,
            angle=angle,
            call_to_action=call_to_action,
            tone=tone,
            required_disclosure=required_disclosure,
            key_benefits=key_benefits,
            proof_points=proof_points if identity_proof_points is None else identity_proof_points,
            target_keywords=target_keywords,
            constraints=constraints,
        )
        existing = self.db.query(ContentBrief).filter(ContentBrief.idempotency_key == identity).first()
        if existing is not None:
            try:
                self._reconcile_evidence_links(existing, candidate, normalized_evidence_links)
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            self.db.refresh(existing)
            return existing

        brief = ContentBrief(
            id=str(uuid4()),
            discovery_run_id=run.id,
            discovery_candidate_id=candidate.id,
            content_type=content_type,
            channel_intent=channel_intent,
            objective=objective,
            audience_intent=audience_intent,
            audience_problem=audience_problem,
            angle=angle,
            call_to_action=call_to_action,
            tone=tone,
            required_disclosure=required_disclosure,
            key_benefits=key_benefits,
            proof_points=proof_points,
            target_keywords=target_keywords,
            constraints=constraints,
            idempotency_key=identity,
            status=status,
            created_at=self._utc_now(),
            updated_at=self._utc_now(),
        )
        self.db.add(brief)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.query(ContentBrief).filter(ContentBrief.idempotency_key == identity).first()
            if existing is not None:
                return existing
            raise

        try:
            self._reconcile_evidence_links(brief, candidate, normalized_evidence_links)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(brief)
        return brief

    def create_generation_run(self, *, content_brief_id: str, provider: str, model: str, prompt_version: str,
                             generation_parameters: dict | None = None, status: str = ContentGenerationRunStatus.CREATED.value,
                             attempt_count: int = 0) -> ContentGenerationRun:
        brief = self.db.get(ContentBrief, content_brief_id)
        if brief is None:
            raise ValueError("content brief does not exist")
        canonical = {
            "content_brief_id": content_brief_id,
            "provider": provider,
            "model": model,
            "prompt_version": prompt_version,
            "generation_parameters": generation_parameters or {},
        }
        idempotency_key = self._canonical_json(canonical)
        existing = self.db.query(ContentGenerationRun).filter(ContentGenerationRun.idempotency_key == idempotency_key).first()
        if existing is not None:
            return existing

        run = ContentGenerationRun(
            id=str(uuid4()),
            content_brief_id=content_brief_id,
            idempotency_key=idempotency_key,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            generation_parameters=generation_parameters,
            status=status,
            attempt_count=attempt_count,
            started_at=self._utc_now(),
            created_at=self._utc_now(),
            updated_at=self._utc_now(),
        )
        self.db.add(run)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.query(ContentGenerationRun).filter(ContentGenerationRun.idempotency_key == idempotency_key).first()
            if existing is not None:
                return existing
            raise
        self.db.refresh(run)
        return run
