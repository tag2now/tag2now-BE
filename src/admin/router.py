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


# --- TTT2 saves ---------------------------------------------------------------
# Edits are two calls: dry_run first, then the same body with expect_sha256 set
# to the sha256 the preview answered. A player who is in-game is refused (409),
# because the game would overwrite the edit on its next save.

@router.post("/saves/show", response_model=models.SaveOut)
async def show_save(request: models.ShowSaveRequest, admin: AuthUser = Depends(admin_user)):
    """A player's TTT2 save: account rank, record and every character's rank."""
    return await service.show_save(admin, request)


@router.post("/saves/backups", response_model=models.BackupsOut)
async def list_backups(request: models.SaveRequest, admin: AuthUser = Depends(admin_user)):
    """The backups of a player's save, oldest first; every write takes one."""
    return await service.list_backups(admin, request)


@router.post("/saves/log", response_model=models.SaveLogOut)
async def read_save_log(request: models.SaveLogRequest, admin: AuthUser = Depends(admin_user)):
    """Save edits from the site and the command line, most recent last."""
    return await service.read_save_log(admin, request)


@router.post("/saves/set-rank", response_model=models.SaveWriteOut)
async def set_rank(request: models.SetRankRequest, admin: AuthUser = Depends(admin_user)):
    """One character's rank (and points), or every character's and the account rank."""
    return await service.edit_save("set-rank", admin, request)


@router.post("/saves/set-account-rank", response_model=models.SaveWriteOut)
async def set_account_rank(request: models.SetAccountRankRequest, admin: AuthUser = Depends(admin_user)):
    """The account rank, which the game never lowers."""
    return await service.edit_save("set-account-rank", admin, request)


@router.post("/saves/floor", response_model=models.FloorWriteOut)
async def floor(request: models.FloorRequest, admin: AuthUser = Depends(admin_user)):
    """Raise every character below the floor to it, with floor points."""
    return await service.edit_save("floor", admin, request)


@router.post("/saves/restore", response_model=models.SaveWriteOut)
async def restore(request: models.RestoreRequest, admin: AuthUser = Depends(admin_user)):
    """Put a backup back as the live save; the save it replaces is backed up first."""
    return await service.edit_save("restore", admin, request)
