"""Two routers over one service: what visitors read, and the admin's writing it under /admin."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Path, Response

from admin.dependencies import admin_user
from auth.models import AuthUser
from popup import models
from popup.dependencies import popup_content, popup_service, uploaded_image
from popup.service import PopupService

router = APIRouter(prefix="/popups", tags=["Popups"])
admin_router = APIRouter(prefix="/admin/popups", tags=["Admin"])

# The path is that of a Postgres bigint; a larger number would be a database error, not a 404.
PopupId = Annotated[int, Path(ge=1, le=2**63 - 1)]
# Safe to keep forever: the URL carries the image's hash, so a new image is a new URL.
_IMAGE_CACHE_CONTROL = "public, max-age=31536000, immutable"


@router.get("/active", response_model=models.ActivePopupsOut)
async def active_popups(service: PopupService = Depends(popup_service)):
    """What a visitor may be shown. Each browser filters out what it has dismissed."""
    return await service.list_active()


@router.get("/{popup_id}/image")
async def popup_image(popup_id: PopupId, service: PopupService = Depends(popup_service)):
    image = await service.get_image(popup_id)
    return Response(image.data, media_type=image.content_type, headers={"Cache-Control": _IMAGE_CACHE_CONTROL})


# --- admin ----------------------------------------------------------------------
# The token's admin claim is enough: these touch only this service's own table.


@admin_router.get("", response_model=models.AdminPopupsOut)
async def list_popups(admin: AuthUser = Depends(admin_user), service: PopupService = Depends(popup_service)):
    """Every popup, inactive ones included, newest first."""
    return await service.list_all()


@admin_router.post("", response_model=models.AdminPopupOut, status_code=201)
async def create_popup(
    admin: AuthUser = Depends(admin_user),
    content: models.PopupContent = Depends(popup_content),
    image: bytes | None = Depends(uploaded_image),
    service: PopupService = Depends(popup_service),
):
    return await service.create(admin, content, image)


@admin_router.put("/{popup_id}", response_model=models.AdminPopupOut)
async def update_popup(
    popup_id: PopupId,
    remove_image: Annotated[bool, Form()] = False,
    admin: AuthUser = Depends(admin_user),
    content: models.PopupContent = Depends(popup_content),
    image: bytes | None = Depends(uploaded_image),
    service: PopupService = Depends(popup_service),
):
    """No image in the form keeps the stored one; `remove_image` drops it."""
    return await service.update(popup_id, content, image, remove_image)


@admin_router.delete("/{popup_id}", status_code=204)
async def delete_popup(
    popup_id: PopupId, admin: AuthUser = Depends(admin_user), service: PopupService = Depends(popup_service)
):
    await service.delete(popup_id)
    return Response(status_code=204)
