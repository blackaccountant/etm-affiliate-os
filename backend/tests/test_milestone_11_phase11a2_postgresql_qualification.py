"""Guarded PostgreSQL qualification for M11A2 settled-lineage evidence measurement."""

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
from app.optimization.operating_profit_evidence_contracts import OperatingProfitEvidenceRequest
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_payout_settlement_link_service import AttributionPayoutSettlementLinkService
from app.services.attribution_publication_service import AttributionPublicationService
from app.services.operating_profit_evidence_service import OperatingProfitEvidenceService
from app.services.operating_profit_signal_service import OperatingProfitSignalService


ROLE, RAW = os.getenv("ETM_G5_M11A2_DB_ROLE"), os.getenv("ETM_G5_M11A2_DATABASE_URL")
if not RAW:
    pytest.skip("requires guarded ETM_G5_M11A2_DATABASE_URL", allow_module_level=True)
URL = make_url(RAW)
if ROLE != "qualification" or not URL.drivername.startswith("postgresql") or URL.host != "127.0.0.1" or URL.port != 5432 or URL.database != "etm_g5_m11a2_operating_profit_evidence_qualification":
    raise RuntimeError("M11A2 qualification database guard failed")


def _session():
    return sessionmaker(bind=create_engine(URL.render_as_string(hide_password=False)), expire_on_commit=False)()


def _settled(*, product_id=None, program_id=None):
    db, token = _session(), uuid4().hex
    try:
        product = db.get(Product, product_id) if product_id else Product(name=token, website=f"https://{token}.invalid", category="test", affiliate_program="test", commission_type="percentage", commission_value="10", affiliate_score=1, grade="A", confidence=1, summary="", recommendation="", status="active")
        if not product_id: db.add(product); db.flush()
        program = db.get(AffiliateProgram, program_id) if program_id else AffiliateProgram(product_id=product.id, program_name=token, commission_type="percentage", commission_value="10", status="active")
        if not program_id: db.add(program); db.flush()
        asset = AffiliateContentAsset(product_id=product.id, asset_type="article", title=token); db.add(asset); db.flush()
        queue = PublishingQueue(content_asset_id=asset.id, channel=token); db.add(queue); db.flush()
        publication = AttributionPublicationService(db).bind_legacy(queue.id)
        context = AttributionContextService(db).create(affiliate_program_id=program.id, attribution_publication_id=publication.id); db.commit()
        link = AttributionLinkBridgeService(db).create_bound_link(affiliate_program_id=program.id, attribution_context_id=context.id, name=token, destination_url="https://private.invalid", content_asset_id=asset.id)
        result = AttributionConversionBridgeService(db).record(affiliate_program_id=program.id, affiliate_link_id=link.id, external_conversion_id=token, customer_reference="private", sale_amount=Decimal("1000.00"), currency="USD", commission_rate=Decimal("10"), metadata_json=json.dumps({"private": token}))
        earning_link = AttributionEarningLinkService(db).reconcile(attribution_fact_id=result["fact"].id)
        earning, now = result["earning"], datetime.now(timezone.utc)
        payout = AffiliatePayout(affiliate_program_id=program.id, total_amount=earning.commission_amount, currency="USD", status="paid", paid_at=now, created_at=now, updated_at=now); db.add(payout); db.flush(); earning.payout_id, earning.status = payout.id, "paid"
        attempt = AffiliatePayoutAttempt(payout_id=payout.id, attempt_number=1, amount=payout.total_amount, currency="USD", status="completed", provider="manual", idempotency_key=token, started_at=now, completed_at=now, created_at=now, updated_at=now); db.add(attempt); db.commit()
        AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=earning_link.id)
        return {"earning": earning.id, "conversion": result["conversion"].id, "product": product.id, "program": program.id}
    finally: db.close()


def _owned(rows, identity):
    return next(row for row in rows if dict(row.dimensions).get("affiliate_program") == identity["program"])


def test_current_head_requires_no_m11a2_migration():
    db = _session()
    try: assert MigrationContext.configure(db.connection()).get_current_revision() == "c3d4e5f6a7b8"
    finally: db.close()


def test_measurement_is_distinct_snapshot_safe_and_signal_aligned(monkeypatch):
    first = _settled(); second = _settled(product_id=first["product"], program_id=first["program"])
    db, statements, calls = _session(), [], []
    engine = db.get_bind(); listener = lambda *args: statements.append(" ".join(args[2].upper().split())); event.listen(engine, "before_cursor_execute", listener)
    monkeypatch.setattr(requests.sessions.Session, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network called")))
    monkeypatch.setattr(httpx.Client, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network called")))
    try:
        service = OperatingProfitEvidenceService(db); real = service._signals.project; service._signals.project = lambda request: calls.append(request) or real(request)
        rows = service.project(OperatingProfitEvidenceRequest(("affiliate_program",), "USD")); row = _owned(rows, first)
        assert len(calls) == 1 and (row.settled_earning_count, row.settled_conversion_count, row.attribution_click_count, row.settlement_link_count) == (2, 2, 0, 2)
        assert row.first_settlement_observed_at.tzinfo is not None and row.first_settlement_observed_at <= row.latest_settlement_observed_at
        setup = [index for index, sql in enumerate(statements) if "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in sql]
        evidence_sql = [index for index, sql in enumerate(statements) if "ATTRIBUTION_PAYOUT_SETTLEMENT_LINKS" in sql]
        assert setup and evidence_sql and setup[0] < evidence_sql[-1]
        with pytest.raises(Exception): db.execute(text("INSERT INTO affiliate_cost_events (id,amount,currency,cost_type,allocation_scope,source_namespace,source_event_digest,fingerprint,created_at) VALUES (:id,1,'USD','x','global','x',:digest,:fingerprint,now())"), {"id":str(uuid4()), "digest":uuid4().hex*2, "fingerprint":"f"*64})
        db.rollback()
    finally: event.remove(engine, "before_cursor_execute", listener); db.close()


def test_a_b_a_c_snapshot_and_no_evidence_only_bucket():
    first = _settled(); request = OperatingProfitEvidenceRequest(("affiliate_program",), "USD")
    reader = _session()
    try:
        service = OperatingProfitEvidenceService(reader); before = _owned(service.project(request), first).settled_earning_count
        _settled(product_id=first["product"], program_id=first["program"])
        same = _owned(service.project(request), first).settled_earning_count
        assert (before, same) == (1, 1)
    finally: reader.close()
    fresh = _session()
    try:
        after = _owned(OperatingProfitEvidenceService(fresh).project(request), first).settled_earning_count
        assert after == 2
    finally: fresh.close()
