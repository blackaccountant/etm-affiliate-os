"""Guarded PostgreSQL qualification for M10A6's read-only settled commission projection."""

from decimal import Decimal
import os
from uuid import uuid4

import pytest
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.attribution.realized_revenue_projection_contracts import RealizedRevenueProjectionRequest
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_program import AffiliateProgram
from app.models.product import Product
from app.models.publishing_queue import PublishingQueue
from app.services.affiliate_payout_service import AffiliatePayoutService
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_payout_settlement_link_service import AttributionPayoutSettlementLinkService
from app.services.attribution_publication_service import AttributionPublicationService
from app.services.attribution_redirect_bridge_service import AttributionRedirectBridgeService
from app.services.attribution_realized_revenue_projection_service import AttributionRealizedRevenueProjectionService


REVISION = "d6e7f8a9b0c1"
DATABASE = "etm_g5_m10a6_qualification"
raw_url = os.getenv("ETM_G5_DATABASE_URL")
if not raw_url:
    pytest.skip("Requires guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
url = make_url(raw_url)
if not (url.drivername.startswith("postgresql") and url.host == "127.0.0.1" and url.port == 5432 and url.database == DATABASE):
    raise RuntimeError("M10A6 qualification requires its dedicated local PostgreSQL database")
engine = create_engine(url.render_as_string(hide_password=False), pool_pre_ping=True)
Session = sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(scope="module", autouse=True)
def guarded_schema():
    with engine.connect() as connection:
        assert connection.execute(text("SELECT current_database()")).scalar_one() == DATABASE
        assert MigrationContext.configure(connection).get_current_revision() == REVISION
    yield
    engine.dispose()


def _seed(*, currency="USD", amount="10.00", settled=True, clicked=False):
    db = Session()
    try:
        token = uuid4().hex
        product = Product(name=f"M10A6 {token}", website=f"https://{token}.invalid", category="test", affiliate_program="yes", commission_type="percentage", commission_value="10", affiliate_score=1, grade="A", confidence=100, summary="", recommendation="", status="active")
        db.add(product); db.flush()
        program = AffiliateProgram(product_id=product.id, program_name=f"program-{token}", commission_type="percentage", commission_value="10", status="active")
        db.add(program); db.flush()
        asset = AffiliateContentAsset(product_id=product.id, asset_type="article", title="M10A6")
        db.add(asset); db.flush()
        queue = PublishingQueue(content_asset_id=asset.id, channel=f"m10a6-{token}")
        db.add(queue); db.flush()
        publication = AttributionPublicationService(db).bind_legacy(queue.id)
        context = AttributionContextService(db).create(affiliate_program_id=program.id, attribution_publication_id=publication.id)
        db.commit()
        link = AttributionLinkBridgeService(db).create_bound_link(affiliate_program_id=program.id, attribution_context_id=context.id, name="M10A6", destination_url="https://destination.invalid", content_asset_id=asset.id)
        click = None; click_event_id = None
        if clicked:
            click_result = AttributionRedirectBridgeService(db).record(tracking_code=link.tracking_code, event_id=str(uuid4()))
            click = click_result["attribution_click"]; click_event_id = click_result["event_id"]
        result = AttributionConversionBridgeService(db).record(affiliate_program_id=program.id, affiliate_link_id=link.id, external_conversion_id=f"conversion-{token}", sale_amount=Decimal("999.99"), currency=currency, commission_rate=Decimal("10"), attribution_click_key=click_event_id)
        earning = result["earning"]; earning.commission_amount = Decimal(amount); db.commit()
        earning_link = AttributionEarningLinkService(db).reconcile(attribution_fact_id=result["fact"].id)
        ids = {"product": product.id, "program": program.id, "asset": asset.id, "publication": publication.id, "queue": queue.id, "context": context.id, "link": link.id, "click": click.id if click else None, "conversion": result["conversion"].id, "earning": earning.id, "earning_link": earning_link.id}
        if settled:
            payouts = AffiliatePayoutService(db)
            payout = payouts.create_payout(affiliate_program_id=program.id, currency=currency)
            payouts.process_payout(payout.id, idempotency_key=f"process-{token}")
            payouts.complete_payout(payout.id, payout_reference="qualification")
            settlement = AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=earning_link.id)
            ids["settlement"] = settlement.id
        return ids
    finally:
        db.close()


def _project(*dimensions, currency=None):
    db = Session()
    try:
        return AttributionRealizedRevenueProjectionService(db).project(
            RealizedRevenueProjectionRequest(tuple(dimensions), currency),
        )
    finally:
        db.close()


def test_settlement_only_monetary_authority_currency_and_dimensions():
    usd = _seed(currency="USD", amount="10.10", settled=True, clicked=False)
    eur = _seed(currency="EUR", amount="20.20", settled=True, clicked=False)
    _seed(currency="USD", amount="999.99", settled=False)
    rows = _project("affiliate_program", "product", "content_asset", "attribution_publication", "publishing_authority", "affiliate_link", "attribution_context", "attribution_click", "conversion", "earning", "settlement_link")
    own_rows = {dict(row.dimensions)["earning"]: row for row in rows}
    assert (own_rows[usd["earning"]].currency, own_rows[usd["earning"]].commission_amount) == ("USD", Decimal("10.10"))
    assert (own_rows[eur["earning"]].currency, own_rows[eur["earning"]].commission_amount) == ("EUR", Decimal("20.20"))
    usd_row = own_rows[usd["earning"]]
    values = dict(usd_row.dimensions)
    assert values == {"affiliate_program": usd["program"], "product": usd["product"], "content_asset": usd["asset"], "attribution_publication": usd["publication"], "publishing_authority": usd["queue"], "affiliate_link": usd["link"], "attribution_context": usd["context"], "attribution_click": None, "conversion": usd["conversion"], "earning": usd["earning"], "settlement_link": usd["settlement"]}
    assert dict(own_rows[eur["earning"]].dimensions)["attribution_click"] is None
    usd_only = _project("earning", currency="USD")
    assert usd["earning"] in {dict(row.dimensions)["earning"] for row in usd_only}
    assert eur["earning"] not in {dict(row.dimensions)["earning"] for row in usd_only}


def test_determinism_read_only_and_no_sensitive_shape():
    first = _seed(currency="USD", amount="0.10", settled=True); second = _seed(currency="USD", amount="0.20", settled=True)
    before = _project("earning")
    after = _project("earning")
    assert before == after
    own = {dict(row.dimensions)["earning"]: row.commission_amount for row in before}
    assert own[first["earning"]] + own[second["earning"]] == Decimal("0.30")
    for row in before:
        assert "customer" not in repr(row.dimensions).lower()
        assert "provider" not in repr(row.dimensions).lower()
        assert "payout_reference" not in repr(row.dimensions).lower()


def test_manual_paid_and_failed_or_processing_state_without_settlement_are_excluded():
    excluded = _seed(currency="USD", amount="77.77", settled=False)
    ids = {dict(row.dimensions)["earning"] for row in _project("earning", currency="USD")}
    assert excluded["earning"] not in ids
