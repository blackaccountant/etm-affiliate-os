"""GLR3 CJ financial ingestion into existing ETM attribution authority."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.models.affiliate_link import AffiliateLink
from app.models.affiliate_program import AffiliateProgram
from app.models.attribution import AttributionContext, AttributionPublication
from app.models.distribution_run import DistributionRun
from app.services.attribution_conversion_bridge_service import (
    AttributionConversionBridgeService,
)
from app.services.cj_commission_client import CjCommissionClient


class CjFinancialIngestionService:
    def __init__(self, db, *, client=None, bridge=None):
        self.db = db
        self.client = CjCommissionClient() if client is None else client
        self.bridge = (
            AttributionConversionBridgeService(db) if bridge is None else bridge
        )

    def _lineage(self, distribution_run_id: str):
        if self.db.get(DistributionRun, distribution_run_id) is None:
            raise ValueError("distribution run does not exist")
        publications = self.db.query(AttributionPublication).filter_by(
            distribution_run_id=distribution_run_id
        ).all()
        if len(publications) != 1:
            raise ValueError("distribution run attribution publication must be unique")
        contexts = self.db.query(AttributionContext).filter_by(
            attribution_publication_id=publications[0].id
        ).all()
        if len(contexts) != 1:
            raise ValueError("distribution run attribution context must be unique")
        context = contexts[0]
        links = self.db.query(AffiliateLink).filter_by(
            attribution_context_id=context.id,
            is_active=True,
        ).all()
        if len(links) != 1:
            raise ValueError("active affiliate link must be unique")
        link = links[0]
        if link.affiliate_program_id != context.affiliate_program_id:
            raise ValueError("affiliate link program conflicts with attribution context")
        program = self.db.get(AffiliateProgram, link.affiliate_program_id)
        if program is None:
            raise ValueError("affiliate program does not exist")
        network = str(program.network or "").strip().lower()
        if "cj" not in network and "commission junction" not in network:
            raise ValueError("affiliate program is not configured for CJ")
        return context, link, program

    @staticmethod
    def _decimal(value, field: str) -> Decimal:
        if value in (None, ""):
            return Decimal("0")
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"CJ {field} is invalid") from exc

    @staticmethod
    def _event_time(value) -> datetime:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("CJ eventDate is required")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("CJ eventDate is invalid") from exc
        if parsed.tzinfo is None:
            raise ValueError("CJ eventDate must be timezone-aware")
        return parsed

    @staticmethod
    def _status(row: dict) -> str:
        return (
            "approved"
            if str(row.get("actionStatus") or "").strip().lower() in {"locked", "closed"}
            else "pending"
        )

    @staticmethod
    def _metadata(row: dict) -> str:
        fields = (
            "commissionId",
            "publisherId",
            "advertiserId",
            "advertiserName",
            "actionStatus",
            "validationStatus",
            "actionType",
            "orderId",
            "original",
            "originalActionId",
            "postingDate",
            "eventDate",
            "websiteId",
            "websiteName",
        )
        return json.dumps(
            {"provider": "cj", **{field: row.get(field) for field in fields}},
            sort_keys=True,
            separators=(",", ":"),
        )

    def sync(
        self,
        *,
        distribution_run_id: str,
        advertiser_id: str,
        since_posting_date: datetime,
        before_posting_date: datetime,
    ) -> dict:
        advertiser = str(advertiser_id).strip()
        if not advertiser or not advertiser.isdigit():
            raise ValueError("CJ advertiser_id must be numeric")
        _context, link, program = self._lineage(distribution_run_id)
        rows = self.client.fetch_commissions(
            since_posting_date=since_posting_date,
            before_posting_date=before_posting_date,
        )

        created = replayed = approved = pending = corrections = matched = 0
        for row in rows:
            publisher_id = str(row.get("publisherId") or "").strip()
            if publisher_id != self.client.publisher_cid:
                raise ValueError("CJ record publisher CID does not match configured publisher")
            if str(row.get("advertiserId") or "").strip() != advertiser:
                continue
            matched += 1
            commission_id = str(row.get("commissionId") or "").strip()
            if not commission_id:
                raise ValueError("CJ commissionId is required")
            original = row.get("original")
            if original is False:
                corrections += 1
            status = self._status(row)
            result = self.bridge.record_provider_conversion(
                affiliate_program_id=program.id,
                sale_amount=self._decimal(row.get("saleAmountUsd"), "saleAmountUsd"),
                commission_amount=self._decimal(
                    row.get("pubCommissionAmountUsd"),
                    "pubCommissionAmountUsd",
                ),
                currency="USD",
                affiliate_link_id=link.id,
                external_conversion_id=f"cj:{commission_id}",
                customer_reference=(
                    str(row.get("orderId")).strip()
                    if row.get("orderId") is not None
                    else None
                ),
                conversion_status=status,
                source="cj",
                metadata_json=self._metadata(row),
                occurred_at=self._event_time(row.get("eventDate")),
            )
            if result["created"]:
                created += 1
            else:
                replayed += 1
            if status == "approved":
                approved += 1
            else:
                pending += 1

        return {
            "provider": "cj",
            "distribution_run_id": distribution_run_id,
            "affiliate_program_id": program.id,
            "affiliate_link_id": link.id,
            "advertiser_id": advertiser,
            "fetched_count": len(rows),
            "matched_count": matched,
            "created_count": created,
            "replayed_count": replayed,
            "approved_count": approved,
            "pending_count": pending,
            "correction_count": corrections,
        }
