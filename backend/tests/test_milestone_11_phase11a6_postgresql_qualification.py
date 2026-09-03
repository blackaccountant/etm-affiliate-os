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
from app.optimization.economic_candidate_comparison_contracts import (
    EconomicCandidatePairwiseComparisonRequest,
    EconomicCandidatePairwiseRelation,
    OperatingProfitComparisonPolicy,
)
from app.optimization.eligible_economic_candidate_contracts import EligibleEconomicCandidateRow
from app.optimization.eligible_operating_profit_candidate_set_contracts import EligibleOperatingProfitCandidateSetRequest
from app.optimization.operating_profit_evidence_eligibility_contracts import OperatingProfitEvidenceEligibilityPolicy
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_payout_settlement_link_service import AttributionPayoutSettlementLinkService
from app.services.attribution_publication_service import AttributionPublicationService
from app.services.economic_candidate_comparison_service import EconomicCandidateComparisonService


DATABASE = "etm_g5_m11a6_pairwise_comparison_qualification"
ROLE, RAW = os.getenv("ETM_G5_M11A6_DB_ROLE"), os.getenv("ETM_G5_M11A6_DATABASE_URL")
if not RAW:
    pytest.skip("requires guarded M11A6 URL", allow_module_level=True)
URL = make_url(RAW)
if (
    ROLE != "qualification" or not URL.drivername.startswith("postgresql")
    or URL.host != "127.0.0.1" or URL.port != 5432 or URL.database != DATABASE
):
    raise RuntimeError("M11A6 database guard failed")


def _session():
    return sessionmaker(bind=create_engine(URL.render_as_string(hide_password=False)), expire_on_commit=False)()


def _request(left, right, minimum=1):
    candidate = EligibleOperatingProfitCandidateSetRequest(
        ("affiliate_program",), "USD",
        OperatingProfitEvidenceEligibilityPolicy("qualification", minimum, minimum, minimum),
        datetime(2100, 1, 1, tzinfo=timezone.utc),
    )
    return EconomicCandidatePairwiseComparisonRequest(
        candidate, (("affiliate_program", left),), (("affiliate_program", right),),
        OperatingProfitComparisonPolicy("qualification-pairwise-v1"),
    )


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
        result = AttributionConversionBridgeService(db).record(affiliate_program_id=program.id, affiliate_link_id=link.id, external_conversion_id=token, customer_reference="private", sale_amount=Decimal("1000"), currency="USD", commission_rate=Decimal("10"), metadata_json=json.dumps({"private": token}))
        earning_link = AttributionEarningLinkService(db).reconcile(attribution_fact_id=result["fact"].id)
        earning, now = result["earning"], datetime.now(timezone.utc)
        payout = AffiliatePayout(affiliate_program_id=program.id, total_amount=earning.commission_amount, currency="USD", status="paid", paid_at=now, created_at=now, updated_at=now); db.add(payout); db.flush(); earning.payout_id, earning.status = payout.id, "paid"
        db.add(AffiliatePayoutAttempt(payout_id=payout.id, attempt_number=1, amount=payout.total_amount, currency="USD", status="completed", provider="manual", idempotency_key=token, started_at=now, completed_at=now, created_at=now, updated_at=now)); db.commit()
        AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=earning_link.id)
        return {"product": product.id, "program": program.id}
    finally:
        db.close()


def _network_forbidden(*_args, **_kwargs):
    raise AssertionError("network called")


def test_current_head_requires_no_m11a6_migration():
    db = _session()
    try:
        assert MigrationContext.configure(db.connection()).get_current_revision() == "c3d4e5f6a7b8"
    finally:
        db.close()


