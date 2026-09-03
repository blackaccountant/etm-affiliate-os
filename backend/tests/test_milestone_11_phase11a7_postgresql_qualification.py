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
from app.optimization.eligible_operating_profit_candidate_set_contracts import EligibleOperatingProfitCandidateSetRequest
from app.optimization.operating_profit_evidence_eligibility_contracts import OperatingProfitEvidenceEligibilityPolicy
from app.optimization.ordered_economic_candidate_preference_contracts import OrderedEconomicCandidatePreferenceRequest
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_payout_settlement_link_service import AttributionPayoutSettlementLinkService
from app.services.attribution_publication_service import AttributionPublicationService
from app.services.ordered_economic_candidate_preference_service import OrderedEconomicCandidatePreferenceService


DATABASE = "etm_g5_m11a7_ordered_preference_qualification"
ROLE, RAW = os.getenv("ETM_G5_M11A7_DB_ROLE"), os.getenv("ETM_G5_M11A7_DATABASE_URL")
if not RAW:
    pytest.skip("requires guarded M11A7 URL", allow_module_level=True)
URL = make_url(RAW)
if ROLE != "qualification" or not URL.drivername.startswith("postgresql") or URL.host != "127.0.0.1" or URL.port != 5432 or URL.database != DATABASE:
    raise RuntimeError("M11A7 database guard failed")


def _session():
    return sessionmaker(bind=create_engine(URL.render_as_string(hide_password=False)), expire_on_commit=False)()


def _request(currency="USD"):
    return OrderedEconomicCandidatePreferenceRequest(
        EligibleOperatingProfitCandidateSetRequest(("affiliate_program",), currency, OperatingProfitEvidenceEligibilityPolicy("qualification", 1, 1, 1), datetime(2100, 1, 1, tzinfo=timezone.utc)),
        OperatingProfitComparisonPolicy("qualification-pairwise-v1"),
    )


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
    finally:
        db.close()


def _seed(counts, currency="USD"):
    identities = [_settled(currency=currency) for _ in counts]
    for identity, count in zip(identities, counts, strict=True):
        for _ in range(count - 1): _settled(product_id=identity["product"], program_id=identity["program"], currency=currency)
    return identities


def _network_forbidden(*_args, **_kwargs): raise AssertionError("network called")


def _ids(rows): return [dict(row.dimensions)["affiliate_program"] for row in rows]


def test_current_head_requires_no_m11a7_migration():
    db = _session()
    try: assert MigrationContext.configure(db.connection()).get_current_revision() == "c3d4e5f6a7b8"
    finally: db.close()


def test_real_one_pass_ordering_uses_one_upstream_graph_and_captured_tuple(monkeypatch):
    left, tied_one, tied_two = _seed((3, 2, 2))
    db, calls, outside = _session(), {"m11a5b": 0, "m11a4": 0, "m11a3": 0, "m11a2": 0, "m11a1": 0}, []
    import app.services.ordered_economic_candidate_preference_service as module
    import app.services.eligible_economic_candidate_service as economic_module
    real, signal, evidence = module.EligibleEconomicCandidateService, economic_module.OperatingProfitSignalService, economic_module.OperatingProfitEvidenceService
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
    class Candidates:
        def __init__(self, value): self.delegate, self.rows = real(value), None
        def project(self, value): calls["m11a5b"] += 1; self.rows = self.delegate.project(value); return self.rows
    monkeypatch.setattr(economic_module, "OperatingProfitSignalService", Signal); monkeypatch.setattr(economic_module, "OperatingProfitEvidenceService", Evidence)
    monkeypatch.setattr(economic_module, "OperatingProfitEvidenceEligibilityService", Eligibility); monkeypatch.setattr(economic_module, "EligibleOperatingProfitCandidateSetService", CandidateSet)
    monkeypatch.setattr(module, "EligibleEconomicCandidateService", Candidates)
    engine, inside = db.get_bind(), [False]; event.listen(engine, "before_cursor_execute", lambda *_args: outside.append(_args[2]) if not inside[0] else None)
    monkeypatch.setattr(requests.sessions.Session, "request", _network_forbidden); monkeypatch.setattr(httpx.Client, "request", _network_forbidden)
    try:
        service = module.OrderedEconomicCandidatePreferenceService(db); adapter_calls, adapter_rows, real_adapter = [], [], service._captured_candidates.project
        def tracked_adapter(request):
            adapter_calls.append(request); returned = real_adapter(request); adapter_rows.append(returned); return returned
        service._captured_candidates.project = tracked_adapter
        assert outside == []; inside[0] = True
        try: rows = service.project(_request())
        finally: inside[0] = False
        assert calls == {"m11a5b": 1, "m11a4": 1, "m11a3": 1, "m11a2": 1, "m11a1": 1} and len(adapter_calls) > 1 and outside == []
        assert adapter_rows and all(rows is service._economic_candidates.rows for rows in adapter_rows)
        assert _ids(rows)[0] == left["program"] and {row.preference_tier for row in rows} == {1, 2}
        assert {row.preference_tier for row in rows if dict(row.dimensions)["affiliate_program"] in {tied_one["program"], tied_two["program"]}} == {2}
        assert all(isinstance(row.operating_profit, Decimal) for row in rows)
        assert db.execute(text("SHOW transaction_isolation")).scalar_one() == "repeatable read"
        assert db.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
        with pytest.raises(Exception): db.execute(text("CREATE TABLE m11a7_forbidden_write (id integer)"))
        db.rollback()
    finally: db.close()


def test_a_b_a_c_snapshot_ordering_is_stable_then_reorders_fresh():
    left, middle, right = _seed((3, 2, 1), "EUR"); reader = _session()
    try:
        service = OrderedEconomicCandidatePreferenceService(reader); before = service.project(_request("EUR"))
        assert _ids(before) == [left["program"], middle["program"], right["program"]]
        original = [(row.operating_profit, row.preference_tier) for row in before]
        for _ in range(3): _settled(product_id=right["product"], program_id=right["program"], currency="EUR")
        same = service.project(_request("EUR"))
        assert _ids(same) == _ids(before) and [(row.operating_profit, row.preference_tier) for row in same] == original
    finally: reader.close()
    fresh = _session()
    try:
        rows = OrderedEconomicCandidatePreferenceService(fresh).project(_request("EUR"))
        assert _ids(rows) == [right["program"], left["program"], middle["program"]]
        assert [row.preference_tier for row in rows] == [1, 2, 3]
    finally: fresh.close()


def test_different_currency_uses_the_frozen_fresh_session_restriction():
    _seed((1,), "USD"); _seed((1,), "EUR"); db = _session()
    try:
        service = OrderedEconomicCandidatePreferenceService(db)
        service.project(_request("USD"))
        with pytest.raises(ValueError, match="fresh Session"):
            service.project(_request("EUR"))
    finally: db.close()
