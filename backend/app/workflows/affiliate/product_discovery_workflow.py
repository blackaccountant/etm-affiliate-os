"""
Product Discovery Workflow

Discovers and ranks affiliate opportunities.

Supports:

1. Existing local discovery mode when no URL is supplied.
2. Real affiliate intelligence discovery when a URL is supplied.
"""

from time import perf_counter

from app.workflow_engine.workflow_result import WorkflowResult

from app.workers.product_hunter_agent import ProductHunterAgent

from app.workflows.affiliate.affiliate_discovery_workflow import (
    AffiliateDiscoveryWorkflow,
)


class ProductDiscoveryWorkflow:

    def __init__(self):

        self.hunter = ProductHunterAgent()

        self.affiliate_discovery = (
            AffiliateDiscoveryWorkflow()
        )


    def execute(
        self,
        payload: dict,
    ):

        start = perf_counter()

        events = [
            "ProductDiscoveryStarted"
        ]

        payload = payload or {}

        try:

            # ==================================================
            # REAL INTELLIGENCE MODE
            # ==================================================

            url = payload.get("url")

            if url:

                events.append(
                    "ResearchStarted"
                )

                result = (
                    self.affiliate_discovery.execute(
                        {
                            "url": url
                        }
                    )
                )

                events.append(
                    "ResearchCompleted"
                )

                if not result.success:

                    events.append(
                        "ProductDiscoveryFailed"
                    )

                    return WorkflowResult(

                        success=False,

                        workflow="product_discovery",

                        data={},

                        events=events
                        + result.events,

                        errors=result.errors,

                        duration=(
                            perf_counter()
                            - start
                        ),
                    )


                # ------------------------------------------
                # Normalize real intelligence result
                # ------------------------------------------

                intelligence_data = (
                    result.data
                )


                analysis = (
                    intelligence_data.get(
                        "analysis"
                    )
                )

                intelligence = (
                    intelligence_data.get(
                        "intelligence"
                    )
                )

                database = (
                    intelligence_data.get(
                        "database"
                    )
                )


                product = {

                    "company": (
                        analysis.company
                        if hasattr(
                            analysis,
                            "company"
                        )
                        else None
                    ),

                    "website": (
                        analysis.website
                        if hasattr(
                            analysis,
                            "website"
                        )
                        else None
                    ),

                    "category": (
                        analysis.category
                        if hasattr(
                            analysis,
                            "category"
                        )
                        else None
                    ),

                    "summary": (
                        analysis.summary
                        if hasattr(
                            analysis,
                            "summary"
                        )
                        else None
                    ),

                    "target_audience": (
                        analysis.target_audience
                        if hasattr(
                            analysis,
                            "target_audience"
                        )
                        else []
                    ),

                    "pricing_model": (
                        analysis.pricing_model
                        if hasattr(
                            analysis,
                            "pricing_model"
                        )
                        else ""
                    ),

                    "affiliate_program_likely": (
                        analysis.affiliate_program_likely
                        if hasattr(
                            analysis,
                            "affiliate_program_likely"
                        )
                        else ""
                    ),

                    "commission_type": (
                        analysis.commission_type
                        if hasattr(
                            analysis,
                            "commission_type"
                        )
                        else ""
                    ),

                    "commission_estimate": (
                        analysis.commission_estimate
                        if hasattr(
                            analysis,
                            "commission_estimate"
                        )
                        else ""
                    ),

                    "affiliate_score": (
                        intelligence.score
                        if hasattr(
                            intelligence,
                            "score"
                        )
                        else 0
                    ),

                    "grade": (
                        intelligence.grade
                        if hasattr(
                            intelligence,
                            "grade"
                        )
                        else ""
                    ),

                    "confidence": (
                        intelligence.confidence
                        if hasattr(
                            intelligence,
                            "confidence"
                        )
                        else 0
                    ),

                    "recommendation": (
                        intelligence.recommendation
                        if hasattr(
                            intelligence,
                            "recommendation"
                        )
                        else ""
                    ),

                    "database": (
                        database.model_dump()
                        if hasattr(
                            database,
                            "model_dump"
                        )
                        else (
                            database.__dict__
                            if hasattr(
                                database,
                                "__dict__"
                            )
                            else database
                        )
                    ),
                }


                events.append(
                    "ProductIntelligenceScored"
                )

                events.append(
                    "ProductDiscovered"
                )

                events.append(
                    "ProductDiscoveryCompleted"
                )


                return WorkflowResult(

                    success=True,

                    workflow="product_discovery",

                    data={
                        "products": [
                            product
                        ]
                    },

                    events=events,

                    errors=[],

                    duration=(
                        perf_counter()
                        - start
                    ),
                )


            # ==================================================
            # EXISTING LOCAL MODE
            # ==================================================

            products = self.hunter.run()

            events.append(
                "ProductsDiscovered"
            )

            events.append(
                "ProductDiscoveryCompleted"
            )


            return WorkflowResult(

                success=True,

                workflow="product_discovery",

                data={
                    "products": products
                },

                events=events,

                errors=[],

                duration=(
                    perf_counter()
                    - start
                ),
            )


        except Exception as exc:

            events.append(
                "ProductDiscoveryFailed"
            )


            return WorkflowResult(

                success=False,

                workflow="product_discovery",

                data={},

                events=events,

                errors=[
                    str(exc)
                ],

                duration=(
                    perf_counter()
                    - start
                ),
            )