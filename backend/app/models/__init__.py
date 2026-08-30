"""SQLAlchemy model registry.

All models must be imported here so SQLAlchemy
can resolve relationship strings.
"""

from app.models.product import Product
from app.models.affiliate_program import AffiliateProgram
from app.models.affiliate_opportunity import AffiliateOpportunity
from app.models.product_intelligence_history import ProductIntelligenceHistory
from app.models.execution import Execution
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.content_seo_score import ContentSEOScore
from app.models.content_approval import ContentApproval
from app.models.publishing_queue import PublishingQueue
from app.models.affiliate_link import AffiliateLink
from app.models.affiliate_click import AffiliateClick
from app.models.affiliate_conversion import AffiliateConversion
from app.models.affiliate_earning import AffiliateEarning
from app.models.affiliate_payout import AffiliatePayout
from app.models.affiliate_payout_attempt import AffiliatePayoutAttempt
from app.models.mission_record import MissionRecord
from app.models.worker import Worker
from app.models.discovery import DiscoveryRun, DiscoveryCandidate, EvidenceObservation
from app.models.content_brief import ContentBrief
from app.models.content_brief_evidence import ContentBriefEvidence
from app.models.content_generation_run import ContentGenerationRun
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.content_evaluation import ContentEvaluation
from app.models.content_repurposing_run import ContentRepurposingRun
from app.models.distribution_run import DistributionRun
from app.models.audience import (
    AudienceEvidence,
    AudienceExternalIdentity,
    AudienceObservation,
    AudienceResearchRun,
    AudienceSubject,
    AudienceSignal,
    AudienceSignalEvidence,
    AudienceProfile,
    AudienceProfileSignal,
    AudienceSegment,
    AudienceSegmentRevision,
    AudienceSegmentMembership,
    AudienceQualificationAssessment,
    AudienceQualificationAssessmentMembership,
    AudienceQualificationContribution,
)
from app.models.crm import (
    Lead,
    ContactPoint,
    ContactPointProvenance,
    ContactPointStateEvent,
    PermissionEvent,
    SuppressionEvent,
)
from app.models.crm_relationships import LeadLifecycleEvent, LeadQualificationLink
