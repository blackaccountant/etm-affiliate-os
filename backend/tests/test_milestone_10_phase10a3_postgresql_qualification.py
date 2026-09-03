"""Guarded real-PostgreSQL qualification of the M10A3 public bridge."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import os
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.attribution.bridge_contracts import (
    CLICK_SOURCE_NAMESPACE,
    LINK_SOURCE_NAMESPACE,
    click_event_digest,
    link_binding_digest,
)
from app.models.affiliate_click import AffiliateClick
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_conversion import AffiliateConversion
from app.models.affiliate_earning import AffiliateEarning
from app.models.affiliate_link import AffiliateLink
from app.models.affiliate_program import AffiliateProgram
from app.models.attribution import AttributionClick, AttributionFact
from app.models.product import Product
from app.models.publishing_queue import PublishingQueue
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_publication_service import AttributionPublicationService
from app.services.attribution_redirect_bridge_service import AttributionRedirectBridgeService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService


REVISION = "b4c5d6e7f8a9"
DATABASE = "etm_g5_m10a3_qualification"
raw_url = os.getenv("ETM_G5_DATABASE_URL")
if not raw_url:
    pytest.skip("Requires guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
url = make_url(raw_url)
if not (
    url.drivername.startswith("postgresql") and url.host == "127.0.0.1"
    and url.port == 5432 and url.database == DATABASE
):
    raise RuntimeError("M10A3 qualification requires the dedicated local PostgreSQL database")

engine = create_engine(url.render_as_string(hide_password=False), pool_pre_ping=True)
Session = sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(scope="module", autouse=True)
def guarded_schema():
    with engine.connect() as connection:
        assert connection.execute(text("SELECT current_database()")).scalar_one() == DATABASE
        assert MigrationContext.configure(connection).get_current_revision() == REVISION
    yield
    engine.dispose()


def _foundation(db):
    token = uuid4().hex
    product = Product(
        name=f"M10A3 {token}", website=f"https://{token}.invalid", category="test",
        affiliate_program="yes", commission_type="percentage", commission_value="10",
        affiliate_score=1, grade="A", confidence=100, summary="", recommendation="", status="active",
    )
    db.add(product); db.flush()
    program = AffiliateProgram(
        product_id=product.id, program_name=f"program-{token}", commission_type="percentage",
        commission_value="10", status="active",
    )
    db.add(program); db.flush()
    asset = AffiliateContentAsset(product_id=product.id, asset_type="article", title="M10A3")
    db.add(asset); db.flush()
    queue = PublishingQueue(content_asset_id=asset.id, channel=f"m10a3-{token}")
    db.add(queue); db.flush()
    publication = AttributionPublicationService(db).bind_legacy(queue.id)
    context = AttributionContextService(db).create(
        affiliate_program_id=program.id, attribution_publication_id=publication.id,
    )
    db.commit()
    return program.id, asset.id, context.id


def _new_link(program_id, asset_id, context_id):
    db = Session()
    try:
        link = AttributionLinkBridgeService(db).create_bound_link(
            affiliate_program_id=program_id, attribution_context_id=context_id,
            name="bridge", destination_url="https://destination.invalid", content_asset_id=asset_id,
        )
        return link.id, link.tracking_code
    finally:
        db.close()


def _counts(link_id):
    db = Session()
    try:
        return {
            "legacy_click": db.query(AffiliateClick).filter_by(affiliate_link_id=link_id).count(),
            "attribution_click": db.query(AttributionClick).filter_by(affiliate_link_id=link_id).count(),
            "click_fact": db.query(AttributionFact).filter_by(fact_kind="CLICK_RECORDED", affiliate_link_id=link_id).count(),
            "conversion": db.query(AffiliateConversion).filter_by(affiliate_link_id=link_id).count(),
            "earning": db.query(AffiliateEarning).join(AffiliateConversion).filter(AffiliateConversion.affiliate_link_id == link_id).count(),
            "conversion_fact": db.query(AttributionFact).filter_by(fact_kind="CONVERSION_REPORTED", affiliate_link_id=link_id).count(),
        }
    finally:
        db.close()


def test_bridge_schema_constraints_and_immutability_are_postgresql_owned():
    inspector = inspect(engine)
    assert "attribution_context_id" in {item["name"] for item in inspector.get_columns("affiliate_links")}
    assert "attribution_click_id" in {item["name"] for item in inspector.get_columns("affiliate_clicks")}
    assert "uq_affiliate_clicks_attribution_click_id" in {
        item["name"] for item in inspector.get_unique_constraints("affiliate_clicks")
    }
    with engine.connect() as c:
        names = set(c.execute(text("""
            SELECT proname FROM pg_proc WHERE proname LIKE 'm10a3_reject_%'
        """)).scalars())
        assert names == {
            "m10a3_reject_link_context_rebinding",
            "m10a3_reject_click_correlation_rebinding",
        }

    db = Session()
    try:
        program, asset, context = _foundation(db)
        link_id, _ = _new_link(program, asset, context)
        with pytest.raises(Exception):
            db.execute(text("UPDATE affiliate_links SET attribution_context_id=NULL WHERE id=:id"), {
                "id": link_id,
            })
        db.rollback()
    finally:
        db.close()


def test_binding_replay_conflict_and_real_overlapping_postgresql_contention():
    db = Session()
    try:
        program, asset, first_context = _foundation(db)
        link = AffiliateLink(
            affiliate_program_id=program, content_asset_id=asset, name="unbound",
            destination_url="https://destination.invalid", tracking_code=f"unbound-{uuid4().hex}", is_active=True,
        )
        db.add(link); db.commit(); link_id = link.id
        assert AttributionLinkBridgeService(db).bind_existing(
            affiliate_link_id=link_id, attribution_context_id=first_context,
        )[0].attribution_context_id == first_context
        product_id = db.get(AffiliateProgram, program).product_id
        second_asset = AffiliateContentAsset(
            product_id=product_id, asset_type="article", title="second authority",
        )
        db.add(second_asset); db.flush()
        second_queue = PublishingQueue(
            content_asset_id=second_asset.id, channel=f"m10a3-second-{uuid4().hex}",
        )
        db.add(second_queue); db.flush()
        second_context = AttributionContextService(db).create(
            affiliate_program_id=program,
            attribution_publication_id=AttributionPublicationService(db).bind_legacy(second_queue.id).id,
        )
        db.commit()
        with pytest.raises(Exception, match="different attribution context"):
            AttributionLinkBridgeService(db).bind_existing(
                affiliate_link_id=link_id, attribution_context_id=second_context.id,
            )
    finally:
        db.close()

    # Two independent sessions contend on the same advisory identity; only one durable LINK_BOUND fact exists.
    barrier = Barrier(2)
    def bind_same():
        local = Session()
        try:
            barrier.wait(timeout=10)
            return AttributionLinkBridgeService(local).bind_existing(
                affiliate_link_id=link_id, attribution_context_id=first_context,
            )[0].id
        finally:
            local.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert set(pool.map(lambda _value: bind_same(), range(2))) == {link_id}
    db = Session()
    try:
        assert db.query(AttributionFact).filter_by(fact_kind="LINK_BOUND", affiliate_link_id=link_id).count() == 1
    finally:
        db.close()


def test_click_and_conversion_replay_conflict_overlap_and_atomic_failure_injection(monkeypatch):
    db = Session()
    try:
        program, asset, context = _foundation(db)
    finally:
        db.close()
    link_id, tracking_code = _new_link(program, asset, context)
    event_id = str(uuid4())

    def click():
        local = Session()
        try:
            return AttributionRedirectBridgeService(local).record(
                tracking_code=tracking_code, event_id=event_id,
                ip_address="203.0.113.7", user_agent="private-agent",
            )["attribution_click"].id
        finally:
            local.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(lambda _value: click(), range(2)))) == 1
    assert _counts(link_id) == {
        "legacy_click": 1, "attribution_click": 1, "click_fact": 1,
        "conversion": 0, "earning": 0, "conversion_fact": 0,
    }

    db = Session()
    try:
        attr_click = db.query(AttributionClick).filter_by(affiliate_link_id=link_id).one()
        click_key = attr_click.click_key
    finally:
        db.close()
    external_id = f"conversion-{uuid4()}"
    def conversion():
        local = Session()
        try:
            return AttributionConversionBridgeService(local).record(
                affiliate_program_id=program, affiliate_link_id=link_id,
                external_conversion_id=external_id, sale_amount=Decimal("100.00"),
                commission_rate=Decimal("10"), attribution_click_key=click_key,
            )["conversion"].id
        finally:
            local.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert len(set(pool.map(lambda _value: conversion(), range(2)))) == 1
    assert _counts(link_id) == {
        "legacy_click": 1, "attribution_click": 1, "click_fact": 1,
        "conversion": 1, "earning": 1, "conversion_fact": 1,
    }

    conflicting = Session()
    try:
        with pytest.raises(Exception, match="conflicts"):
            AttributionConversionBridgeService(conflicting).record(
                affiliate_program_id=program, affiliate_link_id=link_id,
                external_conversion_id=external_id, sale_amount=Decimal("101.00"),
                commission_rate=Decimal("10"), attribution_click_key=click_key,
            )
    finally:
        conflicting.close()

    failed_event = str(uuid4())
    # Inject only after click stages: a failing append must roll all three rows back.
    class FailFacts:
        def append(self, **_kwargs):
            raise RuntimeError("injected click-fact failure")
    failing = Session()
    try:
        service = AttributionRedirectBridgeService(failing)
        service.facts = FailFacts()
        with pytest.raises(RuntimeError, match="injected"):
            service.record(tracking_code=tracking_code, event_id=failed_event)
    finally:
        failing.close()
    assert _counts(link_id)["legacy_click"] == 1

    failed_external = f"failed-{uuid4()}"
    failing = Session()
    try:
        service = AttributionConversionBridgeService(failing)
        service.facts = FailFacts()
        with pytest.raises(RuntimeError, match="injected"):
            service.record(
                affiliate_program_id=program, affiliate_link_id=link_id,
                external_conversion_id=failed_external, sale_amount=Decimal("50"),
            )
    finally:
        failing.close()
    db = Session()
    try:
        assert db.query(AffiliateConversion).filter_by(
            affiliate_program_id=program, external_conversion_id=failed_external,
        ).count() == 0
        persisted = " ".join(
            f"{row.source_namespace} {row.source_event_key_digest} {row.source_fingerprint}"
            for row in [*db.query(AttributionClick).all(), *db.query(AttributionFact).all()]
        )
        for forbidden in (event_id, "203.0.113.7", "private-agent", external_id):
            assert forbidden not in persisted
    finally:
        db.close()


def test_migration_upgrade_downgrade_owns_only_m10a3_objects():
    config = Config("alembic.ini")
    with engine.connect() as c:
        before = {
            table: c.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in (
                "affiliate_links", "affiliate_clicks", "attribution_contexts",
                "attribution_clicks", "attribution_facts",
            )
        }
        assert all(count > 0 for count in before.values())
    with engine.begin() as c:
        c.execute(text("""
            CREATE OR REPLACE FUNCTION reject_attribution_fact_mutation()
            RETURNS integer LANGUAGE sql AS $$ SELECT 42 $$
        """))
    command.downgrade(config, "a3b4c5d6e7f8")
    with engine.connect() as c:
        assert MigrationContext.configure(c).get_current_revision() == "a3b4c5d6e7f8"
        assert "attribution_context_id" not in {item["name"] for item in inspect(c).get_columns("affiliate_links")}
        assert c.execute(text("SELECT to_regprocedure('m10a3_reject_link_context_rebinding()')")).scalar_one() is None
        assert c.execute(text("SELECT reject_attribution_fact_mutation()")).scalar_one() == 42
        assert {
            table: c.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in before
        } == before
    command.upgrade(config, "b4c5d6e7f8a9")
    with engine.connect() as c:
        assert MigrationContext.configure(c).get_current_revision() == REVISION
        assert c.execute(text("SELECT to_regprocedure('m10a3_reject_link_context_rebinding()')")).scalar_one()
        assert c.execute(text("SELECT reject_attribution_fact_mutation()")).scalar_one() == 42
        assert {
            table: c.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in before
        } == before
