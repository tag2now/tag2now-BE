"""RPCS3-compatible RPCN password derivation.

RPCS3 never sends the password a player types verbatim. Its UI derives a
32-byte value with PBKDF2-HMAC-SHA3-256, then sends that value as uppercase
hex. rpcn-narco stores an Argon2 hash of this derived value, so API callers
must use the same first-stage derivation before verification.
"""

import hashlib

_SALT = b"No matter where you go, everybody's connected."
_ITERATIONS = 200_000
_DERIVED_KEY_LENGTH = 32


def derive_rpcn_password(password: str) -> str:
    """Return the value RPCS3 sends to RPCN for a typed password."""
    digest = hashlib.pbkdf2_hmac(
        "sha3_256",
        password.encode("utf-8"),
        _SALT,
        _ITERATIONS,
        dklen=_DERIVED_KEY_LENGTH,
    )
    return digest.hex().upper()
