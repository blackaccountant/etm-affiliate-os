"""Focused GLR1 contracts, reconciliation, and operator-auth coverage."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api import operator_auth
from app.api.distribution import PilotRevenueLaunchPayload, router as distribution_router
from app.api.affiliate_links import router as affiliate_links_router
from app.attribution.bridge_contracts import AttributionBridgeConflict
from app.distribution.pilot_revenue_launch_contracts import PilotRevenueLaunchRequest, PilotRevenueLaunchResult
from app.models.affiliate_link import AffiliateLink
from app.models.affiliate_program import AffiliateProgram
from app.models.attribution import AttributionContext, AttributionPublication
from app.models.content_evaluation import ContentEvaluation
from app.models.distribution_run import DistributionRun
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.services.distribution_run_service import DistributionRunService
from app.services.pilot_revenue_launch_service import PilotRevenueLaunchService


NOW = datetime(2026, 9, 7, tzinfo=timezone.utc)


def _request(**changes):
    values = dict(artifact_id="artifact", evaluation_id="evaluation", platform=" CMS ", account_reference="account", destination="destination", affiliate_link_id=7, prepared_content_body=None, scheduled_for=NOW)
    values.update(changes)
    return PilotRevenueLaunchRequest(**values)


class _Query:
    def filter_by(self, **_): return self
    def first(self): return None


class _Db:
    def __init__(self, objects): self.objects = objects
    def get(self, cls, key): return self.objects.get((cls, key))
    def query(self, _): return _Query()
    def __getattr__(self, name):
        if name in {"commit", "rollback", "flush", "add"}:
            raise AssertionError(f"GLR1 must not call {name}")
        raise AttributeError(name)


class _Runs:
    def __init__(self):
        self.calls = 0
        self.row = SimpleNamespace(
            id="run", generated_content_artifact_id="artifact",
            content_evaluation_id="evaluation", platform="cms",
            account_reference="account", destination="destination",
            prepared_content_body="body",
            payload_fingerprint=DistributionRunService.payload_fingerprint("body"),
            scheduled_for=NOW,
        )
    def create(self, request): self.calls += 1; return self.row


class _Publications:
    def __init__(self): self.calls = 0; self.row = SimpleNamespace(id="publication")
    def bind_distribution(self, run_id): assert run_id == "run"; self.calls += 1; return self.row


class _Contexts:
    def __init__(self): self.calls = 0; self.row = SimpleNamespace(id="context")
    def create(self, **values): assert values == {"affiliate_program_id": 3, "attribution_publication_id": "publication"}; self.calls += 1; return self.row


class _Links:
    def __init__(self, link): self.link = link; self.calls = 0
    def bind_existing(self, **values): assert values == {"affiliate_link_id": 7, "attribution_context_id": "context"}; self.calls += 1; self.link.attribution_context_id = "context"; return self.link, SimpleNamespace(id="fact")


def _service():
    artifact = SimpleNamespace(id="artifact", generation_run_id="generation", content_brief_id="brief", body="body")
    evaluation = SimpleNamespace(id="evaluation", artifact_id="artifact", generation_run_id="generation", content_brief_id="brief", decision="APPROVED", approved=True)
    link = SimpleNamespace(id=7, affiliate_program_id=3, attribution_context_id=None, destination_url="https://provider.test/offer", is_active=True, tracking_code="preserved-code")
    db = _Db({(GeneratedContentArtifact, "artifact"): artifact, (ContentEvaluation, "evaluation"): evaluation, (AffiliateLink, 7): link, (AffiliateProgram, 3): SimpleNamespace(id=3)})
    runs, publications, contexts, links = _Runs(), _Publications(), _Contexts(), _Links(link)
    return PilotRevenueLaunchService(db, distribution_runs=runs, publications=publications, contexts=contexts, links=links), runs, publications, contexts, links, link


def test_request_normalization_rejects_invalid_values_and_result_is_immutable():
    normalized = _request().normalized()
    assert normalized.platform == "cms" and normalized.scheduled_for == NOW
    payload_values = {
        "artifact_id": "artifact", "evaluation_id": "evaluation", "platform": "cms",
        "account_reference": "account", "destination": "destination",
        "affiliate_link_id": 7, "prepared_content_body": None, "scheduled_for": NOW,
    }
    assert PilotRevenueLaunchPayload(**payload_values).model_dump() == payload_values
    for forbidden_field in (
        "distribution_run_id", "idempotency_key", "attribution_publication_id",
        "attribution_context_id", "tracking_code", "destination_url",
        "affiliate_destination_url", "affiliate_program_id", "unknown_authority",
    ):
        with pytest.raises(ValidationError) as rejected:
            PilotRevenueLaunchPayload(**payload_values, **{forbidden_field: "forbidden"})
        assert rejected.value.errors()[0]["type"] == "extra_forbidden"
    for field in ("artifact_id", "evaluation_id", "platform", "account_reference", "destination"):
        with pytest.raises(ValueError): _request(**{field: " "}).normalized()
    with pytest.raises(ValueError): _request(affiliate_link_id=True).normalized()
    with pytest.raises(ValueError): _request(scheduled_for=datetime(2026, 9, 7)).normalized()
    result = PilotRevenueLaunchResult("r", "p", "c", 7, "code", "/affiliate-links/go/code")
    with pytest.raises(Exception): result.tracking_code = "other"


def test_launch_reuses_authorities_preserves_link_and_never_owns_transactions():
    service, runs, publications, contexts, links, link = _service()
    result = service.launch(_request())
    assert result == PilotRevenueLaunchResult("run", "publication", "context", 7, "preserved-code", "/affiliate-links/go/preserved-code")
    assert (runs.calls, publications.calls, contexts.calls, links.calls) == (1, 1, 1, 1)
    assert link.destination_url == "https://provider.test/offer" and link.tracking_code == "preserved-code"
    service.db.objects[(AttributionContext, "context")] = SimpleNamespace(
        affiliate_program_id=3, attribution_publication_id="publication",
    )
    service.db.objects[(AttributionPublication, "publication")] = SimpleNamespace(
        distribution_run_id="run",
    )
    service.db.objects[(DistributionRun, "run")] = runs.row
    assert service.launch(_request()) == result
    assert (runs.calls, publications.calls, contexts.calls, links.calls) == (2, 2, 2, 2)


def test_prevalidation_fails_before_run_creation_and_incompatible_binding_conflicts():
    service, runs, *_ = _service()
    service.db.objects[(AffiliateLink, 7)].is_active = False
    with pytest.raises(ValueError, match="inactive"): service.launch(_request())
    assert runs.calls == 0
    for changes in (
        {"destination": "other-destination"},
        {"platform": "other-platform"},
        {"account_reference": "other-account"},
        {"prepared_content_body": "other body"},
    ):
        service, runs, publications, contexts, links, link = _service()
        link.attribution_context_id = "other"
        service.db.objects[(AttributionContext, "other")] = SimpleNamespace(
            affiliate_program_id=3, attribution_publication_id="publication",
        )
        service.db.objects[(AttributionPublication, "publication")] = SimpleNamespace(
            distribution_run_id="bound-run",
        )
        service.db.objects[(DistributionRun, "bound-run")] = runs.row
        with pytest.raises(AttributionBridgeConflict): service.launch(_request(**changes))
        assert runs.calls == publications.calls == contexts.calls == links.calls == 0
        assert link.attribution_context_id == "other"


def test_operator_auth_fails_closed_uses_constant_time_comparison_and_is_route_scoped(monkeypatch):
    monkeypatch.setattr(operator_auth.settings, "OPERATOR_API_KEY", None)
    with pytest.raises(HTTPException) as missing_server: operator_auth.require_operator_api_key("secret")
    assert missing_server.value.status_code == 503 and "secret" not in missing_server.value.detail
    monkeypatch.setattr(operator_auth.settings, "OPERATOR_API_KEY", "secret")
    with pytest.raises(HTTPException) as missing_header: operator_auth.require_operator_api_key(None)
    with pytest.raises(HTTPException) as wrong: operator_auth.require_operator_api_key("wrong")
    assert missing_header.value.status_code == wrong.value.status_code == 401
    calls = []
    monkeypatch.setattr(operator_auth, "compare_digest", lambda received, configured: calls.append((received, configured)) or True)
    operator_auth.require_operator_api_key("anything")
    assert calls == [("anything", "secret")]
    pilot = next(route for route in distribution_router.routes if getattr(route, "path", "") == "/distribution/pilot-launch")
    redirect = next(route for route in affiliate_links_router.routes if getattr(route, "path", "") == "/affiliate-links/go/{tracking_code}")
    assert pilot.dependencies and not redirect.dependencies


def test_result_contains_only_locked_relative_public_redirect_fields():
    fields = set(PilotRevenueLaunchResult.__dataclass_fields__)
    assert fields == {"distribution_run_id", "attribution_publication_id", "attribution_context_id", "affiliate_link_id", "tracking_code", "public_redirect_path"}
    assert PilotRevenueLaunchResult("r", "p", "c", 1, "x", "/affiliate-links/go/x").public_redirect_path == "/affiliate-links/go/x"
