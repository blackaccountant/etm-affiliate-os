import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
import requests
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.affiliate_program import AffiliateProgram
from app.models.product import Product
from app.models.publishing_queue import PublishingQueue
from app.optimization.economic_candidate_comparison_contracts import OperatingProfitComparisonPolicy
from app.optimization.economic_recommendation_approval_contracts import (
    EconomicRecommendationApprovalDecision, EconomicRecommendationApprovalPolicy,
    EconomicRecommendationApprovalRequest, EconomicRecommendationApprovalState,
)
from app.optimization.economic_recommendation_experiment_design_contracts import (
    EconomicRecommendationExperimentDesignInput, EconomicRecommendationExperimentDesignPolicy,
    EconomicRecommendationExperimentDesignRequest,
)
from app.optimization.economic_recommendation_proposal_contracts import EconomicRecommendationPolicy, EconomicRecommendationProposalRequest
from app.optimization.eligible_operating_profit_candidate_set_contracts import EligibleOperatingProfitCandidateSetRequest
from app.optimization.operating_profit_evidence_eligibility_contracts import OperatingProfitEvidenceEligibilityPolicy
from app.optimization.ordered_economic_candidate_preference_contracts import OrderedEconomicCandidatePreferenceRequest
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_conversion_bridge_service import AttributionConversionBridgeService
from app.services.attribution_earning_link_service import AttributionEarningLinkService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_payout_settlement_link_service import AttributionPayoutSettlementLinkService
from app.services.attribution_publication_service import AttributionPublicationService
from app.services.economic_recommendation_approval_service import EconomicRecommendationApprovalService
from app.services.economic_recommendation_experiment_design_service import EconomicRecommendationExperimentDesignService

DATABASE = 'etm_g5_m11a10_experiment_design_qualification'
ROLE = os.getenv('ETM_G5_M11A10_DB_ROLE')
RAW = os.getenv('ETM_G5_M11A10_DATABASE_URL')
if not RAW:
    pytest.skip('requires guarded M11A10 URL', allow_module_level=True)
URL = make_url(RAW)
if ROLE != 'qualification' or not URL.drivername.startswith('postgresql') or URL.host != '127.0.0.1' or URL.port != 5432 or URL.database != DATABASE:
    raise RuntimeError('M11A10 database guard failed')


def _session():
    engine = create_engine(URL.render_as_string(hide_password=False))
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _proposal_request(currency='USD'):
    return EconomicRecommendationProposalRequest(
        OrderedEconomicCandidatePreferenceRequest(
            EligibleOperatingProfitCandidateSetRequest(
                ('affiliate_program',), currency,
                OperatingProfitEvidenceEligibilityPolicy('qualification',1,1,1),
                datetime(2100,1,1,tzinfo=timezone.utc),
            ),
            OperatingProfitComparisonPolicy('qualification-pairwise-v1'),
        ),
        EconomicRecommendationPolicy('qualification-recommendation-v1'),
    )


def _dimensions(program_id): return (('affiliate_program',program_id),)


def _approval_request(currency, approved_dimensions, state=EconomicRecommendationApprovalState.APPROVED, *, decision_reference='m11a10-approval'):
    when=datetime(2100,1,1,tzinfo=timezone.utc)
    return EconomicRecommendationApprovalRequest(
        _proposal_request(currency),
        EconomicRecommendationApprovalDecision(state,approved_dimensions,'pg-qualification',decision_reference,when),
        EconomicRecommendationApprovalPolicy('qualification-approval-v1'),
    )


def _design_input(dimensions, experiment_reference):
    return EconomicRecommendationExperimentDesignInput(
        experiment_reference, dimensions, f'hypothesis-{experiment_reference}',
        'existing-strategy', f'treatment-{experiment_reference}', 'operating-profit-evidence',
        timedelta(days=14), f'design-{experiment_reference}', datetime(2100,1,2,tzinfo=timezone.utc),
    )


def _design_request(approval_request,*inputs):
    return EconomicRecommendationExperimentDesignRequest(
        approval_request, tuple(inputs), EconomicRecommendationExperimentDesignPolicy('qualification-experiment-design-v1')
    )


