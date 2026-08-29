"""
Application dependency container.

All FastAPI dependencies should be registered here.
"""

from typing import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.mission.manager import MissionManager
from app.repositories.product_repository import ProductRepository
from app.services.product_service import ProductService
from app.repositories.product_intelligence_history_repository import (
    ProductIntelligenceHistoryRepository,
)

from app.services.intelligence_history_service import (
    IntelligenceHistoryService,
)
from app.repositories.execution_repository import (
    ExecutionRepository,
)

from app.services.execution_service import (
    ExecutionService,
)
from app.repositories.discovery_run_repository import DiscoveryRunRepository
from app.repositories.content_generation_run_repository import ContentGenerationRunRepository
from app.repositories.content_repurposing_run_repository import ContentRepurposingRunRepository
from app.repositories.generated_content_artifact_repository import GeneratedContentArtifactRepository
from app.services.discovery_query_service import DiscoveryQueryService
from app.services.discovery_run_orchestration_service import DiscoveryRunOrchestrationService


def get_db() -> Generator[Session, None, None]:
    """
    Create a database session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_product_repository(
    db: Session = Depends(get_db),
) -> ProductRepository:
    """
    Dependency for ProductRepository.
    """
    return ProductRepository(db)


def get_product_service(
    repository: ProductRepository = Depends(get_product_repository),
) -> ProductService:
    """
    Dependency for ProductService.
    """
    return ProductService(repository)


def get_intelligence_history_repository(
    db: Session = Depends(get_db),
):

    return ProductIntelligenceHistoryRepository(
        db
    )


def get_intelligence_history_service(
    repository:
    ProductIntelligenceHistoryRepository =
    Depends(
        get_intelligence_history_repository
    ),
):

    return IntelligenceHistoryService(
        repository
    )


def get_execution_repository(
    db: Session = Depends(get_db),
):

    return ExecutionRepository(
        db
    )


def get_execution_service(
    repository: ExecutionRepository = Depends(
        get_execution_repository
    ),
):

    return ExecutionService(
        repository
    )


def get_discovery_run_repository(db: Session = Depends(get_db)) -> DiscoveryRunRepository:
    return DiscoveryRunRepository(db)


def get_discovery_mission_manager() -> MissionManager:
    """Resolve the shared production MissionManager without constructing a duplicate."""
    from app.system import routes as system_routes

    return system_routes.mission_manager


def get_content_mission_manager() -> MissionManager:
    """Resolve the shared runtime MissionManager for content launch routes."""
    from app.system import routes as system_routes

    return system_routes.mission_manager


def get_content_generation_run_repository(db: Session = Depends(get_db)) -> ContentGenerationRunRepository:
    return ContentGenerationRunRepository(db)


def get_content_repurposing_run_repository(db: Session = Depends(get_db)) -> ContentRepurposingRunRepository:
    return ContentRepurposingRunRepository(db)


def get_generated_content_artifact_repository(db: Session = Depends(get_db)) -> GeneratedContentArtifactRepository:
    return GeneratedContentArtifactRepository(db)


def get_discovery_query_service(db: Session = Depends(get_db)) -> DiscoveryQueryService:
    return DiscoveryQueryService(db)


def get_discovery_run_orchestration_service(db: Session = Depends(get_db)) -> DiscoveryRunOrchestrationService:
    return DiscoveryRunOrchestrationService(db)
