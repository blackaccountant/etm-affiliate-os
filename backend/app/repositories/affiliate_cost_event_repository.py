"""Narrow persistence operations for immutable affiliate cost authority."""
from app.models.affiliate_cost_event import AffiliateCostEvent


class AffiliateCostEventRepository:
    def __init__(self, db): self.db = db
    def get(self, event_id): return self.db.get(AffiliateCostEvent, event_id)
    def by_source(self, namespace, digest): return self.db.query(AffiliateCostEvent).filter_by(source_namespace=namespace, source_event_digest=digest).one_or_none()
    def add(self, event): self.db.add(event); self.db.flush(); return event
