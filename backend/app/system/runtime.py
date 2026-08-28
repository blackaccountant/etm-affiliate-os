"""
Runtime Adapter

Shared runtime bridge for Mission Control.

Retry database resources are created per processing cycle.
No SQLAlchemy Session is shared across the lifetime of the
application or across application/background threads.
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
from app.retry.retry_lifecycle_coordinator import RetryLifecycleCoordinator

from app.repositories.execution_repository import (
    ExecutionRepository,
)
from app.repositories.mission_repository import MissionRepository
from app.repositories.worker_repository import WorkerRepository

from app.services.execution_service import (
    ExecutionService,
)

from app.database.session import SessionLocal


class RuntimeAdapter:

    def __init__(self, session_factory=None):

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

        # Store a factory only; retry cycles own and close their sessions.
        self.session_factory = session_factory or SessionLocal


        # ==================================================
        # Retry Infrastructure
        # ==================================================
        #
        # IMPORTANT:
        #
        # RuntimeAdapter intentionally does NOT create a
        # long-lived SQLAlchemy Session here.
        #
        # RetryManager invokes _process_retry_cycle().
        #
        # Every invocation creates:
        #
        #   SessionLocal
        #       ↓
        #   ExecutionRepository
        #       ↓
        #   ExecutionService
        #       ↓
        #   RetryScanner
        #       ↓
        #   TaskExecutor
        #       ↓
        #   RetryWorker
        #
        # The session is closed before the cycle returns.
        # ==================================================

        self.retry_manager = RetryManager(
            cycle_processor=(
                self._process_retry_cycle
            )
        )


    # ==================================================
    # Retry Processing Cycle
    # ==================================================

    def _process_retry_cycle(
        self,
        limit: int = 10,
    ):
        """
        Execute one isolated retry-processing cycle.

        A fresh SQLAlchemy session is created for this
        cycle and is always closed before returning.

        This prevents SQLAlchemy Session objects from
        being shared between FastAPI/application threads
        and the retry manager background thread.
        """

        db = self.session_factory()


        try:

            # ==============================================
            # Repository
            # ==============================================

            execution_repository = (
                ExecutionRepository(
                    db
                )
            )
            mission_repository = MissionRepository(db)
            worker_repository = WorkerRepository(db)


            # ==============================================
            # Service
            # ==============================================

            execution_service = (
                ExecutionService(
                    execution_repository
                )
            )


            # ==============================================
            # Per-Cycle Scheduler
            # ==============================================

            scheduler = Scheduler()


            # ==============================================
            # Scanner
            # ==============================================

            retry_scanner = RetryScanner(
                execution_service=(
                    execution_service
                ),
                scheduler=scheduler,
            )


            # ==============================================
            # Executor
            # ==============================================

            retry_executor = TaskExecutor(
                runtime=self,
                execution_service=(
                    execution_service
                ),
            )
            # RetryLifecycleCoordinator owns worker finalization after durable release.
            retry_executor.workforce = None

            coordinator = RetryLifecycleCoordinator(
                db=db,
                execution_service=execution_service,
                mission_repository=mission_repository,
                worker_repository=worker_repository,
                workforce=self.workforce,
                executor=retry_executor,
                runtime=self,
            )


            # ==============================================
            # Worker
            # ==============================================

            retry_worker = RetryWorker(
                scheduler=scheduler,
                executor=coordinator,
            )


            # ==============================================
            # Scan / Atomic Claim
            # ==============================================

            queued_tasks = (
                retry_scanner.scan_once(
                    limit=limit
                )
            )


            results = []


            # ==============================================
            # Execute Claimed Tasks
            # ==============================================

            for _ in queued_tasks:

                try:

                    result = (
                        retry_worker.process_once()
                    )

                    results.append(
                        result
                    )


                except Exception as exc:

                    # --------------------------------------
                    # Protect the rest of this retry batch.
                    #
                    # An unexpected infrastructure error
                    # may leave the current transaction in
                    # an unusable state.
                    # --------------------------------------

                    try:

                        db.rollback()

                    except Exception:

                        pass


                    results.append(
                        None
                    )


                    # --------------------------------------
                    # Record operational failure without
                    # terminating the retry manager.
                    # --------------------------------------

                    try:

                        self.record_event(
                            "Retry worker cycle error",
                            event_type="ERROR",
                            metadata={
                                "error": str(
                                    exc
                                )
                            },
                        )

                    except Exception:

                        pass


            return results


        except Exception:

            # ==============================================
            # Cycle-Level Failure
            # ==============================================

            try:

                db.rollback()

            except Exception:

                pass


            raise


        finally:

            # ==============================================
            # ALWAYS release SQLAlchemy session
            # ==============================================

            db.close()


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

            "pending":
                self.queue.size(),

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

        return (
            self.retry_manager.process_once()
        )


    # ==================================================
    # Retry Lifecycle
    # ==================================================

    def start_retry_manager(
        self,
    ):

        return (
            self.retry_manager.start()
        )


    def stop_retry_manager(
        self,
        timeout=10.0,
    ):

        return (
            self.retry_manager.stop(
                timeout=timeout
            )
        )


    def retry_manager_running(
        self,
    ):

        return (
            self.retry_manager.is_running()
        )


    # ==================================================
    # Shutdown
    # ==================================================

    def close(
        self,
    ):
        """
        Gracefully stop runtime background resources.

        There is no persistent database session to close.
        Every retry cycle owns and closes its own session.
        """

        try:

            self.stop_retry_manager()

        except Exception:

            pass
