"""Tekken TT2 domain exceptions."""

from shared.exceptions import ServiceUnavailableError


class RpcnUnavailableError(ServiceUnavailableError):
    """RPCN server connection failed or is in cooldown."""
