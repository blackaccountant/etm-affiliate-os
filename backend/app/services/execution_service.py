"""
Execution Service

Business logic for execution history
and retry management.
"""


from app.repositories.execution_repository import (
    ExecutionRepository,
)


class ExecutionService:
    """
    Service layer for executions.
    """


    def __init__(
        self,
        repository: ExecutionRepository,
    ):

        self.repository = repository



    # ==================================================
    # History Queries
    # ==================================================

    def get_recent(
        self,
        limit: int = 10,
    ):

        return self.repository.list_recent(
            limit=limit
        )



    def get_by_id(
        self,
        execution_id: int,
    ):

        return self.repository.get_by_id(
            execution_id
        )



    def get_by_mission_id(
        self,
        mission_id: str,
    ):

        return self.repository.get_by_mission_id(
            mission_id
        )



    # ==================================================
    # Retry Management
    # ==================================================

    def schedule_retry(
        self,
        execution,
        retry_count: int,
        max_retries: int = 3,
        next_retry_at=None,
        failure_type: str = None,
        error: str = None,
    ):

        return self.repository.schedule_retry(
            execution=execution,
            retry_count=retry_count,
            max_retries=max_retries,
            next_retry_at=next_retry_at,
            failure_type=failure_type,
            error=error,
        )



    def get_retry_queue(
        self,
        limit: int = 10,
    ):

        return self.repository.get_retryable(
            limit=limit
        )



    def claim_retry(
        self,
        execution,
    ):

        return self.repository.claim_retry(
            execution
        )