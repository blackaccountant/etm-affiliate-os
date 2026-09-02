"""Guarded PostgreSQL qualification for read-only M10A9B contribution profit."""
import json
import os
import inspect
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy import event

from app.affiliate_financial.cost_event_contracts import RecordAffiliateCostEventRequest
from app.attribution.contribution_profit_projection_contracts import ContributionProfitProjectionRequest
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_program import AffiliateProgram
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.affiliate_cost_event import AffiliateCostEvent
from app.models.attribution_payout_settlement_link import AttributionPayoutSettlementLink
from app.models.attribution import AttributionContext
from app.models.product import Product
from app.models.publishing_queue import PublishingQueue
from app.models.discovery import DiscoveryRun, DiscoveryCandidate
from app.models.content_brief import ContentBrief
from app.models.content_generation_run import ContentGenerationRun
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.content_evaluation import ContentEvaluation
from app.models.crm import Lead, ContactPoint
from app.models.outreach import OutreachIntent
from app.models.outreach_delivery import OutreachDeliveryAttempt
from app.models.outreach_provider_dispatch import OutreachProviderDispatch
from app.models.attribution import AttributionPublication
from app.services.distribution_run_service import DistributionRunService
from app.distribution.contracts import CreateDistributionRunRequest
from app.services.affiliate_cost_event_service import AffiliateCostEventService
from app.services.affiliate_financial_adjustment_service import AffiliateFinancialAdjustmentService
from app.services.attribution_contribution_profit_projection_service import AttributionContributionProfitProjectionService
from app.repositories.attribution_contribution_profit_projection_repository import AttributionContributionProfitProjectionRepository
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
from app.services.attribution_payout_settlement_link_service import AttributionPayoutSettlementLinkService
from app.services.attribution_publication_service import AttributionPublicationService
from app.services.attribution_net_realized_revenue_projection_service import AttributionNetRealizedRevenueProjectionService
from app.attribution.net_realized_revenue_projection_contracts import NetRealizedRevenueProjectionRequest

ROLE, raw = os.getenv("ETM_G5_M10A9B_DB_ROLE"), os.getenv("ETM_G5_DATABASE_URL")
if not raw:
    pytest.skip("requires guarded ETM_G5_DATABASE_URL", allow_module_level=True)
url = make_url(raw)
if ROLE != "qualification" or not (url.drivername.startswith("postgresql") and url.host == "127.0.0.1" and url.port == 5432 and url.database == "etm_g5_m10a9b_contribution_profit_qualification"):
    raise RuntimeError("M10A9B qualification database guard failed")


def _session():
    return sessionmaker(bind=create_engine(url.render_as_string(hide_password=False)), expire_on_commit=False)()


