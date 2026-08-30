"""Read-only M8D loader for one caller-owned CRM snapshot transaction."""

from sqlalchemy import or_

from app.crm.contactability_contracts import (
    ContactabilitySnapshot,
    ContactPointSnapshot,
    ContactPointStateEventSnapshot,
    PermissionEventSnapshot,
    SuppressionEventSnapshot,
)
from app.models.audience import AudienceSubject
from app.models.crm import ContactPoint, ContactPointStateEvent, Lead, PermissionEvent, SuppressionEvent


class ContactabilitySnapshotRepository:
    """All queries use the supplied Session; production callers provide repeatable-read."""

    def __init__(self, db):
        self.db = db

    def load(self, lead_id: str, channel: str, purpose_key: str, contact_point_id: str | None = None):
        with self.db.no_autoflush:
            return self._load(lead_id, channel, purpose_key, contact_point_id)

    def _load(self, lead_id: str, channel: str, purpose_key: str, contact_point_id: str | None):
        lead = self.db.get(Lead, lead_id)
        if lead is None:
            return None
        subject = self.db.get(AudienceSubject, lead.subject_id) if lead.subject_id else None
        query = self.db.query(
            ContactPoint.id,
            ContactPoint.lead_id,
            ContactPoint.kind,
        ).filter(ContactPoint.lead_id == lead.id)
        if contact_point_id is not None:
            query = query.filter(ContactPoint.id == contact_point_id)
        points = query.order_by(ContactPoint.id).all()
        point_ids = tuple(point.id for point in points)
        state_rows = (
            self.db.query(ContactPointStateEvent)
            .filter(ContactPointStateEvent.contact_point_id.in_(point_ids)).all()
            if point_ids else []
        )
        permission_rows = (
            self.db.query(PermissionEvent).filter(
                PermissionEvent.contact_point_id.in_(point_ids),
                PermissionEvent.channel == channel,
                PermissionEvent.purpose_key == purpose_key,
            ).all()
            if point_ids else []
        )
        suppression_rows = self.db.query(SuppressionEvent).filter(
            SuppressionEvent.lead_id == lead.id,
            or_(
                SuppressionEvent.scope == "GLOBAL_LEAD",
                (SuppressionEvent.scope == "LEAD_CHANNEL") & (SuppressionEvent.channel == channel),
                (SuppressionEvent.scope == "CONTACT_POINT_CHANNEL")
                & (SuppressionEvent.channel == channel)
                & SuppressionEvent.contact_point_id.in_(point_ids or ("",)),
            ),
        ).all()
        return ContactabilitySnapshot(
            lead_id=lead.id,
            subject_type=subject.subject_type if subject else None,
            contact_points=tuple(ContactPointSnapshot(point.id, point.lead_id, point.kind) for point in points),
            state_events=tuple(ContactPointStateEventSnapshot(
                row.id, row.contact_point_id, row.state, row.verification_state,
                row.occurred_at, row.recorded_at,
            ) for row in state_rows),
            permission_events=tuple(PermissionEventSnapshot(
                row.id, row.contact_point_id, row.channel, row.purpose_key, row.event_type,
                row.jurisdiction_context, row.occurred_at, row.recorded_at,
            ) for row in permission_rows),
            suppression_events=tuple(SuppressionEventSnapshot(
                row.id, row.lead_id, row.contact_point_id, row.scope, row.channel, row.action,
                row.reason, row.effective_at, row.recorded_at,
            ) for row in suppression_rows),
        )
