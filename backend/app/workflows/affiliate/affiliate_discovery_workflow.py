"""
Affiliate Discovery Workflow

Coordinates the complete affiliate intelligence workflow.
"""

from __future__ import annotations

from app.database.session import SessionLocal
from app.intelligence.scoring import AffiliateScoringEngine
from app.services.product_intelligence_service import (
    ProductIntelligenceService,
)
from app.services.research_pipeline import ResearchPipeline
from app.workflows.core.workflow_result import (
    WorkflowResult,
)


class AffiliateDiscoveryWorkflow:
    """
    Complete affiliate discovery workflow.
    """

    def __init__(self):

        self.pipeline = ResearchPipeline()
        self.scoring = AffiliateScoringEngine()

    def execute(
        self,
        url: str,
    ) -> WorkflowResult:

        # --------------------------
        # Research
        # --------------------------

        analysis = self.pipeline.analyze(url)

        # --------------------------
        # Intelligence
        # --------------------------

        intelligence = self.scoring.score(
            analysis
        )

        # --------------------------
        # Persistence
        # --------------------------

        db = SessionLocal()

        try:

            service = ProductIntelligenceService(db)

            database = service.save_analysis(
                analysis,
                intelligence,
            )

        finally:

            db.close()

        # --------------------------
        # Result
        # --------------------------

        return WorkflowResult(
            analysis=analysis,
            intelligence=intelligence,
            database=database,
            metadata={
                "workflow": "AffiliateDiscoveryWorkflow",
            },
        )