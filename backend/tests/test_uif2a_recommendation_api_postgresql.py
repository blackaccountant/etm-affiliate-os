import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.dependencies import get_db
from app.main import app
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.affiliate_program import AffiliateProgram
from app.models.product import Product
from app.models.publishing_queue import PublishingQueue
from app.optimization.economic_recommendation_proposal_contracts import (
    ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION,
    ECONOMIC_RECOMMENDATION_PROPOSAL_SEMANTICS,
)
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_conversion_bridge_service import (
    AttributionConversionBridgeService,
)
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_payout_settlement_link_service import (
    AttributionPayoutSettlementLinkService,
)
from app.services.attribution_publication_service import AttributionPublicationService


DATABASE = "etm_uif2a_recommendation_api_qualification"
ROLE = os.getenv("ETM_UIF2A_DB_ROLE")
RAW = os.getenv("ETM_UIF2A_DATABASE_URL")
FRESH = os.getenv("ETM_UIF2A_DB_FRESHNESS_ATTESTED")

if not RAW:
    pytest.skip("requires guarded UIF2A URL", allow_module_level=True)

URL = make_url(RAW)
if (
    ROLE != "qualification"
    or FRESH not in {"1", "true", "TRUE", "yes", "YES", "fresh", "FRESH"}
    or not URL.drivername.startswith("postgresql")
    or URL.host != "127.0.0.1"
    or URL.port != 5432
    or URL.database != DATABASE
):
    raise RuntimeError("UIF2A database guard failed")


ENGINE = create_engine(URL.render_as_string(hide_password=False))
Session = sessionmaker(bind=ENGINE, expire_on_commit=False)


def _session():
    return Session()


