"""Persistence primitives for idempotent DistributionRun creation."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import exists, func

from app.models.distribution_run import DistributionRun
from app.models.execution import Execution
from app.repositories.execution_repository import ExecutionLeaseLostError
from app.services.execution_lease import ExecutionLeaseAuthority


class DistributionRunRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, run_id: str) -> DistributionRun | None:
        return self.db.get(DistributionRun, run_id)

    def get_by_idempotency_key(self, idempotency_key: str) -> DistributionRun | None:
        return self.db.query(DistributionRun).filter_by(idempotency_key=idempotency_key).first()

    def list_by_artifact(self, artifact_id: str) -> list[DistributionRun]:
        return self.db.query(DistributionRun).filter_by(generated_content_artifact_id=artifact_id).order_by(DistributionRun.created_at.asc()).all()

    @staticmethod
    def _now():
        from datetime import datetime, timezone
        return datetime.now(timezone.utc)

    @staticmethod
    def _active_authority(authority: ExecutionLeaseAuthority):
        return exists().where(
            Execution.id == authority.execution_id,
            Execution.status.in_(("RUNNING", "RETRYING")),
            Execution.lease_owner == authority.lease_owner,
            Execution.lease_generation == authority.lease_generation,
            Execution.lease_expires_at.isnot(None),
            Execution.lease_expires_at > func.now(),
        )

    def _authority_is_current(self, authority: ExecutionLeaseAuthority) -> bool:
        return bool(self.db.query(self._active_authority(authority)).scalar())

    def transition_owned(
        self,
        run_id: str,
        authority: ExecutionLeaseAuthority,
        *,
        expected_statuses: tuple[str, ...],
        status: str,
        values: dict | None = None,
    ) -> DistributionRun | None:
        """Apply a business-state transition only while the execution lease is live."""
        changes = dict(values or {})
        changes.update(status=status, updated_at=self._now())
        updated = (
            self.db.query(DistributionRun)
            .filter(DistributionRun.id == run_id)
            .filter(DistributionRun.status.in_(expected_statuses))
            .filter(self._active_authority(authority))
            .update(changes, synchronize_session=False)
        )
        self.db.commit()
        if updated == 1:
            self.db.expire_all()
            return self.get_by_id(run_id)
        if not self._authority_is_current(authority):
            raise ExecutionLeaseLostError("execution lease ownership was lost before DistributionRun transition")
        return None

    def claim_reconciliation(
        self, run_id: str, authority: ExecutionLeaseAuthority,
    ) -> DistributionRun | None:
        return self.transition_owned(
            run_id,
            authority,
            expected_statuses=("RECONCILIATION_REQUIRED",),
            status="RECONCILING",
        )

    def resume_reconciliation(
        self, run_id: str, authority: ExecutionLeaseAuthority,
    ) -> DistributionRun | None:
        """Read an existing durable claim only for the active recovered attempt."""
        run = (
            self.db.query(DistributionRun)
            .filter(DistributionRun.id == run_id)
            .filter(DistributionRun.status == "RECONCILING")
            .filter(self._active_authority(authority))
            .one_or_none()
        )
        if run is not None:
            return run
        if not self._authority_is_current(authority):
            raise ExecutionLeaseLostError("execution lease ownership was lost before DistributionRun resume")
        return None

    def create(self, **values) -> DistributionRun:
        """Create exactly one durable run, resolving a unique-key race by reread."""
        row = DistributionRun(**values)
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.get_by_idempotency_key(values["idempotency_key"])
            if existing is None:
                raise
            return existing
        self.db.refresh(row)
        return row