def _settled(
    *, sale=Decimal("1000.00"), currency="USD", create_settlement=True,
    product_id=None, program_id=None, publication_id=None, payout_id=None,
    payout_attempt_id=None, payout_total=None,
):
    db, token = _session(), uuid4().hex
    try:
        product = db.get(Product, product_id) if product_id is not None else Product(name=token, website=f"https://{token}.invalid", category="test", affiliate_program="test", commission_type="percentage", commission_value="10", affiliate_score=1, grade="A", confidence=1, summary="", recommendation="", status="active")
        if product_id is None: db.add(product); db.flush()
        program = db.get(AffiliateProgram, program_id) if program_id is not None else AffiliateProgram(product_id=product.id, program_name=token, commission_type="percentage", commission_value="10", status="active")
        if program_id is None: db.add(program); db.flush()
        if product is None or program is None or program.product_id != product.id:
            raise ValueError("shared product/program authority is inconsistent")
        asset = AffiliateContentAsset(product_id=product.id, asset_type="article", title=token); db.add(asset); db.flush()
        if publication_id is None:
            queue = PublishingQueue(content_asset_id=asset.id, channel=token); db.add(queue); db.flush()
            publication = AttributionPublicationService(db).bind_legacy(queue.id)
        else:
            publication = db.get(AttributionPublication, publication_id)
            if publication is None: raise ValueError("shared publication authority does not exist")
        context = AttributionContextService(db).create(affiliate_program_id=program.id, attribution_publication_id=publication.id)
        db.commit()
        link = AttributionLinkBridgeService(db).create_bound_link(affiliate_program_id=program.id, attribution_context_id=context.id, name=token, destination_url="https://private.invalid", content_asset_id=asset.id)
        result = AttributionConversionBridgeService(db).record(affiliate_program_id=program.id, affiliate_link_id=link.id, external_conversion_id=token, customer_reference="private-customer", sale_amount=sale, currency=currency, commission_rate=Decimal("10"), metadata_json=json.dumps({"private": token}))
        earning_link = AttributionEarningLinkService(db).reconcile(attribution_fact_id=result["fact"].id)
        earning = result["earning"]; now = datetime.now(timezone.utc)
        payout = db.get(AffiliatePayout, payout_id) if payout_id is not None else AffiliatePayout(affiliate_program_id=program.id, total_amount=payout_total or earning.commission_amount, currency=currency, status="paid", paid_at=now, created_at=now, updated_at=now)
        if payout_id is None: db.add(payout); db.flush()
        if payout is None or payout.affiliate_program_id != program.id or payout.currency != currency or payout.status != "paid":
            raise ValueError("shared payout authority is inconsistent")
        earning.payout_id, earning.status = payout.id, "paid"
        attempt = db.get(AffiliatePayoutAttempt, payout_attempt_id) if payout_attempt_id is not None else AffiliatePayoutAttempt(payout_id=payout.id, attempt_number=1, amount=payout.total_amount, currency=currency, status="completed", provider="manual", idempotency_key=token, started_at=now, completed_at=now, created_at=now, updated_at=now)
        if payout_attempt_id is None: db.add(attempt)
        if attempt is None or attempt.payout_id != payout.id or attempt.status != "completed":
            raise ValueError("shared payout-attempt authority is inconsistent")
        db.commit()
        settlement = AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=earning_link.id) if create_settlement else None
        return dict(product=product.id, program=program.id, asset=asset.id, publication=publication.id, distribution=publication.distribution_run_id, link=link.id, conversion=result["conversion"].id, earning=earning.id, payout=payout.id, attempt=attempt.id, settlement=settlement.id if settlement else None, currency=currency)
    finally:
        db.close()


def _record_cost(identity, amount, *, key=None, **overrides):
    db = _session()
    try:
        data = dict(amount=amount, currency=identity["currency"], cost_type="provider_fee", allocation_scope="direct", source_namespace="m10a9b.test", source_event_key=key or uuid4().hex, affiliate_earning_id=identity["earning"], affiliate_conversion_id=identity["conversion"])
        data.update(overrides)
        return AffiliateCostEventService(db).record(RecordAffiliateCostEventRequest(**data))
    finally:
        db.close()


def _owned(rows, identity):
    return next(row for row in rows if dict(row.dimensions).get("earning") == identity["earning"])


def _cost_event_snapshot(db, event_ids):
    return tuple(
        (row.id, row.amount, row.affiliate_earning_id, row.affiliate_conversion_id, row.distribution_run_id, row.affiliate_payout_id, row.affiliate_payout_attempt_id, row.fingerprint)
        for row in db.query(AffiliateCostEvent).filter(AffiliateCostEvent.id.in_(tuple(event_ids))).order_by(AffiliateCostEvent.id).all()
    )


