"""Guarded PostgreSQL qualification for M11A3 evidence eligibility."""

import json
import os
from datetime import datetime, timedelta, timezone
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
from app.optimization.operating_profit_evidence_eligibility_contracts import (
    REASONS,
    OperatingProfitEvidenceEligibilityPolicy,
    OperatingProfitEvidenceEligibilityRequest,
)
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_payout_settlement_link_service import AttributionPayoutSettlementLinkService
from app.services.attribution_publication_service import AttributionPublicationService
from app.services.operating_profit_evidence_eligibility_service import OperatingProfitEvidenceEligibilityService
from app.services.operating_profit_evidence_service import OperatingProfitEvidenceService


ROLE = os.getenv("ETM_G5_M11A3_DB_ROLE")
RAW = os.getenv("ETM_G5_M11A3_DATABASE_URL")
if not RAW:
    pytest.skip("requires guarded M11A3 URL", allow_module_level=True)
URL = make_url(RAW)
if (
    ROLE != "qualification"
    or not URL.drivername.startswith("postgresql")
    or URL.host != "127.0.0.1"
    or URL.port != 5432
    or URL.database != "etm_g5_m11a3_operating_profit_evidence_eligibility_qualification"
):
    raise RuntimeError("M11A3 database guard failed")


def _session():
    return sessionmaker(bind=create_engine(URL.render_as_string(hide_password=False)), expire_on_commit=False)()


def _settled(*, product_id=None, program_id=None, currency="USD"):
    db, token = _session(), uuid4().hex
    try:
        product = db.get(Product, product_id) if product_id else Product(name=token, website=f"https://{token}.invalid", category="test", affiliate_program="test", commission_type="percentage", commission_value="10", affiliate_score=1, grade="A", confidence=1, summary="", recommendation="", status="active")
        if not product_id:
            db.add(product); db.flush()
        program = db.get(AffiliateProgram, program_id) if program_id else AffiliateProgram(product_id=product.id, program_name=token, commission_type="percentage", commission_value="10", status="active")
        if not program_id:
            db.add(program); db.flush()
        asset = AffiliateContentAsset(product_id=product.id, asset_type="article", title=token); db.add(asset); db.flush()
        queue = PublishingQueue(content_asset_id=asset.id, channel=token); db.add(queue); db.flush()
        publication = AttributionPublicationService(db).bind_legacy(queue.id)
        context = AttributionContextService(db).create(affiliate_program_id=program.id, attribution_publication_id=publication.id); db.commit()
        link = AttributionLinkBridgeService(db).create_bound_link(affiliate_program_id=program.id, attribution_context_id=context.id, name=token, destination_url="https://private.invalid", content_asset_id=asset.id)
        result = AttributionConversionBridgeService(db).record(affiliate_program_id=program.id, affiliate_link_id=link.id, external_conversion_id=token, customer_reference="private", sale_amount=Decimal("1000.00"), currency=currency, commission_rate=Decimal("10"), metadata_json=json.dumps({"private": token}))
        earning_link = AttributionEarningLinkService(db).reconcile(attribution_fact_id=result["fact"].id)
        earning, now = result["earning"], datetime.now(timezone.utc)
        payout = AffiliatePayout(affiliate_program_id=program.id, total_amount=earning.commission_amount, currency=currency, status="paid", paid_at=now, created_at=now, updated_at=now); db.add(payout); db.flush(); earning.payout_id, earning.status = payout.id, "paid"
        attempt = AffiliatePayoutAttempt(payout_id=payout.id, attempt_number=1, amount=payout.total_amount, currency=currency, status="completed", provider="manual", idempotency_key=token, started_at=now, completed_at=now, created_at=now, updated_at=now); db.add(attempt); db.commit()
        AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=earning_link.id)
        return {"product": product.id, "program": program.id}
    finally:
        db.close()


def _request(*, currency="USD", policy=None, evaluated_at=None):
    return OperatingProfitEvidenceEligibilityRequest(dimensions=("affiliate_program",), currency=currency, policy=policy or OperatingProfitEvidenceEligibilityPolicy("m11a3", 1, 1, 1), evaluated_at=evaluated_at or datetime(2100, 1, 1, tzinfo=timezone.utc))


def _owned(rows, identity):
    return next(row for row in rows if dict(row.dimensions).get("affiliate_program") == identity["program"])


def test_current_head_requires_no_m11a3_migration():
    db = _session()
    try:
        assert MigrationContext.configure(db.connection()).get_current_revision() == "c3d4e5f6a7b8"
    finally:
        db.close()


