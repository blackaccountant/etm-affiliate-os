"""Durable rescheduling for distribution intent that has not activated yet."""

from datetime import datetime, timezone

from app.repositories.distribution_run_repository import DistributionRunRepository


class ScheduledDistributionReschedulingService:
    """Reschedule only SCHEDULED runs and let database time define "future"."""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    @staticmethod
    def _normalize_scheduled_for(value):
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scheduled_for must be timezone-aware")
        return value.astimezone(timezone.utc)

    def reschedule(self, run_id, scheduled_for):
        scheduled_for = self._normalize_scheduled_for(scheduled_for)
        db = self.session_factory()
        try:
            run = DistributionRunRepository(db).reschedule_scheduled(run_id, scheduled_for)
            db.commit()
            db.refresh(run)
            return run
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