def _distribution_publication():
    db, token = _session(), uuid4().hex
    try:
        now = datetime.now(timezone.utc)
        discovery = DiscoveryRun(id=token+"d", input_type="URL", input_value=f"https://{token}.invalid", status="COMPLETED", idempotency_key=token+"d", candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now)
        candidate = DiscoveryCandidate(id=token+"c", run_id=discovery.id, source_adapter="test", source_type="test", canonical_domain=f"{token}.invalid", program_identity_key=token+"p", dedupe_key=token+"k", commission_model="UNKNOWN", verification_status="VERIFIED", disposition="SELECTED", created_at=now, updated_at=now)
        brief = ContentBrief(id=token+"b", discovery_run_id=discovery.id, discovery_candidate_id=candidate.id, content_type="ARTICLE", channel_intent="SEO", objective="proof", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key=token+"b", status="READY", created_at=now, updated_at=now)
        generation = ContentGenerationRun(id=token+"g", content_brief_id=brief.id, idempotency_key=token+"g", provider="test", model="test", prompt_version="v1", generation_parameters={}, status="COMPLETED", attempt_count=1, created_at=now, updated_at=now)
        artifact = GeneratedContentArtifact(id=token+"a", generation_run_id=generation.id, content_brief_id=brief.id, content_type="ARTICLE", title="proof", hook="proof", body="proof body", call_to_action="CHECK_DETAILS", affiliate_disclosure="disclosure", claims=[], status="GENERATED", created_at=now, updated_at=now)
        evaluation = ContentEvaluation(id=token+"e", artifact_id=artifact.id, content_brief_id=brief.id, generation_run_id=generation.id, factual_grounding_score=100, offer_alignment_score=100, intent_alignment_score=100, clarity_score=100, cta_score=100, compliance_score=100, overall_score=100, decision="APPROVED", approved=True, evaluator_version="v1", policy_version="v1", claim_results=[], compliance_flags=[], unsupported_claims=[], missing_evidence_ids=[], revision_reasons=[], rejection_reasons=[], created_at=now, updated_at=now)
        for authority in (discovery, candidate, brief, generation, artifact, evaluation):
            db.add(authority); db.flush()
        db.commit()
        run = DistributionRunService(db).create(CreateDistributionRunRequest(artifact.id, evaluation.id, "test", token, "fixture"))
        publication = AttributionPublicationService(db).bind_distribution(run.id); db.commit()
        return run.id, publication.id
    finally:
        db.close()


def test_direct_arithmetic_eligibility_grouping_privacy_and_no_mutation(monkeypatch):
    identity = _settled()
    replay_key = "replay-" + uuid4().hex
    consistent = _record_cost(identity, Decimal("20.00"), key=replay_key, affiliate_program_id=identity["program"], product_id=identity["product"], content_asset_id=identity["asset"], affiliate_link_id=identity["link"], affiliate_payout_id=identity["payout"], affiliate_payout_attempt_id=identity["attempt"])
    replay = _record_cost(identity, Decimal("20.00"), key=replay_key, affiliate_program_id=identity["program"], product_id=identity["product"], content_asset_id=identity["asset"], affiliate_link_id=identity["link"], affiliate_payout_id=identity["payout"], affiliate_payout_attempt_id=identity["attempt"])
    assert replay.id == consistent.id
    _record_cost(identity, Decimal("30.00")); _record_cost(identity, Decimal("10.00"))
    other = _settled()
    _record_cost(identity, Decimal("99.00"), affiliate_program_id=other["program"])
    _record_cost(identity, Decimal("88.00"), affiliate_earning_id=None, affiliate_conversion_id=None, affiliate_program_id=identity["program"])
    _record_cost(identity, Decimal("76.00"), affiliate_earning_id=None, affiliate_conversion_id=None, affiliate_payout_id=identity["payout"])
    _record_cost(identity, Decimal("75.00"), affiliate_conversion_id=other["conversion"])
    _record_cost(identity, Decimal("74.00"), affiliate_payout_id=other["payout"])
    _record_cost(identity, Decimal("77.00"), allocation_scope="shared")
    _record_cost(identity, Decimal("66.00"), allocation_scope="global", affiliate_earning_id=None, affiliate_conversion_id=None)
    _record_cost(identity, Decimal("55.00"), currency="EUR")
    before = _session()
    try:
        fingerprint = tuple(before.execute(text("SELECT id, amount, currency, source_event_digest FROM affiliate_cost_events ORDER BY id")).all())
    finally:
        before.close()
    calls = {"requests": 0, "httpx_sync": 0, "httpx_async": 0, "m10a8": 0}
    def no_requests(*args, **kwargs): calls["requests"] += 1; raise AssertionError("requests called")
    def no_httpx(*args, **kwargs): calls["httpx_sync"] += 1; raise AssertionError("httpx called")
    def no_async(*args, **kwargs): calls["httpx_async"] += 1; raise AssertionError("httpx async called")
    real_project = AttributionNetRealizedRevenueProjectionService.project
    def counted_project(service, request): calls["m10a8"] += 1; return real_project(service, request)
    monkeypatch.setattr(requests.sessions.Session, "request", no_requests)
    monkeypatch.setattr(httpx.Client, "request", no_httpx)
    monkeypatch.setattr(httpx.AsyncClient, "request", no_async)
    monkeypatch.setattr(AttributionNetRealizedRevenueProjectionService, "project", counted_project)
    projection = _session()
    try:
        rows = AttributionContributionProfitProjectionService(projection).project(ContributionProfitProjectionRequest(("earning",)))
        row = _owned(rows, identity)
        assert (row.net_realized_commission, row.directly_attributable_cost, row.contribution_profit) == (Decimal("100.00"), Decimal("60.00"), Decimal("40.00"))
        assert set(asdict(row)) == {"currency", "net_realized_commission", "directly_attributable_cost", "contribution_profit", "dimensions", "semantics"}
        assert "private" not in json.dumps([asdict(value) for value in rows], default=str)
        assert calls == {"requests": 0, "httpx_sync": 0, "httpx_async": 0, "m10a8": 1}
    finally:
        projection.close()
    for dimensions in ((), ("affiliate_program",), ("product",), ("affiliate_program", "product")):
        db = _session()
        try:
            grouped = AttributionContributionProfitProjectionService(db).project(ContributionProfitProjectionRequest(dimensions))
            if not dimensions:
                earning_db = _session()
                try:
                    earning_rows = AttributionContributionProfitProjectionService(earning_db).project(ContributionProfitProjectionRequest(("earning",)))
                    assert next(value.contribution_profit for value in grouped if value.currency == "USD") == sum(value.contribution_profit for value in earning_rows if value.currency == "USD")
                finally:
                    earning_db.close()
            else:
                expected = {"affiliate_program": identity["program"], "product": identity["product"]}
                assert next(value.contribution_profit for value in grouped if dict(value.dimensions) == {name: expected[name] for name in dimensions}) == Decimal("40.00")
        finally:
            db.close()
    after = _session()
    try:
        assert tuple(after.execute(text("SELECT id, amount, currency, source_event_digest FROM affiliate_cost_events ORDER BY id")).all()) == fingerprint
    finally:
        after.close()


