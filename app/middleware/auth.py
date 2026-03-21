"""
Authentication middleware for the InternToJob middleware API.

Provides:
  - require_auth   — validates Bearer token, sets flask.g fields
  - require_role   — require_auth + role allowlist check

After decoration flask.g has:
  g.user_id    : str  — Supabase auth user id
  g.user_email : str
  g.user_role  : str  — value from profiles.role column
  g.profile    : dict — full profiles row
"""

from functools import wraps
from flask import request, jsonify, g
from ..services.supabase_client import supabase


# ---------------------------------------------------------------------------
# Internal helpers (extracted so tests can monkeypatch them independently)
# ---------------------------------------------------------------------------

def _get_token() -> str | None:
    """Extract Bearer token from the Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header.split(" ", 1)[1].strip()


def _get_user_from_token(token: str):
    """Validate token with Supabase and return the user object, or None."""
    try:
        response = supabase.auth.get_user(token)
        return response.user
    except Exception:
        return None


def _get_profile(user_id: str) -> dict:
    """Fetch the profiles row for a user. Returns {} on any error."""
    try:
        res = (
            supabase.table("profiles")
            .select("full_name, role, avatar_url, university_id")
            .eq("id", user_id)
            .single()
            .execute()
        )
        return res.data or {}
    except Exception:
        return {}


# Map DB role values to logical role names used in route guards.
# The DB enum uses "super_admin" but route decorators check for "admin".
_ROLE_ALIASES = {
    "super_admin": "admin",
}


def _normalize_role(role: str) -> str:
    """Return the canonical role name, resolving any DB aliases."""
    return _ROLE_ALIASES.get(role, role)


def _err(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def require_auth(f):
    """Validate Bearer token and populate flask.g. Returns 401 on failure."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = _get_token()
        if not token:
            return _err("UNAUTHORIZED", "Missing or malformed Authorization header", 401)

        user = _get_user_from_token(token)
        if not user:
            return _err("UNAUTHORIZED", "Invalid or expired token", 401)

        profile = _get_profile(user.id)

        g.user_id = user.id
        g.user_email = user.email
        g.user_role = _normalize_role(profile.get("role") or user.user_metadata.get("role", "student"))
        g.profile = profile

        return f(*args, **kwargs)
    return decorated


def require_role(roles: list[str]):
    """
    Decorator factory. Validates auth AND checks that g.user_role is in roles.

    Usage:
        @require_role(["company_admin"])
        def my_view(): ...
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            token = _get_token()
            if not token:
                return _err("UNAUTHORIZED", "Missing or malformed Authorization header", 401)

            user = _get_user_from_token(token)
            if not user:
                return _err("UNAUTHORIZED", "Invalid or expired token", 401)

            profile = _get_profile(user.id)

            g.user_id = user.id
            g.user_email = user.email
            g.user_role = _normalize_role(profile.get("role") or user.user_metadata.get("role", "student"))
            g.profile = profile

            if g.user_role not in roles:
                return _err(
                    "FORBIDDEN",
                    f"Role '{g.user_role}' is not allowed for this endpoint. Required: {roles}",
                    403,
                )

            return f(*args, **kwargs)
        return decorated
    return decorator
