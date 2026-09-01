"""Deterministic contract and transaction-boundary proofs for M10A3."""

import inspect
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import UniqueConstraint

from app.attribution.bridge_contracts import (
    CLICK_FACT_SOURCE_NAMESPACE,
    CLICK_SOURCE_NAMESPACE,
    CONVERSION_FACT_SOURCE_NAMESPACE,
    LINK_SOURCE_NAMESPACE,
    bridge_digest,
    click_event_digest,
    click_fact_digest,
    conversion_fact_digest,
    legacy_utc,
    link_binding_digest,
    opaque_event_id,
)
from app.models.affiliate_click import AffiliateClick
from app.models.affiliate_link import AffiliateLink
from app.services.affiliate_click_service import AffiliateClickService
from app.services.affiliate_conversion_service import AffiliateConversionService
from app.services.affiliate_link_service import AffiliateLinkService


def test_opaque_event_identity_is_uuid_only_and_never_persisted_raw():
    event_id = str(uuid4())
    canonical, digest = click_event_digest(event_id.upper())
    assert canonical == event_id
    assert UUID(opaque_event_id(None))
    assert len(digest) == 64 and event_id not in digest
    for invalid in ("alice@example.test", "203.0.113.9", "not-opaque", str(UUID(int=0)), 42):
        with pytest.raises(ValueError, match="opaque UUID|nil UUID"):
            opaque_event_id(invalid)


def test_bridge_digests_are_deterministic_versioned_and_domain_separated():
    assert bridge_digest("contract-v1", {"b": 2, "a": 1}) == bridge_digest(
        "contract-v1", {"a": 1, "b": 2},
    )
    assert bridge_digest("contract-v1", {"a": 1}) != bridge_digest(
        "contract-v2", {"a": 1},
    )
    event_digest = "a" * 64
    assert click_fact_digest(event_digest) != event_digest
    assert link_binding_digest(1, str(uuid4())) != conversion_fact_digest(1)
    assert len({
        LINK_SOURCE_NAMESPACE,
        CLICK_SOURCE_NAMESPACE,
        CLICK_FACT_SOURCE_NAMESPACE,
        CONVERSION_FACT_SOURCE_NAMESPACE,
    }) == 4


def test_legacy_timestamp_adapter_normalizes_to_aware_utc():
    naive = datetime(2026, 9, 1, 12)
    assert legacy_utc(naive) == naive.replace(tzinfo=timezone.utc)
    offset = datetime(2026, 9, 1, 15, tzinfo=timezone(timedelta(hours=3)))
    assert legacy_utc(offset) == datetime(2026, 9, 1, 12, tzinfo=timezone.utc)


def test_bridge_columns_are_nullable_foreign_keys_with_narrow_uniqueness():
    link_column = AffiliateLink.__table__.c.attribution_context_id
    click_column = AffiliateClick.__table__.c.attribution_click_id
    assert link_column.nullable and click_column.nullable
    assert next(iter(link_column.foreign_keys)).target_fullname == "attribution_contexts.id"
    assert next(iter(click_column.foreign_keys)).target_fullname == "attribution_clicks.id"
    assert "uq_affiliate_links_attributed_tracking_code" in {
        index.name for index in AffiliateLink.__table__.indexes if index.unique
    }
    assert "uq_affiliate_clicks_attribution_click_id" in {
        item.name for item in AffiliateClick.__table__.constraints
        if isinstance(item, UniqueConstraint)
    }


def test_legacy_public_service_signatures_remain_compatible():
    assert list(inspect.signature(AffiliateLinkService.create_link).parameters) == [
        "self", "affiliate_program_id", "name", "destination_url", "content_asset_id",
    ]
    assert list(inspect.signature(AffiliateClickService.record_click).parameters) == [
        "self", "tracking_code", "ip_address", "user_agent",
    ]
    assert list(inspect.signature(AffiliateConversionService.create_conversion).parameters) == [
        "self", "affiliate_program_id", "sale_amount", "currency", "affiliate_link_id",
        "tracking_code", "external_conversion_id", "customer_reference",
        "conversion_status", "commission_rate", "source", "metadata_json",
    ]


def test_internal_legacy_primitives_are_transaction_neutral():
    for method in (
        AffiliateLinkService._create_link_uncommitted,
        AffiliateClickService._record_click_uncommitted,
        AffiliateConversionService._create_conversion_uncommitted,
    ):
        source = inspect.getsource(method)
        assert ".commit(" not in source
        assert ".rollback(" not in source


def test_bridge_services_own_outer_transaction_without_leaking_raw_identity():
    from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
    from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
    from app.services.attribution_redirect_bridge_service import AttributionRedirectBridgeService

    for service in (
        AttributionLinkBridgeService,
        AttributionRedirectBridgeService,
        AttributionConversionBridgeService,
    ):
        source = inspect.getsource(service)
        assert ".commit(" in source
        assert ".rollback(" in source
    redirect_source = inspect.getsource(AttributionRedirectBridgeService)
    for forbidden in ("source_event_key=", "metadata_json=", "customer_reference="):
        assert forbidden not in redirect_source
