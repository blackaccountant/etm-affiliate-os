"""Guarded real-PostgreSQL qualification for M10A4 earning linkage."""

from concurrent.futures import ThreadPoolExecutor
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

from app.attribution.earning_linkage_contracts import EARNING_LINK_SOURCE_NAMESPACE, earning_link_digest
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_conversion import AffiliateConversion
from app.models.affiliate_earning import AffiliateEarning
from app.models.affiliate_link import AffiliateLink
from app.models.affiliate_program import AffiliateProgram
from app.models.attribution import AttributionFact
from app.models.attribution_earning_link import AttributionEarningLink
from app.models.product import Product
from app.models.publishing_queue import PublishingQueue
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_publication_service import AttributionPublicationService


REVISION = "c5d6e7f8a9b0"
DATABASE = "etm_g5_m10a4_qualification"
raw_url = os.getenv("ETM_G5_DATABASE_URL")
if not raw_url:
    pytest.skip("Requires guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
url = make_url(raw_url)
if not (
    url.drivername.startswith("postgresql") and url.host == "127.0.0.1"
    and url.port == 5432 and url.database == DATABASE
):
    raise RuntimeError("M10A4 qualification requires the dedicated local PostgreSQL database")

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
            name=f"M10A4 {token}", website=f"https://{token}.invalid", category="test",
            affiliate_program="yes", commission_type="percentage", commission_value="10",
            affiliate_score=1, grade="A", confidence=100, summary="", recommendation="", status="active",
        )
        db.add(product); db.flush()
        program = AffiliateProgram(
            product_id=product.id, program_name=f"program-{token}",
            commission_type="percentage", commission_value="10", status="active",
        )
        db.add(program); db.flush()
        asset = AffiliateContentAsset(product_id=product.id, asset_type="article", title="M10A4")
        db.add(asset); db.flush()
        queue = PublishingQueue(content_asset_id=asset.id, channel=f"m10a4-{token}")
        db.add(queue); db.flush()
        publication = AttributionPublicationService(db).bind_legacy(queue.id)
        context = AttributionContextService(db).create(
            affiliate_program_id=program.id, attribution_publication_id=publication.id,
        )
        db.commit()
        link = AttributionLinkBridgeService(db).create_bound_link(
            affiliate_program_id=program.id, attribution_context_id=context.id,
            name="M10A4", destination_url="https://destination.invalid", content_asset_id=asset.id,
        )
        result = AttributionConversionBridgeService(db).record(
            affiliate_program_id=program.id, affiliate_link_id=link.id,
            external_conversion_id=f"conversion-{token}", sale_amount=Decimal("100.00"),
            commission_rate=Decimal("10"),
        )
        fact = result["fact"]
        return {
            "program": program.id, "link": link.id, "conversion": result["conversion"].id,
            "earning": result["earning"].id, "fact": fact.id,
        }
    finally:
        db.close()


def _financial_snapshot(ids):
    db = Session()
    try:
        conversion = db.get(AffiliateConversion, ids["conversion"])
        earning = db.get(AffiliateEarning, ids["earning"])
        return (
            conversion.sale_amount, conversion.commission_amount, conversion.conversion_status,
            earning.gross_amount, earning.commission_amount, earning.status, earning.payout_id,
        )
    finally:
        db.close()


