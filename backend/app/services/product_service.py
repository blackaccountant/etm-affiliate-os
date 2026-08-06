"""
Product service.

Contains all business logic for Products.
"""

from typing import List

from app.common.exceptions import (
    DuplicateResourceException,
    ResourceNotFoundException,
)
from app.models.product import Product
from app.repositories.product_repository import ProductRepository
from app.schemas.product import (
    ProductCreate,
    ProductUpdate,
)


class ProductService:
    """
    Business logic for Product operations.
    """

    def __init__(self, repository: ProductRepository):
        self.repository = repository

    def create_product(
        self,
        product: ProductCreate,
    ) -> Product:
        """
        Create a new product.
        """

        if self.repository.exists_by_name(product.name):
            raise DuplicateResourceException(
                f"Product '{product.name}' already exists."
            )

        if self.repository.exists_by_affiliate_url(
            str(product.affiliate_url)
        ):
            raise DuplicateResourceException(
                "Affiliate URL already exists."
            )

        return self.repository.create(product)

    def get_product(
        self,
        product_id: int,
    ) -> Product:
        """
        Get a product by ID.
        """

        product = self.repository.get_by_id(product_id)

        if product is None:
            raise ResourceNotFoundException(
                f"Product {product_id} not found."
            )

        return product

    def get_products(self) -> List[Product]:
        """
        Get all products.
        """

        return self.repository.get_all()

    def update_product(
        self,
        product_id: int,
        product_update: ProductUpdate,
    ) -> Product:
        """
        Update a product.
        """

        product = self.get_product(product_id)

        return self.repository.update(
            product,
            product_update,
        )

    def delete_product(
        self,
        product_id: int,
    ) -> None:
        """
        Delete a product.
        """

        product = self.get_product(product_id)

        self.repository.delete(product)