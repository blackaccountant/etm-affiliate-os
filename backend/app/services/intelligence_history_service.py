"""
Intelligence History Service

Provides historical intelligence
and analytics summaries.
"""


from app.repositories.product_intelligence_history_repository import (
    ProductIntelligenceHistoryRepository,
)


class IntelligenceHistoryService:


    def __init__(
        self,
        repository: ProductIntelligenceHistoryRepository,
    ):

        self.repository = repository


    def get_history(
        self,
        product_id: int,
    ):

        return self.repository.get_by_product_id(
            product_id
        )


    def get_summary(
        self,
        product_id: int,
    ):

        history = self.repository.get_by_product_id(
            product_id
        )


        if not history:

            return {

                "product_id": product_id,

                "evaluations": 0,

                "latest_score": None,

                "average_score": 0,

                "highest_score": None,

                "lowest_score": None,

                "trend": "NO_DATA",

            }


        scores = [

            item.score

            for item in history

        ]


        latest_score = history[0].score


        previous_score = (

            history[1].score

            if len(history) > 1

            else latest_score

        )


        change = (
            latest_score
            -
            previous_score
        )


        if change >= 10:

            trend = "IMPROVING"


        elif change <= -10:

            trend = "DECLINING"


        else:

            trend = "STABLE"



        average_score = round(
            sum(scores)
            /
            len(scores),
            2,
        )


        return {

            "product_id": product_id,

            "evaluations": len(history),

            "latest_score": latest_score,

            "average_score": average_score,

            "highest_score": max(scores),

            "lowest_score": min(scores),

            "trend": trend,

            "score_change": change,

        }