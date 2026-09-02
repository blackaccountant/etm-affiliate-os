"""Guarded PostgreSQL qualification for the read-only M10A9D allocated-profit projection."""
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
import requests
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.affiliate_financial.cost_allocation_contracts import RecordSharedCostAllocationRequest, SharedCostAllocationLineRequest
from app.affiliate_financial.cost_event_contracts import RecordAffiliateCostEventRequest
from app.attribution.allocated_contribution_profit_projection_contracts import AllocatedContributionProfitProjectionRequest
from app.attribution.contribution_profit_projection_contracts import ContributionProfitProjectionRequest
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_cost_allocation import AffiliateCostAllocationBatch, AffiliateCostAllocationLine
from app.models.affiliate_cost_event import AffiliateCostEvent
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.affiliate_program import AffiliateProgram
from app.models.attribution import AttributionPublication
from app.models.product import Product
from app.models.publishing_queue import PublishingQueue
from app.services.affiliate_cost_allocation_service import AffiliateCostAllocationService
from app.services.affiliate_cost_event_service import AffiliateCostEventService
from app.services.affiliate_financial_adjustment_service import AffiliateFinancialAdjustmentService
from app.services.attribution_allocated_contribution_profit_projection_service import AttributionAllocatedContributionProfitProjectionService
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_contribution_profit_projection_service import AttributionContributionProfitProjectionService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_payout_settlement_link_service import AttributionPayoutSettlementLinkService
from app.services.attribution_publication_service import AttributionPublicationService


ROLE, raw = os.getenv("ETM_G5_M10A9D_DB_ROLE"), os.getenv("ETM_G5_DATABASE_URL")
if not raw:
    pytest.skip("requires guarded ETM_G5_DATABASE_URL", allow_module_level=True)
url = make_url(raw)
if ROLE != "qualification" or not (
    url.drivername.startswith("postgresql") and url.host == "127.0.0.1" and url.port == 5432
    and url.database == "etm_g5_m10a9d_allocated_contribution_profit_qualification"
):
    raise RuntimeError("M10A9D qualification database guard failed")


def _session():
    return sessionmaker(bind=create_engine(url.render_as_string(hide_password=False)), expire_on_commit=False)()


def _settled(*, currency="USD", product_id=None, program_id=None):
    db, token = _session(), uuid4().hex
    try:
        product = db.get(Product, product_id) if product_id is not None else Product(
            name=token, website=f"https://{token}.invalid", category="test", affiliate_program="test",
            commission_type="percentage", commission_value="10", affiliate_score=1, grade="A",
            confidence=1, summary="", recommendation="", status="active",
        )
        if product_id is None:
            db.add(product); db.flush()
        program = db.get(AffiliateProgram, program_id) if program_id is not None else AffiliateProgram(
            product_id=product.id, program_name=token, commission_type="percentage", commission_value="10", status="active",
        )
        if program_id is None:
            db.add(program); db.flush()
        asset = AffiliateContentAsset(product_id=product.id, asset_type="article", title=token); db.add(asset); db.flush()
        queue = PublishingQueue(content_asset_id=asset.id, channel=token); db.add(queue); db.flush()
        publication = AttributionPublicationService(db).bind_legacy(queue.id)
        context = AttributionContextService(db).create(affiliate_program_id=program.id, attribution_publication_id=publication.id)
        db.commit()
        link = AttributionLinkBridgeService(db).create_bound_link(
            affiliate_program_id=program.id, attribution_context_id=context.id, name=token,
            destination_url="https://private.invalid", content_asset_id=asset.id,
        )
        result = AttributionConversionBridgeService(db).record(
            affiliate_program_id=program.id, affiliate_link_id=link.id, external_conversion_id=token,
            customer_reference="private", sale_amount=Decimal("1000.00"), currency=currency,
            commission_rate=Decimal("10"), metadata_json=json.dumps({"private": token}),
        )
        earning_link = AttributionEarningLinkService(db).reconcile(attribution_fact_id=result["fact"].id)
        earning, now = result["earning"], datetime.now(timezone.utc)
        payout = AffiliatePayout(
            affiliate_program_id=program.id, total_amount=earning.commission_amount, currency=currency,
            status="paid", paid_at=now, created_at=now, updated_at=now,
        ); db.add(payout); db.flush()
        earning.payout_id, earning.status = payout.id, "paid"
        attempt = AffiliatePayoutAttempt(
            payout_id=payout.id, attempt_number=1, amount=payout.total_amount, currency=currency,
            status="completed", provider="manual", idempotency_key=token, started_at=now,
            completed_at=now, created_at=now, updated_at=now,
        ); db.add(attempt); db.commit()
        settlement = AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=earning_link.id)
        return dict(
            product=product.id, program=program.id, asset=asset.id, publication=publication.id,
            distribution=publication.distribution_run_id, link=link.id, conversion=result["conversion"].id,
            earning=earning.id, payout=payout.id, attempt=attempt.id, settlement=settlement.id, currency=currency,
        )
    finally:
        db.close()