def test_real_one_pass_pair_comparison_is_read_only_and_network_free(monkeypatch):
    left, right, extra = _settled(), _settled(), _settled()
    _settled(product_id=left["product"], program_id=left["program"])
    db, calls, outside = _session(), {"m11a5b": 0, "m11a4": 0, "m11a3": 0, "m11a2": 0, "m11a1": 0}, []
    import app.services.economic_candidate_comparison_service as module
    import app.services.eligible_economic_candidate_service as economic_module
    real = module.EligibleEconomicCandidateService
    real_signal, real_evidence = economic_module.OperatingProfitSignalService, economic_module.OperatingProfitEvidenceService
    real_eligibility, real_candidates = economic_module.OperatingProfitEvidenceEligibilityService, economic_module.EligibleOperatingProfitCandidateSetService
    class Signal:
        def __init__(self, value): self.delegate = real_signal(value)
        def project(self, value): calls["m11a1"] += 1; return self.delegate.project(value)
    class Evidence:
        def __init__(self, value, *, signal_service=None): self.delegate = real_evidence(value, signal_service=signal_service)
        def project(self, value): calls["m11a2"] += 1; return self.delegate.project(value)
    class Eligibility:
        def __init__(self, value, *, evidence_service=None): self.delegate = real_eligibility(value, evidence_service=evidence_service)
        def project(self, value): calls["m11a3"] += 1; return self.delegate.project(value)
    class CandidateSet:
        def __init__(self, value, *, eligibility_service=None): self.delegate = real_candidates(value, eligibility_service=eligibility_service)
        def project(self, value): calls["m11a4"] += 1; return self.delegate.project(value)
    class Candidates:
        def __init__(self, value): self.delegate = real(value)
        def project(self, value): calls["m11a5b"] += 1; return self.delegate.project(value)
    monkeypatch.setattr(economic_module, "OperatingProfitSignalService", Signal)
    monkeypatch.setattr(economic_module, "OperatingProfitEvidenceService", Evidence)
    monkeypatch.setattr(economic_module, "OperatingProfitEvidenceEligibilityService", Eligibility)
    monkeypatch.setattr(economic_module, "EligibleOperatingProfitCandidateSetService", CandidateSet)
    monkeypatch.setattr(module, "EligibleEconomicCandidateService", Candidates)
    engine, inside = db.get_bind(), [False]
    event.listen(engine, "before_cursor_execute", lambda *_args: outside.append(_args[2]) if not inside[0] else None)
    monkeypatch.setattr(requests.sessions.Session, "request", _network_forbidden); monkeypatch.setattr(httpx.Client, "request", _network_forbidden)
    try:
        service = module.EconomicCandidateComparisonService(db)
        assert outside == []
        inside[0] = True
        try:
            result = service.project(_request(left["program"], right["program"]))
        finally:
            inside[0] = False
        assert calls == {"m11a5b": 1, "m11a4": 1, "m11a3": 1, "m11a2": 1, "m11a1": 1}
        assert outside == [] and extra["program"] != left["program"]
        assert result.relation is EconomicCandidatePairwiseRelation.LEFT_PREFERRED
        assert isinstance(result.left_operating_profit, Decimal) and result.left_operating_profit > result.right_operating_profit
        assert db.execute(text("SHOW transaction_isolation")).scalar_one() == "repeatable read"
        assert db.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
        with pytest.raises(Exception): db.execute(text("CREATE TABLE m11a6_forbidden_write (id integer)"))
        db.rollback()
    finally:
        db.close()


def test_orientation_missing_duplicate_and_snapshot_are_fail_closed_or_stable():
    left, right = _settled(), _settled()
    _settled(product_id=left["product"], program_id=left["program"])
    reader = _session()
    try:
        service = EconomicCandidateComparisonService(reader)
        first = service.project(_request(left["program"], right["program"]))
        reverse = service.project(_request(right["program"], left["program"]))
        assert first.relation is EconomicCandidatePairwiseRelation.LEFT_PREFERRED
        assert reverse.relation is EconomicCandidatePairwiseRelation.RIGHT_PREFERRED
        with pytest.raises(ValueError, match="right"):
            service.project(_request(left["program"], -1))
        before = (first.left_operating_profit, first.right_operating_profit)
        _settled(product_id=right["product"], program_id=right["program"])
        same = service.project(_request(left["program"], right["program"]))
        assert (same.left_operating_profit, same.right_operating_profit) == before
    finally:
        reader.close()
    fresh = _session()
    try:
        result = EconomicCandidateComparisonService(fresh).project(_request(left["program"], right["program"]))
        assert result.relation is EconomicCandidatePairwiseRelation.TIE
    finally:
        fresh.close()


def test_a_b_a_c_snapshot_comparison_inverts_only_for_a_fresh_reader():
    left, right = _settled(), _settled()
    _settled(product_id=left["product"], program_id=left["program"])
    reader = _session()
    try:
        service = EconomicCandidateComparisonService(reader)
        before = service.project(_request(left["program"], right["program"]))
        assert before.relation is EconomicCandidatePairwiseRelation.LEFT_PREFERRED
        original = (before.left_operating_profit, before.right_operating_profit)
        _settled(product_id=right["product"], program_id=right["program"])
        _settled(product_id=right["product"], program_id=right["program"])
        same = service.project(_request(left["program"], right["program"]))
        assert same.relation is EconomicCandidatePairwiseRelation.LEFT_PREFERRED
        assert (same.left_operating_profit, same.right_operating_profit) == original
    finally:
        reader.close()
    fresh = _session()
    try:
        result = EconomicCandidateComparisonService(fresh).project(_request(left["program"], right["program"]))
        assert result.relation is EconomicCandidatePairwiseRelation.RIGHT_PREFERRED
        assert isinstance(result.left_operating_profit, Decimal)
        assert isinstance(result.right_operating_profit, Decimal)
        assert result.right_operating_profit > result.left_operating_profit
    finally:
        fresh.close()


def test_local_invalid_duplicate_and_missing_members_fail_closed_without_sql():
    row = EligibleEconomicCandidateRow("USD", (("affiliate_program", 1),), Decimal("1"), datetime(2100, 1, 1, tzinfo=timezone.utc), "qualification", OperatingProfitEvidenceEligibilityPolicy("qualification", 1, 1, 1).fingerprint(), "op", "signal", "v", "evidence", "v", "eligibility", "v", "set", "v")
    class Invalid:
        def __init__(self, rows): self.rows = rows
        def project(self, request): return self.rows
    with pytest.raises(ValueError, match="duplicate"):
        EconomicCandidateComparisonService(None, economic_candidate_service=Invalid((row, row))).project(_request(1, 2))
    with pytest.raises(ValueError, match="right"):
        EconomicCandidateComparisonService(None, economic_candidate_service=Invalid((row,))).project(_request(1, 2))
