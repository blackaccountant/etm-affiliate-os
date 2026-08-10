"""
Product Intelligence History Repository
"""

from sqlalchemy.orm import Session

from app.models.product_intelligence_history import (
    ProductIntelligenceHistory,
)


class ProductIntelligenceHistoryRepository:


    def __init__(
        self,
        db: Session,
    ):

        self.db = db


    def get_by_product_id(
        self,
        product_id: int,
    ):

        return (
            self.db.query(
                ProductIntelligenceHistory
            )
            .filter(
                ProductIntelligenceHistory.product_id
                == product_id
            )
            .order_by(
                ProductIntelligenceHistory.created_at.desc()
            )
            .all()
        )