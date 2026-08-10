"""
Failure Classifier

Determines whether an execution failure
is temporary and retryable or permanent.
"""


class FailureClassifier:

    RETRYABLE = {
        "network",
        "timeout",
        "connection",
        "rate limit",
        "server error",
        "503",
        "502",
        "504",
    }


    PERMANENT = {
        "validation",
        "invalid",
        "required",
        "missing",
        "not found",
        "authentication",
        "permission",
        "unauthorized",
    }


    def classify(
        self,
        error: str | None,
    ):

        if not error:

            return {

                "failure_type": "UNKNOWN",

                "retryable": False,

            }


        message = (
            error.lower()
        )


        for keyword in self.RETRYABLE:

            if keyword in message:

                return {

                    "failure_type": (
                        keyword.upper()
                    ),

                    "retryable": True,

                }


        for keyword in self.PERMANENT:

            if keyword in message:

                return {

                    "failure_type": (
                        "VALIDATION"
                        if keyword in {
                            "required",
                            "missing",
                            "invalid",
                            "validation",
                        }
                        else keyword.upper()
                    ),

                    "retryable": False,

                }


        return {

            "failure_type": "UNKNOWN",

            "retryable": False,

        }