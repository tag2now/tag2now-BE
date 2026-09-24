"""Replaceable contract for checking a username and password."""

from abc import ABC, abstractmethod

from auth.models import VerifiedAccount


class AccountVerifier(ABC):
    @abstractmethod
    async def init(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def verify(self, username: str, password: str) -> VerifiedAccount:
        """Return the account, or raise InvalidCredentialsError / AuthUnavailableError.

        A banned account is still returned --- refusing it is the service's call.
        """
