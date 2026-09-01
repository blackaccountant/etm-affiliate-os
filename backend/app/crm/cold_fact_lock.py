"""Shared transaction lock for writers that can invalidate cold-send authority."""
from sqlalchemy import text
from app.repositories.cold_prospecting_repository import advisory_lock_key

def acquire_cold_fact_lock(db, lead_id, contact_point_id, purpose_key):
    if db.bind.dialect.name == "postgresql":
        identity = "\x00".join((lead_id, contact_point_id, "EMAIL", purpose_key))
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": advisory_lock_key("cold-send-facts-v1", identity)})

def lock_affected_cold_operations(db, lead_id, contact_point_id=None, purpose_key=None):
    from app.models.cold_delivery import ColdDeliveryOperation
    query = db.query(ColdDeliveryOperation).filter_by(lead_id=lead_id)
    if contact_point_id: query = query.filter_by(contact_point_id=contact_point_id)
    if purpose_key: query = query.filter_by(purpose_key=purpose_key)
    for operation in query.order_by(ColdDeliveryOperation.contact_point_id, ColdDeliveryOperation.purpose_key).all():
        acquire_cold_fact_lock(db, lead_id, operation.contact_point_id, operation.purpose_key)
