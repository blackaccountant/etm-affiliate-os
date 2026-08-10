from app.retry.failure_classifier import FailureClassifier



def test_missing_url_is_not_retryable():

    classifier = FailureClassifier()

    result = classifier.classify(
        "A URL is required for affiliate discovery."
    )


    assert result["retryable"] is False

    assert result["failure_type"] == "VALIDATION"



def test_network_error_is_retryable():

    classifier = FailureClassifier()

    result = classifier.classify(
        "Connection timeout while fetching website."
    )


    assert result["retryable"] is True



def test_unknown_failure_is_not_retryable():

    classifier = FailureClassifier()

    result = classifier.classify(
        "Something strange happened."
    )


    assert result["retryable"] is False