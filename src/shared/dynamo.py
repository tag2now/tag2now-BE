"""Shared DynamoDB table connection lifecycle."""

import logging
from collections.abc import Awaitable, Callable

import aioboto3
from botocore.exceptions import ClientError

from shared.settings import get_settings

logger = logging.getLogger(__name__)


class DynamoTableConnection:
    """Manages an aioboto3 DynamoDB session, resource, and table reference.

    AWS region, endpoint, and credentials are read from shared settings.
    Only the *table_name* varies per consumer.
    """

    def __init__(self, table_name: str):
        self._table_name = table_name
        self._session: aioboto3.Session | None = None
        self._resource_ctx = None
        self._resource = None
        self._table = None

    @property
    def table(self):
        if self._table is None:
            raise RuntimeError("DynamoTableConnection not initialized")
        return self._table

    async def init(
        self,
        *,
        create_table_fn: Callable[..., Awaitable] | None = None,
    ) -> None:
        """Set up session, resource, and load the table.

        If ``table.load()`` raises ``ResourceNotFoundException`` and
        *create_table_fn* is provided, it is called with ``(resource, table_name)``
        and must return the new table reference.  Otherwise the error is re-raised.
        """
        settings = get_settings()
        session_kwargs = {}
        if settings.aws_access_key_id:
            session_kwargs["aws_access_key_id"] = settings.aws_access_key_id
        if settings.aws_secret_access_key:
            session_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        self._session = aioboto3.Session(**session_kwargs)

        kwargs = {"region_name": settings.dynamodb_region}
        if settings.dynamodb_endpoint_url:
            kwargs["endpoint_url"] = settings.dynamodb_endpoint_url
        self._resource_ctx = self._session.resource("dynamodb", **kwargs)
        self._resource = await self._resource_ctx.__aenter__()

        try:
            self._table = await self._resource.Table(self._table_name)
            await self._table.load()
        except ClientError as e:
            if (
                e.response["Error"]["Code"] == "ResourceNotFoundException"
                and create_table_fn is not None
            ):
                self._table = await create_table_fn(self._resource, self._table_name)
            else:
                raise

    async def close(self) -> None:
        if self._resource_ctx:
            await self._resource_ctx.__aexit__(None, None, None)
            self._resource_ctx = None
            self._resource = None
            self._table = None
            self._session = None