def test_currency_negative_zero_read_only_and_snapshot_concurrency():
    negative = _settled(); _record_cost(negative, Decimal("120.00"))
    zero = _settled(); _record_cost(zero, Decimal("100.00"))
    usd = _settled(); _record_cost(usd, Decimal("20.00"))
    conversion_anchor = _settled(); _record_cost(conversion_anchor, Decimal("5.00"), affiliate_earning_id=None)
    zero_revenue = _settled()
    adjustment_db = _session()
    try:
        AffiliateFinancialAdjustmentService(adjustment_db).reconcile(earning_id=zero_revenue["earning"], program_id=zero_revenue["program"], conversion_id=zero_revenue["conversion"], settlement_link_id=zero_revenue["settlement"], adjustment_type="REVERSAL", adjustment_amount=Decimal("-100.00"), currency="USD", effective_at=datetime.now(timezone.utc), source_namespace="m10a9b.test", source_event_digest=uuid4().hex * 2)
    finally:
        adjustment_db.close()
    _record_cost(zero_revenue, Decimal("20.00"))
    eur = _settled(currency="EUR"); _record_cost(eur, Decimal("20.00"))
    reader = _session()
    try:
        service = AttributionContributionProfitProjectionService(reader)
        first = service.project(ContributionProfitProjectionRequest(("earning",)))
        assert _owned(first, negative).contribution_profit == Decimal("-20.00")
        assert _owned(first, zero).contribution_profit == Decimal("0.00")
        assert (_owned(first, usd).currency, _owned(first, usd).contribution_profit) == ("USD", Decimal("80.00"))
        assert _owned(first, conversion_anchor).contribution_profit == Decimal("95.00")
        assert (_owned(first, zero_revenue).net_realized_commission, _owned(first, zero_revenue).contribution_profit) == (Decimal("0.00"), Decimal("-20.00"))
        assert (_owned(first, eur).currency, _owned(first, eur).contribution_profit) == ("EUR", Decimal("80.00"))
        _record_cost(usd, Decimal("10.00"))
        again = service.project(ContributionProfitProjectionRequest(("earning",)))
        assert _owned(again, usd).contribution_profit == Decimal("80.00")
        with pytest.raises(Exception) as rejected:
            reader.execute(text("INSERT INTO affiliate_cost_events (id,amount,currency,cost_type,allocation_scope,source_namespace,source_event_digest,fingerprint,created_at) VALUES (:id,1,'USD','x','shared','x',:digest,:fingerprint,now())"), {"id": str(uuid4()), "digest": uuid4().hex * 2, "fingerprint": "f" * 64})
        original = getattr(rejected.value, "orig", rejected.value)
        assert getattr(original, "sqlstate", None) == "25006" or type(original).__name__ == "ReadOnlySqlTransaction"
        assert "read-only" in str(original).lower()
        reader.rollback()
    finally:
        reader.close()
    fresh = _session()
    try:
        rows = AttributionContributionProfitProjectionService(fresh).project(ContributionProfitProjectionRequest(("earning",)))
        assert _owned(rows, usd).contribution_profit == Decimal("70.00")
    finally:
        fresh.close()


