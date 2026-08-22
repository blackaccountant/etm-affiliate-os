"""
Product API

API endpoints for affiliate products.
"""

from fastapi import (
    APIRouter,
    Depends,
    Response,
    status,
)

from app.common.pagination import paginate

from app.dependencies import (
    get_product_service,
    get_intelligence_history_service,
)

from app.schemas.product import (
    ProductCreate,
    ProductResponse,
    ProductUpdate,
)

from app.services.product_service import ProductService

from app.services.intelligence_history_service import (
    IntelligenceHistoryService,
)


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
    return service.create_product(product)


# ==========================================================
# Get Products
# ==========================================================

@router.get(
    "/",
    response_model=list[ProductResponse],
)
def get_products(
    page: int = 1,
    page_size: int = 20,
    service: ProductService = Depends(
        get_product_service
    ),
):

    products = service.get_products()

    return [
        ProductResponse.model_validate(product)
        for product in products
    ]


# ==========================================================
# Intelligence Summary
# ==========================================================

@router.get(
    "/{product_id}/intelligence-summary",
)
def get_intelligence_summary(
    product_id: int,
    service: IntelligenceHistoryService = Depends(
        get_intelligence_history_service
    ),
):

    return service.get_summary(product_id)


# ==========================================================
# Intelligence History
# ==========================================================

@router.get(
    "/{product_id}/intelligence-history",
)
def get_intelligence_history(
    product_id: int,
    service: IntelligenceHistoryService = Depends(
        get_intelligence_history_service
    ),
):

    return {
        "product_id": product_id,
        "history": service.get_history(product_id),
    }


# ==========================================================
# Get Single Product
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

    return service.get_product(product_id)


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

    service.delete_product(product_id)

    return Response(
        status_code=status.HTTP_204_NO_CONTENT
    )
