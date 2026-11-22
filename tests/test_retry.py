from unittest import mock

import pytest
import requests

import retry


def _http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


def _flaky(errors):
    calls = []

    @retry.with_retry
    def fn():
        calls.append(1)
        if len(calls) <= len(errors):
            raise errors[len(calls) - 1]
        return "ok"

    return fn, calls


@pytest.fixture(autouse=True)
def _no_sleep():
    with mock.patch("tenacity.nap.time.sleep"):
        yield


def test_4xx_is_not_retried():
    fn, calls = _flaky([_http_error(400)] * 3)
    with pytest.raises(requests.HTTPError):
        fn()
    assert len(calls) == 1


def test_5xx_is_retried_then_succeeds():
    fn, calls = _flaky([_http_error(503), _http_error(502)])
    assert fn() == "ok"
    assert len(calls) == 3


def test_5xx_gives_up_after_max_attempts():
    fn, calls = _flaky([_http_error(500)] * 5)
    with pytest.raises(requests.HTTPError):
        fn()
    assert len(calls) == retry.MAX_ATTEMPTS


def test_connection_error_and_timeout_are_retried():
    fn, calls = _flaky([requests.ConnectionError(), requests.Timeout()])
    assert fn() == "ok"
    assert len(calls) == 3


def test_non_request_exceptions_are_not_retried():
    fn, calls = _flaky([ValueError("boom")])
    with pytest.raises(ValueError):
        fn()
    assert len(calls) == 1


def test_timeout_constant_is_positive():
    assert retry.REQUEST_TIMEOUT_SECONDS > 0


def test_dns_call_passes_timeout():
    from notifiers import technitium_dns

    with mock.patch.object(technitium_dns.requests, "get") as get:
        get.return_value.raise_for_status.return_value = None
        technitium_dns._do_dns_update("http://dns", {"a": 1})
    assert get.call_args.kwargs["timeout"] == retry.REQUEST_TIMEOUT_SECONDS
