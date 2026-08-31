"""Activate or reuse the durable Mission for one prepared delivery attempt."""

from dataclasses import dataclass

from app.outreach.delivery_mission_contracts import (
    OUTREACH_DELIVERY_CAPABILITY,
    OUTREACH_DELIVERY_MISSION_NAME,
    OUTREACH_DELIVERY_WORKFLOW,
    OutreachDeliveryWorkflowPayload,
    outreach_delivery_mission_idempotency_key,
)
from app.repositories.mission_repository import MissionRepository
from app.repositories.outreach_delivery_attempt_repository import OutreachDeliveryAttemptRepository
from app.repositories.outreach_delivery_event_repository import OutreachDeliveryEventRepository
from app.services.durable_operation_activation_service import DurableOperationActivationService, SuccessorOperationSpec


@dataclass(frozen=True)
class OutreachDeliveryMissionLaunchResult:
    delivery_attempt_id: str
    mission_id: str
    mission_status: str
    idempotency_key: str
    created: bool


class OutreachDeliveryMissionLaunchService:
    workflow_name = OUTREACH_DELIVERY_WORKFLOW
    required_capability = OUTREACH_DELIVERY_CAPABILITY

    def __init__(self, session_factory):
        self.session_factory = session_factory

    def launch(self, delivery_attempt_id: str) -> OutreachDeliveryMissionLaunchResult:
        key = outreach_delivery_mission_idempotency_key(delivery_attempt_id)
        db = self.session_factory()
        try:
            existing = MissionRepository(db).get_by_idempotency_key(key)
            if existing is not None:
                return OutreachDeliveryMissionLaunchResult(
                    delivery_attempt_id, existing.id, existing.status, key, False,
                )
            attempt = OutreachDeliveryAttemptRepository(db).get(delivery_attempt_id)
            prepared = OutreachDeliveryEventRepository(db).by_attempt_sequence(delivery_attempt_id, 1)
            if attempt is None:
                raise ValueError("delivery attempt does not exist")
            if prepared is None or prepared.event_type != "PREPARED":
                raise ValueError("delivery attempt is not prepared")
            payload = OutreachDeliveryWorkflowPayload(delivery_attempt_id).to_dict()
            operation = DurableOperationActivationService(db).activate(SuccessorOperationSpec(
                OUTREACH_DELIVERY_MISSION_NAME,
                "deliver one consented immutable outreach message",
                OUTREACH_DELIVERY_WORKFLOW,
                OUTREACH_DELIVERY_CAPABILITY,
                key,
                payload,
            ))
            db.commit()
            return OutreachDeliveryMissionLaunchResult(
                delivery_attempt_id, operation.mission_id, operation.state.value, key, True,
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
