"""Two routers over one service: the owner's own channel, and the admin's
list and removal under /admin. Who is live rides on /rooms/all."""

from fastapi import APIRouter, Depends, Path, Response

from admin.dependencies import admin_user
from auth.dependencies import current_user
from auth.models import AuthUser
from streaming import models
from streaming.dependencies import streaming_service
from streaming.service import StreamingService

router = APIRouter(prefix="/streams", tags=["Streams"])
admin_router = APIRouter(prefix="/admin/streams", tags=["Admin"])


@router.get("/me", response_model=models.MyStreamChannelOut)
async def my_channel(user: AuthUser = Depends(current_user), service: StreamingService = Depends(streaming_service)):
    """The signed-in account's channel, or null."""
    return await service.get_my_channel(user)


@router.put("/me", response_model=models.MyStreamChannelOut)
async def register_channel(
    request: models.ChannelRequest,
    user: AuthUser = Depends(current_user),
    service: StreamingService = Depends(streaming_service),
):
    """Connect a Chzzk channel to the signed-in account, replacing any before it."""
    return await service.register_channel(user, request.channel)


@router.delete("/me", status_code=204)
async def unregister_channel(
    user: AuthUser = Depends(current_user), service: StreamingService = Depends(streaming_service)
):
    """Disconnect the signed-in account's channel. Succeeds when there is none."""
    await service.unregister_channel(user)
    return Response(status_code=204)


# --- admin ----------------------------------------------------------------------
# The token's admin claim is enough: these touch only this service's own table.


@admin_router.get("", response_model=models.AdminStreamChannelsOut)
async def list_channels(admin: AuthUser = Depends(admin_user), service: StreamingService = Depends(streaming_service)):
    """Every registered channel, most recently registered first."""
    return await service.list_channels()


@admin_router.delete("/{username}", status_code=204)
async def remove_channel(
    username: str = Path(min_length=1, max_length=64),
    admin: AuthUser = Depends(admin_user),
    service: StreamingService = Depends(streaming_service),
):
    """Disconnect an account's channel, e.g. one registered by someone else."""
    await service.remove_channel(username)
    return Response(status_code=204)
