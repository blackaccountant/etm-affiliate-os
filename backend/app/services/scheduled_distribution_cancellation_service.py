"""Durable cancellation for distribution intent that has not activated yet."""

from app.repositories.distribution_run_repository import DistributionRunRepository


class ScheduledDistributionCancellationService:
    """Cancel only SCHEDULED runs; active operation cancellation is out of scope."""

    def __init__(self, session_factory):
        self.session_factory = session_factory

    def cancel(self, run_id):
        db = self.session_factory()
        try:
            run = DistributionRunRepository(db).cancel_scheduled(run_id)
            db.commit()
            db.refresh(run)
            return run
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
