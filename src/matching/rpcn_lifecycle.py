"""Singleton RPCN client lifecycle management."""
import logging
import time
import threading
from contextlib import contextmanager

from rpcn_client import RpcnClient, RpcnError
from matching.exceptions import RpcnUnavailableError
from shared.settings import get_settings, Settings
from rpcn_client.metrics import TrackedRpcnClient

logger = logging.getLogger(__name__)

_client_lock = threading.Lock()
_shared_client: RpcnClient | None = None
_RECONNECT_COOLDOWN = 5.0  # seconds
_last_failure: float = 0.0

settings = get_settings()

def init_rpcn_client():
    global _shared_client
    client = RpcnClient(host=settings.rpcn_host, port=settings.rpcn_port)
    if settings.rpcn_metric_enable:
        client = TrackedRpcnClient(client)

    client.connect()
    client.login(settings.rpcn_user, settings.rpcn_password, settings.rpcn_token)
    return client


def shutdown_client():
    """Disconnect the shared RPCN client if connected."""
    global _shared_client
    with _client_lock:
        if _shared_client is not None:
            try:
                _shared_client.disconnect()
                logger.info("RPCN client disconnected")
            except Exception:
                logger.warning("RPCN disconnect failed", exc_info=True)
            finally:
                _shared_client = None


@contextmanager
def api_client():
    global _shared_client, _last_failure
    with _client_lock:
        if _shared_client is None:
            elapsed = time.monotonic() - _last_failure
            if _last_failure and elapsed < _RECONNECT_COOLDOWN:
                raise RpcnUnavailableError(f"RPCN reconnect cooldown ({_RECONNECT_COOLDOWN - elapsed:.1f}s remaining)")
        try:
            if _shared_client is None:
                _shared_client = init_rpcn_client()
            yield _shared_client
        except (RpcnError, OSError) as exc:
            logger.error("RPCN connection error: %s", exc)
            if _shared_client is not None:
                try:
                    _shared_client.disconnect()
                except Exception:
                    pass
                _shared_client = None
            _last_failure = time.monotonic()
            raise RpcnUnavailableError(str(exc)) from exc
