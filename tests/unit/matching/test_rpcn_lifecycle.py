"""The shared RPCN client: one connection, dropped on a connection error, retried after a pause."""

import pytest

from matching.exceptions import RpcnUnavailableError
from matching.rpcn_lifecycle import SharedRpcnClient
from rpcn_client import RpcnError


class FakeClient:
    def __init__(self):
        self.disconnected = False

    def disconnect(self):
        self.disconnected = True


class Factory:
    """Makes a fresh FakeClient per call, or raises `error` instead."""

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.made: list[FakeClient] = []

    def __call__(self) -> FakeClient:
        if self.error:
            raise self.error
        self.made.append(FakeClient())
        return self.made[-1]


def _fail_once(shared: SharedRpcnClient) -> None:
    with pytest.raises(RpcnUnavailableError):
        with shared.api_client():
            raise RpcnError("connection reset")


def test_the_first_use_connects_and_later_uses_share_that_connection():
    factory = Factory()
    shared = SharedRpcnClient(factory)

    with shared.api_client() as first:
        pass
    with shared.api_client() as second:
        pass

    assert len(factory.made) == 1
    assert first is second


def test_a_connection_error_disconnects_and_reports_rpcn_unavailable():
    factory = Factory()
    shared = SharedRpcnClient(factory)

    _fail_once(shared)

    assert factory.made[0].disconnected


def test_a_failed_connect_reports_rpcn_unavailable():
    shared = SharedRpcnClient(Factory(error=OSError("refused")))

    with pytest.raises(RpcnUnavailableError, match="refused"):
        with shared.api_client():
            pass


def test_a_retry_within_the_cooldown_fails_without_connecting():
    factory = Factory()
    shared = SharedRpcnClient(factory, cooldown=60)
    _fail_once(shared)

    with pytest.raises(RpcnUnavailableError, match="cooldown"):
        with shared.api_client():
            pass

    assert len(factory.made) == 1


def test_a_retry_after_the_cooldown_connects_anew():
    factory = Factory()
    shared = SharedRpcnClient(factory, cooldown=0)
    _fail_once(shared)

    with shared.api_client() as client:
        pass

    assert client is factory.made[1]


def test_an_error_other_than_a_connection_error_keeps_the_connection():
    factory = Factory()
    shared = SharedRpcnClient(factory)

    with pytest.raises(ValueError):
        with shared.api_client():
            raise ValueError("bad reply")
    with shared.api_client() as client:
        pass

    assert client is factory.made[0]
    assert not client.disconnected


def test_shutdown_disconnects_and_the_next_use_connects_anew():
    factory = Factory()
    shared = SharedRpcnClient(factory)
    with shared.api_client():
        pass

    shared.shutdown()
    with shared.api_client() as client:
        pass

    assert factory.made[0].disconnected
    assert client is factory.made[1]
