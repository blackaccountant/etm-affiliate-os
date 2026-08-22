"""
Product Service

Contains business logic for Product operations.

Responsibilities:
    - Product creation
    - Product retrieval
    - Product listing
    - Product updates
    - Product deletion
    - URL canonicalization
    - Duplicate protection

The service layer accepts Pydantic schemas from the API layer
and converts ProductCreate data into a SQLAlchemy Product ORM
object before sending it to the repository.
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
from app.services.url_normalizer import normalize_url


class ProductService:
    """
    Business logic for Product operations.
    """

    def __init__(
        self,
        repository: ProductRepository,
    ):
        self.repository = repository

    # ==========================================================
    # Create Product
    # ==========================================================

    def create_product(
        self,
        product: ProductCreate,
    ) -> Product:
        """
        Create a new product.

        Incoming ProductCreate is a Pydantic object.

        It is normalized and then converted into a SQLAlchemy
        Product ORM object before being passed to the repository.
        """

        # ------------------------------------------------------
        # Normalize website
        # ------------------------------------------------------

        canonical_website = normalize_url(
            str(product.website)
        )

        # ------------------------------------------------------
        # Normalize affiliate URL
        # ------------------------------------------------------

        canonical_affiliate_url = None

        if product.affiliate_url:
            canonical_affiliate_url = normalize_url(
                str(product.affiliate_url)
            )

        # ------------------------------------------------------
        # Duplicate: product name
        # ------------------------------------------------------

        if self.repository.exists_by_name(
            product.name
        ):
            raise DuplicateResourceException(
                f"Product '{product.name}' already exists."
            )

        # ------------------------------------------------------
        # Duplicate: affiliate URL
        # ------------------------------------------------------

        if canonical_affiliate_url:
            if self.repository.exists_by_affiliate_url(
                canonical_affiliate_url
            ):
                raise DuplicateResourceException(
                    "Affiliate URL already exists."
                )

        # ------------------------------------------------------
        # Duplicate: website
        # ------------------------------------------------------

        if self.repository.exists_by_website(
            canonical_website
        ):
            raise DuplicateResourceException(
                "Product website already exists."
            )

        # ------------------------------------------------------
        # Convert Pydantic schema -> SQLAlchemy ORM model
        #
        # THIS IS THE IMPORTANT FIX.
        #
        # ProductCreate cannot be passed directly to
        # SQLAlchemy Session.add().
        # ------------------------------------------------------

        product_model = Product(
            name=product.name,
            website=canonical_website,
            category=product.category,
            affiliate_program=product.affiliate_program,
            affiliate_url=canonical_affiliate_url,
            commission_type=product.commission_type,
            commission_value=product.commission_value,
            cookie_duration=product.cookie_duration,
            status=product.status,
        )

        # ------------------------------------------------------
        # Persist ORM object
        # ------------------------------------------------------

        return self.repository.create(
            product_model
        )

    # ==========================================================
    # Get Product
    # ==========================================================

    def get_product(
        self,
        product_id: int,
    ) -> Product:
        """
        Get a product by ID.
        """

        product = self.repository.get_by_id(
            product_id
        )

        if product is None:
            raise ResourceNotFoundException(
                f"Product {product_id} not found."
            )

        return product

    # ==========================================================
    # Get Products
    # ==========================================================

    def get_products(
        self,
    ) -> List[Product]:
        """
        Get all products.
        """

        return self.repository.get_all()

    # ==========================================================
    # Update Product
    # ==========================================================

    def update_product(
        self,
        product_id: int,
        product_update: ProductUpdate,
    ) -> Product:
        """
        Update a product.

        Website and affiliate URLs are canonicalized before
        persistence.

        Duplicate website and affiliate URL protection is
        applied while allowing the current product to retain
        its own values.
        """

        # ------------------------------------------------------
        # Load existing product
        # ------------------------------------------------------

        product = self.get_product(
            product_id
        )

        # ------------------------------------------------------
        # Convert update schema to a dictionary
        # ------------------------------------------------------

        update_data = product_update.model_dump(
            exclude_unset=True
        )

        # ------------------------------------------------------
        # Website normalization + duplicate protection
        # ------------------------------------------------------

        if "website" in update_data:

            canonical_website = normalize_url(
                str(update_data["website"])
            )

            existing_product = (
                self.repository.get_by_website(
                    canonical_website
                )
            )

            if (
                existing_product is not None
                and existing_product.id != product.id
            ):
                raise DuplicateResourceException(
                    "Product website already exists."
                )

            update_data["website"] = (
                canonical_website
            )

        # ------------------------------------------------------
        # Affiliate URL normalization + duplicate protection
        # ------------------------------------------------------

        if "affiliate_url" in update_data:

            if update_data["affiliate_url"]:

                canonical_affiliate_url = normalize_url(
                    str(update_data["affiliate_url"])
                )

                existing_product = (
                    self.repository.get_by_affiliate_url(
                        canonical_affiliate_url
                    )
                )

                if (
                    existing_product is not None
                    and existing_product.id != product.id
                ):
                    raise DuplicateResourceException(
                        "Affiliate URL already exists."
                    )

                update_data["affiliate_url"] = (
                    canonical_affiliate_url
                )

        # ------------------------------------------------------
        # Build normalized ProductUpdate schema
        # ------------------------------------------------------

        normalized_update = (
            product_update.model_copy(
                update=update_data
            )
        )

        # ------------------------------------------------------
        # Persist update
        # ------------------------------------------------------

        return self.repository.update(
            product,
            normalized_update,
        )

    # ==========================================================
    # Delete Product
    # ==========================================================

    def delete_product(
        self,
        product_id: int,
    ) -> None:
        """
        Delete a product.
        """

        product = self.get_product(
            product_id
        )

        self.repository.delete(
            product
        )