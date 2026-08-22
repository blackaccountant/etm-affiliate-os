"""
Product Opportunity Model

Represents an affiliate opportunity
discovered by Product Hunter.
"""


from dataclasses import dataclass


@dataclass
class ProductOpportunity:

    name: str

    category: str

    commission: float

    price: float

    demand_score: float

    competition_score: float


    def opportunity_score(self):

        return round(
            (
                self.commission * 0.3
                +
                self.demand_score * 0.4
                +
                (10 - self.competition_score) * 0.3
            ),
            2
        )


    def to_dict(self):

        return {

            "name": self.name,

            "category": self.category,

            "commission": self.commission,

            "price": self.price,

            "demand_score": self.demand_score,

            "competition_score": self.competition_score,

            "opportunity_score": self.opportunity_score(),

        }