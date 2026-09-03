import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
import requests
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.affiliate_program import AffiliateProgram
from app.models.product import Product
from app.models.publishing_queue import PublishingQueue
from app.optimization.eligible_operating_profit_candidate_set_contracts import EligibleOperatingProfitCandidateSetRequest
from app.optimization.operating_profit_evidence_eligibility_contracts import OperatingProfitEvidenceEligibilityPolicy
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_payout_settlement_link_service import AttributionPayoutSettlementLinkService
from app.services.attribution_publication_service import AttributionPublicationService
from app.services.eligible_operating_profit_candidate_set_service import EligibleOperatingProfitCandidateSetService
from app.services.operating_profit_evidence_eligibility_service import OperatingProfitEvidenceEligibilityService
from app.services.operating_profit_evidence_service import OperatingProfitEvidenceService
from app.services.operating_profit_signal_service import OperatingProfitSignalService


ROLE = os.getenv("ETM_G5_M11A5A_DB_ROLE")
RAW = os.getenv("ETM_G5_M11A5A_DATABASE_URL")
if not RAW:
    pytest.skip("requires guarded M11A5A URL", allow_module_level=True)
URL = make_url(RAW)
if (
    ROLE != "qualification"
    or not URL.drivername.startswith("postgresql")
    or URL.host != "127.0.0.1"
    or URL.port != 5432
    or URL.database != "etm_g5_m11a5a_composition_seam_qualification"
):
    raise RuntimeError("M11A5A database guard failed")


def _session():
    engine = create_engine(URL.render_as_string(hide_password=False))
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _request(minimum=1):
    return EligibleOperatingProfitCandidateSetRequest(
        ("affiliate_program",),
        "USD",
        OperatingProfitEvidenceEligibilityPolicy("p", minimum, minimum, minimum),
        datetime(2100, 1, 1, tzinfo=timezone.utc),
    )


def _ids(rows):
    return {dict(row.dimensions)["affiliate_program"] for row in rows}


