"""FastAPI dependencies for reservations."""

from fastapi import Request

from reservation.service import ReservationService


def reservation_service(request: Request) -> ReservationService:
    return request.app.state.container.reservations
