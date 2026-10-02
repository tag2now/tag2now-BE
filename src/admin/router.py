from fastapi import APIRouter, Depends

from admin import models, service
from admin.dependencies import admin_user
from auth.models import AuthUser

router = APIRouter(prefix="/admin", tags=["Admin"])


# POST, not GET: the admin's password travels in the body, never in a URL.
@router.post("/users/lookup", response_model=models.AccountStatusOut)
async def lookup(request: models.AdminActionRequest, admin: AuthUser = Depends(admin_user)):
    """An RPCN account's standing: role, ban, whether it is in-game now."""
    return await service.lookup(admin, request.password, request.username)


@router.post("/users/ban", response_model=models.BanOut)
async def ban(request: models.AdminActionRequest, admin: AuthUser = Depends(admin_user)):
    """Ban an RPCN account and disconnect it if it is in-game.

    The ban is RPCN's: RPCS3 and this site's login both refuse the account from
    then on. A site token it already holds stays valid until it expires.
    """
    result = await service.ban(admin, request.password, request.username)
    return {"username": result.username, "kicked": result.kicked}
