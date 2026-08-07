"""
Global exception handlers for ETM Affiliate OS.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.common.exceptions import (
    DuplicateResourceException,
    ETMException,
    ResourceNotFoundException,
    ValidationException,
)
from app.common.responses import error_response


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all application exception handlers.
    """

    @app.exception_handler(ResourceNotFoundException)
    async def resource_not_found_handler(
        request: Request,
        exc: ResourceNotFoundException,
    ):
        return JSONResponse(
            status_code=404,
            content=error_response(exc.message).model_dump(),
        )

    @app.exception_handler(DuplicateResourceException)
    async def duplicate_resource_handler(
        request: Request,
        exc: DuplicateResourceException,
    ):
        return JSONResponse(
            status_code=409,
            content=error_response(exc.message).model_dump(),
        )

    @app.exception_handler(ValidationException)
    async def validation_exception_handler(
        request: Request,
        exc: ValidationException,
    ):
        return JSONResponse(
            status_code=400,
            content=error_response(exc.message).model_dump(),
        )

    @app.exception_handler(ETMException)
    async def etm_exception_handler(
        request: Request,
        exc: ETMException,
    ):
        return JSONResponse(
            status_code=400,
            content=error_response(exc.message).model_dump(),
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(
        request: Request,
        exc: Exception,
    ):
        return JSONResponse(
            status_code=500,
            content=error_response(
                "An unexpected error occurred."
            ).model_dump(),
        )