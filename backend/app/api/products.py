"""
Product API

API endpoints for affiliate products.
"""

from fastapi import APIRouter, Depends, Response, status

from app.common.pagination import paginate
from app.dependencies import get_product_service

from app.schemas.product import (
    ProductCreate,
    ProductResponse,
    ProductUpdate,
)

from app.services.product_service import ProductService


router = APIRouter()


# ==========================================================
# Create Product
# ==========================================================

@router.post(
    "/",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_product(
    product: ProductCreate,
    service: ProductService = Depends(
        get_product_service
    ),
):
    """
    Create a new product.
    """

    return service.create_product(
        product
    )


# ==========================================================
# Get Products
# ==========================================================

@router.get("/")
def get_products(
    page: int = 1,
    page_size: int = 20,
    service: ProductService = Depends(
        get_product_service
    ),
):
    """
    Get all products with pagination.
    """

    products = service.get_products()

    return paginate(
        products,
        page=page,
        page_size=page_size,
    )


# ==========================================================
# Get Product
# ==========================================================

@router.get(
    "/{product_id}",
    response_model=ProductResponse,
)
def get_product(
    product_id: int,
    service: ProductService = Depends(
        get_product_service
    ),
):
    """
    Get a single product by ID.
    """

    return service.get_product(
        product_id
    )


# ==========================================================
# Update Product
# ==========================================================

@router.put(
    "/{product_id}",
    response_model=ProductResponse,
)
def update_product(
    product_id: int,
    product: ProductUpdate,
    service: ProductService = Depends(
        get_product_service
    ),
):
    """
    Update a product.
    """

    return service.update_product(
        product_id,
        product,
    )


# ==========================================================
# Delete Product
# ==========================================================

@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_product(
    product_id: int,
    service: ProductService = Depends(
        get_product_service
    ),
):
    """
    Delete a product.
    """

    service.delete_product(
        product_id
    )

    return Response(
        status_code=status.HTTP_204_NO_CONTENT
    )