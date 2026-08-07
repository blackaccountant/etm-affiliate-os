from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """
    Standard API response model.

    Example:
    {
        "success": true,
        "message": "Product created successfully.",
        "data": {...}
    }
    """

    success: bool = True
    message: str
    data: Optional[T] = None


class PaginatedResponse(BaseModel, Generic[T]):
    """
    Standard paginated API response.
    """

    success: bool = True
    message: str
    data: list[T]

    page: int
    page_size: int
    total: int
    total_pages: int


def success_response(
    message: str,
    data: Any = None,
) -> ApiResponse:
    """
    Helper for successful responses.
    """
    return ApiResponse(
        success=True,
        message=message,
        data=data,
    )


def error_response(
    message: str,
) -> ApiResponse:
    """
    Helper for error responses.
    """
    return ApiResponse(
        success=False,
        message=message,
        data=None,
    )