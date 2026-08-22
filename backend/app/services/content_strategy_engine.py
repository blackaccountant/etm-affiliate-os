"""
Content Strategy Engine

Transforms affiliate opportunities
into marketing content assets.
"""


from app.schemas.affiliate_content_asset import (
    AffiliateContentAssetSchema,
)



class ContentStrategyEngine:


    def generate(
        self,
        product,
        opportunity,
    ):

        """
        Generate content strategy
        from affiliate opportunity.
        """


        assets = []


        keywords = [
            f"{product.name} review",
            f"{product.name} alternatives",
            f"best {product.category}",
            f"{product.name} pricing",
            f"{product.name} vs competitors",
        ]



        assets.append(

            AffiliateContentAssetSchema(

                asset_type="SEO Article",

                title=(
                    f"{product.name} Review: "
                    "Complete Guide For Businesses"
                ),

                target_keyword=(
                    keywords[0]
                ),

                audience=(
                    opportunity.audience
                ),

                search_intent="Buyer",

                content_outline=[
                    "Introduction",
                    "Features",
                    "Pricing",
                    "Pros and Cons",
                    "Alternatives",
                    "Final Recommendation",
                ],

                call_to_action=(
                    f"Start using {product.name}"
                ),

            )

        )



        assets.append(

            AffiliateContentAssetSchema(

                asset_type="Comparison Article",

                title=(
                    f"{product.name} Alternatives "
                    "and Competitors"
                ),

                target_keyword=(
                    keywords[1]
                ),

                audience=(
                    opportunity.audience
                ),

                search_intent="Commercial",

                content_outline=[
                    "Market comparison",
                    "Feature comparison",
                    "Pricing comparison",
                    "Best choice",
                ],

                call_to_action=(
                    f"Try {product.name}"
                ),

            )

        )


        return assets