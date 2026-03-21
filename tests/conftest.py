"""
Shared test fixtures and mock helpers for the InternToJob middleware test suite.

Strategy:
  - Set fake Supabase env vars before app import to avoid network calls.
  - `mock_auth` monkeypatches middleware.auth._get_user_from_token and
    _get_profile so every route test starts as an authenticated company_admin
    without hitting Supabase.
  - Each test patches `app.routes.<module>.supabase` (the imported name in
    the route file) using unittest.mock.patch or monkeypatch.setattr to
    control what Supabase returns.
"""

import os
import pytest
from unittest.mock import MagicMock

# Must be set before the app is imported so supabase_client.py doesn't crash.
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")

from app import create_app  # noqa: E402 — import after env vars are set

# ---------------------------------------------------------------------------
# Shared UUIDs used across all test modules
# ---------------------------------------------------------------------------

MOCK_USER_ID = "11111111-1111-1111-1111-111111111111"
MOCK_COMPANY_ID = "22222222-2222-2222-2222-222222222222"
MOCK_JOB_ID = "33333333-3333-3333-3333-333333333333"
MOCK_APP_ID = "44444444-4444-4444-4444-444444444444"
MOCK_STUDENT_ID = "55555555-5555-5555-5555-555555555555"
MOCK_RUN_ID = "66666666-6666-6666-6666-666666666666"
MOCK_ADMIN_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
MOCK_UNIVERSITY_ID = "77777777-7777-7777-7777-777777777777"
MOCK_FLAG_ID = "88888888-8888-8888-8888-888888888888"
MOCK_EXPORT_ID = "99999999-9999-9999-9999-999999999999"
MOCK_TARGET_USER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