def _settled(*, product_id=None, program_id=None):
    db, token = _session(), uuid4().hex
    try:
        product = (
            db.get(Product, product_id)
            if product_id
            else Product(
                name=token,
                website=f"https://{token}.invalid",
                category="test",
                affiliate_program="test",
                commission_type="percentage",
                commission_value="10",
                affiliate_score=1,
                grade="A",
                confidence=1,
                summary="",
                recommendation="",
                status="active",
            )
        )
        if not product_id:
            db.add(product)
            db.flush()
        program = (
            db.get(AffiliateProgram, program_id)
            if program_id
            else AffiliateProgram(
                product_id=product.id,
                program_name=token,
                commission_type="percentage",
                commission_value="10",
                status="active",
            )
        )
        if not program_id:
            db.add(program)
            db.flush()
        asset = AffiliateContentAsset(product_id=product.id, asset_type="article", title=token)
        db.add(asset)
        db.flush()
        queue = PublishingQueue(content_asset_id=asset.id, channel=token)
        db.add(queue)
        db.flush()
        publication = AttributionPublicationService(db).bind_legacy(queue.id)
        context = AttributionContextService(db).create(
            affiliate_program_id=program.id,
            attribution_publication_id=publication.id,
        )
        db.commit()
        link = AttributionLinkBridgeService(db).create_bound_link(
            affiliate_program_id=program.id,
            attribution_context_id=context.id,
            name=token,
            destination_url="https://private.invalid",
            content_asset_id=asset.id,
        )
        result = AttributionConversionBridgeService(db).record(
            affiliate_program_id=program.id,
            affiliate_link_id=link.id,
            external_conversion_id=token,
            customer_reference="private",
            sale_amount=Decimal("1000"),
            currency="USD",
            commission_rate=Decimal("10"),
            metadata_json=json.dumps({"private": token}),
        )
        earning_link = AttributionEarningLinkService(db).reconcile(
            attribution_fact_id=result["fact"].id
        )
        earning, now = result["earning"], datetime.now(timezone.utc)
        payout = AffiliatePayout(
            affiliate_program_id=program.id,
            total_amount=earning.commission_amount,
            currency="USD",
            status="paid",
            paid_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(payout)
        db.flush()
        earning.payout_id, earning.status = payout.id, "paid"
        db.add(
            AffiliatePayoutAttempt(
                payout_id=payout.id,
                attempt_number=1,
                amount=payout.total_amount,
                currency="USD",
                status="completed",
                provider="manual",
                idempotency_key=token,
                started_at=now,
                completed_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
        AttributionPayoutSettlementLinkService(db).reconcile(
            attribution_earning_link_id=earning_link.id
        )
        return {"product": product.id, "program": program.id}
    finally:
        db.close()


class CaptureM11A1:
    def __init__(self, delegate, state):
        self.delegate, self.state, self.rows, self.returned = delegate, state, None, None

    def project(self, request):
        self.state["m11a1"] += 1
        if self.state.get("single_projection") and self.state["m11a1"] > 1:
            raise AssertionError("M11A1 traversed more than once for one projection")
        previous = self.state["inside_delegate"]
        self.state["inside_delegate"] = True
        try:
            self.returned = self.delegate.project(request)
            self.rows = self.returned
            return self.returned
        finally:
            self.state["inside_delegate"] = previous


class ForwardingProxy:
    def __init__(self, delegate, state, key):
        self.delegate, self.state, self.key = delegate, state, key

    def project(self, request):
        self.state[self.key] += 1
        previous = self.state["inside_delegate"]
        self.state["inside_delegate"] = True
        try:
            return self.delegate.project(request)
        finally:
            self.state["inside_delegate"] = previous


def _graph(db, state):
    capture = CaptureM11A1(OperatingProfitSignalService(db), state)
    evidence = OperatingProfitEvidenceService(db, signal_service=capture)
    eligibility = OperatingProfitEvidenceEligibilityService(
        db,
        evidence_service=ForwardingProxy(evidence, state, "m11a2"),
    )
    candidate_set = EligibleOperatingProfitCandidateSetService(
        db,
        eligibility_service=ForwardingProxy(eligibility, state, "m11a3"),
    )
    return candidate_set, capture


def _network_forbidden(*_args, **_kwargs):
    raise AssertionError("network called")


def test_current_head_requires_no_m11a5a_migration():
    db = _session()
    try:
        assert MigrationContext.configure(db.connection()).get_current_revision() == "c3d4e5f6a7b8"
    finally:
        db.close()


def test_real_default_and_injected_composition_is_once_read_only_and_network_free(monkeypatch):
    lineage = _settled()
    default_db = _session()
    try:
        default_rows = EligibleOperatingProfitCandidateSetService(default_db).project(_request())
    finally:
        default_db.close()

    db = _session()
    state = {"m11a1": 0, "m11a2": 0, "m11a3": 0, "inside_delegate": False, "outside_sql": []}
    engine = db.get_bind()

    def observe(_conn, _cursor, statement, *_args):
        if not state["inside_delegate"]:
            state["outside_sql"].append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    monkeypatch.setattr(requests.sessions.Session, "request", _network_forbidden)
    monkeypatch.setattr(httpx.Client, "request", _network_forbidden)
    try:
        service, capture = _graph(db, state)
        assert state["outside_sql"] == []
        state["single_projection"] = True
        state["inside_delegate"] = True
        try:
            injected_rows = service.project(_request())
        finally:
            state["inside_delegate"] = False
        assert injected_rows == default_rows
        assert lineage["program"] in _ids(injected_rows)
        assert (state["m11a1"], state["m11a2"], state["m11a3"]) == (1, 1, 1)
        assert capture.rows is capture.returned
        assert state["outside_sql"] == []
        assert db.execute(text("SHOW transaction_isolation")).scalar_one() == "repeatable read"
        assert db.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
        with pytest.raises(Exception):
            db.execute(text("CREATE TABLE m11a5a_forbidden_write (id integer)"))
        db.rollback()
    finally:
        event.remove(engine, "before_cursor_execute", observe)
        db.close()


def test_injected_a_b_a_c_membership_uses_one_snapshot_per_session():
    first, second = _settled(), _settled()
    _settled(product_id=first["product"], program_id=first["program"])
    request = _request(2)
    reader = _session()
    try:
        state = {"m11a1": 0, "m11a2": 0, "m11a3": 0, "inside_delegate": False, "outside_sql": []}
        service, _capture = _graph(reader, state)
        before = _ids(service.project(request))
        assert first["program"] in before and second["program"] not in before
        _settled(product_id=second["product"], program_id=second["program"])
        assert _ids(service.project(request)) == before
    finally:
        reader.close()

    fresh = _session()
    try:
        state = {"m11a1": 0, "m11a2": 0, "m11a3": 0, "inside_delegate": False, "outside_sql": []}
        service, _capture = _graph(fresh, state)
        assert _ids(service.project(request)) == before | {second["program"]}
    finally:
        fresh.close()
