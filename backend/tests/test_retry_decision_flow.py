from app.retry.failure_classifier import FailureClassifier


def test_validation_failure_does_not_retry():

    classifier = FailureClassifier()

    result = classifier.classify(
        "A URL is required for affiliate discovery."
    )

    assert result["retryable"] is False
    assert result["failure_type"] == "VALIDATION"



def test_network_failure_retries():

    classifier = FailureClassifier()

    result = classifier.classify(
        "Connection timeout while fetching website."
    )

    assert result["retryable"] is True