"""User identity resolution for the community board."""

from fastapi import HTTPException, Request


def get_user(request: Request) -> str:
    """Resolve user name from header or cookie. Raises 400 if absent."""
    name = request.headers.get("X-Community-User") or request.cookies.get("community_user")
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="User identity required (X-Community-User header or community_user cookie)")
    name = name.strip()[:50]
    return name
