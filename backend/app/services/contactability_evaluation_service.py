"""Read-only M8D orchestration over a caller-owned stable snapshot transaction.

Production PostgreSQL callers requiring cross-query consistency must supply a
caller-owned repeatable-read transaction. This service never changes isolation,
opens another Session, writes, flushes, or commits.
"""

from app.crm.contact_point_state_resolution import resolve_contact_point_state
from app.crm.contactability import aggregate_lead_contactability, evaluate_contact_point
from app.crm.contactability_contracts import ContactabilityContext
from app.crm.contracts import CRMError, required_text
from app.crm.permission_resolution import resolve_permission
from app.crm.suppression_resolution import resolve_suppression
from app.repositories.contactability_snapshot_repository import ContactabilitySnapshotRepository


class ContactabilityEvaluationService:
    def __init__(self, db):
        self.db = db
        self.snapshots = ContactabilitySnapshotRepository(db)

    def evaluate_point(self, lead_id, contact_point_id, *, channel, purpose_key, evaluated_as_of):
        context = ContactabilityContext(channel, purpose_key, evaluated_as_of)
        lead_id = required_text(lead_id, "lead_id", 36)
        contact_point_id = required_text(contact_point_id, "contact_point_id", 36)
        snapshot = self.snapshots.load(lead_id, context.channel, context.purpose_key, contact_point_id)
        if snapshot is None:
            raise CRMError("LEAD_NOT_FOUND", "Lead does not exist")
        if not snapshot.contact_points:
            raise CRMError("CONTACT_POINT_NOT_FOUND", "contact point does not belong to Lead")
        return self._evaluate(snapshot, snapshot.contact_points[0], context)

    def evaluate_lead(self, lead_id, *, channel, purpose_key, evaluated_as_of):
        context = ContactabilityContext(channel, purpose_key, evaluated_as_of)
        lead_id = required_text(lead_id, "lead_id", 36)
        snapshot = self.snapshots.load(lead_id, context.channel, context.purpose_key)
        if snapshot is None:
            raise CRMError("LEAD_NOT_FOUND", "Lead does not exist")
        results = tuple(self._evaluate(snapshot, point, context) for point in snapshot.contact_points)
        return aggregate_lead_contactability(snapshot.lead_id, context, results)

    @staticmethod
    def _evaluate(snapshot, point, context):
        state_events = tuple(row for row in snapshot.state_events if row.contact_point_id == point.id)
        permission_events = tuple(row for row in snapshot.permission_events if row.contact_point_id == point.id)
        state = resolve_contact_point_state(state_events, context.evaluated_as_of)
        permission = resolve_permission(
            permission_events,
            contact_point_id=point.id,
            channel=context.channel,
            purpose_key=context.purpose_key,
            evaluated_as_of=context.evaluated_as_of,
        )
        suppression = resolve_suppression(
            snapshot.suppression_events,
            lead_id=snapshot.lead_id,
            contact_point_id=point.id,
            channel=context.channel,
            evaluated_as_of=context.evaluated_as_of,
        )
        return evaluate_contact_point(
            subject_type=snapshot.subject_type,
            contact_point=point,
            context=context,
            contact_state=state,
            permission=permission,
            suppression=suppression,
        )
