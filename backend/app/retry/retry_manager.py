"""
Retry Manager

Coordinates retry recovery and execution.

The manager supports:

    process_once()
        Manual / synchronous retry processing.

    start()
        Start the background retry recovery loop.

    stop()
        Gracefully stop the background retry recovery loop.

Production mode may provide a cycle_processor callback.
The callback is responsible for creating and disposing
resources such as database sessions for each retry cycle.

Legacy scanner/worker mode remains supported for tests
and backward compatibility.
"""

import threading


class RetryManager:

    def __init__(
        self,
        scanner=None,
        worker=None,
        poll_interval: float = 30.0,
        cycle_processor=None,
    ):

        self.scanner = scanner

        self.worker = worker

        self.cycle_processor = (
            cycle_processor
        )

        self.poll_interval = max(
            float(
                poll_interval
            ),
            0.1,
        )


        # ==================================================
        # Configuration Validation
        # ==================================================

        if (
            self.cycle_processor is None
            and (
                self.scanner is None
                or self.worker is None
            )
        ):

            raise ValueError(
                "RetryManager requires either "
                "cycle_processor or both "
                "scanner and worker."
            )


        # ==================================================
        # Background Lifecycle
        # ==================================================

        self._stop_event = (
            threading.Event()
        )

        self._thread = None

        self._lifecycle_lock = (
            threading.RLock()
        )


        # ==================================================
        # Runtime State
        # ==================================================

        self._running = False

        self._last_results = []

        self._last_error = None


    # ==================================================
    # Normalize Results
    # ==================================================

    @staticmethod
    def _normalize_results(
        results,
    ):

        if results is None:

            return []


        if isinstance(
            results,
            list,
        ):

            return results


        return [
            results
        ]


    # ==================================================
    # Process Once
    # ==================================================

    def process_once(
        self,
        limit: int = 10,
    ):

        # --------------------------------------------------
        # Production cycle processor
        #
        # RuntimeAdapter will use this mode.
        #
        # The processor can create a fresh SQLAlchemy
        # session for this single cycle and close it before
        # returning.
        # --------------------------------------------------

        if self.cycle_processor is not None:

            results = (
                self.cycle_processor(
                    limit=limit
                )
            )

            results = (
                self._normalize_results(
                    results
                )
            )

            self._last_results = list(
                results
            )

            return results


        # --------------------------------------------------
        # Legacy scanner / worker mode
        # --------------------------------------------------

        queued_tasks = (
            self.scanner.scan_once(
                limit=limit
            )
        )


        results = []


        for _ in queued_tasks:

            try:

                result = (
                    self.worker.process_once()
                )

                results.append(
                    result
                )

            except Exception as exc:

                # ------------------------------------------
                # One retry must not stop remaining retries.
                # ------------------------------------------

                results.append(
                    None
                )

                self._last_error = (
                    str(exc)
                )


        self._last_results = list(
            results
        )


        return results


    # ==================================================
    # Background Loop
    # ==================================================

    def _run_loop(
        self,
    ):

        while not self._stop_event.is_set():

            try:

                self.process_once()

            except Exception as exc:

                # ------------------------------------------
                # The background manager must remain alive
                # after an unexpected infrastructure error.
                # ------------------------------------------

                self._last_error = (
                    str(exc)
                )


            # ----------------------------------------------
            # Event.wait() allows stop() to wake this
            # thread immediately.
            # ----------------------------------------------

            self._stop_event.wait(
                self.poll_interval
            )


        with self._lifecycle_lock:

            self._running = False


    # ==================================================
    # Start
    # ==================================================

    def start(
        self,
    ):

        with self._lifecycle_lock:

            if (
                self._thread is not None
                and
                self._thread.is_alive()
            ):

                self._running = True

                return False


            self._stop_event.clear()

            self._last_error = None


            self._thread = threading.Thread(

                target=self._run_loop,

                name=(
                    "etm-retry-manager"
                ),

                daemon=True,

            )


            self._running = True

            self._thread.start()


            return True


    # ==================================================
    # Stop
    # ==================================================

    def stop(
        self,
        timeout: float = 10.0,
    ):

        with self._lifecycle_lock:

            thread = self._thread


            if (
                thread is None
                or
                not thread.is_alive()
            ):

                self._running = False

                self._thread = None

                return False


            self._stop_event.set()


        # --------------------------------------------------
        # Wait outside lifecycle lock.
        #
        # _run_loop() acquires this lock when it exits.
        # --------------------------------------------------

        thread.join(
            timeout=max(
                float(
                    timeout
                ),
                0.0,
            )
        )


        with self._lifecycle_lock:

            if thread.is_alive():

                self._running = True

                return False


            self._running = False

            self._thread = None


            return True


    # ==================================================
    # Running State
    # ==================================================

    def is_running(
        self,
    ):

        with self._lifecycle_lock:

            return bool(
                self._running
                and
                self._thread is not None
                and
                self._thread.is_alive()
            )


    # ==================================================
    # Last Results
    # ==================================================

    def get_last_results(
        self,
    ):

        return list(
            self._last_results
        )


    # ==================================================
    # Last Error
    # ==================================================

    def get_last_error(
        self,
    ):

        return self._last_error