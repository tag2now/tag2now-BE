"""FastAPI dependencies for the community board."""

from fastapi import Request

from community.service import CommunityService


def community_service(request: Request) -> CommunityService:
    return request.app.state.container.community