def _cost(identity, amount, scope, *, source=None, **overrides):
    db = _session()
    try:
        values = dict(
            amount=amount, currency=identity["currency"], cost_type="provider_fee", allocation_scope=scope,
            source_namespace="m10a9d.cost", source_event_key=source or uuid4().hex,
        )
        values.update(overrides)
        return AffiliateCostEventService(db).record(RecordAffiliateCostEventRequest(**values))
    finally:
        db.close()


def _direct(identity, amount):
    return _cost(
        identity, amount, "direct", affiliate_earning_id=identity["earning"],
        affiliate_conversion_id=identity["conversion"],
    )


def _allocate(cost, lines, *, source=None):
    db = _session()
    try:
        request = RecordSharedCostAllocationRequest(
            cost.id,
            tuple(SharedCostAllocationLineRequest(identity["earning"], amount) for identity, amount in lines),
            "explicit-v1", "m10a9d.allocation", source or uuid4().hex,
        )
        return AffiliateCostAllocationService(db).record(request)
    finally:
        db.close()


def _owned(rows, identity):
    return next(row for row in rows if dict(row.dimensions).get("earning") == identity["earning"])


def test_database_head_and_finalized_allocation_read_surface():
    db = _session()
    try:
        assert MigrationContext.configure(db.connection()).get_current_revision() == "b1c2d3e4f5a6"
        schema = inspect(db.get_bind())
        assert {"affiliate_cost_allocation_batches", "affiliate_cost_allocation_lines"}.issubset(schema.get_table_names())
        assert "status" not in {column["name"] for column in schema.get_columns("affiliate_cost_allocation_batches")}
        assert "status" not in {column["name"] for column in schema.get_columns("affiliate_cost_allocation_lines")}
    finally:
        db.close()


