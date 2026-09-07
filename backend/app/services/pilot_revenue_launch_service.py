"""Reconcile Pilot 1 pre-publication revenue lineage without owning transactions."""

from app.distribution.contracts import CreateDistributionRunRequest, canonicalize_prepared_content_body
from app.distribution.pilot_revenue_launch_contracts import PilotRevenueLaunchRequest, PilotRevenueLaunchResult
from app.attribution.bridge_contracts import AttributionBridgeConflict
from app.models.affiliate_link import AffiliateLink
from app.models.affiliate_program import AffiliateProgram
from app.models.attribution import AttributionContext, AttributionPublication
from app.models.content_evaluation import ContentEvaluation
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.repositories.distribution_run_repository import DistributionRunRepository
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_link_bridge_service import AttributionLinkBridgeService
from app.services.attribution_publication_service import AttributionPublicationService
from app.services.distribution_run_service import DistributionRunService


class PilotRevenueLaunchService:
    def __init__(self, db, *, distribution_runs=None, publications=None, contexts=None, links=None):
        self.db = db
        self._distribution_runs = DistributionRunService(db) if distribution_runs is None else distribution_runs
        self._publications = AttributionPublicationService(db) if publications is None else publications
        self._contexts = AttributionContextService(db) if contexts is None else contexts
        self._links = AttributionLinkBridgeService(db) if links is None else links

    @staticmethod
    def _run_authority(artifact, evaluation, request):
        prepared_body = canonicalize_prepared_content_body(
            artifact.body if request.prepared_content_body is None else request.prepared_content_body
        )
        return {
            "generated_content_artifact_id": artifact.id,
            "content_evaluation_id": evaluation.id,
            "platform": request.platform,
            "account_reference": request.account_reference,
            "destination": request.destination,
            "payload_fingerprint": DistributionRunService.payload_fingerprint(prepared_body),
            "scheduled_for": request.scheduled_for,
        }

    @staticmethod
    def _matches_run_authority(run, authority):
        return all(
            getattr(run, field) == value
            for field, value in authority.items()
        )

    def _prevalidate(self, request):
        artifact = self.db.get(GeneratedContentArtifact, request.artifact_id)
        evaluation = self.db.get(ContentEvaluation, request.evaluation_id)
        link = self.db.get(AffiliateLink, request.affiliate_link_id)
        if artifact is None:
            raise ValueError("generated content artifact does not exist")
        if evaluation is None:
            raise ValueError("content evaluation does not exist")
        if evaluation.artifact_id != artifact.id or evaluation.generation_run_id != artifact.generation_run_id or evaluation.content_brief_id != artifact.content_brief_id:
            raise ValueError("content evaluation does not match artifact lineage")
        if evaluation.decision != "APPROVED" or evaluation.approved is not True:
            raise ValueError("content evaluation is not approved for distribution")
        if link is None:
            raise ValueError("affiliate link does not exist")
        if link.is_active is not True:
            raise ValueError("affiliate link is inactive")
        if type(link.destination_url) is not str or not link.destination_url.strip():
            raise ValueError("affiliate link destination_url is invalid")
        if self.db.get(AffiliateProgram, link.affiliate_program_id) is None:
            raise ValueError("affiliate link program does not exist")

        authority = self._run_authority(artifact, evaluation, request)
        if link.attribution_context_id is not None:
            context = self.db.get(AttributionContext, link.attribution_context_id)
            publication = self.db.get(AttributionPublication, context.attribution_publication_id) if context is not None else None
            bound_run = (
                DistributionRunRepository(self.db).get_by_id(publication.distribution_run_id)
                if publication is not None else None
            )
            if context is None or publication is None or bound_run is None:
                raise AttributionBridgeConflict("affiliate link is bound to incompatible attribution authority")
            if (
                context.affiliate_program_id != link.affiliate_program_id
                or not self._matches_run_authority(bound_run, authority)
            ):
                raise AttributionBridgeConflict("affiliate link is bound to incompatible attribution authority")
        return artifact, evaluation, link

    def launch(self, request: PilotRevenueLaunchRequest):
        normalized = request.normalized()
        artifact, evaluation, link = self._prevalidate(normalized)
        run = self._distribution_runs.create(CreateDistributionRunRequest(
            generated_content_artifact_id=artifact.id,
            content_evaluation_id=evaluation.id,
            platform=normalized.platform,
            account_reference=normalized.account_reference,
            destination=normalized.destination,
            prepared_content_body=normalized.prepared_content_body,
            scheduled_for=normalized.scheduled_for,
        ))
        publication = self._publications.bind_distribution(run.id)
        context = self._contexts.create(
            affiliate_program_id=link.affiliate_program_id,
            attribution_publication_id=publication.id,
        )
        bound_link, _fact = self._links.bind_existing(
            affiliate_link_id=link.id, attribution_context_id=context.id,
        )
        return PilotRevenueLaunchResult(
            distribution_run_id=run.id,
            attribution_publication_id=publication.id,
            attribution_context_id=context.id,
            affiliate_link_id=bound_link.id,
            tracking_code=bound_link.tracking_code,
            public_redirect_path=f"/affiliate-links/go/{bound_link.tracking_code}",
        )
