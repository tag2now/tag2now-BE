from reservation.adapters.postgresql import PostgresReservationRepository
from reservation import service
from reservation.ports import ReservationRepository
from shared.settings import get_settings

_repo: ReservationRepository | None = None

async def init_db() -> None:
    global _repo
    settings = get_settings()
    if settings.db_type != "postgresql": raise ValueError("Reservations require PostgreSQL")
    _repo = PostgresReservationRepository(settings.db_url)
    await _repo.init()
    service.configure(_repo)

async def close_db() -> None:
    global _repo
    if _repo: await _repo.close(); _repo = None
