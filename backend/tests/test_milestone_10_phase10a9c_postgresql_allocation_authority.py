"""Guarded PostgreSQL qualification for immutable M10A9C shared-cost allocation authority."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.affiliate_financial.cost_allocation_contracts import RecordSharedCostAllocationRequest, SharedCostAllocationLineRequest
from app.affiliate_financial.cost_event_contracts import RecordAffiliateCostEventRequest
from app.distribution.contracts import CreateDistributionRunRequest
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_cost_allocation import AffiliateCostAllocationBatch, AffiliateCostAllocationLine
from app.models.affiliate_cost_event import AffiliateCostEvent
from app.models.affiliate_program import AffiliateProgram
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.attribution import AttributionContext, AttributionPublication
from app.models.content_brief import ContentBrief
from app.models.content_evaluation import ContentEvaluation
from app.models.content_generation_run import ContentGenerationRun
from app.models.crm import ContactPoint, Lead
from app.models.discovery import DiscoveryCandidate, DiscoveryRun
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.outreach import OutreachIntent
from app.models.outreach_delivery import OutreachDeliveryAttempt
from app.models.outreach_provider_dispatch import OutreachProviderDispatch
from app.models.product import Product
from app.models.publishing_queue import PublishingQueue
from app.services.affiliate_cost_allocation_service import AffiliateCostAllocationConflict, AffiliateCostAllocationService
from app.services.affiliate_cost_event_service import AffiliateCostEventService
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_payout_settlement_link_service import AttributionPayoutSettlementLinkService
from app.services.attribution_publication_service import AttributionPublicationService
from app.services.distribution_run_service import DistributionRunService


ROLE, raw = os.getenv("ETM_G5_M10A9C_DB_ROLE"), os.getenv("ETM_G5_DATABASE_URL")
if not raw:
    pytest.skip("requires guarded ETM_G5_DATABASE_URL", allow_module_level=True)
url = make_url(raw)
if ROLE != "qualification" or not (url.drivername.startswith("postgresql") and url.host == "127.0.0.1" and url.port == 5432 and url.database == "etm_g5_m10a9c_shared_cost_allocation_qualification"):
    raise RuntimeError("M10A9C qualification database guard failed")


def _session():
    return sessionmaker(bind=create_engine(url.render_as_string(hide_password=False)), expire_on_commit=False)()


def _settled(*, currency="USD", create_settlement=True, product_id=None, program_id=None, publication_id=None):
    db, token = _session(), uuid4().hex
    try:
        product = db.get(Product, product_id) if product_id is not None else Product(name=token, website=f"https://{token}.invalid", category="test", affiliate_program="test", commission_type="percentage", commission_value="10", affiliate_score=1, grade="A", confidence=1, summary="", recommendation="", status="active")
        if product_id is None: db.add(product); db.flush()
        program = db.get(AffiliateProgram, program_id) if program_id is not None else AffiliateProgram(product_id=product.id, program_name=token, commission_type="percentage", commission_value="10", status="active")
        if program_id is None: db.add(program); db.flush()
        asset = AffiliateContentAsset(product_id=product.id, asset_type="article", title=token); db.add(asset); db.flush()
        if publication_id is None:
            queue = PublishingQueue(content_asset_id=asset.id, channel=token); db.add(queue); db.flush()
            publication = AttributionPublicationService(db).bind_legacy(queue.id)
        else:
            publication = db.get(AttributionPublication, publication_id)
        context = AttributionContextService(db).create(affiliate_program_id=program.id, attribution_publication_id=publication.id)
        db.commit()
        link = AttributionLinkBridgeService(db).create_bound_link(affiliate_program_id=program.id, attribution_context_id=context.id, name=token, destination_url="https://private.invalid", content_asset_id=asset.id)
        result = AttributionConversionBridgeService(db).record(affiliate_program_id=program.id, affiliate_link_id=link.id, external_conversion_id=token, customer_reference="private", sale_amount=Decimal("1000.00"), currency=currency, commission_rate=Decimal("10"), metadata_json=json.dumps({"private": token}))
        earning_link = AttributionEarningLinkService(db).reconcile(attribution_fact_id=result["fact"].id)
        earning, now = result["earning"], datetime.now(timezone.utc)
        payout = AffiliatePayout(affiliate_program_id=program.id, total_amount=earning.commission_amount, currency=currency, status="paid", paid_at=now, created_at=now, updated_at=now); db.add(payout); db.flush()
        earning.payout_id, earning.status = payout.id, "paid"
        attempt = AffiliatePayoutAttempt(payout_id=payout.id, attempt_number=1, amount=payout.total_amount, currency=currency, status="completed", provider="manual", idempotency_key=token, started_at=now, completed_at=now, created_at=now, updated_at=now); db.add(attempt); db.commit()
        settlement = AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=earning_link.id) if create_settlement else None
        return dict(product=product.id, program=program.id, content_asset=asset.id, distribution=publication.distribution_run_id, link=link.id, conversion=result["conversion"].id, earning=earning.id, payout=payout.id, payout_attempt=attempt.id, settlement=settlement.id if settlement else None, currency=currency)
    finally:
        db.close()


def _distribution_publication():
    db, token, now = _session(), uuid4().hex, datetime.now(timezone.utc)
    try:
        values = [
            DiscoveryRun(id=token+"d", input_type="URL", input_value=f"https://{token}.invalid", status="COMPLETED", idempotency_key=token+"d", candidate_count=1, verified_count=1, selected_count=1, created_at=now, updated_at=now),
        ]
        for value in values: db.add(value); db.flush()
        candidate = DiscoveryCandidate(id=token+"c", run_id=values[0].id, source_adapter="test", source_type="test", canonical_domain=f"{token}.invalid", program_identity_key=token, dedupe_key=token, commission_model="UNKNOWN", verification_status="VERIFIED", disposition="SELECTED", created_at=now, updated_at=now); db.add(candidate); db.flush()
        brief = ContentBrief(id=token+"b", discovery_run_id=values[0].id, discovery_candidate_id=candidate.id, content_type="ARTICLE", channel_intent="SEO", objective="proof", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key=token+"b", status="READY", created_at=now, updated_at=now); db.add(brief); db.flush()
        generation = ContentGenerationRun(id=token+"g", content_brief_id=brief.id, idempotency_key=token+"g", provider="test", model="test", prompt_version="v1", generation_parameters={}, status="COMPLETED", attempt_count=1, created_at=now, updated_at=now); db.add(generation); db.flush()
        artifact = GeneratedContentArtifact(id=token+"a", generation_run_id=generation.id, content_brief_id=brief.id, content_type="ARTICLE", title="proof", hook="proof", body="proof body", call_to_action="CHECK_DETAILS", affiliate_disclosure="disclosure", claims=[], status="GENERATED", created_at=now, updated_at=now); db.add(artifact); db.flush()
        evaluation = ContentEvaluation(id=token+"e", artifact_id=artifact.id, content_brief_id=brief.id, generation_run_id=generation.id, factual_grounding_score=100, offer_alignment_score=100, intent_alignment_score=100, clarity_score=100, cta_score=100, compliance_score=100, overall_score=100, decision="APPROVED", approved=True, evaluator_version="v1", policy_version="v1", claim_results=[], compliance_flags=[], unsupported_claims=[], missing_evidence_ids=[], revision_reasons=[], rejection_reasons=[], created_at=now, updated_at=now); db.add(evaluation); db.commit()
        run = DistributionRunService(db).create(CreateDistributionRunRequest(artifact.id, evaluation.id, "test", token, "fixture"))
        publication = AttributionPublicationService(db).bind_distribution(run.id); db.commit()
        return generation.id, run.id, publication.id
    finally:
        db.close()


def _outreach_dispatch():
    db, token, now = _session(), uuid4().hex, datetime.now(timezone.utc)
    try:
        fingerprint = uuid4().hex * 2
        lead = Lead(subject_id=None); db.add(lead); db.flush()
        contact = ContactPoint(lead_id=lead.id, kind="EMAIL", normalized_value=f"{token}@fixture.invalid"); db.add(contact); db.flush()
        intent = OutreachIntent(lead_id=lead.id, contact_point_id=contact.id, channel="EMAIL", purpose_key="affiliate:qualification", source_namespace="m10a9c.test", source_event_key=token+"-intent", request_fingerprint=fingerprint, eligibility_policy_version="v1", creation_contactability_state="CONTACTABLE", contactability_evaluated_as_of=now, contactability_decision_fingerprint=fingerprint, contactability_evidence={}); db.add(intent); db.flush()
        attempt = OutreachDeliveryAttempt(outreach_intent_id=intent.id, attempt_number=1, source_namespace="m10a9c.test", source_event_key=token+"-attempt", request_fingerprint=fingerprint); db.add(attempt); db.flush()
        dispatch = OutreachProviderDispatch(delivery_attempt_id=attempt.id, provider_key="test", provider_contract_version="v1", provider_operation_key=token, provider_operation_fingerprint=fingerprint, provider_payload_fingerprint=fingerprint, sender_identity_fingerprint=fingerprint, planned_at=now, dispatch_started_at=now); db.add(dispatch); db.commit()
        return dispatch.id
    finally:
        db.close()


def _cost(scope, amount, **correlations):
    db = _session()
    try:
        return AffiliateCostEventService(db).record(RecordAffiliateCostEventRequest(amount=amount, currency=correlations.pop("currency", "USD"), cost_type="provider_fee", allocation_scope=scope, source_namespace="m10a9c.cost", source_event_key=uuid4().hex, **correlations))
    finally:
        db.close()


def _request(cost_id, lines, *, source=None, policy="explicit-v1"):
    return RecordSharedCostAllocationRequest(cost_id, tuple(SharedCostAllocationLineRequest(earning, amount) for earning, amount in lines), policy, "m10a9c.allocation", source or uuid4().hex)


def test_database_head_schema_and_authority_only_surface():
    db = _session()
    try:
        assert MigrationContext.configure(db.connection()).get_current_revision() == "b1c2d3e4f5a6"
        schema = inspect(db.get_bind())
        assert {"affiliate_cost_allocation_batches", "affiliate_cost_allocation_lines"}.issubset(schema.get_table_names())
        batch_uniques = {tuple(item["column_names"]) for item in schema.get_unique_constraints("affiliate_cost_allocation_batches")}
        assert ("affiliate_cost_event_id",) in batch_uniques and ("source_namespace", "source_event_digest") in batch_uniques
    finally:
        db.close()


def test_balanced_explicit_allocation_exact_replay_and_conflicts():
    first = _settled(); second = _settled(product_id=first["product"], program_id=first["program"])
    cost = _cost("shared", Decimal("30.00"), product_id=first["product"], affiliate_program_id=first["program"])
    source = uuid4().hex
    request = _request(cost.id, ((first["earning"], Decimal("10.00")), (second["earning"], Decimal("20.00"))), source=source)
    db = _session()
    try:
        record = AffiliateCostAllocationService(db).record(request)
    finally: db.close()
    replay_db = _session()
    try:
        replay = AffiliateCostAllocationService(replay_db).record(_request(cost.id, tuple(reversed(((first["earning"], Decimal("10.00")), (second["earning"], Decimal("20.00"))))), source=source))
        assert replay == record and record.allocated_amount == Decimal("30.00") and record.currency == "USD"
        assert tuple((line.affiliate_earning_id, line.amount) for line in record.allocations) == ((first["earning"], Decimal("10.00")), (second["earning"], Decimal("20.00")))
    finally: replay_db.close()
    for conflicting in (_request(cost.id, ((first["earning"], Decimal("11.00")), (second["earning"], Decimal("19.00"))), source=source), _request(cost.id, ((first["earning"], Decimal("10.00")), (second["earning"], Decimal("20.00"))))):
        db = _session()
        try:
            with pytest.raises(AffiliateCostAllocationConflict): AffiliateCostAllocationService(db).record(conflicting)
        finally: db.close()
    other_cost = _cost("shared", Decimal("30.00"))
    db = _session()
    try:
        with pytest.raises(AffiliateCostAllocationConflict):
            AffiliateCostAllocationService(db).record(_request(other_cost.id, ((first["earning"], Decimal("30.00")),), source=source))
    finally: db.close()


def test_scope_balance_settlement_and_native_currency_fail_closed():
    settled = _settled(); unsettled = _settled(create_settlement=False)
    direct = _cost("direct", Decimal("10.00"), affiliate_earning_id=settled["earning"])
    global_cost = _cost("global", Decimal("10.00"))
    shared = _cost("shared", Decimal("10.00"))
    eur = _cost("shared", Decimal("10.00"), currency="EUR")
    cases = [
        _request(direct.id, ((settled["earning"], Decimal("10.00")),)),
        _request(global_cost.id, ((settled["earning"], Decimal("10.00")),)),
        _request(shared.id, ((settled["earning"], Decimal("9.99")),)),
        _request(shared.id, ((unsettled["earning"], Decimal("10.00")),)),
        _request(eur.id, ((settled["earning"], Decimal("10.00")),)),
    ]
    for request in cases:
        db = _session()
        try:
            with pytest.raises(ValueError): AffiliateCostAllocationService(db).record(request)
            assert not db.in_transaction()
        finally: db.close()


def test_all_traceable_correlations_match_or_fail_closed():
    generation_a, _, publication_a = _distribution_publication(); _, _, publication_b = _distribution_publication()
    first, second = _settled(publication_id=publication_a), _settled(publication_id=publication_b)
    fields = {"product_id":"product", "affiliate_program_id":"program", "content_asset_id":"content_asset", "distribution_run_id":"distribution", "affiliate_link_id":"link", "affiliate_conversion_id":"conversion", "affiliate_earning_id":"earning", "affiliate_payout_id":"payout", "affiliate_payout_attempt_id":"payout_attempt"}
    matching = _cost("shared", Decimal("9.00"), **{field:first[key] for field, key in fields.items()})
    db = _session()
    try:
        result = AffiliateCostAllocationService(db).record(_request(matching.id, ((first["earning"], Decimal("9.00")),)))
        assert result.allocated_amount == Decimal("9.00")
    finally: db.close()
    for field, key in fields.items():
        contradictory = _cost("shared", Decimal("1.00"), **{field:second[key]})
        db = _session()
        try:
            with pytest.raises(ValueError, match="contradicts"): AffiliateCostAllocationService(db).record(_request(contradictory.id, ((first["earning"], Decimal("1.00")),)))
            assert not db.in_transaction()
        finally: db.close()
    assert generation_a


def test_unsupported_operational_correlations_fail_closed():
    generation, _, publication = _distribution_publication(); identity = _settled(publication_id=publication); dispatch = _outreach_dispatch()
    costs = (_cost("shared", Decimal("5.00"), affiliate_earning_id=identity["earning"], content_generation_run_id=generation), _cost("shared", Decimal("5.00"), affiliate_earning_id=identity["earning"], outreach_provider_dispatch_id=dispatch))
    for cost in costs:
        db = _session()
        try:
            with pytest.raises(ValueError, match="unsupported operational"): AffiliateCostAllocationService(db).record(_request(cost.id, ((identity["earning"], Decimal("5.00")),)))
            assert not db.in_transaction()
        finally: db.close()


def test_batches_and_lines_are_append_only_and_cost_is_unchanged():
    identity = _settled(); cost = _cost("shared", Decimal("7.00"), affiliate_earning_id=identity["earning"])
    db = _session()
    try:
        result = AffiliateCostAllocationService(db).record(_request(cost.id, ((identity["earning"], Decimal("7.00")),)))
    finally: db.close()
    verify = _session()
    try:
        original_cost = verify.get(AffiliateCostEvent, cost.id)
        cost_state = (original_cost.id, original_cost.amount, original_cost.currency, original_cost.allocation_scope, original_cost.fingerprint)
        batch = verify.get(AffiliateCostAllocationBatch, result.id); line = verify.query(AffiliateCostAllocationLine).filter_by(allocation_batch_id=batch.id).one()
        authority = (batch.id, batch.allocated_amount, batch.fingerprint, line.id, line.amount, line.fingerprint)
        mutations = (
            ("UPDATE affiliate_cost_allocation_batches SET allocated_amount=8 WHERE id=:id", batch.id),
            ("DELETE FROM affiliate_cost_allocation_batches WHERE id=:id", batch.id),
            ("UPDATE affiliate_cost_allocation_lines SET amount=8 WHERE id=:id", line.id),
            ("DELETE FROM affiliate_cost_allocation_lines WHERE id=:id", line.id),
        )
        for statement, authority_id in mutations:
            with pytest.raises(Exception) as rejected: verify.execute(text(statement), {"id":authority_id})
            assert "append-only" in str(rejected.value).lower(); verify.rollback()
        batch = verify.get(AffiliateCostAllocationBatch, result.id); line = verify.query(AffiliateCostAllocationLine).filter_by(allocation_batch_id=batch.id).one(); original_cost = verify.get(AffiliateCostEvent, cost.id)
        assert (batch.id, batch.allocated_amount, batch.fingerprint, line.id, line.amount, line.fingerprint) == authority
        assert (original_cost.id, original_cost.amount, original_cost.currency, original_cost.allocation_scope, original_cost.fingerprint) == cost_state
    finally: verify.close()


def test_concurrent_same_cost_conflict_and_exact_replay():
    first, second = _settled(), _settled()
    conflict_cost = _cost("shared", Decimal("20.00")); barrier = Barrier(2)
    requests = (_request(conflict_cost.id, ((first["earning"], Decimal("20.00")),)), _request(conflict_cost.id, ((second["earning"], Decimal("20.00")),)))
    def allocate(request):
        db = _session()
        try:
            barrier.wait()
            try: return ("ok", AffiliateCostAllocationService(db).record(request).id)
            except AffiliateCostAllocationConflict: return ("conflict", None)
        finally: db.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(allocate, requests))
    assert sorted(value[0] for value in outcomes) == ["conflict", "ok"]
    verify = _session()
    try:
        batch = verify.query(AffiliateCostAllocationBatch).filter_by(affiliate_cost_event_id=conflict_cost.id).one()
        assert verify.query(AffiliateCostAllocationLine).filter_by(allocation_batch_id=batch.id).count() == 1
    finally: verify.close()
    replay_cost = _cost("shared", Decimal("6.00")); replay_request = _request(replay_cost.id, ((first["earning"], Decimal("6.00")),), source=uuid4().hex); replay_barrier = Barrier(2)
    def replay():
        db = _session()
        try:
            replay_barrier.wait(); return AffiliateCostAllocationService(db).record(replay_request).id
        finally: db.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: replay(), range(2)))
    assert ids[0] == ids[1]