# ---------------------------------------------------------------------------
# Flask app + test client
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def app():
    return create_app({"TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer valid-test-token-abc123"}


# ---------------------------------------------------------------------------
# Auth bypass
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_auth(monkeypatch):
    """
    Bypass the auth middleware for company_admin tests.

    Patches _get_user_from_token → returns a mock User object.
    Patches _get_profile         → returns a company_admin profile dict.

    Both are module-level names inside app.middleware.auth, so the decorator
    (which calls them at request time via their module globals) will use the
    patched versions.
    """
    import app.middleware.auth as auth_module

    mock_user = MagicMock()
    mock_user.id = MOCK_USER_ID
    mock_user.email = "admin@sony.com"
    mock_user.user_metadata = {}

    monkeypatch.setattr(auth_module, "_get_user_from_token", lambda token: mock_user)
    monkeypatch.setattr(
        auth_module,
        "_get_profile",
        lambda uid: {"full_name": "Sato Kenji", "role": "company_admin", "avatar_url": None},
    )
    return mock_user


@pytest.fixture
def mock_auth_recruiter(monkeypatch):
    """Auth bypass for recruiter role tests."""
    import app.middleware.auth as auth_module

    mock_user = MagicMock()
    mock_user.id = MOCK_USER_ID
    mock_user.email = "recruiter@sony.com"
    mock_user.user_metadata = {}

    monkeypatch.setattr(auth_module, "_get_user_from_token", lambda token: mock_user)
    monkeypatch.setattr(
        auth_module,
        "_get_profile",
        lambda uid: {"full_name": "Recruiter San", "role": "recruiter", "avatar_url": None},
    )
    return mock_user


@pytest.fixture
def mock_auth_admin(monkeypatch):
    """Auth bypass for platform admin role tests."""
    import app.middleware.auth as auth_module

    mock_user = MagicMock()
    mock_user.id = MOCK_ADMIN_ID
    mock_user.email = "admin@intern2job.com"
    mock_user.user_metadata = {}

    monkeypatch.setattr(auth_module, "_get_user_from_token", lambda token: mock_user)
    monkeypatch.setattr(
        auth_module,
        "_get_profile",
        lambda uid: {"full_name": "Platform Admin", "role": "admin", "avatar_url": None},
    )
    return mock_user


# ---------------------------------------------------------------------------
# Supabase mock builder helpers
# ---------------------------------------------------------------------------

def make_supabase_mock():
    """Return a fresh MagicMock that mimics the Supabase client interface."""
    return MagicMock()


def recruiter_table_mock(mock_sb, company_id=MOCK_COMPANY_ID):
    """
    Configure mock_sb.table("recruiters") to return a recruiter row with company_id.
    Returns the configured mock for further chaining if needed.
    """
    recruiter_res = MagicMock()
    recruiter_res.data = {"company_id": company_id}

    def _table(name):
        m = MagicMock()
        if name == "recruiters":
            m.select.return_value.eq.return_value.single.return_value.execute.return_value = recruiter_res
        return m

    mock_sb.table.side_effect = _table
    return mock_sb


def table_side_effect(responses: dict):
    """
    Build a side_effect function for mock_sb.table() that routes to
    per-table MagicMocks configured from `responses` dict.

    responses = {
        "recruiters": <MagicMock with .data already set>,
        "companies":  <MagicMock with .data already set>,
    }

    Each value should be a fully configured chain mock whose .execute() result
    is set. Alternatively, pass a dict like {"data": {...}} and this helper
    wraps it.
    """
    def _table(name):
        mock = MagicMock()
        resp = responses.get(name, MagicMock())
        # If caller passed a plain dict, wrap it
        if isinstance(resp, dict):
            execute_result = MagicMock()
            execute_result.data = resp.get("data")
            execute_result.count = resp.get("count")
            mock.select.return_value.eq.return_value.single.return_value.execute.return_value = execute_result
            mock.select.return_value.eq.return_value.execute.return_value = execute_result
            mock.select.return_value.in_.return_value.execute.return_value = execute_result
            mock.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value = execute_result
            mock.select.return_value.eq.return_value.in_.return_value.execute.return_value = execute_result
            mock.update.return_value.eq.return_value.execute.return_value = execute_result
            mock.insert.return_value.execute.return_value = execute_result
            mock.upsert.return_value.execute.return_value = execute_result
        else:
            mock = resp
        return mock

    return _table


# ---------------------------------------------------------------------------
# Sample fixture data
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_company():
    return {
        "id": MOCK_COMPANY_ID,
        "name": "Sony Group Corporation",
        "name_jp": "ソニーグループ株式会社",
        "tagline": "Inspiring the world with creativity and technology",
        "logo_url": None,
        "website": "https://www.sony.com",
        "industry": "Technology & Electronics",
        "size": "10,000+ employees",
        "location": "Tokyo, Japan",
        "description": "A leading tech company.",
        "mission": "Fill the world with emotion.",
        "culture": "Innovation meets creativity.",
        "values": ["Innovation", "Creativity"],
        "benefits": ["Health insurance", "Remote work"],
        "founded_year": 1946,
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-01T00:00:00+00:00",
    }


@pytest.fixture
def sample_job():
    return {
        "id": MOCK_JOB_ID,
        "company_id": MOCK_COMPANY_ID,
        "recruiter_id": MOCK_USER_ID,
        "title": "Senior AI Research Engineer",
        "department": "R&D Division - AI Lab",
        "description": "Work on cutting-edge AI research.",
        "responsibilities": ["Conduct AI research", "Publish papers"],
        "qualifications": ["PhD in CS", "5+ years ML experience"],
        "skills": ["Python", "PyTorch", "NLP"],
        "requirements": ["Strong math background"],
        "location": "Tokyo, Japan",
        "is_remote": False,
        "salary_min": 8000000,
        "salary_max": 12000000,
        "status": "published",
        "deadline": "2026-06-30",
        "priority": "high",
        "ai_matching_enabled": True,
        "openings": 2,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }


@pytest.fixture
def sample_application():
    return {
        "id": MOCK_APP_ID,
        "job_id": MOCK_JOB_ID,
        "student_id": MOCK_STUDENT_ID,
        "status": "pending",
        "ai_score": 87.5,
        "cover_letter": "I am excited to apply...",
        "note": None,
        "created_at": "2026-02-01T00:00:00+00:00",
        "updated_at": "2026-02-01T00:00:00+00:00",
    }
