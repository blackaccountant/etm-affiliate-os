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
from app.optimization.economic_candidate_comparison_contracts import OperatingProfitComparisonPolicy
from app.optimization.economic_recommendation_proposal_contracts import EconomicRecommendationPolicy, EconomicRecommendationProposalRequest
from app.optimization.eligible_operating_profit_candidate_set_contracts import EligibleOperatingProfitCandidateSetRequest
from app.optimization.operating_profit_evidence_eligibility_contracts import OperatingProfitEvidenceEligibilityPolicy
from app.optimization.ordered_economic_candidate_preference_contracts import OrderedEconomicCandidatePreferenceRequest
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_payout_settlement_link_service import AttributionPayoutSettlementLinkService
from app.services.attribution_publication_service import AttributionPublicationService
from app.services.economic_recommendation_proposal_service import EconomicRecommendationProposalService
from app.services.ordered_economic_candidate_preference_service import OrderedEconomicCandidatePreferenceService

DATABASE = "etm_g5_m11a8_recommendation_proposal_qualification"
ROLE, RAW = os.getenv("ETM_G5_M11A8_DB_ROLE"), os.getenv("ETM_G5_M11A8_DATABASE_URL")
if not RAW:
    pytest.skip("requires guarded M11A8 URL", allow_module_level=True)
URL = make_url(RAW)
if ROLE != "qualification" or not URL.drivername.startswith("postgresql") or URL.host != "127.0.0.1" or URL.port != 5432 or URL.database != DATABASE:
    raise RuntimeError("M11A8 database guard failed")

def _session(): return sessionmaker(bind=create_engine(URL.render_as_string(hide_password=False)), expire_on_commit=False)()
def _request(currency="USD"):
    return EconomicRecommendationProposalRequest(OrderedEconomicCandidatePreferenceRequest(EligibleOperatingProfitCandidateSetRequest(("affiliate_program",), currency, OperatingProfitEvidenceEligibilityPolicy("qualification", 1, 1, 1), datetime(2100, 1, 1, tzinfo=timezone.utc)), OperatingProfitComparisonPolicy("qualification-pairwise-v1")), EconomicRecommendationPolicy("qualification-recommendation-v1"))
def _settled(*, product_id=None, program_id=None, currency="USD"):
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
        result = AttributionConversionBridgeService(db).record(affiliate_program_id=program.id, affiliate_link_id=link.id, external_conversion_id=token, customer_reference="private", sale_amount=Decimal("1000"), currency=currency, commission_rate=Decimal("10"), metadata_json=json.dumps({"private": token}))
        earning_link = AttributionEarningLinkService(db).reconcile(attribution_fact_id=result["fact"].id)
        earning, now = result["earning"], datetime.now(timezone.utc)
        payout = AffiliatePayout(affiliate_program_id=program.id, total_amount=earning.commission_amount, currency=currency, status="paid", paid_at=now, created_at=now, updated_at=now); db.add(payout); db.flush(); earning.payout_id, earning.status = payout.id, "paid"
        db.add(AffiliatePayoutAttempt(payout_id=payout.id, attempt_number=1, amount=payout.total_amount, currency=currency, status="completed", provider="manual", idempotency_key=token, started_at=now, completed_at=now, created_at=now, updated_at=now)); db.commit()
        AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=earning_link.id)
        return {"product": product.id, "program": program.id}
    finally: db.close()
def _seed(counts, currency="USD"):
    identities = [_settled(currency=currency) for _ in counts]
    for identity, count in zip(identities, counts, strict=True):
        for _ in range(count - 1): _settled(product_id=identity["product"], program_id=identity["program"], currency=currency)
    return identities
def _ids(rows): return [dict(row.dimensions)["affiliate_program"] for row in rows]
def _network_forbidden(*_args, **_kwargs): raise AssertionError("network called")

def test_current_head_requires_no_m11a8_migration():
    db = _session()
    try: assert MigrationContext.configure(db.connection()).get_current_revision() == "c3d4e5f6a7b8"
    finally: db.close()