def test_arithmetic_replay_grouping_privacy_and_frozen_composition(monkeypatch):
    first = _settled(); second = _settled(product_id=first["product"], program_id=first["program"])
    direct_first, direct_second = _direct(first, Decimal("20.00")), _direct(second, Decimal("5.00"))
    shared = _cost(first, Decimal("30.00"), "shared", product_id=first["product"], affiliate_program_id=first["program"])
    source = uuid4().hex
    allocation = _allocate(shared, ((first, Decimal("10.00")), (second, Decimal("20.00"))), source=source)
    replay = _allocate(shared, ((second, Decimal("20.00")), (first, Decimal("10.00"))), source=source)
    unallocated = _cost(first, Decimal("77.00"), "shared")
    global_cost = _cost(first, Decimal("66.00"), "global")
    assert replay == allocation and unallocated.id and global_cost.id

    before = _session()
    try:
        authority = (
            tuple(before.query(AffiliateCostEvent.id, AffiliateCostEvent.amount, AffiliateCostEvent.fingerprint).filter(
                AffiliateCostEvent.id.in_((direct_first.id, direct_second.id, shared.id, unallocated.id, global_cost.id))
            ).order_by(AffiliateCostEvent.id).all()),
            tuple(before.query(AffiliateCostAllocationBatch.id, AffiliateCostAllocationBatch.fingerprint).filter_by(id=allocation.id).all()),
            tuple(before.query(AffiliateCostAllocationLine.affiliate_earning_id, AffiliateCostAllocationLine.amount).filter_by(allocation_batch_id=allocation.id).order_by(AffiliateCostAllocationLine.affiliate_earning_id).all()),
        )
    finally:
        before.close()

    calls = {"m10a9b": 0, "requests": 0, "httpx": 0, "async": 0}
    real_project = AttributionContributionProfitProjectionService.project
    def counted(service, request): calls["m10a9b"] += 1; return real_project(service, request)
    def no_requests(*args, **kwargs): calls["requests"] += 1; raise AssertionError("network called")
    def no_httpx(*args, **kwargs): calls["httpx"] += 1; raise AssertionError("network called")
    def no_async(*args, **kwargs): calls["async"] += 1; raise AssertionError("network called")
    monkeypatch.setattr(AttributionContributionProfitProjectionService, "project", counted)
    monkeypatch.setattr(requests.sessions.Session, "request", no_requests)
    monkeypatch.setattr(httpx.Client, "request", no_httpx)
    monkeypatch.setattr(httpx.AsyncClient, "request", no_async)
    db = _session()
    try:
        service = AttributionAllocatedContributionProfitProjectionService(db)
        rows = service.project(AllocatedContributionProfitProjectionRequest(("earning",)))
        first_row, second_row = _owned(rows, first), _owned(rows, second)
        grouped = service.project(AllocatedContributionProfitProjectionRequest(("affiliate_program",)))
        assert (first_row.net_realized_commission, first_row.directly_attributable_cost, first_row.contribution_profit, first_row.allocated_shared_cost, first_row.allocated_contribution_profit) == (
            Decimal("100.00"), Decimal("20.00"), Decimal("80.00"), Decimal("10.00"), Decimal("70.00"),
        )
        assert (second_row.contribution_profit, second_row.allocated_shared_cost, second_row.allocated_contribution_profit) == (
            Decimal("95.00"), Decimal("20.00"), Decimal("75.00"),
        )
        owned_group = next(row for row in grouped if dict(row.dimensions).get("affiliate_program") == first["program"])
        assert (owned_group.contribution_profit, owned_group.allocated_shared_cost, owned_group.allocated_contribution_profit) == (
            Decimal("175.00"), Decimal("30.00"), Decimal("145.00"),
        )
        assert calls == {"m10a9b": 1, "requests": 0, "httpx": 0, "async": 0}
        payload = json.dumps([asdict(row) for row in rows], default=str)
        assert all(secret not in payload for secret in (shared.id, allocation.id, "m10a9d.cost", "m10a9d.allocation", "private"))
        assert set(asdict(first_row)) == {
            "currency", "net_realized_commission", "directly_attributable_cost", "contribution_profit",
            "allocated_shared_cost", "allocated_contribution_profit", "dimensions", "semantics",
        }
    finally:
        db.close()

    after = _session()
    try:
        same = (
            tuple(after.query(AffiliateCostEvent.id, AffiliateCostEvent.amount, AffiliateCostEvent.fingerprint).filter(
                AffiliateCostEvent.id.in_((direct_first.id, direct_second.id, shared.id, unallocated.id, global_cost.id))
            ).order_by(AffiliateCostEvent.id).all()),
            tuple(after.query(AffiliateCostAllocationBatch.id, AffiliateCostAllocationBatch.fingerprint).filter_by(id=allocation.id).all()),
            tuple(after.query(AffiliateCostAllocationLine.affiliate_earning_id, AffiliateCostAllocationLine.amount).filter_by(allocation_batch_id=allocation.id).order_by(AffiliateCostAllocationLine.affiliate_earning_id).all()),
        )
        assert same == authority
    finally:
        after.close()


def test_currency_negative_zero_and_zero_revenue_semantics():
    negative = _settled(); _direct(negative, Decimal("120.00")); _allocate(_cost(negative, Decimal("30.00"), "shared"), ((negative, Decimal("30.00")),))
    zero = _settled(); _direct(zero, Decimal("70.00")); _allocate(_cost(zero, Decimal("30.00"), "shared"), ((zero, Decimal("30.00")),))
    zero_revenue = _settled()
    adjustment_db = _session()
    try:
        AffiliateFinancialAdjustmentService(adjustment_db).reconcile(
            earning_id=zero_revenue["earning"], program_id=zero_revenue["program"],
            conversion_id=zero_revenue["conversion"], settlement_link_id=zero_revenue["settlement"],
            adjustment_type="REVERSAL", adjustment_amount=Decimal("-100.00"), currency="USD",
            effective_at=datetime.now(timezone.utc), source_namespace="m10a9d.test",
            source_event_digest=uuid4().hex * 2,
        )
    finally:
        adjustment_db.close()
    _allocate(_cost(zero_revenue, Decimal("20.00"), "shared"), ((zero_revenue, Decimal("20.00")),))
    eur = _settled(currency="EUR"); _allocate(_cost(eur, Decimal("20.00"), "shared"), ((eur, Decimal("20.00")),))
    db = _session()
    try:
        rows = AttributionAllocatedContributionProfitProjectionService(db).project(AllocatedContributionProfitProjectionRequest(("earning",)))
        assert _owned(rows, negative).allocated_contribution_profit == Decimal("-50.00")
        assert _owned(rows, zero).allocated_contribution_profit == Decimal("0.00")
        assert (_owned(rows, zero_revenue).net_realized_commission, _owned(rows, zero_revenue).allocated_contribution_profit) == (Decimal("0.00"), Decimal("-20.00"))
        assert (_owned(rows, eur).currency, _owned(rows, eur).allocated_contribution_profit) == ("EUR", Decimal("80.00"))
    finally:
        db.close()
    usd_db = _session()
    try:
        usd = AttributionAllocatedContributionProfitProjectionService(usd_db).project(AllocatedContributionProfitProjectionRequest(("earning",), "USD"))
        assert all(row.currency == "USD" for row in usd) and all(dict(row.dimensions)["earning"] != eur["earning"] for row in usd)
    finally:
        usd_db.close()


