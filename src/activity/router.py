"""FastAPI router for activity endpoints."""

from fastapi import APIRouter

from activity import service
from matching.models import TTT2_COM_ID

router = APIRouter(tags=["Activity"])


@router.get("/stats/activity", summary="Hourly player activity (KST)")
async def stats_activity():
    """Return average player count per KST hour (0-23) over the last 7 days."""
    return await service.get_global_activity(TTT2_COM_ID)
