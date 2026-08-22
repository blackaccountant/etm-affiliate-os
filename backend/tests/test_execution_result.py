from app.execution.execution_result import ExecutionResult


def test_success_result():

    result = ExecutionResult(
        success=True,
        data={
            "message": "completed"
        }
    )

    assert result.success is True

    assert result.retryable is False

    assert result.error is None


def test_failed_retryable_result():

    result = ExecutionResult(
        success=False,
        error="timeout",
        retryable=True
    )

    assert result.success is False

    assert result.retryable is True

    assert result.error == "timeout"


def test_failed_permanent_result():

    result = ExecutionResult(
        success=False,
        error="invalid api key",
        retryable=False
    )

    assert result.success is False

    assert result.retryable is False