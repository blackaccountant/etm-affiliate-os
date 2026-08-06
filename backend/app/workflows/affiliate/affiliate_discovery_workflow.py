from time import perf_counter

from app.workflow_engine.workflow_result import WorkflowResult
from app.services.research_pipeline import ResearchPipeline
from app.services.product_intelligence_service import ProductIntelligenceService
from app.intelligence.scoring import AffiliateScoringEngine
from app.database.session import SessionLocal


class AffiliateDiscoveryWorkflow:
    """
    Complete Affiliate Discovery Workflow

    Flow:

        URL
          ↓
    Research Pipeline
          ↓
    Affiliate Analysis
          ↓
    Intelligence Scoring
          ↓
    Database Save
          ↓
    WorkflowResult
    """

    def __init__(self):

        self.pipeline = ResearchPipeline()
        self.scorer = AffiliateScoringEngine()

    def execute(self, payload: dict):

        start = perf_counter()

        db = SessionLocal()

        events = [
            "WorkflowStarted"
        ]

        try:

            url = payload.get("url")

            # --------------------------------------------------
            # Step 1 - AI Research
            # --------------------------------------------------

            analysis = self.pipeline.analyze(url)

            events.append(
                "AnalysisCompleted"
            )

            # --------------------------------------------------
            # Step 2 - Intelligence Scoring
            # --------------------------------------------------

            intelligence = self.scorer.score(
                analysis
            )

            events.append(
                "ScoringCompleted"
            )

            # --------------------------------------------------
            # Step 3 - Save to Database
            # --------------------------------------------------

            service = ProductIntelligenceService(db)

            database = service.save_analysis(
                analysis,
                intelligence,
            )

            events.append(
                "DatabaseSaved"
            )

            duration = perf_counter() - start

            events.append(
                "WorkflowCompleted"
            )

            return WorkflowResult(
                success=True,
                workflow="affiliate_discovery",
                data={
                    "analysis": analysis,
                    "intelligence": intelligence,
                    "database": database,
                },
                events=events,
                errors=[],
                duration=duration,
            )

        except Exception as exc:

            duration = perf_counter() - start

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