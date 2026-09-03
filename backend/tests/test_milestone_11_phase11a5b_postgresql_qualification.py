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
from app.services.eligible_economic_candidate_service import EligibleEconomicCandidateService


ROLE, RAW = os.getenv("ETM_G5_M11A5B_DB_ROLE"), os.getenv("ETM_G5_M11A5B_DATABASE_URL")
if not RAW:
    pytest.skip("requires guarded M11A5B URL", allow_module_level=True)
URL = make_url(RAW)
if ROLE != "qualification" or not URL.drivername.startswith("postgresql") or URL.host != "127.0.0.1" or URL.port != 5432 or URL.database != "etm_g5_m11a5b_economic_candidate_qualification":
    raise RuntimeError("M11A5B database guard failed")


def _session():
    return sessionmaker(bind=create_engine(URL.render_as_string(hide_password=False)), expire_on_commit=False)()


def _request(minimum=1, currency="USD"):
    return EligibleOperatingProfitCandidateSetRequest(
        ("affiliate_program",), currency,
        OperatingProfitEvidenceEligibilityPolicy("qualification", minimum, minimum, minimum),
        datetime(2100, 1, 1, tzinfo=timezone.utc),
    )


def _ids(rows):
    return {dict(row.dimensions)["affiliate_program"] for row in rows}


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


def _network_forbidden(*_args, **_kwargs):
    raise AssertionError("network called")


def test_current_head_requires_no_m11a5b_migration():
    db = _session()
    try: assert MigrationContext.configure(db.connection()).get_current_revision() == "c3d4e5f6a7b8"
    finally: db.close()


def test_real_one_pass_decimal_read_only_and_network_free(monkeypatch):
    identity = _settled()
    db, calls, outside = _session(), {"m11a1": 0, "m11a2": 0, "m11a3": 0, "m11a4": 0}, []
    import app.services.eligible_economic_candidate_service as module
    real_signal, real_evidence, real_eligibility, real_candidates = module.OperatingProfitSignalService, module.OperatingProfitEvidenceService, module.OperatingProfitEvidenceEligibilityService, module.EligibleOperatingProfitCandidateSetService
    class Signal:
        def __init__(self, value): self.delegate = real_signal(value)
        def project(self, value): calls["m11a1"] += 1; self.rows = self.delegate.project(value); return self.rows
    class Evidence:
        def __init__(self, value, *, signal_service=None): self.delegate = real_evidence(value, signal_service=signal_service)
        def project(self, value): calls["m11a2"] += 1; return self.delegate.project(value)
    class Eligibility:
        def __init__(self, value, *, evidence_service=None): self.delegate = real_eligibility(value, evidence_service=evidence_service)
        def project(self, value): calls["m11a3"] += 1; return self.delegate.project(value)
    class Candidates:
        def __init__(self, value, *, eligibility_service=None): self.delegate = real_candidates(value, eligibility_service=eligibility_service)
        def project(self, value): calls["m11a4"] += 1; return self.delegate.project(value)
    monkeypatch.setattr(module, "OperatingProfitSignalService", Signal); monkeypatch.setattr(module, "OperatingProfitEvidenceService", Evidence)
    monkeypatch.setattr(module, "OperatingProfitEvidenceEligibilityService", Eligibility); monkeypatch.setattr(module, "EligibleOperatingProfitCandidateSetService", Candidates)
    engine = db.get_bind(); inside = [False]
    event.listen(engine, "before_cursor_execute", lambda *_args: outside.append(_args[2]) if not inside[0] else None)
    monkeypatch.setattr(requests.sessions.Session, "request", _network_forbidden); monkeypatch.setattr(httpx.Client, "request", _network_forbidden)
    try:
        service = module.EligibleEconomicCandidateService(db); assert outside == []
        inside[0] = True
        try: rows = service.project(_request())
        finally: inside[0] = False
        assert identity["program"] in _ids(rows) and calls == {"m11a1": 1, "m11a2": 1, "m11a3": 1, "m11a4": 1} and outside == []
        row = next(row for row in rows if dict(row.dimensions)["affiliate_program"] == identity["program"])
        captured = service._capture._delegate.rows
        signal = next(signal for signal in captured if signal.dimensions == row.dimensions)
        assert isinstance(row.operating_profit, Decimal) and row.operating_profit is signal.operating_profit
        assert db.execute(text("SHOW transaction_isolation")).scalar_one() == "repeatable read"
        assert db.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
        with pytest.raises(Exception): db.execute(text("CREATE TABLE m11a5b_forbidden_write (id integer)"))
        db.rollback()
    finally: db.close()


def test_extra_ineligible_signal_is_omitted_currency_isolated_and_capture_resets():
    eligible, ineligible, eur = _settled(), _settled(), _settled(currency="EUR")
    _settled(product_id=eligible["product"], program_id=eligible["program"])
    db = _session()
    try:
        service = EligibleEconomicCandidateService(db)
        first = service.project(_request(2)); second = service.project(_request(2))
        assert _ids(first) == _ids(second) and eligible["program"] in _ids(first) and ineligible["program"] not in _ids(first)
    finally: db.close()
    eur_db = _session()
    try:
        rows = EligibleEconomicCandidateService(eur_db).project(_request(1, "EUR"))
        assert {row.currency for row in rows} == {"EUR"} and eur["program"] in _ids(rows)
    finally: eur_db.close()


def test_a_b_a_c_snapshot_association():
    first, second = _settled(), _settled()
    _settled(product_id=first["product"], program_id=first["program"])
    request = _request(2); reader = _session()
    try:
        service = EligibleEconomicCandidateService(reader); before = service.project(request)
        assert first["program"] in _ids(before) and second["program"] not in _ids(before)
        original = next(row.operating_profit for row in before if dict(row.dimensions)["affiliate_program"] == first["program"])
        _settled(product_id=second["product"], program_id=second["program"])
        same = service.project(request)
        assert _ids(same) == _ids(before) and next(row.operating_profit for row in same if dict(row.dimensions)["affiliate_program"] == first["program"]) == original
    finally: reader.close()
    fresh = _session()
    try:
        rows = EligibleEconomicCandidateService(fresh).project(request)
        assert _ids(rows) == _ids(before) | {second["program"]}
    finally: fresh.close()
