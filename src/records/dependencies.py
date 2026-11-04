"""FastAPI dependencies for match records."""

from fastapi import Request

from records.service import RecordsService


def records_service(request: Request) -> RecordsService:
    return request.app.state.container.records
