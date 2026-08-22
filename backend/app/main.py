"""
ETM Affiliate OS

Application entry point.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.ai import router as ai_router
from app.api.products import router as products_router
from app.api.workers import router as workers_router
from app.api.executions import router as execution_router

from app.system.routes import router as system_router

from app.core.config import settings
from app.exceptions.handlers import register_exception_handlers
from app.logging.logger import get_logger
from app.logging.logging_config import setup_logging

from app.api.publisher import router as publisher_router
from app.api.affiliate_links import router as affiliate_links_router
from app.api.affiliate_conversions import router as affiliate_conversions_router
from app.api.affiliate_earnings import router as affiliate_earnings_router
from app.api.affiliate_payouts import router as affiliate_payouts_router

# -----------------------------------------------------
# Logging
# -----------------------------------------------------

setup_logging()

logger = get_logger(__name__)


# -----------------------------------------------------
# FastAPI App
# -----------------------------------------------------

app = FastAPI(
    title=settings.APP_NAME,
    version="0.9.1",
    description="ETM Affiliate OS API",
)


# -----------------------------------------------------
# CORS
# -----------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------
# Exceptions
# -----------------------------------------------------

register_exception_handlers(app)


logger.info("Starting ETM Affiliate OS...")


# -----------------------------------------------------
# System Routes
# -----------------------------------------------------

@app.get("/", tags=["System"])
def root():
    return {
        "success": True,
        "message": f"Welcome to {settings.APP_NAME}",
        "version": "0.9.1",
    }


@app.get("/health", tags=["System"])
def health():
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

app.include_router(
    execution_router,
)

app.include_router(
    system_router,
)

app.include_router(
    publisher_router
)

app.include_router(
    affiliate_links_router
)

app.include_router(
    affiliate_conversions_router
)

app.include_router(
    affiliate_earnings_router
)

app.include_router(
    affiliate_payouts_router
)