def test_first_sql_single_composition_read_only_and_snapshot_concurrency(monkeypatch):
    identity = _settled(); _allocate(_cost(identity, Decimal("20.00"), "shared"), ((identity, Decimal("20.00")),))
    calls, statements = {"m10a9b": 0}, []
    real_project = AttributionContributionProfitProjectionService.project
    def counted(service, request): calls["m10a9b"] += 1; return real_project(service, request)
    monkeypatch.setattr(AttributionContributionProfitProjectionService, "project", counted)
    reader = _session(); engine = reader.get_bind()
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(" ".join(statement.upper().split()))
    event.listen(engine, "before_cursor_execute", capture)
    try:
        service = AttributionAllocatedContributionProfitProjectionService(reader)
        first = _owned(service.project(AllocatedContributionProfitProjectionRequest(("earning",))), identity)
        assert first.allocated_contribution_profit == Decimal("80.00")
        _allocate(_cost(identity, Decimal("10.00"), "shared"), ((identity, Decimal("10.00")),))
        again = _owned(service.project(AllocatedContributionProfitProjectionRequest(("earning",))), identity)
        assert again.allocated_contribution_profit == Decimal("80.00") and calls["m10a9b"] == 1
        setup = [i for i, sql in enumerate(statements) if "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in sql]
        allocation_reads = [i for i, sql in enumerate(statements) if "AFFILIATE_COST_ALLOCATION_LINES" in sql]
        assert len(setup) == 1 and allocation_reads and setup[0] < allocation_reads[0]
        with pytest.raises(Exception) as rejected:
            reader.execute(text("INSERT INTO affiliate_cost_events (id,amount,currency,cost_type,allocation_scope,source_namespace,source_event_digest,fingerprint,created_at) VALUES (:id,1,'USD','x','shared','x',:digest,:fingerprint,now())"), {"id":str(uuid4()), "digest":uuid4().hex * 2, "fingerprint":"f" * 64})
        original = getattr(rejected.value, "orig", rejected.value)
        assert getattr(original, "sqlstate", None) == "25006" or "read-only" in str(original).lower()
        reader.rollback()
    finally:
        event.remove(engine, "before_cursor_execute", capture); reader.close()
    fresh = _session()
    try:
        row = _owned(AttributionAllocatedContributionProfitProjectionService(fresh).project(AllocatedContributionProfitProjectionRequest(("earning",))), identity)
        assert row.allocated_contribution_profit == Decimal("70.00")
    finally:
        fresh.close()


def test_m10a9b_components_are_preserved_and_no_cost_only_rows_are_created():
    identity = _settled(); _direct(identity, Decimal("20.00")); _allocate(_cost(identity, Decimal("30.00"), "shared"), ((identity, Decimal("30.00")),))
    unallocated = _cost(identity, Decimal("99.00"), "shared")
    global_cost = _cost(identity, Decimal("88.00"), "global")
    for dimensions in ((), ("affiliate_program",), ("product",), ("earning",), ("affiliate_program", "product")):
        upstream_db, allocated_db = _session(), _session()
        try:
            upstream = AttributionContributionProfitProjectionService(upstream_db).project(ContributionProfitProjectionRequest(dimensions))
            allocated = AttributionAllocatedContributionProfitProjectionService(allocated_db).project(AllocatedContributionProfitProjectionRequest(dimensions))
            assert {
                (row.currency, row.dimensions): (row.net_realized_commission, row.directly_attributable_cost, row.contribution_profit)
                for row in allocated
            } == {
                (row.currency, row.dimensions): (row.net_realized_commission, row.directly_attributable_cost, row.contribution_profit)
                for row in upstream
            }
        finally:
            upstream_db.close(); allocated_db.close()
    db = _session()
    try:
        row = _owned(AttributionAllocatedContributionProfitProjectionService(db).project(AllocatedContributionProfitProjectionRequest(("earning",))), identity)
        assert row.allocated_shared_cost == Decimal("30.00") and row.allocated_shared_cost not in {unallocated.amount, global_cost.amount}
    finally:
        db.close()