def test_real_one_pass_proposes_only_tier_one_from_one_m11a7_graph(monkeypatch):
    x, y, z = _seed((3, 2, 1)); db, calls, outside = _session(), {key: 0 for key in ("m11a1", "m11a2", "m11a3", "m11a4", "m11a7")}, []
    import app.services.economic_recommendation_proposal_service as proposal_module
    import app.services.eligible_economic_candidate_service as economic_module
    real_ordered, signal, evidence = OrderedEconomicCandidatePreferenceService, economic_module.OperatingProfitSignalService, economic_module.OperatingProfitEvidenceService
    eligibility, candidate_set = economic_module.OperatingProfitEvidenceEligibilityService, economic_module.EligibleOperatingProfitCandidateSetService
    class Signal:
        def __init__(self, value): self.delegate = signal(value)
        def project(self, value): calls["m11a1"] += 1; return self.delegate.project(value)
    class Evidence:
        def __init__(self, value, *, signal_service=None): self.delegate = evidence(value, signal_service=signal_service)
        def project(self, value): calls["m11a2"] += 1; return self.delegate.project(value)
    class Eligibility:
        def __init__(self, value, *, evidence_service=None): self.delegate = eligibility(value, evidence_service=evidence_service)
        def project(self, value): calls["m11a3"] += 1; return self.delegate.project(value)
    class CandidateSet:
        def __init__(self, value, *, eligibility_service=None): self.delegate = candidate_set(value, eligibility_service=eligibility_service)
        def project(self, value): calls["m11a4"] += 1; return self.delegate.project(value)
    class Ordered:
        def __init__(self, value): self.delegate, self.rows = real_ordered(value), None
        def project(self, value): calls["m11a7"] += 1; self.rows = self.delegate.project(value); return self.rows
    monkeypatch.setattr(economic_module, "OperatingProfitSignalService", Signal); monkeypatch.setattr(economic_module, "OperatingProfitEvidenceService", Evidence); monkeypatch.setattr(economic_module, "OperatingProfitEvidenceEligibilityService", Eligibility); monkeypatch.setattr(economic_module, "EligibleOperatingProfitCandidateSetService", CandidateSet); monkeypatch.setattr(proposal_module, "OrderedEconomicCandidatePreferenceService", Ordered)
    monkeypatch.setattr(requests.sessions.Session, "request", _network_forbidden); monkeypatch.setattr(httpx.Client, "request", _network_forbidden)
    engine, inside = db.get_bind(), [False]; event.listen(engine, "before_cursor_execute", lambda *_args: outside.append(_args[2]) if not inside[0] else None)
    try:
        service = EconomicRecommendationProposalService(db); inside[0] = True
        try: rows = service.project(_request())
        finally: inside[0] = False
        source = service._ordered_preferences.rows
        assert calls == {key: 1 for key in calls} and outside == []
        assert _ids(source) == [x["program"], y["program"], z["program"]] and [row.preference_tier for row in source] == [1, 2, 3]
        assert _ids(rows) == [x["program"]] and rows[0].preference_tier == 1 and rows[0].recommendation_policy_version == "qualification-recommendation-v1"
        assert rows[0].operating_profit is source[0].operating_profit and type(rows[0].operating_profit) is Decimal
        assert "EconomicCandidateComparisonService" not in open(proposal_module.__file__, encoding="utf-8").read()
        assert db.execute(text("SHOW transaction_isolation")).scalar_one() == "repeatable read" and db.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
        with pytest.raises(Exception): db.execute(text("CREATE TABLE m11a8_forbidden_write (id integer)"))
        db.rollback()
    finally: db.close()

def test_real_tier_one_tie_retains_exact_m11a7_order():
    x, y, z = _seed((2, 1, 2), "EUR"); db = _session()
    try:
        source = OrderedEconomicCandidatePreferenceService(db).project(_request("EUR").preference_request); rows = EconomicRecommendationProposalService(db).project(_request("EUR"))
        assert _ids(source) == [x["program"], z["program"], y["program"]] and [row.preference_tier for row in source] == [1, 1, 2]
        assert _ids(rows) == _ids(source[:2]) and [row.preference_tier for row in rows] == [1, 1]
    finally: db.close()

def test_a_b_a_c_snapshot_proposal_is_stable_then_fresh_reorders_and_is_read_only():
    x, y, z = _seed((3, 2, 1), "CAD"); reader = _session()
    try:
        service = EconomicRecommendationProposalService(reader); before = service.project(_request("CAD")); original = [(row.operating_profit, row.preference_tier) for row in before]
        assert _ids(before) == [x["program"]]
        for _ in range(3): _settled(product_id=z["product"], program_id=z["program"], currency="CAD")
        same = service.project(_request("CAD"))
        assert _ids(same) == [x["program"]] and [(row.operating_profit, row.preference_tier) for row in same] == original
        assert reader.execute(text("SHOW transaction_isolation")).scalar_one() == "repeatable read" and reader.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
        with pytest.raises(Exception): reader.execute(text("CREATE TABLE m11a8_snapshot_forbidden_write (id integer)"))
        reader.rollback()
    finally: reader.close()
    fresh = _session()
    try:
        rows = EconomicRecommendationProposalService(fresh).project(_request("CAD")); assert _ids(rows) == [z["program"]] and [row.preference_tier for row in rows] == [1]
    finally: fresh.close()

def test_same_service_allows_same_currency_and_rejects_different_currency():
    _seed((1,), "GBP"); _seed((1,), "JPY"); db = _session()
    try:
        service = EconomicRecommendationProposalService(db); service.project(_request("GBP")); service.project(_request("GBP"))
        with pytest.raises(ValueError, match="fresh Session"): service.project(_request("JPY"))
    finally: db.close()
