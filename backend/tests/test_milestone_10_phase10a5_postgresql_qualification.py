"""Guarded real-PostgreSQL qualification for M10A5 payout settlement linkage."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_earning import AffiliateEarning
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.affiliate_program import AffiliateProgram
from app.models.attribution_payout_settlement_link import AttributionPayoutSettlementLink
from app.models.product import Product
from app.models.publishing_queue import PublishingQueue
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_payout_settlement_link_service import AttributionPayoutSettlementLinkService
from app.services.attribution_publication_service import AttributionPublicationService
from app.services.affiliate_payout_service import AffiliatePayoutService


REVISION = "d6e7f8a9b0c1"
DATABASE = "etm_g5_m10a5_qualification"
raw_url = os.getenv("ETM_G5_DATABASE_URL")
if not raw_url:
    pytest.skip("Requires guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
url = make_url(raw_url)
if not (
    url.drivername.startswith("postgresql") and url.host == "127.0.0.1"
    and url.port == 5432 and url.database == DATABASE
):
    raise RuntimeError("M10A5 qualification requires the dedicated local PostgreSQL database")

engine = create_engine(url.render_as_string(hide_password=False), pool_pre_ping=True)
Session = sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(scope="module", autouse=True)
def guarded_schema():
    with engine.connect() as connection:
        assert connection.execute(text("SELECT current_database()")).scalar_one() == DATABASE
        assert MigrationContext.configure(connection).get_current_revision() == REVISION
    yield
    engine.dispose()


def _foundation():
    db = Session()
    try:
        token = uuid4().hex
        product = Product(
            name=f"M10A5 {token}", website=f"https://{token}.invalid", category="test",
            affiliate_program="yes", commission_type="percentage", commission_value="10",
            affiliate_score=1, grade="A", confidence=100, summary="", recommendation="", status="active",
        )
        db.add(product); db.flush()
        program = AffiliateProgram(
            product_id=product.id, program_name=f"program-{token}",
            commission_type="percentage", commission_value="10", status="active",
        )
        db.add(program); db.flush()
        asset = AffiliateContentAsset(product_id=product.id, asset_type="article", title="M10A5")
        db.add(asset); db.flush()
        queue = PublishingQueue(content_asset_id=asset.id, channel=f"m10a5-{token}")
        db.add(queue); db.flush()
        publication = AttributionPublicationService(db).bind_legacy(queue.id)
        context = AttributionContextService(db).create(
            affiliate_program_id=program.id, attribution_publication_id=publication.id,
        )
        db.commit()
        link = AttributionLinkBridgeService(db).create_bound_link(
            affiliate_program_id=program.id, attribution_context_id=context.id, name="M10A5",
            destination_url="https://destination.invalid", content_asset_id=asset.id,
        )
        result = AttributionConversionBridgeService(db).record(
            affiliate_program_id=program.id, affiliate_link_id=link.id,
            external_conversion_id=f"conversion-{token}", sale_amount=Decimal("100.00"),
            commission_rate=Decimal("10"),
        )
        earning_link = AttributionEarningLinkService(db).reconcile(attribution_fact_id=result["fact"].id)
        return {"earning": result["earning"].id, "earning_link": earning_link.id, "program": program.id}
    finally:
        db.close()


def _settle(ids, *, failed_first=False):
    db = Session()
    try:
        earning = db.get(AffiliateEarning, ids["earning"])
        now = datetime.now(timezone.utc)
        payout = AffiliatePayout(
            affiliate_program_id=ids["program"], total_amount=earning.commission_amount,
            currency=earning.currency, status="paid", paid_at=now, created_at=now, updated_at=now,
        )
        db.add(payout); db.flush()
        earning.payout_id = payout.id; earning.status = "paid"; earning.paid_at = now; earning.updated_at = now
        if failed_first:
            db.add(AffiliatePayoutAttempt(
                payout_id=payout.id, attempt_number=1, amount=payout.total_amount, currency=payout.currency,
                status="failed", provider="manual", idempotency_key=f"failed-{uuid4().hex}",
                failure_reason="test", started_at=now, completed_at=now, created_at=now, updated_at=now,
            ))
        attempt = AffiliatePayoutAttempt(
            payout_id=payout.id, attempt_number=2 if failed_first else 1, amount=payout.total_amount,
            currency=payout.currency, status="completed", provider="manual", idempotency_key=f"done-{uuid4().hex}",
            started_at=now, completed_at=now, created_at=now, updated_at=now,
        )
        db.add(attempt); db.commit(); return payout.id, attempt.id
    finally:
        db.close()


def _financial_snapshot(ids):
    db = Session()
    try:
        earning = db.get(AffiliateEarning, ids["earning"])
        return earning.status, earning.payout_id, earning.paid_at
    finally:
        db.close()


def test_valid_replay_schema_privacy_and_aware_utc_roundtrip():
    ids = _foundation(); payout_id, attempt_id = _settle(ids)
    before = _financial_snapshot(ids)
    db = Session()
    try:
        service = AttributionPayoutSettlementLinkService(db)
        first = service.reconcile(attribution_earning_link_id=ids["earning_link"])
        second = service.reconcile(attribution_earning_link_id=ids["earning_link"])
        assert first.id == second.id
        assert (first.affiliate_earning_id, first.affiliate_payout_id, first.affiliate_payout_attempt_id) == (ids["earning"], payout_id, attempt_id)
    finally:
        db.close()
    assert _financial_snapshot(ids) == before
    db = Session()
    try:
        persisted = db.query(AttributionPayoutSettlementLink).filter_by(attribution_earning_link_id=ids["earning_link"]).one()
        assert persisted.observed_at.tzinfo is not None and persisted.observed_at.utcoffset() == timezone.utc.utcoffset(persisted.observed_at)
        assert persisted.recorded_at.tzinfo is not None and persisted.recorded_at.utcoffset() == timezone.utc.utcoffset(persisted.recorded_at)
    finally:
        db.close()
    columns = {item["name"] for item in inspect(engine).get_columns("attribution_payout_settlement_links")}
    assert not columns & {"commission_amount", "total_amount", "currency", "status", "provider_reference", "payout_reference"}


def test_unsettled_manual_failed_retry_and_failure_rollback(monkeypatch):
    pending = _foundation()
    db = Session()
    try:
        with pytest.raises(ValueError, match="no payout settlement"):
            AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=pending["earning_link"])
    finally:
        db.close()
    payout_id, attempt_id = _settle(pending, failed_first=True)
    db = Session()
    try:
        link = AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=pending["earning_link"])
        assert link.affiliate_payout_id == payout_id and link.affiliate_payout_attempt_id == attempt_id
    finally:
        db.close()

    injected = _foundation(); _settle(injected)
    before = _financial_snapshot(injected)
    db = Session()
    try:
        service = AttributionPayoutSettlementLinkService(db)
        monkeypatch.setattr(service.links, "create", lambda _link: (_ for _ in ()).throw(RuntimeError("injected")))
        with pytest.raises(RuntimeError, match="injected"):
            service.reconcile(attribution_earning_link_id=injected["earning_link"])
    finally:
        db.close()
    db = Session()
    try:
        assert db.query(AttributionPayoutSettlementLink).filter_by(attribution_earning_link_id=injected["earning_link"]).count() == 0
    finally:
        db.close()
    assert _financial_snapshot(injected) == before


def test_constraints_conflict_concurrency_and_completion_race():
    ids = _foundation()
    db = Session()
    try:
        with pytest.raises(ValueError, match="no payout settlement"):
            AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=ids["earning_link"])
    finally:
        db.close()
    payout_id, attempt_id = _settle(ids)

    def reconcile_once():
        local = Session()
        try:
            return AttributionPayoutSettlementLinkService(local).reconcile(
                attribution_earning_link_id=ids["earning_link"],
            ).id
        finally:
            local.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(lambda _value: reconcile_once(), range(2)))) == 1
    db = Session()
    try:
        row = db.query(AttributionPayoutSettlementLink).filter_by(attribution_earning_link_id=ids["earning_link"]).one()
        assert row.affiliate_payout_id == payout_id and row.affiliate_payout_attempt_id == attempt_id
    finally:
        db.close()
    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(DBAPIError):
            connection.execute(text("""
                UPDATE attribution_payout_settlement_links SET affiliate_payout_attempt_id=:attempt
                WHERE attribution_earning_link_id=:earning_link
            """), {"attempt": attempt_id + 100000, "earning_link": ids["earning_link"]})
        transaction.rollback()


def test_rejects_manual_paid_unsettled_states_ambiguity_and_mismatched_lineage():
    manual = _foundation()
    db = Session()
    try:
        earning = db.get(AffiliateEarning, manual["earning"])
        earning.status = "paid"; earning.payout_reference = "legacy-manual"; earning.paid_at = datetime.now(timezone.utc)
        db.commit()
        with pytest.raises(ValueError, match="no payout settlement"):
            AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=manual["earning_link"])
    finally:
        db.close()

    states = _foundation()
    db = Session()
    try:
        earning = db.get(AffiliateEarning, states["earning"])
        now = datetime.now(timezone.utc)
        payout = AffiliatePayout(
            affiliate_program_id=states["program"], total_amount=earning.commission_amount,
            currency=earning.currency, status="pending", created_at=now, updated_at=now,
        )
        db.add(payout); db.flush(); earning.payout_id = payout.id; earning.status = "approved"; db.commit()
        service = AttributionPayoutSettlementLinkService(db)
        with pytest.raises(ValueError, match="not complete"):
            service.reconcile(attribution_earning_link_id=states["earning_link"])
        payout.status = "processing"; earning.status = "paid"; db.commit()
        with pytest.raises(ValueError, match="not complete"):
            service.reconcile(attribution_earning_link_id=states["earning_link"])
        payout.status = "failed"; db.commit()
        with pytest.raises(ValueError, match="not complete"):
            service.reconcile(attribution_earning_link_id=states["earning_link"])
    finally:
        db.close()

    ambiguous = _foundation(); payout_id, _attempt_id = _settle(ambiguous)
    db = Session()
    try:
        payout = db.get(AffiliatePayout, payout_id); now = datetime.now(timezone.utc)
        db.add(AffiliatePayoutAttempt(
            payout_id=payout.id, attempt_number=2, amount=payout.total_amount, currency=payout.currency,
            status="completed", provider="manual", idempotency_key=f"ambiguous-{uuid4().hex}",
            started_at=now, completed_at=now, created_at=now, updated_at=now,
        ))
        db.commit()
        with pytest.raises(ValueError, match="ambiguous"):
            AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=ambiguous["earning_link"])
    finally:
        db.close()

    valid = _foundation(); payout_id, attempt_id = _settle(valid)
    db = Session()
    try:
        earning = db.get(AffiliateEarning, valid["earning"]); now = datetime.now(timezone.utc)
        other = AffiliatePayout(
            affiliate_program_id=valid["program"], total_amount=earning.commission_amount,
            currency=earning.currency, status="paid", paid_at=now, created_at=now, updated_at=now,
        )
        db.add(other); db.flush()
        other_attempt = AffiliatePayoutAttempt(
            payout_id=other.id, attempt_number=1, amount=other.total_amount, currency=other.currency,
            status="completed", provider="manual", idempotency_key=f"other-{uuid4().hex}",
            started_at=now, completed_at=now, created_at=now, updated_at=now,
        )
        db.add(other_attempt); db.commit()
    finally:
        db.close()
    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(DBAPIError):
            connection.execute(text("""
                INSERT INTO attribution_payout_settlement_links(
                    id,attribution_earning_link_id,affiliate_earning_id,affiliate_payout_id,
                    affiliate_payout_attempt_id,source_namespace,source_event_key_digest,
                    linkage_fingerprint,observed_at,recorded_at
                ) VALUES (:id,:link,:earning,:payout,:attempt,'m10a5.payout-settlement',:digest,:fingerprint,now(),now())
            """), {
                "id": str(uuid4()), "link": valid["earning_link"], "earning": valid["earning"],
                "payout": other.id, "attempt": other_attempt.id, "digest": "a" * 64, "fingerprint": "b" * 64,
            })
        transaction.rollback()


def test_existing_payout_failure_retry_completion_remains_compatible():
    ids = _foundation()
    db = Session()
    try:
        payouts = AffiliatePayoutService(db)
        payout = payouts.create_payout(affiliate_program_id=ids["program"])
        payouts.process_payout(payout.id, idempotency_key=f"process-{uuid4().hex}")
        payouts.fail_payout(payout.id)
        assert db.get(AffiliatePayout, payout.id).status == "failed"
        payouts.retry_payout(payout.id, idempotency_key=f"retry-{uuid4().hex}")
        completed = payouts.complete_payout(payout.id, payout_reference="test-reference")
        assert completed.status == "paid"
        settlement = AttributionPayoutSettlementLinkService(db).reconcile(
            attribution_earning_link_id=ids["earning_link"],
        )
        assert settlement.affiliate_payout_id == payout.id
        attempts = db.query(AffiliatePayoutAttempt).filter_by(payout_id=payout.id).all()
        assert sorted(attempt.status for attempt in attempts) == ["completed", "failed"]
    finally:
        db.close()


def test_populated_upgrade_downgrade_and_unowned_object_preservation():
    _settle(_foundation())
    config = Config("alembic.ini")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE OR REPLACE FUNCTION m10a5_unowned_probe() RETURNS integer
            LANGUAGE sql AS $$ SELECT 42 $$
        """))
    command.downgrade(config, "c5d6e7f8a9b0")
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == "c5d6e7f8a9b0"
        assert "attribution_payout_settlement_links" not in inspect(connection).get_table_names()
        assert connection.execute(text("SELECT m10a5_unowned_probe()")).scalar_one() == 42
    command.upgrade(config, "d6e7f8a9b0c1")
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == REVISION
        assert "attribution_payout_settlement_links" in inspect(connection).get_table_names()
        assert connection.execute(text("SELECT m10a5_unowned_probe()")).scalar_one() == 42
