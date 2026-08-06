"""
Affiliate Discovery Workflow

Coordinates the affiliate discovery pipeline.
"""

from app.database.session import SessionLocal
from app.intelligence.scoring import AffiliateScoringEngine
from app.services.product_intelligence_service import (
    ProductIntelligenceService,
)
from app.services.research_pipeline import ResearchPipeline
from app.workflows.core.workflow_result import WorkflowResult


class AffiliateDiscoveryWorkflow:
    """
    Complete affiliate discovery workflow.
    """

    def __init__(self):
        self.pipeline = ResearchPipeline()
        self.scoring = AffiliateScoringEngine()

    def execute(self, payload: dict) -> WorkflowResult:
        """
        Execute the affiliate discovery workflow.

        Expected payload:
        {
            "url": "https://example.com"
        }
        """

        url = payload.get("url")

        if not url:
            raise ValueError("Payload must contain a 'url'.")

        # -------------------------------
        # Run research pipeline
        # -------------------------------

        analysis = self.pipeline.analyze(url)

        # -------------------------------
        # Score the analysis
        # (ResearchPipeline already returns
        # an AffiliateAnalysis object)
        # -------------------------------

        intelligence = self.scoring.score(analysis)

        # -------------------------------
        # Save to database
        # -------------------------------

        db = SessionLocal()

        try:
            service = ProductIntelligenceService(db)

            database = service.save_analysis(
                analysis,
                intelligence,
            )

        finally:
            db.close()

        # -------------------------------
        # Return workflow result
        # -------------------------------

        return WorkflowResult(
            analysis=analysis,
            intelligence=intelligence,
            database=database,
            metadata={
                "workflow": "AffiliateDiscoveryWorkflow"
            },
        )