"""
Failure Classifier

Determines whether an execution failure
is temporary and retryable or permanent.
"""


class FailureClassifier:

    # ==================================================
    # Retryable failures
    # ==================================================

    RETRYABLE = {
        # Network / connectivity
        "network",
        "timeout",
        "timed out",
        "request timed out",
        "connection",
        "connection refused",
        "connection reset",
        "connection aborted",
        "dns",
        "host unreachable",

        # Website / HTTP fetching
        "unable to fetch",
        "failed to fetch",
        "could not fetch",
        "unable to fetch website",
        "failed to fetch website",
        "could not fetch website",
        "website unavailable",
        "site unavailable",
        "temporarily unavailable",

        # HTTP / infrastructure
        "rate limit",
        "server error",
        "502",
        "503",
        "504",
        "bad gateway",
        "service unavailable",
        "gateway timeout",

        # Common transient infrastructure errors
        "temporary failure",
        "temporary error",
        "temporarily failed",
        "upstream error",
        "upstream unavailable",
    }


    # ==================================================
    # Permanent failures
    # ==================================================

    PERMANENT = {
        "validation",
        "invalid",
        "required",
        "missing",
        "not found",
        "authentication",
        "permission",
        "unauthorized",
        "forbidden",
    }


    # ==================================================
    # Classify
    # ==================================================

    def classify(
        self,
        error: str | None,
    ):

        # --------------------------------------------------
        # No error information
        # --------------------------------------------------

        if not error:

            return {
                "failure_type": "UNKNOWN",
                "retryable": False,
            }


        # --------------------------------------------------
        # Normalize error message
        # --------------------------------------------------

        message = (
            str(error)
            .lower()
            .strip()
        )


        # --------------------------------------------------
        # Retryable failures
        # --------------------------------------------------

        for keyword in self.RETRYABLE:

            if keyword in message:

                return {
                    "failure_type": (
                        "NETWORK"
                        if keyword in {
                            "network",
                            "connection",
                            "connection refused",
                            "connection reset",
                            "connection aborted",
                            "dns",
                            "host unreachable",
                            "unable to fetch",
                            "failed to fetch",
                            "could not fetch",
                            "unable to fetch website",
                            "failed to fetch website",
                            "could not fetch website",
                            "website unavailable",
                            "site unavailable",
                        }
                        else keyword.upper()
                    ),

                    "retryable": True,
                }


        # --------------------------------------------------
        # Permanent failures
        # --------------------------------------------------

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


        # --------------------------------------------------
        # Unknown failures
        #
        # Unknown failures remain non-retryable.
        # This prevents accidental infinite retries.
        # --------------------------------------------------

        return {
            "failure_type": "UNKNOWN",
            "retryable": False,
        }