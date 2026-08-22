"""
Opportunity Engine

Transforms affiliate intelligence
into actionable monetization strategy.
"""

from app.schemas.affiliate_opportunity import (
    AffiliateOpportunitySchema,
)


class OpportunityEngine:


    def generate(
        self,
        product,
        affiliate_program,
        intelligence,
    ) -> AffiliateOpportunitySchema:
        """
        Generate affiliate opportunity strategy.
        """


        grade = intelligence.grade


        audience = self._generate_audience(
            product.category
        )


        content_strategy = (
            self._generate_content_strategy(
                product.name
            )
        )


        seo_keywords = (
            self._generate_seo_keywords(
                product.name,
                product.category,
            )
        )


        channels = (
            self._generate_channels()
        )


        funnel = (
            self._generate_funnel()
        )


        revenue = (
            self._generate_revenue_projection(
                affiliate_program
            )
        )


        recommendation = (
            self._generate_recommendation(
                product,
                affiliate_program,
                intelligence,
            )
        )


        return AffiliateOpportunitySchema(

            opportunity_grade=grade,

            audience=audience,

            content_strategy=content_strategy,

            seo_keywords=seo_keywords,

            promotion_channels=channels,

            funnel_strategy=funnel,

            revenue_projection=revenue,

            ai_recommendation=recommendation,

            confidence=int(
                intelligence.confidence
            ),

        )



    def _generate_audience(
        self,
        category,
    ):


        return [

            "business owners",

            "startup founders",

            "marketing teams",

            "sales professionals",

            "software buyers",

        ]



    def _generate_content_strategy(
        self,
        name,
    ):


        return [

            f"{name} review",

            f"{name} alternatives",

            f"best tools like {name}",

            f"{name} pricing comparison",

        ]



    def _generate_seo_keywords(
        self,
        name,
        category,
    ):


        return [

            f"{name} review",

            f"best {category}",

            f"{name} affiliate",

            f"{name} vs competitors",

        ]



    def _generate_channels(
        self,
    ):


        return [

            "SEO",

            "YouTube",

            "LinkedIn",

            "Email marketing",

            "Content marketing",

        ]



    def _generate_funnel(
        self,
    ):


        return {

            "lead_magnet":
                "Comparison guide",

            "landing_page":
                "Product review page",

            "conversion":
                "Affiliate signup",

        }



    def _generate_revenue_projection(
        self,
        affiliate_program,
    ):


        return {

            "low":
                "$500/month",

            "medium":
                "$5000/month",

            "high":
                "$20000/month",

        }



    def _generate_recommendation(
        self,
        product,
        affiliate_program,
        intelligence,
    ):


        return (
            f"{product.name} is a "
            f"{intelligence.grade}-grade affiliate "
            "opportunity. "
            "Recommended strategy is to build "
            "content-driven acquisition using SEO, "
            "comparison pages, and targeted audiences."
        )