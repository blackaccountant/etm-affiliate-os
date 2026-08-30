"""JSON-safe durable Mission contract for initial distribution publication."""
from dataclasses import asdict, dataclass

CONTENT_DISTRIBUTION_MISSION_NAME = "ContentDistribution"
CONTENT_DISTRIBUTION_WORKFLOW = "distribution_publish"
CONTENT_DISTRIBUTION_CAPABILITY = "content_distribution"
CONTENT_DISTRIBUTION_RECONCILIATION_MISSION_NAME = "ContentDistributionReconciliation"
CONTENT_DISTRIBUTION_RECONCILIATION_WORKFLOW = "distribution_reconcile"

def distribution_mission_idempotency_key(run_id: object) -> str:
    if not isinstance(run_id, str) or not run_id.strip(): raise ValueError("distribution_run_id is required")
    return f"distribution:{run_id.strip()}"
def distribution_reconciliation_mission_idempotency_key(run_id: object) -> str:
    return f"distribution-reconciliation:{distribution_mission_idempotency_key(run_id).removeprefix('distribution:')}"
def distribution_followup_publish_mission_idempotency_key(run_id: object, generation: int) -> str:
    if not isinstance(generation, int) or generation < 1: raise ValueError("follow-up publish generation must be at least 1")
    return f"distribution-publish:{distribution_mission_idempotency_key(run_id).removeprefix('distribution:')}:{generation}"

@dataclass(frozen=True)
class DistributionWorkflowPayload:
    distribution_run_id: str
    def __post_init__(self):
        object.__setattr__(self, "distribution_run_id", distribution_mission_idempotency_key(self.distribution_run_id).removeprefix("distribution:"))
    def to_dict(self): return asdict(self)
    @classmethod
    def from_payload(cls, payload):
        if not isinstance(payload, dict) or "distribution_run_id" not in payload or set(payload) - {"distribution_run_id", "mission_id", "execution_id", "worker_name", "retry_count", "max_retries", "failure_type", "execution_recovery", "recovered_execution_id"}:
            raise ValueError("workflow payload contains unsupported runtime data")
        return cls(payload["distribution_run_id"])
