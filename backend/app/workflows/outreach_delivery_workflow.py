"""Fresh-session M9C1 workflow for consented Resend EMAIL delivery."""

from app.database.session import SessionLocal
from app.outreach.contracts import OutreachError
from app.outreach.delivery_mission_contracts import OUTREACH_DELIVERY_WORKFLOW, OutreachDeliveryWorkflowPayload
from app.outreach.provider_registry import build_default_provider_registry
from app.repositories.execution_repository import ExecutionLeaseLostError
from app.services.execution_runtime_context import current_execution_runtime_context
from app.services.outreach_provider_delivery_service import OutreachProviderDeliveryService
from app.workflow_engine.workflow_result import WorkflowResult


class OutreachDeliveryWorkflow:
    workflow_name = OUTREACH_DELIVERY_WORKFLOW

    def __init__(self, session_factory=SessionLocal, provider_registry=None, clock=None):
        self.session_factory = session_factory
        self.provider_registry = provider_registry or build_default_provider_registry()
        self.clock = clock

    def execute(self, payload):
        try:
            values = OutreachDeliveryWorkflowPayload.from_payload(payload)
        except OutreachError as error:
            return WorkflowResult(False, self.workflow_name, {}, errors=[f"validation error: {error}"])
        context = current_execution_runtime_context()
        if context is None:
            return WorkflowResult(False, self.workflow_name, values.to_dict(), errors=["execution authority is required"])
        db = self.session_factory()
        try:
            result = OutreachProviderDeliveryService(
                db, self.provider_registry, clock=self.clock,
            ).deliver(values.delivery_attempt_id, context.authority)
            data = result.to_dict()
            if result.retryable:
                return WorkflowResult(False, self.workflow_name, data, errors=[result.safe_message])
            return WorkflowResult(True, self.workflow_name, data, errors=[])
        except ExecutionLeaseLostError:
            db.rollback()
            raise
        except OutreachError as error:
            db.rollback()
            return WorkflowResult(False, self.workflow_name, values.to_dict(), errors=[f"validation error: {error}"])
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
