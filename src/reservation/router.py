from fastapi import APIRouter, Depends, Response

from auth.dependencies import current_user
from auth.models import AuthUser
from reservation import models, service

router = APIRouter(prefix="/reservations", tags=["Reservations"])

@router.get("", response_model=list[models.ReservationOut])
async def list_reservations():
    """Reservations from now until the next 06:00 KST."""
    return await service.list_reservations()

@router.post("", response_model=models.ReservationOut, status_code=201)
async def create_reservation(request: models.CreateReservationRequest, user: AuthUser = Depends(current_user)):
    return await service.create_reservation(subject=user.username, display_name=user.online_name, **request.model_dump())

@router.get("/{reservation_id}", response_model=models.ReservationOut)
async def get_reservation(reservation_id: int): return await service.get_reservation(reservation_id)

@router.patch("/{reservation_id}", response_model=models.ReservationOut)
async def update_reservation(reservation_id: int, request: models.UpdateReservationRequest, user: AuthUser = Depends(current_user)):
    return await service.update_reservation(reservation_id, user.username, **request.model_dump(exclude_unset=True))

@router.post("/{reservation_id}/participants", response_model=models.ReservationOut, status_code=201)
async def join_reservation(reservation_id: int, request: models.JoinReservationRequest, user: AuthUser = Depends(current_user)):
    return await service.join_reservation(reservation_id, subject=user.username, display_name=user.online_name, **request.model_dump())

@router.delete("/{reservation_id}/participants/me", response_model=models.ReservationOut)
async def cancel_participation(reservation_id: int, user: AuthUser = Depends(current_user)):
    return await service.cancel_participation(reservation_id, user.username)

@router.get("/{reservation_id}/comments", response_model=list[models.CommentOut])
async def list_comments(reservation_id: int):
    return await service.list_comments(reservation_id)

@router.post("/{reservation_id}/comments", response_model=models.CommentOut, status_code=201)
async def add_comment(reservation_id: int, request: models.CreateCommentRequest, user: AuthUser = Depends(current_user)):
    return await service.add_comment(reservation_id, subject=user.username, display_name=user.online_name, **request.model_dump())

@router.delete("/{reservation_id}/comments/{comment_id}", status_code=204)
async def delete_comment(reservation_id: int, comment_id: int, user: AuthUser = Depends(current_user)):
    await service.delete_comment(reservation_id, comment_id, user.username)
    return Response(status_code=204)

@router.delete("/{reservation_id}", status_code=204)
async def cancel_reservation(reservation_id: int, user: AuthUser = Depends(current_user)):
    await service.cancel_reservation(reservation_id, user.username)
    return Response(status_code=204)