def _settled(*,product_id=None,program_id=None,currency='USD'):
    db=_session(); token=uuid4().hex
    try:
        product=db.get(Product,product_id) if product_id else Product(name=token,website=f'https://{token}.invalid',category='test',affiliate_program='test',commission_type='percentage',commission_value='10',affiliate_score=1,grade='A',confidence=1,summary='',recommendation='',status='active')
        if not product_id: db.add(product); db.flush()
        program=db.get(AffiliateProgram,program_id) if program_id else AffiliateProgram(product_id=product.id,program_name=token,commission_type='percentage',commission_value='10',status='active')
        if not program_id: db.add(program); db.flush()
        asset=AffiliateContentAsset(product_id=product.id,asset_type='article',title=token); db.add(asset); db.flush()
        queue=PublishingQueue(content_asset_id=asset.id,channel=token); db.add(queue); db.flush()
        publication=AttributionPublicationService(db).bind_legacy(queue.id)
        context=AttributionContextService(db).create(affiliate_program_id=program.id,attribution_publication_id=publication.id)
        db.commit()
        link=AttributionLinkBridgeService(db).create_bound_link(affiliate_program_id=program.id,attribution_context_id=context.id,name=token,destination_url='https://private.invalid',content_asset_id=asset.id)
        result=AttributionConversionBridgeService(db).record(affiliate_program_id=program.id,affiliate_link_id=link.id,external_conversion_id=token,customer_reference='private',sale_amount=Decimal('1000'),currency=currency,commission_rate=Decimal('10'),metadata_json=json.dumps({'private':token}))
        earning_link=AttributionEarningLinkService(db).reconcile(attribution_fact_id=result['fact'].id)
        earning=result['earning']; now=datetime.now(timezone.utc)
        payout=AffiliatePayout(affiliate_program_id=program.id,total_amount=earning.commission_amount,currency=currency,status='paid',paid_at=now,created_at=now,updated_at=now); db.add(payout); db.flush()
        earning.payout_id=payout.id; earning.status='paid'
        db.add(AffiliatePayoutAttempt(payout_id=payout.id,attempt_number=1,amount=payout.total_amount,currency=currency,status='completed',provider='manual',idempotency_key=token,started_at=now,completed_at=now,created_at=now,updated_at=now)); db.commit()
        AttributionPayoutSettlementLinkService(db).reconcile(attribution_earning_link_id=earning_link.id)
        return {'product':product.id,'program':program.id}
    finally: db.close()


def _seed(counts,currency='USD'):
    identities=[_settled(currency=currency) for _ in counts]
    for identity,count in zip(identities,counts,strict=True):
        for _ in range(count-1): _settled(product_id=identity['product'],program_id=identity['program'],currency=currency)
    return identities


def _ids(rows): return [dict(row.approved_recommendation_row.dimensions)['affiliate_program'] for row in rows]
def _network_forbidden(*_args,**_kwargs): raise AssertionError('network called')
def _forbid_network(monkeypatch):
    monkeypatch.setattr(requests.sessions.Session,'request',_network_forbidden)
    monkeypatch.setattr(httpx.Client,'request',_network_forbidden)


class _CapturedApprovalService:
    def __init__(self,db,inside): self._delegate=EconomicRecommendationApprovalService(db); self._inside=inside; self.calls=0; self.outcome=None
    def project(self,value):
        self.calls+=1; self._inside[0]=True
        try: self.outcome=self._delegate.project(value); return self.outcome
        finally: self._inside[0]=False


def _design_service(db,outside):
    inside=[False]; captured=_CapturedApprovalService(db,inside)
    event.listen(db.get_bind(),'before_cursor_execute',lambda *_args: outside.append(_args[2]) if not inside[0] else None)
    return EconomicRecommendationExperimentDesignService(db,recommendation_approval_service=captured),captured


def test_current_head_requires_no_m11a10_migration():
    db=_session()
    try: assert MigrationContext.configure(db.connection()).get_current_revision()=='c3d4e5f6a7b8'
    finally: db.close()


