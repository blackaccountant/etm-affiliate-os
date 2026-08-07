"""
Application dependency container.

All FastAPI dependencies should be registered here.
"""

from typing import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.repositories.product_repository import ProductRepository
from app.services.product_service import ProductService


def get_db() -> Generator[Session, None, None]:
    """
    Create a database session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_product_repository(
    db: Session = Depends(get_db),
) -> ProductRepository:
    """
    Dependency for ProductRepository.
    """
    return ProductRepository(db)


def get_product_service(
    repository: ProductRepository = Depends(get_product_repository),
) -> ProductService:
    """
    Dependency for ProductService.
    """
    return ProductService(repository)