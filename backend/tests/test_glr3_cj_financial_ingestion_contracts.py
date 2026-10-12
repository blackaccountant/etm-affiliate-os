from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app.api.affiliate_conversions import CjCommissionSyncRequest
from app.core.config import settings
from app.services.cj_commission_client import (
    CjCommissionClient,
    CjCommissionClientError,
)
from app.services.cj_financial_ingestion_service import CjFinancialIngestionService


NOW = datetime(2026, 10, 12, tzinfo=timezone.utc)


class Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def client(monkeypatch, *, token="secret-token", cid="800000089"):
    monkeypatch.setattr(settings, "CJ_PERSONAL_ACCESS_TOKEN", token)
    monkeypatch.setattr(settings, "CJ_PUBLISHER_CID", cid)
    monkeypatch.setattr(
        settings,
        "CJ_COMMISSIONS_API_URL",
        "https://commissions.api.cj.com/query",
    )
    return CjCommissionClient()


def page(records, *, complete=True, cursor=None):
    return {
        "data": {
            "publisherCommissions": {
                "count": len(records),
                "payloadComplete": complete,
                "maxCommissionId": cursor,
                "records": records,
            }
        }
    }


def record(**overrides):
    base = {
        "commissionId": "1001",
        "publisherId": "800000089",
        "advertiserId": "4001",
        "advertiserName": "Vendor",
        "actionStatus": "new",
        "validationStatus": "PENDING",
        "actionType": "sim_sale",
        "orderId": "order-1",
        "original": True,
        "originalActionId": "action-1",
        "postingDate": "2026-10-12T00:00:00Z",
        "eventDate": "2026-10-11T23:59:00Z",
        "saleAmountUsd": "100.00",
        "pubCommissionAmountUsd": "10.00",
        "websiteId": "55",
        "websiteName": "ETM Insights",
    }
    base.update(overrides)
    return base


def test_client_requires_cj_configuration(monkeypatch):
    monkeypatch.setattr(settings, "CJ_PERSONAL_ACCESS_TOKEN", "")
    monkeypatch.setattr(settings, "CJ_PUBLISHER_CID", "")
    with pytest.raises(CjCommissionClientError):
        CjCommissionClient()


def test_client_rejects_posting_window_over_31_days(monkeypatch):
    c = client(monkeypatch)
    with pytest.raises(ValueError):
        c.fetch_commissions(
            since_posting_date=NOW - timedelta(days=32),
            before_posting_date=NOW,
        )


def test_client_paginates_with_max_commission_id(monkeypatch):
    c = client(monkeypatch)
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs["content"])
        if len(calls) == 1:
            return Response(200, page([record()], complete=False, cursor="1001"))
        return Response(
            200,
            page([record(commissionId="1002")], complete=True, cursor="1002"),
        )

    monkeypatch.setattr("app.services.cj_commission_client.httpx.post", fake_post)
    rows = c.fetch_commissions(
        since_posting_date=NOW - timedelta(days=1),
        before_posting_date=NOW,
    )
    assert [row["commissionId"] for row in rows] == ["1001", "1002"]
    assert "sinceCommissionId" not in calls[0]
    assert 'sinceCommissionId: "1001"' in calls[1]


def test_client_http_failure_does_not_expose_token(monkeypatch):
    token = "never-print-this-token"
    c = client(monkeypatch, token=token)
    monkeypatch.setattr(
        "app.services.cj_commission_client.httpx.post",
        lambda *a, **k: Response(401, {}),
    )
    with pytest.raises(CjCommissionClientError) as captured:
        c.fetch_commissions(
            since_posting_date=NOW - timedelta(days=1),
            before_posting_date=NOW,
        )
    assert token not in str(captured.value)


def test_client_transport_failure_does_not_expose_token(monkeypatch):
    token = "never-print-this-token"
    c = client(monkeypatch, token=token)
    monkeypatch.setattr(
        "app.services.cj_commission_client.httpx.post",
        lambda *a, **k: (_ for _ in ()).throw(httpx.TimeoutException(token)),
    )
    with pytest.raises(CjCommissionClientError) as captured:
        c.fetch_commissions(
            since_posting_date=NOW - timedelta(days=1),
            before_posting_date=NOW,
        )
    assert token not in str(captured.value)