def _settled(*, product_id=None, program_id=None, currency="USD"):
    db = _session()
    token = uuid4().hex
    try:
        product = (
            db.get(Product, product_id)
            if product_id
            else Product(
                name=token,
                website=f"https://{token}.invalid",
                category="test",
                affiliate_program="test",
                commission_type="percentage",
                commission_value="10",
                affiliate_score=1,
                grade="A",
                confidence=1,
                summary="",
                recommendation="",
                status="active",
            )
        )
        if not product_id:
            db.add(product)
            db.flush()

        program = (
            db.get(AffiliateProgram, program_id)
            if program_id
            else AffiliateProgram(
                product_id=product.id,
                program_name=token,
                commission_type="percentage",
                commission_value="10",
                status="active",
            )
        )
        if not program_id:
            db.add(program)
            db.flush()

        asset = AffiliateContentAsset(
            product_id=product.id,
            asset_type="article",
            title=token,
        )
        db.add(asset)
        db.flush()

        queue = PublishingQueue(
            content_asset_id=asset.id,
            channel=token,
        )
        db.add(queue)
        db.flush()

        publication = AttributionPublicationService(db).bind_legacy(queue.id)
        context = AttributionContextService(db).create(
            affiliate_program_id=program.id,
            attribution_publication_id=publication.id,
        )
        db.commit()

        link = AttributionLinkBridgeService(db).create_bound_link(
            affiliate_program_id=program.id,
            attribution_context_id=context.id,
            name=token,
            destination_url="https://private.invalid",
            content_asset_id=asset.id,
        )
        result = AttributionConversionBridgeService(db).record(
            affiliate_program_id=program.id,
            affiliate_link_id=link.id,
            external_conversion_id=token,
            customer_reference="private",
            sale_amount=Decimal("1000"),
            currency=currency,
            commission_rate=Decimal("10"),
            metadata_json=json.dumps({"private": token}),
        )

        earning_link = AttributionEarningLinkService(db).reconcile(
            attribution_fact_id=result["fact"].id
        )
        earning = result["earning"]
        now = datetime.now(timezone.utc)

        payout = AffiliatePayout(
            affiliate_program_id=program.id,
            total_amount=earning.commission_amount,
            currency=currency,
            status="paid",
            paid_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(payout)
        db.flush()

        earning.payout_id = payout.id
        earning.status = "paid"

        db.add(
            AffiliatePayoutAttempt(
                payout_id=payout.id,
                attempt_number=1,
                amount=payout.total_amount,
                currency=currency,
                status="completed",
                provider="manual",
                idempotency_key=token,
                started_at=now,
                completed_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

        AttributionPayoutSettlementLinkService(db).reconcile(
            attribution_earning_link_id=earning_link.id
        )
        return {"product": product.id, "program": program.id}
    finally:
        db.close()


def _seed(counts, currency):
    identities = [_settled(currency=currency) for _ in counts]
    for identity, count in zip(identities, counts, strict=True):
        for _ in range(count - 1):
            _settled(
                product_id=identity["product"],
                program_id=identity["program"],
                currency=currency,
            )
    return identities


def _payload(currency):
    return {
        "dimensions": ["affiliate_program"],
        "currency": currency,
        "evaluated_at": "2100-01-01T00:00:00Z",
        "eligibility_policy": {
            "policy_version": "qualification",
            "minimum_settled_earning_count": 1,
            "minimum_settled_conversion_count": 1,
            "minimum_settlement_link_count": 1,
            "minimum_attribution_click_count": None,
            "maximum_settlement_observation_age": None,
        },
        "comparison_policy_version": "qualification-pairwise-v1",
        "recommendation_policy_version": "qualification-recommendation-v1",
    }


def _ids(rows):
    return [
        item["dimensions"][0]["value"]
        for item in rows
    ]


@pytest.fixture
def client_and_sql():
    statements = []
    event.listen(
        ENGINE,
        "before_cursor_execute",
        lambda _conn, _cursor, statement, _parameters, _context, _many:
            statements.append(statement),
    )

    def qualification_db():
        db = _session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = qualification_db
    client = TestClient(app)

    try:
        yield client, statements
    finally:
        app.dependency_overrides.clear()
        event.remove(
            ENGINE,
            "before_cursor_execute",
            next(
                listener
                for listener in []
            ),
        ) if False else None


def _assert_no_http_layer_writes(statements):
    forbidden = (
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "CREATE ",
        "DROP ",
        "ALTER ",
        "TRUNCATE ",
    )
    normalized = [statement.lstrip().upper() for statement in statements]
    assert not [
        statement
        for statement in normalized
        if statement.startswith(forbidden)
    ]


def test_current_head_requires_no_uif2a_migration():
    db = _session()
    try:
        assert (
            MigrationContext.configure(db.connection()).get_current_revision()
            == "c3d4e5f6a7b8"
        )
    finally:
        db.close()


def test_real_http_projection_returns_one_tier_one_with_decimal_and_provenance():
    x, _y, _z = _seed((3, 2, 1), "USD")
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(ENGINE, "before_cursor_execute", capture)

    def qualification_db():
        db = _session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = qualification_db
    try:
        response = TestClient(app).post(
            "/optimization/recommendations/project",
            json=_payload("USD"),
        )
    finally:
        app.dependency_overrides.clear()
        event.remove(ENGINE, "before_cursor_execute", capture)

    assert response.status_code == 200
    rows = response.json()["recommendations"]
    assert _ids(rows) == [x["program"]]
    assert rows[0]["preference_tier"] == 1
    assert isinstance(rows[0]["operating_profit"], str)
    Decimal(rows[0]["operating_profit"])
    assert rows[0]["recommendation_proposal_semantics"] == (
        ECONOMIC_RECOMMENDATION_PROPOSAL_SEMANTICS
    )
    assert rows[0]["recommendation_proposal_contract_version"] == (
        ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION
    )
    _assert_no_http_layer_writes(statements)


def test_real_http_projection_preserves_exact_tier_one_tie_order():
    x, _y, z = _seed((2, 1, 2), "EUR")
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(ENGINE, "before_cursor_execute", capture)

    def qualification_db():
        db = _session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = qualification_db
    try:
        response = TestClient(app).post(
            "/optimization/recommendations/project",
            json=_payload("EUR"),
        )
    finally:
        app.dependency_overrides.clear()
        event.remove(ENGINE, "before_cursor_execute", capture)

    assert response.status_code == 200
    rows = response.json()["recommendations"]
    assert _ids(rows) == [x["program"], z["program"]]
    assert [row["preference_tier"] for row in rows] == [1, 1]
    assert rows[0]["operating_profit"] == rows[1]["operating_profit"]
    assert all(
        row["recommendation_proposal_contract_version"]
        == ECONOMIC_RECOMMENDATION_PROPOSAL_CONTRACT_VERSION
        for row in rows
    )
    _assert_no_http_layer_writes(statements)


def test_uif2a_route_source_adds_no_network_client():
    import app.api.optimization_recommendation_routes as route_module

    source = open(route_module.__file__, encoding="utf-8").read()
    forbidden = (
        "import requests",
        "from requests",
        "import httpx",
        "from httpx",
        "urllib.request",
    )
    assert all(token not in source for token in forbidden)
