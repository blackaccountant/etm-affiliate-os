"""Persistence helpers for the single durable cold dispatch authority."""
from sqlalchemy.exc import IntegrityError
from app.models.cold_delivery import ColdDispatchReservation

class ColdDispatchReservationRepository:
    def __init__(self, db): self.db = db
    def by_operation(self, operation_id): return self.db.query(ColdDispatchReservation).filter_by(operation_id=operation_id).one_or_none()
    def insert(self, reservation):
        try:
            with self.db.begin_nested(): self.db.add(reservation); self.db.flush()
            return reservation, False
        except IntegrityError:
            existing = self.by_operation(reservation.operation_id)
            if existing is None: raise
            return existing, True
