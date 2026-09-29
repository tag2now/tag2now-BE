"""The admin gate routers depend on."""

from fastapi import Depends

from admin.exceptions import NotAdminError
from auth.dependencies import current_user
from auth.models import AuthUser


def admin_user(user: AuthUser = Depends(current_user)) -> AuthUser:
    """The signed-in admin, or 403.

    Only a first filter: the claim can be up to a token's lifetime old, so RPCN
    checks the role again, with the password, on every action.
    """
    if not user.admin:
        raise NotAdminError("관리자 권한이 없습니다.")
    return user
