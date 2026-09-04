"""
ETM Affiliate OS

Application entry point.
"""

from contextlib import asynccontextmanager

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
from app.api.discovery import router as discovery_router
from app.api.content import router as content_router
from app.api.audience_visibility_routes import router as audience_visibility_router
from app.api.attribution_lineage_routes import router as attribution_lineage_router
from app.api.optimization_recommendation_routes import (
    router as optimization_recommendation_router,
)
from app.api.optimization_approval_routes import (
    router as optimization_approval_router,
)
from app.api.optimization_experiment_design_routes import (
    router as optimization_experiment_design_router,
)


# -----------------------------------------------------
# Logging
# -----------------------------------------------------

setup_logging()

logger = get_logger(__name__)


# -----------------------------------------------------
# Runtime Lifecycle
# -----------------------------------------------------

@asynccontextmanager
async def lifespan(
    app: FastAPI,
):

    """
    Application lifecycle.

    Startup:
        Starts the background retry manager.

    Shutdown:
        Stops the retry manager and closes runtime
        resources.
    """

    # --------------------------------------------------
    # Startup
    # --------------------------------------------------

    logger.info(
        "Starting ETM Affiliate OS..."
    )


    try:

        from app.system.routes import runtime

        started = (
            runtime.start_retry_manager()
        )


        if started:

            logger.info(
                "Retry manager started."
            )

        else:

            logger.info(
                "Retry manager was already running."
            )


    except Exception as exc:

        logger.exception(
            "Failed to start retry manager: %s",
            exc,
        )

        raise


    try:

        yield


    finally:

        # ----------------------------------------------
        # Shutdown
        # ----------------------------------------------

        logger.info(
            "Stopping ETM Affiliate OS..."
        )


        try:

            from app.system.routes import runtime

            runtime.close()


            logger.info(
                "ETM Affiliate OS shutdown complete."
            )


        except Exception as exc:

            logger.exception(
                "Error during ETM Affiliate OS shutdown: %s",
                exc,
            )


# -----------------------------------------------------
# FastAPI App
# -----------------------------------------------------

app = FastAPI(

    title=settings.APP_NAME,

    version="0.9.1",

    description="ETM Affiliate OS API",

    lifespan=lifespan,

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

register_exception_handlers(
    app
)


# -----------------------------------------------------
# Root
# -----------------------------------------------------

@app.get(
    "/",
    tags=["System"],
)
def root():

    return {

        "success": True,

        "message": (
            f"Welcome to {settings.APP_NAME}"
        ),

        "version": "0.9.1",

    }


# -----------------------------------------------------
# Health
# -----------------------------------------------------

@app.get(
    "/health",
    tags=["System"],
)
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
    publisher_router,
)


app.include_router(
    affiliate_links_router,
)


app.include_router(
    affiliate_conversions_router,
)


app.include_router(
    affiliate_earnings_router,
)


app.include_router(
    affiliate_payouts_router,
)


app.include_router(
    discovery_router,
    prefix="/discovery",
    tags=["Discovery"],
)


app.include_router(
    content_router,
)


app.include_router(
    audience_visibility_router,
)


app.include_router(
    attribution_lineage_router,
)


app.include_router(
    optimization_recommendation_router,
)


app.include_router(
    optimization_approval_router,
)


app.include_router(
    optimization_experiment_design_router,
)
