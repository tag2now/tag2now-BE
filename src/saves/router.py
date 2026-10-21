"""Two routers over one service: anyone's read-only profile view, and the
admin's reads and edits under /admin."""

from fastapi import APIRouter, Depends, Path, Query

from admin.dependencies import admin_user
from auth.models import AuthUser
from saves import models, service

router = APIRouter(prefix="/saves", tags=["Saves"])
admin_router = APIRouter(prefix="/admin/saves", tags=["Admin"])


@router.get("/players/{npid}", response_model=models.PlayerSaveOut)
async def player_save(npid: str = Path(min_length=1, max_length=64, description="Player NPID")):
    """A player's TTT2 save: account rank, record and the rank of every character
    they have used. Read-only, and up to ten minutes behind the game."""
    return await service.get_player_save(npid)


@router.get("/leaderboard", response_model=models.CurrentRankLeaderboardOut)
async def current_rank_leaderboard(
    top: int = Query(100, ge=1, le=1000, description="How many players to answer"),
    days: int | None = Query(None, ge=1, le=365, description="Only players whose game saved within this many days"),
):
    """Players by their current ranks: the best character's rank, then the second's,
    then their points; with `days`, only recent players, ranked among themselves.
    Read-only, and up to five minutes behind the game."""
    return await service.get_current_rank_leaderboard(top, days)


@router.get("/current-rank-holders", response_model=models.CurrentRankHoldersOut)
async def current_rank_holders(
    rank: int = Query(ge=models.HOLDER_RANKS.start, le=models.HOLDER_RANKS.stop - 1,
                      description="Current rank code, from 1st dan (10)"),
    top: int = Query(100, ge=1, le=1000, description="How many players to answer"),
    days: int = Query(30, ge=1, le=365, description="Only players whose game saved within this many days"),
):
    """Players to play now at a rank: those who played a character currently at
    `rank` and saved within `days`, the lowest on the leaderboard first.
    Read-only, and up to five minutes behind the game."""
    return await service.get_current_rank_holders(rank, top, days)


# --- admin ----------------------------------------------------------------------
# POST, not GET: the admin's password travels in the body, never in a URL.
# Edits are two calls: dry_run first, then the same body with expect_sha256 set
# to the sha256 the preview answered. A player who is in-game is refused (409),
# because the game would overwrite the edit on its next save.

@admin_router.post("/show", response_model=models.SaveOut)
async def show_save(request: models.ShowSaveRequest, admin: AuthUser = Depends(admin_user)):
    """A player's TTT2 save: account rank, record and every character's rank."""
    return await service.show_save(admin, request)


@admin_router.post("/backups", response_model=models.BackupsOut)
async def list_backups(request: models.SaveRequest, admin: AuthUser = Depends(admin_user)):
    """The backups of a player's save, oldest first; every write takes one."""
    return await service.list_backups(admin, request)


@admin_router.post("/log", response_model=models.SaveLogOut)
async def read_save_log(request: models.SaveLogRequest, admin: AuthUser = Depends(admin_user)):
    """Save edits from the site and the command line, most recent last."""
    return await service.read_save_log(admin, request)


@admin_router.post("/set-rank", response_model=models.SaveWriteOut)
async def set_rank(request: models.SetRankRequest, admin: AuthUser = Depends(admin_user)):
    """One character's rank (and points), or every character's and the account rank."""
    return await service.edit_save("set-rank", admin, request)


@admin_router.post("/set-account-rank", response_model=models.SaveWriteOut)
async def set_account_rank(request: models.SetAccountRankRequest, admin: AuthUser = Depends(admin_user)):
    """The account rank, which the game never lowers."""
    return await service.edit_save("set-account-rank", admin, request)


@admin_router.post("/floor", response_model=models.FloorWriteOut)
async def floor(request: models.FloorRequest, admin: AuthUser = Depends(admin_user)):
    """Raise every character below the floor to it, with floor points."""
    return await service.edit_save("floor", admin, request)


@admin_router.post("/restore", response_model=models.SaveWriteOut)
async def restore(request: models.RestoreRequest, admin: AuthUser = Depends(admin_user)):
    """Put a backup back as the live save; the save it replaces is backed up first."""
    return await service.edit_save("restore", admin, request)
