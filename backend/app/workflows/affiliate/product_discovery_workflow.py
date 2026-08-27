"""
Product Discovery Workflow

Discovers and ranks affiliate opportunities.

Supports:

1. Existing local discovery mode when no URL is supplied.
2. Real affiliate intelligence discovery when a URL is supplied.

The real intelligence workflow may return Pydantic models
or serialized dictionaries. This workflow normalizes those
values at the boundary so downstream code always works with
dictionaries.
"""

from time import perf_counter

from app.workflow_engine.workflow_result import WorkflowResult

from app.workers.product_hunter_agent import (
    ProductHunterAgent,
)

from app.workflows.affiliate.affiliate_discovery_workflow import (
    AffiliateDiscoveryWorkflow,
)


class ProductDiscoveryWorkflow:

    def __init__(self):

        self.hunter = ProductHunterAgent()

        self.affiliate_discovery = (
            AffiliateDiscoveryWorkflow()
        )

    # ==================================================
    # NORMALIZATION
    # ==================================================

    @staticmethod
    def _to_dict(
        value,
    ) -> dict:
        """
        Normalize a Pydantic model or dictionary
        into a dictionary.

        This keeps workflow boundaries deterministic.
        """

        if value is None:
            return {}

        if isinstance(
            value,
            dict,
        ):
            return value

        if hasattr(
            value,
            "model_dump",
        ):
            return value.model_dump()

        if hasattr(
            value,
            "dict",
        ):
            return value.dict()

        return {}

    # ==================================================
    # EXECUTE
    # ==================================================

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

            url = payload.get(
                "url"
            )

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

                        events=(
                            events
                            + result.events
                        ),

                        errors=result.errors,

                        duration=(
                            perf_counter()
                            - start
                        ),

                    )

                # ==================================================
                # WORKFLOW RESULT DATA
                # ==================================================

                intelligence_data = (
                    result.data
                    or {}
                )

                analysis = self._to_dict(
                    intelligence_data.get(
                        "analysis"
                    )
                )

                discovery = self._to_dict(
                    intelligence_data.get(
                        "discovery"
                    )
                )

                intelligence = self._to_dict(
                    intelligence_data.get(
                        "intelligence"
                    )
                )

                decision = self._to_dict(
                    intelligence_data.get(
                        "decision"
                    )
                )

                database = self._to_dict(
                    intelligence_data.get(
                        "database"
                    )
                )

                # ==================================================
                # PRODUCT OUTPUT
                # ==================================================

                product = {

                    "company": (
                        analysis.get(
                            "company"
                        )
                    ),

                    "website": (
                        analysis.get(
                            "website"
                        )
                    ),

                    "category": (
                        analysis.get(
                            "category"
                        )
                    ),

                    "summary": (
                        analysis.get(
                            "summary"
                        )
                    ),

                    "target_audience": (
                        analysis.get(
                            "target_audience",
                            []
                        )
                    ),

                    "pricing_model": (
                        analysis.get(
                            "pricing_model",
                            ""
                        )
                    ),

                    "affiliate_program_likely": (
                        analysis.get(
                            "affiliate_program_likely",
                            ""
                        )
                    ),

                    "commission_type": (
                        analysis.get(
                            "commission_type",
                            ""
                        )
                    ),

                    "commission_estimate": (
                        analysis.get(
                            "commission_estimate",
                            ""
                        )
                    ),

                    "affiliate_score": (
                        intelligence.get(
                            "score",
                            0
                        )
                    ),

                    "grade": (
                        intelligence.get(
                            "grade",
                            ""
                        )
                    ),

                    "confidence": (
                        intelligence.get(
                            "confidence",
                            0
                        )
                    ),

                    "recommendation": (
                        intelligence.get(
                            "recommendation",
                            ""
                        )
                    ),

                    # Decision Engine output
                    "decision": decision,

                    # Discovery evidence
                    "discovery": discovery,

                    # Database result
                    "database": database,

                }

                # ==================================================
                # EVENTS
                # ==================================================

                events.append(
                    "ProductIntelligenceScored"
                )

                events.append(
                    "DecisionGenerated"
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