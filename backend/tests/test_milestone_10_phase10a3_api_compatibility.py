"""Public API compatibility proofs for attributed and unbound legacy flows."""

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 - populate the complete SQLAlchemy registry
from app.api.affiliate_conversions import get_db as conversion_get_db
from app.api.affiliate_conversions import router as conversion_router
from app.api.affiliate_links import get_db as link_get_db
from app.api.affiliate_links import router as link_router
from app.database.base import Base
from app.models.affiliate_click import AffiliateClick
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_conversion import AffiliateConversion
from app.models.affiliate_earning import AffiliateEarning
from app.models.affiliate_link import AffiliateLink
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_program import AffiliateProgram
from app.models.attribution import AttributionClick, AttributionFact
from app.models.product import Product
from app.models.publishing_queue import PublishingQueue
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_publication_service import AttributionPublicationService


@pytest.fixture()
def api(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'm10a3-api.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    application = FastAPI()
    application.include_router(link_router)
    application.include_router(conversion_router)
    application.dependency_overrides[link_get_db] = override_db
    application.dependency_overrides[conversion_get_db] = override_db
    with TestClient(application, raise_server_exceptions=True) as client:
        yield client, Session
    engine.dispose()


def _foundation(Session):
    token = uuid4().hex
    with Session() as db:
        product = Product(
            name=f"M10A3 {token}", website=f"https://{token}.invalid", category="test",
            affiliate_program="yes", commission_type="percentage", commission_value="10",
            affiliate_score=1, grade="A", confidence=100, summary="", recommendation="",
            status="active",
        )
        db.add(product); db.flush()
        program = AffiliateProgram(
            product_id=product.id, program_name=f"program-{token}",
            commission_type="percentage", commission_value="10", status="active",
        )
        db.add(program); db.flush()
        asset = AffiliateContentAsset(product_id=product.id, asset_type="article", title="M10A3")
        db.add(asset); db.flush()
        queue = PublishingQueue(content_asset_id=asset.id, channel=f"m10a3-{token}")
        db.add(queue); db.flush()
        publication = AttributionPublicationService(db).bind_legacy(queue.id)
        context = AttributionContextService(db).create(
            affiliate_program_id=program.id,
            attribution_publication_id=publication.id,
        )
        db.commit()
        return program.id, asset.id, context.id


def _create_link(client, program_id, asset_id, *, context_id=None):
    params = {
        "affiliate_program_id": program_id,
        "name": "M10A3 link",
        "destination_url": "https://destination.invalid/offer",
        "content_asset_id": asset_id,
    }
    if context_id is not None:
        params["attribution_context_id"] = context_id
    response = client.post("/affiliate-links/create", params=params)
    assert response.status_code == 200
    return response.json()


def test_unbound_public_link_redirect_and_conversion_remain_legacy_compatible(api):
    client, Session = api
    program_id, asset_id, _ = _foundation(Session)
    link = _create_link(client, program_id, asset_id)

    redirect = client.get(
        f"/affiliate-links/go/{link['tracking_code']}",
        follow_redirects=False,
        headers={"user-agent": "legacy-compatible"},
    )
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "https://destination.invalid/offer"

    conversion_payload = {
        "affiliate_program_id": program_id,
        "affiliate_link_id": link["id"],
        "external_conversion_id": f"legacy-{uuid4()}",
        "sale_amount": "100.00",
        "currency": "usd",
        "customer_reference": "legacy@example.test",
        "metadata": {"provider": "legacy-compatible"},
    }
    conversion = client.post("/affiliate-conversions/create", json=conversion_payload)
    assert conversion.status_code == 200
    assert conversion.json()["sale_amount"] == "100.00"
    assert conversion.json()["commission_amount"] == "10.00"

    with Session() as db:
        assert db.query(AffiliateClick).count() == 1
        assert db.query(AffiliateConversion).count() == 1
        assert db.query(AffiliateEarning).count() == 1
        assert db.query(AttributionClick).count() == 0
        assert db.query(AttributionFact).count() == 0
        assert db.query(AffiliatePayout).count() == 0


def test_attributed_api_is_atomic_idempotent_and_response_compatible(api):
    client, Session = api
    program_id, asset_id, context_id = _foundation(Session)
    link = _create_link(client, program_id, asset_id, context_id=context_id)
    event_id = str(uuid4())

    first_redirect = client.get(
        f"/affiliate-links/go/{link['tracking_code']}",
        follow_redirects=False,
        headers={"Idempotency-Key": event_id, "user-agent": "private-legacy-value"},
    )
    replay_redirect = client.get(
        f"/affiliate-links/go/{link['tracking_code']}",
        follow_redirects=False,
        headers={"Idempotency-Key": event_id, "user-agent": "changed-legacy-value"},
    )
    assert first_redirect.status_code == replay_redirect.status_code == 307
    assert first_redirect.headers["location"] == "https://destination.invalid/offer"

    with Session() as db:
        attribution_click = db.query(AttributionClick).one()
        assert db.query(AffiliateClick).one().attribution_click_id == attribution_click.id
        assert db.query(AttributionFact).filter_by(fact_kind="LINK_BOUND").count() == 1
        assert db.query(AttributionFact).filter_by(fact_kind="CLICK_RECORDED").count() == 1
        click_key = attribution_click.click_key

    payload = {
        "affiliate_program_id": program_id,
        "affiliate_link_id": link["id"],
        "external_conversion_id": f"attributed-{uuid4()}",
        "sale_amount": "125.00",
        "currency": "USD",
        "commission_rate": "10",
        "attribution_click_key": click_key,
        "customer_reference": "must-not-enter-attribution@example.test",
        "metadata": {"ip": "203.0.113.77", "secret": "sk_live_private"},
    }
    first = client.post("/affiliate-conversions/create", json=payload)
    replay = client.post("/affiliate-conversions/create", json=payload)
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()

    conflict_payload = {**payload, "sale_amount": "126.00"}
    conflict = client.post("/affiliate-conversions/create", json=conflict_payload)
    assert conflict.status_code == 409

    with Session() as db:
        assert db.query(AffiliateLink).one().attribution_context_id == context_id
        assert db.query(AffiliateClick).count() == 1
        assert db.query(AttributionClick).count() == 1
        assert db.query(AffiliateConversion).count() == 1
        assert db.query(AffiliateEarning).count() == 1
        conversion_fact = db.query(AttributionFact).filter_by(
            fact_kind="CONVERSION_REPORTED",
        ).one()
        assert conversion_fact.attribution_click_id == attribution_click.id
        persisted = " ".join(
            f"{row.source_namespace} {row.source_event_key_digest} {row.source_fingerprint}"
            for row in db.query(AttributionFact).all()
        )
        for forbidden in (
            event_id, "private-legacy-value", "changed-legacy-value",
            "must-not-enter-attribution@example.test", "203.0.113.77", "sk_live_private",
        ):
            assert forbidden not in persisted
