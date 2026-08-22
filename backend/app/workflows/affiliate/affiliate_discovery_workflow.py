"""
Affiliate Discovery Workflow

Production affiliate intelligence pipeline.

Flow:

URL
 ↓
Research
 ↓
Discovery
 ↓
Scoring
 ↓
Decision
 ↓
Save Intelligence
 ↓
Opportunity Generation
 ↓
Content Strategy
 ↓
Content Generation
 ↓
SEO Optimization
 ↓
Approval Engine
 ↓
Publishing Ready
"""


from time import perf_counter


from app.workflow_engine.workflow_result import WorkflowResult


from app.services.research_pipeline import ResearchPipeline
from app.services.affiliate_discovery_service import AffiliateDiscoveryService

from app.services.product_intelligence_service import (
    ProductIntelligenceService,
)

from app.services.opportunity_engine import OpportunityEngine

from app.services.affiliate_opportunity_service import (
    AffiliateOpportunityService,
)

from app.services.content_strategy_engine import (
    ContentStrategyEngine,
)

from app.services.affiliate_content_asset_service import (
    AffiliateContentAssetService,
)

from app.services.content_execution_service import (
    ContentExecutionService,
)

from app.services.seo_optimizer_service import (
    SEOOptimizerService,
)

from app.services.content_approval_service import (
    ContentApprovalService,
)

from app.services.publishing_queue_service import (
    PublishingQueueService,
)


from app.intelligence.scoring import AffiliateScoringEngine
from app.intelligence.decision_engine import AffiliateDecisionEngine


from app.models.product import Product
from app.models.affiliate_program import AffiliateProgram


from app.database.session import SessionLocal



class AffiliateDiscoveryWorkflow:


    def __init__(self):

        self.research_pipeline = ResearchPipeline()

        self.discovery_service = AffiliateDiscoveryService()

        self.scoring_engine = AffiliateScoringEngine()

        self.decision_engine = AffiliateDecisionEngine()

        self.opportunity_engine = OpportunityEngine()

        self.content_strategy_engine = ContentStrategyEngine()



    def execute(
        self,
        payload: dict,
    ):


        start = perf_counter()

        db = SessionLocal()

        events = [
            "WorkflowStarted"
        ]


        content_assets = []

        opportunity = None



        try:


            url = payload.get("url")


            if not url:

                raise ValueError(
                    "URL is required"
                )


            events.append(
                "ResearchStarted"
            )


            analysis = (
                self.research_pipeline.analyze(url)
            )


            events.append(
                "ResearchCompleted"
            )



            discovery = (
                self.discovery_service.discover(url)
            )


            events.append(
                "AffiliateDiscoveryCompleted"
            )



            intelligence = (
                self.scoring_engine.score(
                    analysis,
                    discovery,
                )
            )


            events.append(
                "ScoringCompleted"
            )



            decision = (
                self.decision_engine.decide(
                    intelligence
                )
            )


            events.append(
                "DecisionGenerated"
            )



            intelligence_service = ProductIntelligenceService(db)


            database = (
                intelligence_service.save_analysis(
                    analysis,
                    discovery,
                    intelligence,
                )
            )


            events.append(
                "DatabaseSaved"
            )



            product = (
                db.query(Product)
                .filter(
                    Product.id == database.product_id
                )
                .first()
            )



            affiliate_program = None


            if product:

                affiliate_program = (
                    db.query(AffiliateProgram)
                    .filter(
                        AffiliateProgram.product_id
                        ==
                        product.id
                    )
                    .first()
                )



            if product and affiliate_program:


                opportunity = (
                    self.opportunity_engine.generate(
                        product,
                        affiliate_program,
                        intelligence,
                    )
                )



                AffiliateOpportunityService(db).save_opportunity(
                    product.id,
                    opportunity,
                )


                events.append(
                    "OpportunityGenerated"
                )



                content_assets = (
                    self.content_strategy_engine.generate(
                        product,
                        opportunity,
                    )
                )


                events.append(
                    "ContentAssetsGenerated"
                )



                saved_assets = (
                    AffiliateContentAssetService(db)
                    .save_assets(
                        product.id,
                        content_assets,
                    )
                )


                events.append(
                    "ContentAssetsSaved"
                )



                execution_service = ContentExecutionService(db)


                seo_service = SEOOptimizerService(db)


                approval_service = ContentApprovalService(db)



                for asset in saved_assets:


                    execution_service.generate_content(
                        asset.id
                    )


                    events.append(
                        "ContentGenerated"
                    )



                    seo_service.analyze_content(
                        asset.id
                    )


                    events.append(
                        "SEOAnalysisCompleted"
                    )



                    approval = approval_service.evaluate(
                        asset.id
                    )


                    events.append(
                        "ApprovalGenerated"
                    )



                    if approval.decision == "approved":

                        publishing_service = PublishingQueueService(db)


                        publishing_service.queue_content(
                            asset.id
                    )


                    events.append(
                        "PublishingQueued"
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

                    "discovery": discovery,

                    "intelligence": intelligence,

                    "decision": decision,

                    "database": database,

                    "opportunity": opportunity,

                    "content_assets": content_assets,

                },

                events=events,

                errors=[],

                duration=duration,

            )



        except Exception as exc:


            return WorkflowResult(

                success=False,

                workflow="affiliate_discovery",

                data={},

                events=events + [
                    "WorkflowFailed"
                ],

                errors=[
                    str(exc)
                ],

                duration=perf_counter()-start,

            )


        finally:

            db.close()