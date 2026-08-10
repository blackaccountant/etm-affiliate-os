"""
Retry Manager

Coordinates retry scanning and retry execution.
"""


class RetryManager:

    def __init__(
        self,
        scanner,
        worker,
    ):

        self.scanner = scanner

        self.worker = worker


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

            result = (
                self.worker.process_once()
            )

            results.append(
                result
            )


        return results