def test_real_approved_design_binds_exact_row_and_adds_no_sql(monkeypatch):
    x,_y,_z=_seed((3,2,1),'USD'); db=_session(); outside=[]; service,captured=_design_service(db,outside); _forbid_network(monkeypatch)
    try:
        approval=_approval_request('USD',(_dimensions(x['program']),),decision_reference='approve-x')
        result=service.project(_design_request(approval,_design_input(_dimensions(x['program']),'experiment-x')))
        assert captured.calls==1 and outside==[] and len(result)==1 and _ids(result)==[x['program']]
        assert result[0].approved_recommendation_row is captured.outcome.approved_rows[0]
        assert result[0].approved_recommendation_row.operating_profit is captured.outcome.approved_rows[0].operating_profit
        assert type(result[0].approved_recommendation_row.operating_profit) is Decimal
        assert result[0].actor_reference=='pg-qualification' and result[0].decision_reference=='approve-x'
        assert result[0].approval_policy_version=='qualification-approval-v1'
        assert result[0].experiment_design_policy_version=='qualification-experiment-design-v1'
        assert db.execute(text('SHOW transaction_isolation')).scalar_one()=='repeatable read'
        assert db.execute(text('SHOW transaction_read_only')).scalar_one()=='on'
        with pytest.raises(Exception): db.execute(text('CREATE TABLE m11a10_forbidden_write (id integer)'))
        db.rollback()
    finally: db.close()


def test_real_multiple_approved_designs_normalize_input_order(monkeypatch):
    x,_y,z=_seed((2,1,2),'EUR'); db=_session(); outside=[]; service,captured=_design_service(db,outside); _forbid_network(monkeypatch)
    try:
        approval=_approval_request('EUR',(_dimensions(x['program']),_dimensions(z['program'])),decision_reference='approve-tie')
        result=service.project(_design_request(approval,_design_input(_dimensions(z['program']),'experiment-z'),_design_input(_dimensions(x['program']),'experiment-x')))
        assert captured.calls==1 and outside==[] and _ids(result)==[x['program'],z['program']]
        assert [r.experiment_reference for r in result]==['experiment-x','experiment-z']
        assert result[0].approved_recommendation_row is captured.outcome.approved_rows[0]
        assert result[1].approved_recommendation_row is captured.outcome.approved_rows[1]
    finally: db.close()


def test_a_b_a_c_snapshot_design_is_stable_then_fresh_approval_is_required(monkeypatch):
    x,_y,z=_seed((3,2,1),'CAD'); _forbid_network(monkeypatch)
    reader=_session(); outside_a=[]; service_a,captured_a=_design_service(reader,outside_a)
    try:
        before=service_a.project(_design_request(_approval_request('CAD',(_dimensions(x['program']),),decision_reference='snapshot-x-before'),_design_input(_dimensions(x['program']),'experiment-x-before')))
        original_profit=captured_a.outcome.approved_rows[0].operating_profit
        assert captured_a.calls==1 and outside_a==[] and _ids(before)==[x['program']]
        for _ in range(3): _settled(product_id=z['product'],program_id=z['program'],currency='CAD')
        same=service_a.project(_design_request(_approval_request('CAD',(_dimensions(x['program']),),decision_reference='snapshot-x-same'),_design_input(_dimensions(x['program']),'experiment-x-same')))
        assert captured_a.calls==2 and outside_a==[] and _ids(same)==[x['program']]
        assert captured_a.outcome.approved_rows[0].operating_profit==original_profit
        assert reader.execute(text('SHOW transaction_isolation')).scalar_one()=='repeatable read'
        assert reader.execute(text('SHOW transaction_read_only')).scalar_one()=='on'
        with pytest.raises(Exception): reader.execute(text('CREATE TABLE m11a10_snapshot_forbidden_write (id integer)'))
        reader.rollback()
    finally: reader.close()
    fresh=_session(); outside_c=[]; service_c,captured_c=_design_service(fresh,outside_c)
    try:
        with pytest.raises(ValueError):
            service_c.project(_design_request(_approval_request('CAD',(_dimensions(x['program']),),decision_reference='snapshot-stale-x'),_design_input(_dimensions(x['program']),'experiment-stale-x')))
        assert captured_c.calls==1 and outside_c==[]
        current=service_c.project(_design_request(_approval_request('CAD',(_dimensions(z['program']),),decision_reference='snapshot-current-z'),_design_input(_dimensions(z['program']),'experiment-current-z')))
        assert captured_c.calls==2 and outside_c==[] and _ids(current)==[z['program']]
    finally: fresh.close()
