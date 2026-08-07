"""
Execution Result

Standard response object for task execution.
"""


class ExecutionResult:

    def __init__(
        self,
        success: bool,
        data=None,
        error=None,
        retryable: bool = False,
    ):

        self.success = success

        self.data = data

        self.error = error

        self.retryable = retryable


    def __repr__(self):

        return (
            f"ExecutionResult("
            f"success={self.success}, "
            f"retryable={self.retryable}, "
            f"error={self.error}"
            f")"
        )