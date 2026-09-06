from fastapi import APIRouter, Header, Response

from reservation import models, service

router = APIRouter(prefix="/reservations", tags=["Reservations"])

def _token(value: str | None) -> str:
    if not value: from fastapi import HTTPException; raise HTTPException(400, "X-Reservation-Token header required")
    return value

@router.get("", response_model=list[models.ReservationOut])
async def list_reservations():
    """Reservations from now until the next 06:00 KST."""
    return await service.list_reservations()

@router.post("", response_model=models.CreateReservationOut, status_code=201)
async def create_reservation(request: models.CreateReservationRequest):
    reservation, token = await service.create_reservation(**request.model_dump())
    return {"reservation": reservation, "owner_token": token}

@router.get("/{reservation_id}", response_model=models.ReservationOut)
async def get_reservation(reservation_id: int): return await service.get_reservation(reservation_id)

@router.patch("/{reservation_id}", response_model=models.ReservationOut)
async def update_reservation(reservation_id: int, request: models.UpdateReservationRequest, x_reservation_token: str | None = Header(default=None)):
    return await service.update_reservation(reservation_id, _token(x_reservation_token), **request.model_dump(exclude_unset=True))

@router.post("/{reservation_id}/participants", response_model=models.JoinReservationOut, status_code=201)
async def join_reservation(reservation_id: int, request: models.JoinReservationRequest):
    reservation, token = await service.join_reservation(reservation_id, **request.model_dump())
    return {"reservation": reservation, "participant_token": token}

@router.delete("/{reservation_id}/participants/me", response_model=models.ReservationOut)
async def cancel_participation(reservation_id: int, x_reservation_token: str | None = Header(default=None)):
    return await service.cancel_participation(reservation_id, _token(x_reservation_token))

@router.delete("/{reservation_id}", status_code=204)
async def cancel_reservation(reservation_id: int, x_reservation_token: str | None = Header(default=None)):
    await service.cancel_reservation(reservation_id, _token(x_reservation_token))
    return Response(status_code=204)