def test_explicit_eligibility_boundaries_and_no_independent_adjustment_read():
    """Focused assertions for static M10A9B-only boundaries; revenue authority remains delegated."""
    import app.services.attribution_contribution_profit_projection_service as module
    source = inspect.getsource(module)
    repository = inspect.getsource(AttributionContributionProfitProjectionRepository)
    assert "AffiliateFinancialAdjustment" not in source + repository
    assert "payout.total_amount" not in source + repository and "attempt.amount" not in source + repository
    assert "content_generation_run_id is not None" in source and "outreach_provider_dispatch_id is not None" in source
    assert "distribution_run_id" in source and "affiliate_payout_attempt_id" in source


def test_unsettled_anchors_are_persisted_but_create_no_cost_only_rows():
    settled = _settled()
    unsettled_earning = _settled(create_settlement=False)
    unsettled_conversion = _settled(create_settlement=False)
    baseline = _record_cost(settled, Decimal("20.00"))
    earning_cost = _record_cost(unsettled_earning, Decimal("31.00"), affiliate_conversion_id=None)
    conversion_cost = _record_cost(unsettled_conversion, Decimal("32.00"), affiliate_earning_id=None)
    assert earning_cost.id and conversion_cost.id and baseline.id
    db = _session()
    try:
        rows = AttributionContributionProfitProjectionService(db).project(ContributionProfitProjectionRequest(("earning",)))
        assert _owned(rows, settled).directly_attributable_cost == Decimal("20.00")
        assert all(dict(row.dimensions)["earning"] not in {unsettled_earning["earning"], unsettled_conversion["earning"]} for row in rows)
    finally:
        db.close()


def test_m10a8_revenue_is_preserved_row_by_row_and_authority_state_is_unchanged():
    identity = _settled(); cost = _record_cost(identity, Decimal("20.00"))
    adjustment_db = _session()
    try:
        adjustment = AffiliateFinancialAdjustmentService(adjustment_db).reconcile(earning_id=identity["earning"], program_id=identity["program"], conversion_id=identity["conversion"], settlement_link_id=identity["settlement"], adjustment_type="RESTORATION", adjustment_amount=Decimal("1.00"), currency="USD", effective_at=datetime.now(timezone.utc), source_namespace="m10a9b.immutability", source_event_digest=uuid4().hex * 2)
    finally:
        adjustment_db.close()
    before = _session()
    try:
        snapshot = tuple(before.execute(text("SELECT e.id,e.commission_amount,e.currency,e.status,e.payout_id,p.total_amount,p.currency,p.status,a.payout_id,a.attempt_number,a.amount,a.status,s.affiliate_earning_id,s.affiliate_payout_id,s.affiliate_payout_attempt_id,f.adjustment_amount,f.currency,f.adjustment_type,c.amount,c.currency,c.fingerprint FROM affiliate_earnings e JOIN affiliate_payouts p ON p.id=e.payout_id JOIN affiliate_payout_attempts a ON a.id=:attempt JOIN attribution_payout_settlement_links s ON s.id=:settlement JOIN affiliate_financial_adjustments f ON f.id=:adjustment JOIN affiliate_cost_events c ON c.id=:cost WHERE e.id=:earning"), {"attempt":identity["attempt"],"settlement":identity["settlement"],"adjustment":adjustment.id,"cost":cost.id,"earning":identity["earning"]}).one())
    finally: before.close()
    for dimensions in ((), ("affiliate_program",), ("product",), ("earning",), ("affiliate_program", "product")):
        a, b = _session(), _session()
        try:
            frozen = AttributionNetRealizedRevenueProjectionService(a).project(NetRealizedRevenueProjectionRequest(dimensions))
            contribution = AttributionContributionProfitProjectionService(b).project(ContributionProfitProjectionRequest(dimensions))
            assert {(r.currency,r.dimensions):r.net_realized_commission for r in contribution} == {(r.currency,r.dimensions):r.net_realized_commission for r in frozen}
        finally: a.close(); b.close()
    after = _session()
    try:
        same = tuple(after.execute(text("SELECT e.id,e.commission_amount,e.currency,e.status,e.payout_id,p.total_amount,p.currency,p.status,a.payout_id,a.attempt_number,a.amount,a.status,s.affiliate_earning_id,s.affiliate_payout_id,s.affiliate_payout_attempt_id,f.adjustment_amount,f.currency,f.adjustment_type,c.amount,c.currency,c.fingerprint FROM affiliate_earnings e JOIN affiliate_payouts p ON p.id=e.payout_id JOIN affiliate_payout_attempts a ON a.id=:attempt JOIN attribution_payout_settlement_links s ON s.id=:settlement JOIN affiliate_financial_adjustments f ON f.id=:adjustment JOIN affiliate_cost_events c ON c.id=:cost WHERE e.id=:earning"), {"attempt":identity["attempt"],"settlement":identity["settlement"],"adjustment":adjustment.id,"cost":cost.id,"earning":identity["earning"]}).one())
        assert same == snapshot
    finally: after.close()


