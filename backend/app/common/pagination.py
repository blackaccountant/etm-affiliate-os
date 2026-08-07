"""
Reusable pagination utilities for ETM Affiliate OS.
"""

from math import ceil
from typing import Generic, List, Sequence, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginationParams(BaseModel):
    """
    Pagination request parameters.
    """

    page: int = 1
    page_size: int = 20


class PaginationResult(BaseModel, Generic[T]):
    """
    Standard pagination response.
    """

    items: List[T]

    page: int

    page_size: int

    total_items: int

    total_pages: int


def paginate(
    items: Sequence[T],
    page: int = 1,
    page_size: int = 20,
) -> PaginationResult[T]:
    """
    Paginate a sequence.
    """

    total_items = len(items)

    total_pages = max(
        1,
        ceil(total_items / page_size),
    )

    start = (page - 1) * page_size

    end = start + page_size

    return PaginationResult(
        items=list(items[start:end]),
        page=page,
        page_size=page_size,
        total_items=total_items,
        total_pages=total_pages,
    )