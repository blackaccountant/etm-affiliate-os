"""
Product Hunter Agent

Discovers and scores affiliate
product opportunities.
"""


from app.products.opportunity import ProductOpportunity



class ProductHunterAgent:


    def __init__(self):

        self.name = "Product Hunter"



    def discover(self):

        """
        Temporary discovery provider.

        Later this will connect to:
        - Impact
        - PartnerStack
        - CJ
        - ShareASale
        - ClickBank
        """


        products = [

            ProductOpportunity(
                name="AI Writing Assistant",
                category="AI SaaS",
                commission=30,
                price=49,
                demand_score=9,
                competition_score=4,
            ),


            ProductOpportunity(
                name="Email Marketing Platform",
                category="Marketing SaaS",
                commission=25,
                price=79,
                demand_score=8,
                competition_score=5,
            ),


            ProductOpportunity(
                name="Website Builder",
                category="SaaS Tools",
                commission=40,
                price=99,
                demand_score=7,
                competition_score=6,
            ),

        ]


        return products



    def rank(
        self,
        products,
    ):

        return sorted(
            products,
            key=lambda product:
                product.opportunity_score(),
            reverse=True,
        )



    def run(self):

        products = self.discover()

        ranked = self.rank(
            products
        )


        return [

            product.to_dict()

            for product in ranked

        ]