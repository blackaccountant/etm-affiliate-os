"""B2 durable-ID-only cold delivery runtime contracts."""
from dataclasses import dataclass
from app.outreach.contracts import OutreachError, required_text

COLD_B2B_DELIVERY_WORKFLOW = "cold_b2b_delivery"
COLD_B2B_DELIVERY_CAPABILITY = "cold_b2b_delivery"

def cold_delivery_mission_key(operation_id):
    return f"cold-b2b-delivery:{required_text(operation_id, 'cold_delivery_operation_id', 36)}"

@dataclass(frozen=True)
class ColdDeliveryWorkflowPayload:
    cold_delivery_operation_id: str
    def __post_init__(self):
        object.__setattr__(self, "cold_delivery_operation_id", required_text(self.cold_delivery_operation_id, "cold_delivery_operation_id", 36))
    def to_dict(self): return {"cold_delivery_operation_id": self.cold_delivery_operation_id}
    @classmethod
    def from_payload(cls, payload):
        if not isinstance(payload, dict) or set(payload) != {"cold_delivery_operation_id"}:
            raise OutreachError("INVALID_MISSION_PAYLOAD", "Mission payload must contain cold_delivery_operation_id only")
        return cls(payload["cold_delivery_operation_id"])