class Query:
    def __init__(self, rows):
        self.rows = rows

    def filter_by(self, **kwargs):
        return self

    def all(self):
        return self.rows


class FakeDb:
    def __init__(self, *, network="CJ Affiliate"):
        self.run = SimpleNamespace(id="run")
        self.publication = SimpleNamespace(id="pub")
        self.context = SimpleNamespace(id="ctx", affiliate_program_id=7)
        self.link = SimpleNamespace(
            id=8,
            affiliate_program_id=7,
            attribution_context_id="ctx",
            is_active=True,
        )
        self.program = SimpleNamespace(id=7, network=network)

    def get(self, model, key):
        name = model.__name__
        return {
            "DistributionRun": self.run if key == "run" else None,
            "AffiliateProgram": self.program if key == 7 else None,
        }.get(name)

    def query(self, model):
        name = model.__name__
        if name == "AttributionPublication":
            return Query([self.publication])
        if name == "AttributionContext":
            return Query([self.context])
        if name == "AffiliateLink":
            return Query([self.link])
        raise AssertionError(name)


class FakeClient:
    publisher_cid = "800000089"

    def __init__(self, rows):
        self.rows = rows

    def fetch_commissions(self, **kwargs):
        return self.rows


class FakeBridge:
    def __init__(self):
        self.calls = []

    def record_provider_conversion(self, **kwargs):
        self.calls.append(kwargs)
        return {"created": True}


def service(rows, *, network="CJ Affiliate"):
    bridge = FakeBridge()
    result = CjFinancialIngestionService(
        FakeDb(network=network),
        client=FakeClient(rows),
        bridge=bridge,
    )
    return result, bridge


def test_ingestion_maps_cj_signed_correction_as_distinct_provider_event():
    rows = [
        record(),
        record(
            commissionId="1002",
            original=False,
            saleAmountUsd="-100.00",
            pubCommissionAmountUsd="-10.00",
        ),
    ]
    s, bridge = service(rows)
    result = s.sync(
        distribution_run_id="run",
        advertiser_id="4001",
        since_posting_date=NOW - timedelta(days=1),
        before_posting_date=NOW,
    )
    assert result["matched_count"] == 2
    assert result["correction_count"] == 1
    assert [call["external_conversion_id"] for call in bridge.calls] == [
        "cj:1001",
        "cj:1002",
    ]
    assert str(bridge.calls[1]["sale_amount"]) == "-100.00"
    assert str(bridge.calls[1]["commission_amount"]) == "-10.00"


def test_ingestion_uses_only_locked_or_closed_as_approved():
    rows = [
        record(commissionId="1", actionStatus="new"),
        record(commissionId="2", actionStatus="extended"),
        record(commissionId="3", actionStatus="locked"),
        record(commissionId="4", actionStatus="closed"),
    ]
    s, bridge = service(rows)
    result = s.sync(
        distribution_run_id="run",
        advertiser_id="4001",
        since_posting_date=NOW - timedelta(days=1),
        before_posting_date=NOW,
    )
    assert [call["conversion_status"] for call in bridge.calls] == [
        "pending",
        "pending",
        "approved",
        "approved",
    ]
    assert result["pending_count"] == 2
    assert result["approved_count"] == 2


def test_ingestion_rejects_publisher_cid_mismatch():
    s, _bridge = service([record(publisherId="999")])
    with pytest.raises(ValueError, match="publisher CID"):
        s.sync(
            distribution_run_id="run",
            advertiser_id="4001",
            since_posting_date=NOW - timedelta(days=1),
            before_posting_date=NOW,
        )


def test_ingestion_rejects_non_cj_program():
    s, _bridge = service([record()], network="Impact")
    with pytest.raises(ValueError, match="configured for CJ"):
        s.sync(
            distribution_run_id="run",
            advertiser_id="4001",
            since_posting_date=NOW - timedelta(days=1),
            before_posting_date=NOW,
        )


def test_sync_payload_forbids_caller_secret_fields():
    base = {
        "distribution_run_id": "run",
        "advertiser_id": "4001",
        "since_posting_date": NOW - timedelta(days=1),
        "before_posting_date": NOW,
    }
    for field in ("token", "publisher_cid", "personal_access_token"):
        with pytest.raises(ValidationError):
            CjCommissionSyncRequest(**base, **{field: "secret"})
