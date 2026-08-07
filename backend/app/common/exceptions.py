class ETMException(Exception):
    """
    Base exception for ETM Affiliate OS.
    """

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class ResourceNotFoundException(ETMException):
    """
    Raised when a requested resource cannot be found.
    """

    pass


class DuplicateResourceException(ETMException):
    """
    Raised when attempting to create a duplicate resource.
    """

    pass


class ValidationException(ETMException):
    """
    Raised when business validation fails.
    """

    pass


class ProviderException(ETMException):
    """
    Raised by AI providers.
    """

    pass


class WorkflowException(ETMException):
    """
    Raised during workflow execution.
    """

    pass