def test_m10a8_transaction_setup_precedes_cost_reads_exactly_once():
    identity = _settled(); _record_cost(identity, Decimal("20.00"))
    db, statements = _session(), []
    engine = db.get_bind()
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(" ".join(statement.upper().split()))
    event.listen(engine, "before_cursor_execute", capture)
    try:
        row = _owned(AttributionContributionProfitProjectionService(db).project(ContributionProfitProjectionRequest(("earning",))), identity)
        assert row.directly_attributable_cost == Decimal("20.00")
    finally:
        event.remove(engine, "before_cursor_execute", capture); db.close()
    setup = [i for i, value in enumerate(statements) if "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in value]
    costs = [i for i, value in enumerate(statements) if "AFFILIATE_COST_EVENTS" in value]
    revenue = [i for i, value in enumerate(statements) if "ATTRIBUTION_PAYOUT_SETTLEMENT_LINKS" in value and "ATTRIBUTION_EARNING_LINKS" in value]
    assert len(setup) == 1 and revenue and costs and setup[0] < revenue[0] < costs[0]


def test_persisted_content_generation_run_cost_is_excluded():
    identity, db, token = _settled(), _session(), uuid4().hex
    try:
        now = datetime.now(timezone.utc)
        run = DiscoveryRun(id=token+"d", input_type="URL", input_value="https://fixture.invalid", status="COMPLETED", idempotency_key=token+"d", candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now)
        candidate = DiscoveryCandidate(id=token+"c", run_id=run.id, source_adapter="test", source_type="test", canonical_domain="fixture.invalid", program_identity_key=token, dedupe_key=token, commission_model="UNKNOWN", verification_status="VERIFIED", disposition="SELECTED", created_at=now, updated_at=now)
        brief = ContentBrief(id=token+"b", discovery_run_id=run.id, discovery_candidate_id=candidate.id, content_type="ARTICLE", channel_intent="SEO", objective="proof", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key=token+"b", status="READY", created_at=now, updated_at=now)
        generation = ContentGenerationRun(id=token+"g", content_brief_id=brief.id, idempotency_key=token+"g", provider="test", model="test", prompt_version="v1", generation_parameters={}, status="COMPLETED", attempt_count=1, created_at=now, updated_at=now)
        db.add_all([run,candidate,brief,generation]); db.commit()
    finally: db.close()
    before = _session()
    try: baseline = _owned(AttributionContributionProfitProjectionService(before).project(ContributionProfitProjectionRequest(("earning",))), identity)
    finally: before.close()
    event = _record_cost(identity, Decimal("31.00"), content_generation_run_id=generation.id)
    after = _session()
    try:
        row = _owned(AttributionContributionProfitProjectionService(after).project(ContributionProfitProjectionRequest(("earning",))), identity)
        assert event.id and event.amount == Decimal("31.00") and row.directly_attributable_cost == baseline.directly_attributable_cost and row.contribution_profit == baseline.contribution_profit
    finally: after.close()


def test_persisted_outreach_provider_dispatch_cost_is_excluded():
    identity, db, token = _settled(), _session(), uuid4().hex
    try:
        now, fingerprint = datetime.now(timezone.utc), uuid4().hex * 2
        lead = Lead(subject_id=None); db.add(lead); db.flush()
        contact = ContactPoint(lead_id=lead.id, kind="EMAIL", normalized_value=f"{token}@fixture.invalid"); db.add(contact); db.flush()
        intent = OutreachIntent(lead_id=lead.id, contact_point_id=contact.id, channel="EMAIL", purpose_key="affiliate:qualification", source_namespace="m10a9b.test", source_event_key=token+"-intent", request_fingerprint=fingerprint, eligibility_policy_version="v1", creation_contactability_state="CONTACTABLE", contactability_evaluated_as_of=now, contactability_decision_fingerprint=fingerprint, contactability_evidence={}); db.add(intent); db.flush()
        attempt = OutreachDeliveryAttempt(outreach_intent_id=intent.id, attempt_number=1, source_namespace="m10a9b.test", source_event_key=token+"-attempt", request_fingerprint=fingerprint); db.add(attempt); db.flush()
        dispatch = OutreachProviderDispatch(delivery_attempt_id=attempt.id, provider_key="test", provider_contract_version="v1", provider_operation_key=token, provider_operation_fingerprint=fingerprint, provider_payload_fingerprint=fingerprint, sender_identity_fingerprint=fingerprint, planned_at=now, dispatch_started_at=now); db.add(dispatch); db.commit()
    finally: db.close()
    before = _session()
    try: baseline = _owned(AttributionContributionProfitProjectionService(before).project(ContributionProfitProjectionRequest(("earning",))), identity)
    finally: before.close()
    event = _record_cost(identity, Decimal("37.00"), outreach_provider_dispatch_id=dispatch.id)
    verify = _session()
    try:
        persisted = verify.get(__import__('app.models.affiliate_cost_event', fromlist=['AffiliateCostEvent']).AffiliateCostEvent, event.id)
        authority = (persisted.id, persisted.amount, persisted.affiliate_earning_id, persisted.affiliate_conversion_id, persisted.outreach_provider_dispatch_id, persisted.fingerprint)
        assert authority[:5] == (event.id, Decimal("37.00"), identity["earning"], identity["conversion"], dispatch.id)
    finally: verify.close()
    after = _session()
    try:
        row = _owned(AttributionContributionProfitProjectionService(after).project(ContributionProfitProjectionRequest(("earning",))), identity)
        assert (row.net_realized_commission, row.directly_attributable_cost, row.contribution_profit) == (baseline.net_realized_commission, baseline.directly_attributable_cost, baseline.contribution_profit)
    finally: after.close()
    verify = _session()
    try:
        persisted = verify.get(__import__('app.models.affiliate_cost_event', fromlist=['AffiliateCostEvent']).AffiliateCostEvent, event.id)
        assert (persisted.id, persisted.amount, persisted.affiliate_earning_id, persisted.affiliate_conversion_id, persisted.outreach_provider_dispatch_id, persisted.fingerprint) == authority
    finally: verify.close()


def test_distribution_only_matching_and_contradictory_correlations():
    matching_run, matching_publication = _distribution_publication()
    contradictory_run, _ = _distribution_publication()
    identity = _settled(publication_id=matching_publication)
    assert matching_run != contradictory_run and identity["distribution"] == matching_run
    before = _session()
    try:
        baseline = _owned(AttributionContributionProfitProjectionService(before).project(ContributionProfitProjectionRequest(("earning",))), identity)
        assert baseline.directly_attributable_cost == Decimal("0")
    finally:
        before.close()
    distribution_only = _record_cost(identity, Decimal("11.00"), affiliate_earning_id=None, affiliate_conversion_id=None, distribution_run_id=matching_run)
    matching = _record_cost(identity, Decimal("20.00"), distribution_run_id=matching_run)
    contradictory = _record_cost(identity, Decimal("30.00"), distribution_run_id=contradictory_run)
    event_ids = (distribution_only.id, matching.id, contradictory.id)
    verify = _session()
    try:
        persisted = _cost_event_snapshot(verify, event_ids)
        assert len(persisted) == 3
    finally:
        verify.close()
    after = _session()
    try:
        row = _owned(AttributionContributionProfitProjectionService(after).project(ContributionProfitProjectionRequest(("earning",))), identity)
        assert row.net_realized_commission == baseline.net_realized_commission
        assert row.directly_attributable_cost == baseline.directly_attributable_cost + matching.amount
        assert row.contribution_profit == baseline.contribution_profit - matching.amount
        assert row.directly_attributable_cost not in {distribution_only.amount, contradictory.amount, matching.amount + distribution_only.amount, matching.amount + contradictory.amount}
    finally:
        after.close()
    verify = _session()
    try:
        assert _cost_event_snapshot(verify, event_ids) == persisted
    finally:
        verify.close()


def test_payout_fanout_and_payout_attempt_correlations():
    first = _settled(payout_total=Decimal("200.00"))
    second = _settled(product_id=first["product"], program_id=first["program"], payout_id=first["payout"], payout_attempt_id=first["attempt"])
    unrelated = _settled()
    assert first["payout"] == second["payout"] and first["attempt"] == second["attempt"] and first["earning"] != second["earning"] and first["attempt"] != unrelated["attempt"]
    cardinality = _session()
    try:
        settlement_earnings = {row.affiliate_earning_id for row in cardinality.query(AttributionPayoutSettlementLink).filter_by(affiliate_payout_id=first["payout"]).all()}
        assert settlement_earnings == {first["earning"], second["earning"]} and len(settlement_earnings) >= 2
    finally:
        cardinality.close()
    baseline_db = _session()
    try:
        baseline_rows = AttributionContributionProfitProjectionService(baseline_db).project(ContributionProfitProjectionRequest(("earning",)))
        first_baseline, second_baseline = _owned(baseline_rows, first), _owned(baseline_rows, second)
        assert first_baseline.directly_attributable_cost == second_baseline.directly_attributable_cost == Decimal("0")
    finally:
        baseline_db.close()
    payout_only = _record_cost(first, Decimal("41.00"), affiliate_earning_id=None, affiliate_conversion_id=None, affiliate_payout_id=first["payout"])
    attempt_only = _record_cost(first, Decimal("42.00"), affiliate_earning_id=None, affiliate_conversion_id=None, affiliate_payout_attempt_id=first["attempt"])
    matching = _record_cost(first, Decimal("20.00"), affiliate_payout_id=first["payout"], affiliate_payout_attempt_id=first["attempt"])
    mismatched = _record_cost(first, Decimal("30.00"), affiliate_payout_id=first["payout"], affiliate_payout_attempt_id=unrelated["attempt"])
    event_ids = (payout_only.id, attempt_only.id, matching.id, mismatched.id)
    verify = _session()
    try:
        persisted = _cost_event_snapshot(verify, event_ids)
        assert len(persisted) == 4
    finally:
        verify.close()
    projection = _session()
    try:
        rows = AttributionContributionProfitProjectionService(projection).project(ContributionProfitProjectionRequest(("earning",)))
        first_row, second_row = _owned(rows, first), _owned(rows, second)
        assert first_row.directly_attributable_cost == first_baseline.directly_attributable_cost + matching.amount
        assert first_row.contribution_profit == first_baseline.contribution_profit - matching.amount
        assert second_row.directly_attributable_cost == second_baseline.directly_attributable_cost
        assert second_row.contribution_profit == second_baseline.contribution_profit
        assert first_row.directly_attributable_cost + second_row.directly_attributable_cost == matching.amount
        assert all(row.directly_attributable_cost not in {payout_only.amount, attempt_only.amount, mismatched.amount} for row in (first_row, second_row))
    finally:
        projection.close()
    verify = _session()
    try:
        assert _cost_event_snapshot(verify, event_ids) == persisted
    finally:
        verify.close()
