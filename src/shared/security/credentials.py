"""Generic opaque credentials for anonymous ownership until RPCN login is available."""

from abc import ABC, abstractmethod
import hashlib
import secrets


class CredentialManager(ABC):
    @abstractmethod
    def issue(self) -> tuple[str, str]:
        """Return a client credential and its non-reversible stored form."""


class TokenCredentialManager(CredentialManager):
    def issue(self) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        return token, hash_credential(token)


def hash_credential(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
