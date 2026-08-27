"""
Retry Manager

Coordinates retry scanning and retry execution.

The manager supports both:

    process_once()
        Manual / synchronous retry processing.

    start()
        Start a background retry recovery loop.

    stop()
        Gracefully stop the background retry recovery loop.
"""

import threading
import time


class RetryManager:

    def __init__(
        self,
        scanner,
        worker,
        poll_interval: float = 30.0,
    ):

        self.scanner = scanner

        self.worker = worker

        self.poll_interval = (
            max(
                float(
                    poll_interval
                ),
                0.1,
            )
        )


        # ==================================================
        # Background lifecycle
        # ==================================================

        self._stop_event = (
            threading.Event()
        )

        self._thread = None

        self._lifecycle_lock = (
            threading.RLock()
        )


        # ==================================================
        # Runtime state
        # ==================================================

        self._running = False

        self._last_results = []

        self._last_error = None


    # ==================================================
    # Process Once
    # ==================================================

    def process_once(
        self,
        limit: int = 10,
    ):

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
                # One retry must not prevent the manager
                # from processing the remaining retry tasks.
                # ------------------------------------------

                results.append(
                    None
                )

                self._last_error = (
                    str(exc)
                )


        self._last_results = (
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
                # even if scanning itself encounters an
                # unexpected infrastructure error.
                # ------------------------------------------

                self._last_error = (
                    str(exc)
                )


            # ----------------------------------------------
            # Event.wait() is preferable to time.sleep().
            #
            # It allows stop() to wake the loop immediately
            # instead of waiting for the entire interval.
            # ----------------------------------------------

            self._stop_event.wait(
                self.poll_interval
            )


        # ----------------------------------------------
        # Background loop has exited.
        # ----------------------------------------------

        with self._lifecycle_lock:

            self._running = False


    # ==================================================
    # Start
    # ==================================================

    def start(
        self,
    ):

        with self._lifecycle_lock:

            # ------------------------------------------
            # Already running.
            # ------------------------------------------

            if (
                self._thread is not None
                and self._thread.is_alive()
            ):

                self._running = True

                return False


            # ------------------------------------------
            # Reset lifecycle state.
            # ------------------------------------------

            self._stop_event.clear()

            self._last_error = None


            # ------------------------------------------
            # Create background thread.
            # ------------------------------------------

            self._thread = threading.Thread(

                target=self._run_loop,

                name="etm-retry-manager",

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
                or not thread.is_alive()
            ):

                self._running = False

                self._thread = None

                return False


            # ------------------------------------------
            # Signal the background loop.
            # ------------------------------------------

            self._stop_event.set()


        # --------------------------------------------------
        # Wait OUTSIDE the lifecycle lock.
        #
        # This prevents deadlock because _run_loop()
        # acquires the same lock when it exits.
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

                # --------------------------------------
                # The thread did not stop within the
                # requested timeout.
                # --------------------------------------

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
                and self._thread is not None
                and self._thread.is_alive()
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