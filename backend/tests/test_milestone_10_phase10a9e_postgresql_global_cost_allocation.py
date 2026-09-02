"""Guarded PostgreSQL qualification for immutable M10A9E global-cost allocation authority."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import httpx
import pytest
import requests
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.affiliate_financial.global_cost_allocation_contracts import RecordGlobalCostAllocationRequest, GlobalCostAllocationLineRequest
from app.affiliate_financial.cost_event_contracts import RecordAffiliateCostEventRequest
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_cost_event import AffiliateCostEvent
from app.models.affiliate_global_cost_allocation import AffiliateGlobalCostAllocationBatch, AffiliateGlobalCostAllocationLine
from app.models.affiliate_program import AffiliateProgram
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.attribution import AttributionContext
from app.models.content_brief import ContentBrief
from app.models.content_generation_run import ContentGenerationRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun
from app.models.product import Product
from app.models.publishing_queue import PublishingQueue
from app.services.affiliate_cost_event_service import AffiliateCostEventService
from app.services.affiliate_global_cost_allocation_service import AffiliateGlobalCostAllocationConflict, AffiliateGlobalCostAllocationService
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_payout_settlement_link_service import AttributionPayoutSettlementLinkService
from app.services.attribution_publication_service import AttributionPublicationService


ROLE, raw = os.getenv("ETM_G5_M10A9E_DB_ROLE"), os.getenv("ETM_G5_DATABASE_URL")
if not raw:
    pytest.skip("requires guarded ETM_G5_DATABASE_URL", allow_module_level=True)
url = make_url(raw)
if ROLE != "qualification" or not (url.drivername.startswith("postgresql") and url.host == "127.0.0.1" and url.port == 5432 and url.database == "etm_g5_m10a9e_global_cost_allocation_qualification"):
    raise RuntimeError("M10A9E qualification database guard failed")


def _session():
    return sessionmaker(bind=create_engine(url.render_as_string(hide_password=False)), expire_on_commit=False)()


def _settled(*, currency="USD", create_settlement=True, product_id=None, program_id=None):
    db, token = _session(), uuid4().hex
    try:
        product = db.get(Product, product_id) if product_id is not None else Product(name=token, website=f"https://{token}.invalid", category="test", affiliate_program="test", commission_type="percentage", commission_value="10", affiliate_score=1, grade="A", confidence=1, summary="", recommendation="", status="active")
        if product_id is None: db.add(product); db.flush()
        program = db.get(AffiliateProgram, program_id) if program_id is not None else AffiliateProgram(product_id=product.id, program_name=token, commission_type="percentage", commission_value="10", status="active")
        if program_id is None: db.add(program); db.flush()
        asset = AffiliateContentAsset(product_id=product.id, asset_type="article", title=token); db.add(asset); db.flush()
        queue = PublishingQueue(content_asset_id=asset.id, channel=token); db.add(queue); db.flush()
        publication = AttributionPublicationService(db).bind_legacy(queue.id)
        context = AttributionContextService(db).create(affiliate_program_id=program.id, attribution_publication_id=publication.id)
        db.commit()
        link = AttributionLinkBridgeService(db).create_bound_link(affiliate_program_id=program.id, attribution_context_id=context.id, name=token, destination_url="https://private.invalid", content_asset_id=asset.id)
        result = AttributionConversionBridgeService(db).record(affiliate_program_id=program.id, affiliate_link_id=link.id, external_conversion_id=token, customer_reference="private", sale_amount=Decimal("1000.00"), currency=currency, commission_rate=Decimal("10"), metadata_json=json.dumps({"private": token}))
        earning_link = AttributionEarningLinkService(db).reconcile(attribution_fact_id=result["fact"].id)
        earning, now = result["earning"], datetime.now(timezone.utc)
        payout = AffiliatePayout(affiliate_program_id=program.id, total_amount=earning.commission_amount, currency=currency, status="paid", paid_at=now, created_at=now, updated_at=now); db.add(payout); db.flush()
        earning.payout_id, earning.status = payout.id, "paid"
        attempt = AffiliatePayoutAttempt(payout_id=payout.id, attempt_number=1, amount=payout.total_amount, currency=currency, status="completed", provider="manual", idempotency_key=token, started_at=now, completed_at=now, created_at=now, updated_at=now); db.add(attempt); db.commit()
        settlement = AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=earning_link.id) if create_settlement else None
        return dict(product=product.id, program=program.id, earning=earning.id, currency=currency, settlement=settlement.id if settlement else None)
    finally:
        db.close()


def _generation_run():
    db, token, now = _session(), uuid4().hex, datetime.now(timezone.utc)
    try:
        discovery = DiscoveryRun(id=token+"d", input_type="URL", input_value=f"https://{token}.invalid", status="COMPLETED", idempotency_key=token+"d", candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now); db.add(discovery); db.flush()
        candidate = DiscoveryCandidate(id=token+"c", run_id=discovery.id, source_adapter="test", source_type="test", canonical_domain=f"{token}.invalid", program_identity_key=token, dedupe_key=token, commission_model="UNKNOWN", verification_status="VERIFIED", disposition="SELECTED", created_at=now, updated_at=now); db.add(candidate); db.flush()
        brief = ContentBrief(id=token+"b", discovery_run_id=discovery.id, discovery_candidate_id=candidate.id, content_type="ARTICLE", channel_intent="SEO", objective="proof", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key=token+"b", status="READY", created_at=now, updated_at=now); db.add(brief); db.flush()
        generation = ContentGenerationRun(id=token+"g", content_brief_id=brief.id, idempotency_key=token+"g", provider="test", model="test", prompt_version="v1", generation_parameters={}, status="COMPLETED", attempt_count=1, created_at=now, updated_at=now); db.add(generation); db.commit()
        return generation.id
    finally:
        db.close()


def _cost(scope, amount, *, currency="USD", **correlations):
    db = _session()
    try:
        return AffiliateCostEventService(db).record(RecordAffiliateCostEventRequest(amount=amount, currency=currency, cost_type="provider_fee", allocation_scope=scope, source_namespace="m10a9e.cost", source_event_key=uuid4().hex, **correlations))
    finally:
        db.close()


def _request(cost_id, lines, *, source=None):
    return RecordGlobalCostAllocationRequest(cost_id, tuple(GlobalCostAllocationLineRequest(earning, amount) for earning, amount in lines), "explicit-v1", "m10a9e.allocation", source or uuid4().hex)


def _snapshot(db, cost_id):
    cost = db.get(AffiliateCostEvent, cost_id)
    return cost.id, cost.amount, cost.currency, cost.allocation_scope, cost.fingerprint


def test_database_head_schema_constraints_indexes_and_triggers():
    db = _session()
    try:
        assert MigrationContext.configure(db.connection()).get_current_revision() == "c3d4e5f6a7b8"
        schema = inspect(db.get_bind())
        assert {"affiliate_global_cost_allocation_batches", "affiliate_global_cost_allocation_lines"}.issubset(schema.get_table_names())
        assert ("affiliate_cost_event_id",) in {tuple(item["column_names"]) for item in schema.get_unique_constraints("affiliate_global_cost_allocation_batches")}
        assert ("allocation_batch_id", "affiliate_earning_id") in {tuple(item["column_names"]) for item in schema.get_unique_constraints("affiliate_global_cost_allocation_lines")}
        assert "ix_affiliate_global_cost_allocation_lines_earning" in {item["name"] for item in schema.get_indexes("affiliate_global_cost_allocation_lines")}
        triggers = {row[0] for row in db.execute(text("SELECT tgname FROM pg_trigger WHERE tgrelid IN ('affiliate_global_cost_allocation_batches'::regclass, 'affiliate_global_cost_allocation_lines'::regclass) AND NOT tgisinternal"))}
        assert {"trg_m10a9e_global_allocation_batch_immutable", "trg_m10a9e_global_allocation_line_immutable"}.issubset(triggers)
    finally:
        db.close()


def test_explicit_balanced_global_allocation_scope_currency_and_target_boundaries():
    first = _settled(); second = _settled(product_id=first["product"], program_id=first["program"]); unsettled = _settled(create_settlement=False); eur = _settled(currency="EUR")
    global_cost = _cost("global", Decimal("30.00")); direct = _cost("direct", Decimal("10.00"), affiliate_earning_id=first["earning"]); shared = _cost("shared", Decimal("10.00"))
    db = _session()
    try:
        record = AffiliateGlobalCostAllocationService(db).record(_request(global_cost.id, ((first["earning"], Decimal("10.00")), (second["earning"], Decimal("20.00")))))
        assert record.allocated_amount == Decimal("30.00") and record.currency == "USD"
        assert tuple((line.affiliate_earning_id, line.amount) for line in record.allocations) == ((first["earning"], Decimal("10.00")), (second["earning"], Decimal("20.00")))
    finally: db.close()
    invalid = (
        _request(direct.id, ((first["earning"], Decimal("10.00")),)),
        _request(shared.id, ((first["earning"], Decimal("10.00")),)),
        _request(_cost("global", Decimal("10.00")).id, ((unsettled["earning"], Decimal("10.00")),)),
        _request(_cost("global", Decimal("10.00")).id, ((eur["earning"], Decimal("10.00")),)),
        _request(_cost("global", Decimal("10.00")).id, ((first["earning"], Decimal("9.99")),)),
        _request(_cost("global", Decimal("10.00")).id, ((first["earning"], Decimal("5.00")), (first["earning"], Decimal("5.00")))),
        _request(_cost("global", Decimal("10.00")).id, ()),
    )
    for request in invalid:
        db = _session()
        try:
            with pytest.raises(ValueError): AffiliateGlobalCostAllocationService(db).record(request)
            assert not db.in_transaction()
        finally: db.close()


def test_replay_conflicts_operational_non_inference_and_no_network(monkeypatch):
    first, second = _settled(), _settled(); source = uuid4().hex; generation = _generation_run()
    cost = _cost("global", Decimal("10.00"), content_generation_run_id=generation)
    calls = {"requests": 0, "httpx": 0, "async": 0}
    monkeypatch.setattr(requests.sessions.Session, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("requests called")))
    monkeypatch.setattr(httpx.Client, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("httpx called")))
    monkeypatch.setattr(httpx.AsyncClient, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("httpx async called")))
    request = _request(cost.id, ((second["earning"], Decimal("10.00")),), source=source)
    db = _session()
    try:
        record = AffiliateGlobalCostAllocationService(db).record(request)
        assert record.allocations[0].affiliate_earning_id == second["earning"]
    finally: db.close()
    db = _session()
    try:
        assert AffiliateGlobalCostAllocationService(db).record(request) == record
        with pytest.raises(AffiliateGlobalCostAllocationConflict): AffiliateGlobalCostAllocationService(db).record(_request(cost.id, ((first["earning"], Decimal("10.00")),), source=source))
    finally: db.close()
    db = _session()
    try:
        with pytest.raises(AffiliateGlobalCostAllocationConflict): AffiliateGlobalCostAllocationService(db).record(_request(cost.id, ((second["earning"], Decimal("10.00")),)))
    finally: db.close()
    assert calls == {"requests": 0, "httpx": 0, "async": 0}


def test_batches_and_lines_are_immutable_and_original_cost_is_unchanged():
    earning = _settled(); cost = _cost("global", Decimal("7.00"))
    db = _session()
    try:
        record = AffiliateGlobalCostAllocationService(db).record(_request(cost.id, ((earning["earning"], Decimal("7.00")),)))
    finally: db.close()
    verify = _session()
    try:
        original = _snapshot(verify, cost.id)
        batch = verify.get(AffiliateGlobalCostAllocationBatch, record.id); line = verify.query(AffiliateGlobalCostAllocationLine).filter_by(allocation_batch_id=batch.id).one()
        authority = (batch.id, batch.allocated_amount, batch.fingerprint, line.id, line.amount, line.fingerprint)
        for statement, authority_id in (("UPDATE affiliate_global_cost_allocation_batches SET allocated_amount=8 WHERE id=:id", batch.id), ("DELETE FROM affiliate_global_cost_allocation_batches WHERE id=:id", batch.id), ("UPDATE affiliate_global_cost_allocation_lines SET amount=8 WHERE id=:id", line.id), ("DELETE FROM affiliate_global_cost_allocation_lines WHERE id=:id", line.id)):
            with pytest.raises(Exception) as rejected: verify.execute(text(statement), {"id": authority_id})
            assert "immutable" in str(rejected.value).lower(); verify.rollback()
        batch = verify.get(AffiliateGlobalCostAllocationBatch, record.id); line = verify.query(AffiliateGlobalCostAllocationLine).filter_by(allocation_batch_id=batch.id).one()
        assert (batch.id, batch.allocated_amount, batch.fingerprint, line.id, line.amount, line.fingerprint) == authority
        assert _snapshot(verify, cost.id) == original
    finally: verify.close()


def test_concurrent_same_cost_is_single_authority_or_conflict_and_persistent_safe():
    first, second = _settled(), _settled(); cost = _cost("global", Decimal("20.00")); barrier = Barrier(2)
    requests_ = (_request(cost.id, ((first["earning"], Decimal("20.00")),)), _request(cost.id, ((second["earning"], Decimal("20.00")),)))
    def allocate(request):
        db = _session()
        try:
            barrier.wait()
            try: return "ok", AffiliateGlobalCostAllocationService(db).record(request).id
            except AffiliateGlobalCostAllocationConflict: return "conflict", None
        finally: db.close()
    with ThreadPoolExecutor(max_workers=2) as pool: outcomes = list(pool.map(allocate, requests_))
    assert sorted(value[0] for value in outcomes) == ["conflict", "ok"]
    db = _session()
    try:
        batch = db.query(AffiliateGlobalCostAllocationBatch).filter_by(affiliate_cost_event_id=cost.id).one()
        assert db.query(AffiliateGlobalCostAllocationLine).filter_by(allocation_batch_id=batch.id).count() == 1
    finally: db.close()
    replay_cost = _cost("global", Decimal("6.00")); source = uuid4().hex; request = _request(replay_cost.id, ((first["earning"], Decimal("6.00")),), source=source); replay_barrier = Barrier(2)
    def replay():
        db = _session()
        try:
            replay_barrier.wait(); return AffiliateGlobalCostAllocationService(db).record(request).id
        finally: db.close()
    with ThreadPoolExecutor(max_workers=2) as pool: ids = list(pool.map(lambda _: replay(), range(2)))
    assert ids[0] == ids[1]
