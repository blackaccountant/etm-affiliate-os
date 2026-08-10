"""
Affiliate Discovery Workflow

Complete affiliate discovery pipeline.

Flow:

    URL
      ↓
    Research Pipeline
      ↓
    Affiliate Analysis
      ↓
    Intelligence Scoring
      ↓
    Decision Engine
      ↓
    Database Save
      ↓
    WorkflowResult
"""

from time import perf_counter

from app.workflow_engine.workflow_result import WorkflowResult

from app.services.research_pipeline import ResearchPipeline

from app.services.product_intelligence_service import (
    ProductIntelligenceService,
)

from app.intelligence.scoring import (
    AffiliateScoringEngine,
)

from app.intelligence.decision_engine import (
    AffiliateDecisionEngine,
)

from app.database.session import SessionLocal


class AffiliateDiscoveryWorkflow:
    """
    Complete Affiliate Discovery Workflow.

    Coordinates:

    1. Website research
    2. Affiliate analysis
    3. Intelligence scoring
    4. Business decision
    5. Database persistence
    6. Workflow result
    """

    def __init__(self):

        self.pipeline = ResearchPipeline()

        self.scorer = AffiliateScoringEngine()

        self.decision_engine = (
            AffiliateDecisionEngine()
        )


    def execute(
        self,
        payload: dict,
    ):

        start = perf_counter()

        db = SessionLocal()

        events = [
            "WorkflowStarted"
        ]


        try:

            # ==================================================
            # Step 1 - Get URL
            # ==================================================

            payload = payload or {}

            url = payload.get(
                "url"
            )


            if not url:

                raise ValueError(
                    "A URL is required for "
                    "affiliate discovery."
                )


            events.append(
                "ResearchStarted"
            )


            # ==================================================
            # Step 2 - AI Research
            # ==================================================

            analysis = self.pipeline.analyze(
                url
            )


            events.append(
                "AnalysisCompleted"
            )

            events.append(
                "ResearchCompleted"
            )


            # ==================================================
            # Step 3 - Intelligence Scoring
            # ==================================================

            intelligence = self.scorer.score(
                analysis
            )


            events.append(
                "ScoringCompleted"
            )


            # ==================================================
            # Step 4 - Decision Engine
            # ==================================================

            decision = self.decision_engine.decide(
                intelligence
            )


            events.append(
                "DecisionGenerated"
            )


            # ==================================================
            # Step 5 - Database Save
            # ==================================================

            service = ProductIntelligenceService(
                db
            )


            database = service.save_analysis(
                analysis,
                intelligence,
            )


            events.append(
                "DatabaseSaved"
            )


            # ==================================================
            # Step 6 - Complete
            # ==================================================

            duration = (
                perf_counter()
                - start
            )


            events.append(
                "WorkflowCompleted"
            )


            return WorkflowResult(

                success=True,

                workflow="affiliate_discovery",

                data={

                    "analysis": analysis,

                    "intelligence": intelligence,

                    "decision": decision,

                    "database": database,

                },

                events=events,

                errors=[],

                duration=duration,

            )


        except Exception as exc:

            duration = (
                perf_counter()
                - start
            )


            events.append(
                "WorkflowFailed"
            )


            return WorkflowResult(

                success=False,

                workflow="affiliate_discovery",

                data={},

                events=events,

                errors=[
                    str(exc)
                ],

                duration=duration,

            )


        finally:

            db.close()