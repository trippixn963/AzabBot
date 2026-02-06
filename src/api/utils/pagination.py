"""
AzabBot - Pagination Utilities
==============================

Helpers for paginating query results.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from typing import Any, Generic, List, Optional, TypeVar

from src.api.models.base import PaginatedResponse, PaginationMeta
from src.api.dependencies import PaginationParams


T = TypeVar("T")


def paginate(
    items: List[T],
    total: int,
    params: PaginationParams,
) -> tuple[List[T], PaginationMeta]:
    """
    Create pagination metadata for a list of items.

    Args:
        items: The items for the current page
        total: Total number of items across all pages
        params: Pagination parameters

    Returns:
        Tuple of (items, metadata)
    """
    total_pages = (total + params.per_page - 1) // params.per_page if total > 0 else 1

    meta = PaginationMeta(
        page=params.page,
        per_page=params.per_page,
        total=total,
        total_pages=total_pages,
        has_next=params.page < total_pages,
        has_prev=params.page > 1,
    )

    return items, meta


def create_paginated_response(
    items: List[Any],
    total: int,
    params: PaginationParams,
    message: Optional[str] = None,
) -> PaginatedResponse:
    """
    Create a full paginated response.

    Args:
        items: The items for the current page
        total: Total number of items across all pages
        params: Pagination parameters
        message: Optional message

    Returns:
        PaginatedResponse with items and metadata
    """
    _, meta = paginate(items, total, params)

    return PaginatedResponse(
        success=True,
        message=message,
        data=items,
        pagination=meta,
    )


__all__ = ["paginate", "create_paginated_response"]