def test_schema_reference_only_replay_and_cross_domain_protection():
    ids = _foundation()
    before = _financial_snapshot(ids)
    db = Session()
    try:
        service = AttributionEarningLinkService(db)
        first = service.reconcile(attribution_fact_id=ids["fact"])
        second = service.reconcile(attribution_fact_id=ids["fact"])
        assert first.id == second.id
        assert first.affiliate_conversion_id == ids["conversion"]
        assert first.affiliate_earning_id == ids["earning"]
        assert db.query(AttributionEarningLink).filter_by(attribution_fact_id=ids["fact"]).count() == 1
    finally:
        db.close()
    assert _financial_snapshot(ids) == before

    inspector = inspect(engine)
    columns = {item["name"] for item in inspector.get_columns("attribution_earning_links")}
    assert not columns & {"sale_amount", "commission_amount", "currency", "status", "customer_reference"}
    assert "uq_attribution_earning_links_conversion" in {
        item["name"] for item in inspector.get_unique_constraints("attribution_earning_links")
    }
    digest = earning_link_digest(
        attribution_fact_id=ids["fact"], affiliate_conversion_id=ids["conversion"],
        affiliate_earning_id=ids["earning"],
    )
    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(DBAPIError):
            connection.execute(text("""
                INSERT INTO attribution_earning_links(
                    id,attribution_fact_id,affiliate_conversion_id,affiliate_earning_id,
                    source_namespace,source_event_key_digest,linkage_fingerprint,observed_at,recorded_at
                ) VALUES (:id,:fact,:conversion,:earning,:namespace,:digest,:fingerprint,now(),now())
            """), {
                "id": str(uuid4()), "fact": ids["fact"], "conversion": ids["conversion"],
                "earning": ids["earning"], "namespace": EARNING_LINK_SOURCE_NAMESPACE,
                "digest": "b" * 64, "fingerprint": "c" * 64,
            })
        transaction.rollback()
    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(DBAPIError):
            connection.execute(text("""
                UPDATE attribution_earning_links SET affiliate_earning_id=:earning
                WHERE attribution_fact_id=:fact
            """), {"earning": ids["earning"] + 100000, "fact": ids["fact"]})
        transaction.rollback()


def test_missing_ambiguous_concurrent_and_failure_rollback(monkeypatch):
    missing = _foundation()
    db = Session()
    try:
        db.query(AffiliateEarning).filter_by(id=missing["earning"]).delete()
        db.commit()
    finally:
        db.close()
    db = Session()
    try:
        with pytest.raises(ValueError, match="does not exist"):
            AttributionEarningLinkService(db).reconcile(attribution_fact_id=missing["fact"])
    finally:
        db.close()

    ambiguous = _foundation()
    db = Session()
    try:
        original = db.get(AffiliateEarning, ambiguous["earning"])
        db.add(AffiliateEarning(
            conversion_id=ambiguous["conversion"], affiliate_program_id=ambiguous["program"],
            gross_amount=original.gross_amount, commission_rate=original.commission_rate,
            commission_amount=original.commission_amount, currency=original.currency, status="approved",
        ))
        db.commit()
        with pytest.raises(ValueError, match="ambiguous"):
            AttributionEarningLinkService(db).reconcile(attribution_fact_id=ambiguous["fact"])
    finally:
        db.close()

    ids = _foundation()
    before = _financial_snapshot(ids)
    def reconcile_once():
        local = Session()
        try:
            return AttributionEarningLinkService(local).reconcile(attribution_fact_id=ids["fact"]).id
        finally:
            local.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(lambda _value: reconcile_once(), range(2)))) == 1
    db = Session()
    try:
        assert db.query(AttributionEarningLink).filter_by(attribution_fact_id=ids["fact"]).count() == 1
    finally:
        db.close()
    assert _financial_snapshot(ids) == before

    failed = _foundation()
    before_failed = _financial_snapshot(failed)
    db = Session()
    try:
        service = AttributionEarningLinkService(db)
        monkeypatch.setattr(service.links, "create", lambda _link: (_ for _ in ()).throw(RuntimeError("injected")))
        with pytest.raises(RuntimeError, match="injected"):
            service.reconcile(attribution_fact_id=failed["fact"])
    finally:
        db.close()
    db = Session()
    try:
        assert db.query(AttributionEarningLink).filter_by(attribution_fact_id=failed["fact"]).count() == 0
    finally:
        db.close()
    assert _financial_snapshot(failed) == before_failed


def test_populated_upgrade_downgrade_and_unowned_object_preservation():
    ids = _foundation()
    db = Session()
    try:
        AttributionEarningLinkService(db).reconcile(attribution_fact_id=ids["fact"])
    finally:
        db.close()
    config = Config("alembic.ini")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE OR REPLACE FUNCTION m10a4_unowned_probe() RETURNS integer
            LANGUAGE sql AS $$ SELECT 42 $$
        """))
    command.downgrade(config, "b4c5d6e7f8a9")
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == "b4c5d6e7f8a9"
        assert "attribution_earning_links" not in inspect(connection).get_table_names()
        assert connection.execute(text("SELECT m10a4_unowned_probe()")).scalar_one() == 42
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == REVISION
        assert "attribution_earning_links" in inspect(connection).get_table_names()
        assert connection.execute(text("SELECT m10a4_unowned_probe()")).scalar_one() == 42
