"""One RPCN connection shared by every caller, replaced after a failure."""
import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from rpcn_client import RpcnClient, RpcnError
from matching.exceptions import RpcnUnavailableError
from rpcn_client.metrics import TrackedRpcnClient

logger = logging.getLogger(__name__)


def create_client(host: str, port: int, user: str, password: str, token: str, metric_enable: bool) -> RpcnClient:
    """A connected client, already logged in."""
    client = RpcnClient(host=host, port=port)
    if metric_enable:
        client = TrackedRpcnClient(client)

    client.connect()
    client.login(user, password, token)
    return client


class SharedRpcnClient:
    """Hands out one client at a time, since its socket is not concurrency-safe."""

    def __init__(self, client_factory: Callable[[], RpcnClient], cooldown: float = 5.0):
        self._client_factory = client_factory
        self._cooldown = cooldown
        self._lock = threading.Lock()
        self._client: RpcnClient | None = None
        self._failed_at = float("-inf")

    def shutdown(self) -> None:
        """Disconnect the client if connected."""
        with self._lock:
            if self._client is None:
                return
            try:
                self._client.disconnect()
                logger.info("RPCN client disconnected")
            except Exception:
                logger.warning("RPCN disconnect failed", exc_info=True)
            finally:
                self._client = None

    @contextmanager
    def api_client(self) -> Iterator[RpcnClient]:
        with self._lock:
            try:
                yield self._connected()
            except (RpcnError, OSError) as exc:
                logger.error("RPCN connection error: %s", exc)
                self._discard()
                raise RpcnUnavailableError(str(exc)) from exc

    def _connected(self) -> RpcnClient:
        if self._client is None:
            self._ensure_cooled_down()
            self._client = self._client_factory()
        return self._client

    def _ensure_cooled_down(self) -> None:
        # Without a pause every request would retry a server that just refused us.
        remaining = self._failed_at + self._cooldown - time.monotonic()
        if remaining > 0:
            raise RpcnUnavailableError(f"RPCN reconnect cooldown ({remaining:.1f}s remaining)")

    def _discard(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
        self._client = None
        self._failed_at = time.monotonic()
