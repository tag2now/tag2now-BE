from fastapi import APIRouter, Depends

from auth import models, service
from auth.dependencies import current_user

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=models.LoginOut)
async def login(request: models.LoginRequest):
    """Verify an RPCN account and issue an access token.

    There is no logout route: the token is stateless, so signing out is the
    client discarding it.
    """
    token, expires_in, user = await service.login(request.username, request.password)
    return {"access_token": token, "expires_in": expires_in, "user": user}


@router.get("/me", response_model=models.AuthUser)
async def me(user: models.AuthUser = Depends(current_user)):
    return user
