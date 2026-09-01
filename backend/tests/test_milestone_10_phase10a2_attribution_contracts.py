from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.attribution.contracts import (
    AttributionContractError,
    AttributionFactKind,
    aware_utc,
    canonical_fingerprint,
    context_fingerprint,
    fact_references,
    source_identity,
    validate_fingerprint,
)
from app.attribution.privacy import validate_privacy_safe_source


def test_canonical_fingerprint_is_deterministic_order_independent_and_versioned():
    first = canonical_fingerprint("example-v1", {"z": 2, "a": "café"})
    assert first == canonical_fingerprint("example-v1", {"a": "café", "z": 2})
    assert first != canonical_fingerprint("example-v2", {"z": 2, "a": "café"})
    assert len(first) == 64 and first == first.lower()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_json_rejects_non_finite_numbers_at_any_depth(value):
    with pytest.raises(AttributionContractError, match="non-finite"):
        canonical_fingerprint("example-v1", {"nested": ["safe", {"value": value}]})


def test_context_fingerprint_changes_when_authority_changes_and_sha_is_strict():
    assert context_fingerprint(affiliate_program_id=1, attribution_publication_id="p1") != context_fingerprint(
        affiliate_program_id=1, attribution_publication_id="p2"
    )
    assert validate_fingerprint("a" * 64) == "a" * 64
    for invalid in ("a" * 63, "A" * 64, "g" * 64, None):
        with pytest.raises(AttributionContractError):
            validate_fingerprint(invalid)


def test_utc_contract_rejects_naive_and_normalizes_aware_values():
    with pytest.raises(AttributionContractError, match="timezone-aware"):
        aware_utc(datetime(2026, 1, 1), "occurred_at")
    source = datetime(2026, 1, 1, 3, tzinfo=timezone(timedelta(hours=3)))
    assert aware_utc(source, "occurred_at") == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_source_identity_normalization_and_bounds():
    digest = "a" * 64
    assert source_identity("  ProViDer.WebHook ", digest) == ("provider.webhook", digest)
    with pytest.raises(AttributionContractError):
        source_identity("x" * 64, digest)
    with pytest.raises(AttributionContractError):
        source_identity("provider webhook", digest)
    with pytest.raises(AttributionContractError):
        source_identity("provider", "event-42")


@pytest.mark.parametrize("value", [
    "alice@example.test", "203.0.113.9", "2001:db8::1", "+2348012345678",
    "Safari/605.1.15", "customer-784392", "sk_live_51ABCDEF",
])
def test_privacy_boundary_rejects_raw_pii_and_secrets(value):
    with pytest.raises(AttributionContractError, match="source_event_key_digest"):
        validate_privacy_safe_source("provider", value)
    assert validate_privacy_safe_source("provider", "a" * 64) == ("provider", "a" * 64)


def test_allowed_fact_contracts_and_correction_requirement():
    valid = {
        AttributionFactKind.PUBLICATION_BOUND: {"attribution_publication_id": "p"},
        AttributionFactKind.LINK_BOUND: {"attribution_context_id": "c", "affiliate_link_id": 1},
        AttributionFactKind.CLICK_RECORDED: {
            "attribution_context_id": "c", "attribution_click_id": "k", "affiliate_link_id": 1,
        },
        AttributionFactKind.CONVERSION_REPORTED: {
            "attribution_context_id": "c", "affiliate_conversion_id": 1,
        },
        AttributionFactKind.ATTRIBUTION_CORRECTED: {"supersedes_fact_id": "f"},
    }
    for kind, refs in valid.items():
        assert fact_references(fact_kind=kind, **refs)["fact_kind"] == kind.value
    with pytest.raises(AttributionContractError, match="requires supersedes_fact_id"):
        fact_references(fact_kind="ATTRIBUTION_CORRECTED")
    with pytest.raises(AttributionContractError, match="unsupported"):
        fact_references(fact_kind="COMMISSION_EARNED")


def test_repositories_and_services_do_not_own_transactions():
    root = Path(__file__).parents[1] / "app"
    files = [
        *root.joinpath("repositories").glob("attribution_*_repository.py"),
        *root.joinpath("services").glob("attribution_*_service.py"),
    ]
    assert len(files) == 8
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert ".commit(" not in source
        assert ".rollback(" not in source
