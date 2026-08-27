"""
Runtime Adapter

Shared runtime bridge for Mission Control.
"""

from app.memory.memory_bus import MemoryBus
from app.task_queue.queue import TaskQueue
from app.system.history import ExecutionHistory
from app.system.event_monitor import EventMonitor
from app.workforce.manager import WorkforceManager

from app.scheduler.scheduler import Scheduler

from app.executor.executor import TaskExecutor

from app.retry.retry_scanner import RetryScanner
from app.retry.retry_worker import RetryWorker
from app.retry.retry_manager import RetryManager

from app.repositories.execution_repository import (
    ExecutionRepository,
)

from app.services.execution_service import (
    ExecutionService,
)

from app.database.session import SessionLocal


class RuntimeAdapter:

    def __init__(self):

        # ==================================================
        # Core Runtime Infrastructure
        # ==================================================

        self.memory = MemoryBus()

        self.queue = TaskQueue()

        self.history = ExecutionHistory()

        self.events = EventMonitor()


        self.workforce = WorkforceManager(
            load_defaults=True
        )


        # ==================================================
        # Retry Infrastructure
        # ==================================================

        self.scheduler = Scheduler()


        # --------------------------------------------------
        # Database Session
        # --------------------------------------------------

        self.db = SessionLocal()


        # --------------------------------------------------
        # Execution Repository
        # --------------------------------------------------

        self.execution_repository = (
            ExecutionRepository(
                self.db
            )
        )


        # --------------------------------------------------
        # Execution Service
        # --------------------------------------------------

        self.execution_service = (
            ExecutionService(
                self.execution_repository
            )
        )


        # --------------------------------------------------
        # Retry Scanner
        # --------------------------------------------------

        self.retry_scanner = RetryScanner(
            self.execution_service,
            self.scheduler,
        )


        # --------------------------------------------------
        # Retry Executor
        #
        # This is the real TaskExecutor used by retries.
        # It has both:
        #
        #   1. RuntimeAdapter
        #   2. PostgreSQL ExecutionService
        #
        # This ensures retry executions follow the same
        # persistence path as normal executions.
        # --------------------------------------------------

        self.retry_executor = TaskExecutor(
            runtime=self,
            execution_service=self.execution_service,
        )


        # --------------------------------------------------
        # Retry Worker
        # --------------------------------------------------

        self.retry_worker = RetryWorker(
            self.scheduler,
            self.retry_executor,
        )


        # --------------------------------------------------
        # Retry Manager
        # --------------------------------------------------

        self.retry_manager = RetryManager(
            self.retry_scanner,
            self.retry_worker,
        )


    # ==================================================
    # Memory
    # ==================================================

    def get_memory_count(
        self,
    ):

        try:

            return len(
                self.memory.all()
            )

        except Exception:

            return 0


    # ==================================================
    # Queue
    # ==================================================

    def get_queue_status(
        self,
    ):

        return {

            "pending": self.queue.size(),

            "running": 0,

            "completed": 0,

            "failed": 0,

        }


    # ==================================================
    # Workers
    # ==================================================

    def get_workers(
        self,
    ):

        return [

            worker.to_dict()

            for worker in (
                self.workforce.workers()
            )

        ]


    # ==================================================
    # Events
    # ==================================================

    def record_event(
        self,
        event,
        event_type="INFO",
        metadata=None,
    ):

        return self.events.publish(

            event=event,

            event_type=event_type,

            metadata=metadata,

        )


    def get_events(
        self,
    ):

        return self.events.all()


    def get_event_records(
        self,
    ):

        return self.events.records()


    def get_latest_event(
        self,
    ):

        return self.events.latest()


    def get_latest_event_record(
        self,
    ):

        return self.events.latest_record()


    # ==================================================
    # Execution History
    # ==================================================

    def record_execution(
        self,
        execution,
    ):

        self.history.add(
            execution
        )


    def update_execution_status(
        self,
        workflow,
        status,
    ):

        return self.history.update_status(

            workflow,

            status,

        )


    def get_history(
        self,
    ):

        return self.history.all()


    # ==================================================
    # Mission Results
    # ==================================================

    def get_latest_mission_result(
        self,
    ):

        return self.memory.get(
            "latest_mission_result"
        )


    # ==================================================
    # Retry Recovery
    # ==================================================

    def recover_failed_tasks(
        self,
    ):

        return self.retry_manager.process_once()


    # ==================================================
    # Retry Lifecycle
    # ==================================================

    def start_retry_manager(
        self,
    ):

        return self.retry_manager.start()


    def stop_retry_manager(
        self,
        timeout=10.0,
    ):

        return self.retry_manager.stop(
            timeout=timeout
        )


    def retry_manager_running(
        self,
    ):

        return self.retry_manager.is_running()


    # ==================================================
    # Shutdown
    # ==================================================

    def close(
        self,
    ):

        # --------------------------------------------------
        # Stop retry manager first.
        # --------------------------------------------------

        try:

            self.stop_retry_manager()

        except Exception:

            pass


        # --------------------------------------------------
        # Close database session.
        # --------------------------------------------------

        try:

            if self.db:

                self.db.close()

        except Exception:

            pass