"""Durable-ID-only Mission contract for consented outreach delivery."""

from dataclasses import dataclass

from app.outreach.contracts import OutreachError, required_text


OUTREACH_DELIVERY_WORKFLOW = "outreach_delivery"
OUTREACH_DELIVERY_MISSION_NAME = "Outreach delivery"
OUTREACH_DELIVERY_CAPABILITY = "outreach_delivery"


def outreach_delivery_mission_idempotency_key(delivery_attempt_id: object) -> str:
    return f"outreach-delivery:{required_text(delivery_attempt_id, 'delivery_attempt_id', 36)}"


@dataclass(frozen=True)
class OutreachDeliveryWorkflowPayload:
    delivery_attempt_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "delivery_attempt_id", required_text(
            self.delivery_attempt_id, "delivery_attempt_id", 36,
        ))

    def to_dict(self) -> dict[str, str]:
        return {"delivery_attempt_id": self.delivery_attempt_id}

    @classmethod
    def from_payload(cls, payload: object) -> "OutreachDeliveryWorkflowPayload":
        if not isinstance(payload, dict) or set(payload) != {"delivery_attempt_id"}:
            raise OutreachError("INVALID_MISSION_PAYLOAD", "Mission payload must contain delivery_attempt_id only")
        return cls(payload["delivery_attempt_id"])
