"""Idempotently activate generic runtime work for a cold operation."""
from app.outreach.cold_delivery_runtime_contracts import COLD_B2B_DELIVERY_CAPABILITY, COLD_B2B_DELIVERY_WORKFLOW, ColdDeliveryWorkflowPayload, cold_delivery_mission_key
from app.repositories.mission_repository import MissionRepository
from app.repositories.cold_prospecting_repository import ColdProspectingRepository
from app.services.durable_operation_activation_service import DurableOperationActivationService, SuccessorOperationSpec

class ColdDeliveryMissionLaunchService:
    def __init__(self, session_factory): self.session_factory = session_factory
    def launch(self, operation_id):
        db = self.session_factory()
        try:
            key = cold_delivery_mission_key(operation_id)
            # Serializing launch by its opaque logical identity avoids the generic
            # create-race rollback path creating an additional execution/claim.
            ColdProspectingRepository(db).acquire_lock("cold-delivery-mission-v1", key)
            payload = ColdDeliveryWorkflowPayload(operation_id).to_dict()
            spec = SuccessorOperationSpec("Cold B2B delivery", "orchestrate one cold delivery operation", COLD_B2B_DELIVERY_WORKFLOW, COLD_B2B_DELIVERY_CAPABILITY, key, payload)
            existing = MissionRepository(db).get_by_idempotency_key(key)
            if existing:
                return DurableOperationActivationService(db)._existing_operation(spec, existing), False
            operation = DurableOperationActivationService(db).activate(spec)
            db.commit(); return operation, True
        except Exception: db.rollback(); raise
        finally: db.close()
