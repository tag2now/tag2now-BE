from reservation.adapters.postgresql import PostgresReservationRepository
from reservation import service
from reservation.ports import ReservationRepository

_repo: ReservationRepository | None = None

async def init_db() -> None:
    global _repo
    _repo = PostgresReservationRepository()
    await _repo.init()
    service.configure(_repo)

async def close_db() -> None:
    global _repo
    if _repo: await _repo.close(); _repo = None
