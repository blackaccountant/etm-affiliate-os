"""Replay-safe pre-publication launch contracts for Pilot 1."""

from dataclasses import dataclass
from datetime import datetime, timezone


GLR1_PILOT_REVENUE_LAUNCH_CONTRACT_VERSION = "glr1-pilot-revenue-launch-v1"
GLR1_PILOT_REVENUE_LAUNCH_SEMANTICS = (
    "create or reconcile the minimum pre-publication revenue lineage for one approved "
    "content asset and one pre-existing active AffiliateLink by reusing existing "
    "DistributionRun, AttributionPublication, AttributionContext, and attribution-link "
    "authorities. The operation is deterministic and replay-safe despite independent "
    "lower-layer commit boundaries. It returns final reconciled launch identities and "
    "a public tracked redirect path only; it does not publish, create affiliate links, "
    "reinterpret attribution, mutate provider destination URLs, compensate or delete "
    "durable rows, own transaction primitives, or create a second attribution authority."
)


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be nonblank text")
    return " ".join(value.split())


@dataclass(frozen=True)
class PilotRevenueLaunchRequest:
    artifact_id: str
    evaluation_id: str
    platform: str
    account_reference: str
    destination: str
    affiliate_link_id: int
    prepared_content_body: str | None
    scheduled_for: datetime | None

    def normalized(self):
        if type(self.affiliate_link_id) is not int or isinstance(self.affiliate_link_id, bool) or self.affiliate_link_id < 1:
            raise ValueError("affiliate_link_id must be a positive integer")
        if self.prepared_content_body is not None and type(self.prepared_content_body) is not str:
            raise ValueError("prepared_content_body must be text or null")
        if self.scheduled_for is not None:
            if not isinstance(self.scheduled_for, datetime) or self.scheduled_for.tzinfo is None or self.scheduled_for.utcoffset() is None:
                raise ValueError("scheduled_for must be timezone-aware")
            scheduled_for = self.scheduled_for.astimezone(timezone.utc)
        else:
            scheduled_for = None
        return PilotRevenueLaunchRequest(
            artifact_id=_text(self.artifact_id, "artifact_id"),
            evaluation_id=_text(self.evaluation_id, "evaluation_id"),
            platform=_text(self.platform, "platform").lower(),
            account_reference=_text(self.account_reference, "account_reference"),
            destination=_text(self.destination, "destination"),
            affiliate_link_id=self.affiliate_link_id,
            prepared_content_body=self.prepared_content_body,
            scheduled_for=scheduled_for,
        )


@dataclass(frozen=True)
class PilotRevenueLaunchResult:
    distribution_run_id: str
    attribution_publication_id: str
    attribution_context_id: str
    affiliate_link_id: int
    tracking_code: str
    public_redirect_path: str
