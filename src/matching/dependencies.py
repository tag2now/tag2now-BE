"""FastAPI dependencies for live rooms and the leaderboard."""

from fastapi import Request

from matching.service import MatchingService


def matching_service(request: Request) -> MatchingService:
    return request.app.state.container.matching
