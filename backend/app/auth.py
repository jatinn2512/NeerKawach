"""Development-only mock authentication.

This module deliberately does not authenticate real users. It maps the
``X-Mock-Role`` request header to a small demo identity so routers can exercise
authorization boundaries until production authentication is added later.
"""

from typing import Annotated, Callable

from fastapi import Depends, Header, HTTPException, status

from app.schemas import MockUser

MOCK_ROLES = {"admin", "operator", "viewer"}


def get_current_user(
    mock_role: Annotated[str, Header(alias="X-Mock-Role")] = "viewer",
) -> MockUser:
    """Build a demo user from ``X-Mock-Role``; never use this in production."""

    role = mock_role.strip().lower()
    if role not in MOCK_ROLES:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid mock role. Use admin, operator, or viewer.",
        )
    return MockUser(username=f"demo-{role}", role=role)  # type: ignore[arg-type]


def require_roles(*allowed_roles: str) -> Callable:
    """Return a dependency that restricts an endpoint to mock roles."""

    def dependency(user: Annotated[MockUser, Depends(get_current_user)]) -> MockUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Mock role '{user.role}' is not allowed for this endpoint.",
            )
        return user

    return dependency
