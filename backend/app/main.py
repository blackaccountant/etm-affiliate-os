"""
ETM Affiliate OS

Application entry point.
"""

from fastapi import FastAPI

from app.api.ai import router as ai_router
from app.api.products import router as products_router
from app.api.workers import router as workers_router
from app.core.config import settings
from app.exceptions.handlers import register_exception_handlers
from app.logging.logger import get_logger
from app.logging.logging_config import setup_logging

# -----------------------------------------------------
# Configure Logging
# -----------------------------------------------------

setup_logging()

logger = get_logger(__name__)

# -----------------------------------------------------
# Create FastAPI Application
# -----------------------------------------------------

app = FastAPI(
    title=settings.APP_NAME,
    version="0.4.0",
    description="ETM Affiliate OS API",
)

# -----------------------------------------------------
# Register Global Exception Handlers
# -----------------------------------------------------

register_exception_handlers(app)

logger.info("Starting ETM Affiliate OS...")

# -----------------------------------------------------
# System Endpoints
# -----------------------------------------------------


@app.get("/", tags=["System"])
def root():
    """
    Root endpoint.
    """

    logger.info("Root endpoint accessed.")

    return {
        "success": True,
        "message": f"Welcome to {settings.APP_NAME}",
        "version": "0.4.0",
    }


@app.get("/health", tags=["System"])
def health():
    """
    Health check endpoint.
    """

    logger.info("Health check requested.")

    return {
        "success": True,
        "status": "healthy",
    }


# -----------------------------------------------------
# API Routers
# -----------------------------------------------------

app.include_router(
    products_router,
    prefix="/products",
    tags=["Products"],
)

app.include_router(
    ai_router,
)

app.include_router(
    workers_router,
)