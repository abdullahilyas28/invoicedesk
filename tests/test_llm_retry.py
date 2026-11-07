import pytest
from google.genai import errors

import invoicedesk.llm as llm


class FakeModels:
    def __init__(self, errors_to_raise):
        self.errors_to_raise = list(errors_to_raise)
        self.calls = 0

    def generate_content(self, **kwargs):
        self.calls += 1
        if self.errors_to_raise:
            raise self.errors_to_raise.pop(0)
        return "fake response"


class FakeClient:
    def __init__(self, errors_to_raise):
        self.models = FakeModels(errors_to_raise)


def server_error() -> errors.ServerError:
    return errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}})


def client_error() -> errors.ClientError:
    return errors.ClientError(400, {"error": {"code": 400, "message": "bad request", "status": "INVALID_ARGUMENT"}})


@pytest.fixture
def no_waiting(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(llm, "_wait_for_rate_limit", lambda: None)


def test_retries_then_succeeds(monkeypatch, no_waiting):
    fake_client = FakeClient([server_error(), server_error()])
    monkeypatch.setattr(llm, "client", fake_client)
    assert llm._call_with_retry("model", [], None) == "fake response"
    assert fake_client.models.calls == 3


def test_gives_up_after_max_attempts(monkeypatch, no_waiting):
    fake_client = FakeClient([server_error()] * 10)
    monkeypatch.setattr(llm, "client", fake_client)
    with pytest.raises(errors.ServerError):
        llm._call_with_retry("model", [], None)
    assert fake_client.models.calls == llm.MAX_ATTEMPTS


def test_does_not_retry_bad_requests(monkeypatch, no_waiting):
    fake_client = FakeClient([client_error()])
    monkeypatch.setattr(llm, "client", fake_client)
    with pytest.raises(errors.ClientError):
        llm._call_with_retry("model", [], None)
    assert fake_client.models.calls == 1