"""B2 orchestration-only workflow; it never resolves or sends to a recipient."""
from app.database.session import SessionLocal
from datetime import datetime, timezone
from sqlalchemy import and_, exists, or_, update
from app.models.cold_delivery import ColdDeliveryEvent, ColdDeliveryOperationState
from app.models.execution import Execution
from app.outreach.contracts import sha256_fingerprint
from app.outreach.cold_delivery_runtime_contracts import COLD_B2B_DELIVERY_WORKFLOW, ColdDeliveryWorkflowPayload
from app.repositories.execution_repository import ExecutionRepository
from app.services.execution_runtime_context import current_execution_runtime_context
from app.services.cold_delivery_t3_service import ColdDeliveryT3Service
from app.services.cold_delivery_pre_send_service import ColdDeliveryPreSendService
from app.workflow_engine.workflow_result import WorkflowResult

class ColdDeliveryWorkflow:
    workflow_name = COLD_B2B_DELIVERY_WORKFLOW
    def __init__(self, session_factory=SessionLocal, cold_provider_registry=None): self.session_factory, self.cold_provider_registry = session_factory, cold_provider_registry
    def execute(self, payload):
        try: values = ColdDeliveryWorkflowPayload.from_payload(payload)
        except Exception as error: return WorkflowResult(False, self.workflow_name, {}, errors=[str(error)])
        context = current_execution_runtime_context()
        if context is None: return WorkflowResult(False, self.workflow_name, values.to_dict(), errors=["execution authority is required"])
        db = self.session_factory()
        try:
            authority = context.authority
            state = db.query(ColdDeliveryOperationState).filter_by(operation_id=values.cold_delivery_operation_id).one_or_none()
            if state is None: return WorkflowResult(False, self.workflow_name, values.to_dict(), errors=["cold delivery operation state is missing"])
            fence = f"{authority.lease_owner}:{authority.lease_generation}"
            if state.active_execution_id is not None and (state.active_execution_id != str(authority.execution_id) or state.active_fence_identity != fence):
                return WorkflowResult(False, self.workflow_name, values.to_dict(), errors=["cold delivery execution authority was superseded"])
            if state.current_state == "CREATED":
                now = datetime.now(timezone.utc)
                expected_revision = state.revision
                event_sequence = state.next_event_sequence
                execution_is_owned = exists().where(and_(
                    Execution.id == authority.execution_id,
                    Execution.status.in_(("RUNNING", "RETRYING")),
                    Execution.lease_owner == authority.lease_owner,
                    Execution.lease_generation == authority.lease_generation,
                    Execution.lease_expires_at > now,
                ))
                result = db.execute(update(ColdDeliveryOperationState).where(
                    ColdDeliveryOperationState.operation_id == values.cold_delivery_operation_id,
                    ColdDeliveryOperationState.revision == expected_revision,
                    ColdDeliveryOperationState.next_event_sequence == event_sequence,
                    execution_is_owned,
                    or_(ColdDeliveryOperationState.active_execution_id.is_(None), ColdDeliveryOperationState.active_execution_id == str(authority.execution_id)),
                    or_(ColdDeliveryOperationState.active_fence_identity.is_(None), ColdDeliveryOperationState.active_fence_identity == fence),
                ).values(current_state="READY", revision=expected_revision + 1,
                         next_event_sequence=event_sequence + 1,
                         active_execution_id=str(authority.execution_id),
                         active_fence_identity=fence, updated_at=now))
                if result.rowcount != 1:
                    db.rollback()
                    return WorkflowResult(False, self.workflow_name, values.to_dict(), errors=["cold delivery execution authority or state revision was superseded"])
                db.add(ColdDeliveryEvent(operation_id=values.cold_delivery_operation_id,
                    sequence_number=event_sequence, event_type="RUNTIME_READY", occurred_at=now,
                    source_namespace="cold-b2b-runtime-v1",
                    source_event_key=f"{values.cold_delivery_operation_id}:{authority.execution_id}:{authority.lease_generation}:{expected_revision}",
                    event_fingerprint=sha256_fingerprint({"operation_id": values.cold_delivery_operation_id, "state": "READY", "execution_id": authority.execution_id, "generation": authority.lease_generation, "revision": expected_revision}),
                    safe_payload={"state": "READY"}))
                db.flush()
                db.commit()
            elif state.current_state == "READY":
                result = ColdDeliveryT3Service(db).evaluate_and_plan(values.cold_delivery_operation_id, authority)
                return WorkflowResult(True, self.workflow_name, result, errors=[])
            elif state.current_state == "DISPATCH_PLANNED":
                result = ColdDeliveryPreSendService(db, self.cold_provider_registry).reserve(values.cold_delivery_operation_id, authority)
                return WorkflowResult(True, self.workflow_name, result, errors=[])
            return WorkflowResult(True, self.workflow_name, values.to_dict(), errors=[])
        except Exception:
            db.rollback(); raise
        finally: db.close()
