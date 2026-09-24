def signed_in(username: str) -> dict[str, str]:
    """Authorization headers for an RPCN account, signed with the test key.

    A plain function rather than a fixture, because these modules build their
    headers once at import. tests/conftest.py has set JWT_SECRET by then.
    """
    from auth.models import AuthUser
    from auth.tokens import issue_token

    token, _ = issue_token(AuthUser(username=username, online_name=username))
    return {"Authorization": f"Bearer {token}"}