def test_real_assessment_composes_evidence_once_and_adds_no_sql(monkeypatch):
    first = _settled()
    db, calls, post_upstream_sql = _session(), [], []
    engine, inside_upstream = db.get_bind(), [False]

    def record_sql(*args):
        if not inside_upstream[0]:
            post_upstream_sql.append(" ".join(args[2].upper().split()))

    event.listen(engine, "before_cursor_execute", record_sql)
    monkeypatch.setattr(requests.sessions.Session, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network called")))
    monkeypatch.setattr(httpx.Client, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network called")))
    try:
        service = OperatingProfitEvidenceEligibilityService(db)
        real = service._evidence.project

        def wrapped(request):
            calls.append(request); inside_upstream[0] = True
            try:
                return real(request)
            finally:
                inside_upstream[0] = False

        monkeypatch.setattr(service._evidence, "project", wrapped)
        row = _owned(service.project(_request()), first)
        assert len(calls) == 1 and row.eligible is True and row.reason_codes == ()
        assert post_upstream_sql == []
        statements = []
        event.remove(engine, "before_cursor_execute", record_sql)

        def all_sql(*args):
            statements.append(" ".join(args[2].upper().split()))

        event.listen(engine, "before_cursor_execute", all_sql)
        _owned(service.project(_request()), first)
        setup = [i for i, sql in enumerate(statements) if "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in sql]
        evidence = [i for i, sql in enumerate(statements) if "ATTRIBUTION_PAYOUT_SETTLEMENT_LINKS" in sql]
        assert setup and evidence and setup[0] < evidence[-1]
        with pytest.raises(Exception):
            db.execute(text("CREATE TABLE m11a3_forbidden_write (id integer)"))
        db.rollback()
    finally:
        if event.contains(engine, "before_cursor_execute", record_sql): event.remove(engine, "before_cursor_execute", record_sql)
        if event.contains(engine, "before_cursor_execute", all_sql): event.remove(engine, "before_cursor_execute", all_sql)
        db.close()


def test_policy_threshold_freshness_and_currency_behavior():
    usd, eur = _settled(currency="USD"), _settled(currency="EUR")
    db = _session()
    try:
        service = OperatingProfitEvidenceEligibilityService(db)
        usd_row = _owned(service.project(_request(currency="USD")), usd)
        assert {row.currency for row in service.project(_request(currency="USD"))} == {"USD"}
        assert usd_row.eligible is True
        strict = _owned(service.project(_request(policy=OperatingProfitEvidenceEligibilityPolicy("strict", 2, 1, 1))), usd)
        assert strict.eligible is False and strict.reason_codes == (REASONS[0],)
        evidence = _owned(OperatingProfitEvidenceService(db).project(OperatingProfitEvidenceRequest(("affiliate_program",), "USD")), usd)
        equal = _owned(service.project(_request(policy=OperatingProfitEvidenceEligibilityPolicy("fresh", 1, 1, 1, maximum_settlement_observation_age=timedelta()), evaluated_at=evidence.latest_settlement_observed_at)), usd)
        stale = _owned(service.project(_request(policy=OperatingProfitEvidenceEligibilityPolicy("stale", 1, 1, 1, maximum_settlement_observation_age=timedelta()), evaluated_at=evidence.latest_settlement_observed_at + timedelta(microseconds=1))), usd)
        assert equal.eligible is True and REASONS[3] not in equal.reason_codes
        assert stale.reason_codes == (REASONS[4],)
    finally:
        db.close()
    eur_db = _session()
    try:
        assert {row.currency for row in OperatingProfitEvidenceEligibilityService(eur_db).project(_request(currency="EUR"))} == {"EUR"}
    finally:
        eur_db.close()


def test_a_b_a_c_snapshot_behavior_is_inherited():
    first = _settled()
    request = _request(policy=OperatingProfitEvidenceEligibilityPolicy("two", 2, 1, 1))
    reader = _session()
    try:
        service = OperatingProfitEvidenceEligibilityService(reader)
        before = _owned(service.project(request), first).eligible
        _settled(product_id=first["product"], program_id=first["program"])
        same = _owned(service.project(request), first).eligible
        assert (before, same) == (False, False)
    finally:
        reader.close()
    fresh = _session()
    try:
        row = _owned(OperatingProfitEvidenceEligibilityService(fresh).project(request), first)
        assert row.eligible is True and row.reason_codes == ()
    finally:
        fresh.close()
