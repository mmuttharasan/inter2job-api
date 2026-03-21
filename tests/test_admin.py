"""
Unit tests for Platform Admin API — /api/admin/* and /api/platform/*

Coverage (22 API endpoints, 60+ test cases):
  §1 Platform Stats & Dashboard
  §2 User Management (list, detail, suspend, role change, delete)
  §3 Company & University Approval
  §4 Content Moderation (flags)
  §5 AI Matching Configuration
  §6 Platform Analytics
  §7 Data Export
  §8 Audit Log
  Auth Guards (401/403)

Auth bypassed via mock_auth_admin fixture (conftest.py).
Supabase fully mocked per-test via monkeypatch.
"""

import pytest
from unittest.mock import MagicMock
from tests.conftest import (
    MOCK_ADMIN_ID, MOCK_USER_ID, MOCK_COMPANY_ID,
    MOCK_UNIVERSITY_ID, MOCK_FLAG_ID, MOCK_EXPORT_ID,
    MOCK_TARGET_USER_ID,
)


# ---------------------------------------------------------------------------
# Helper: Build a configurable Supabase mock for admin routes
# ---------------------------------------------------------------------------

class _FluentChain:
    """
    A fully-chainable mock that returns itself for any query-building calls
    (eq, ilike, gte, lte, order, range, limit, in_, neq, etc.) and resolves
    data only when .execute() or .single().execute() is called.
    """

    def __init__(self, data, count):
        self._data = data
        self._count = count

    def __getattr__(self, name):
        if name == "execute":
            return self._execute
        if name == "single":
            return self._single
        # All other chaining methods return a callable that returns self
        return lambda *a, **kw: self

    def _execute(self):
        result = MagicMock()
        result.data = self._data
        result.count = self._count
        return result

    def _single(self):
        return self  # .single().execute() still works


def _mock_admin_supabase(monkeypatch, table_responses: dict):
    """
    Patch app.services.admin_service.supabase with a mock that routes
    by table name and supports arbitrary query chaining.

    table_responses = {
        "table_name": {
            "select_single": <data>,       # .select()...single().execute().data
            "select_many": <list>,         # .select()...execute().data
            "select_count": <int>,         # .execute().count
            "update": <data>,              # .update()...execute().data
            "insert": <data>,              # .insert().execute().data
            "delete": <data>,              # .delete()...execute().data
            "upsert": <data>,              # .upsert()...execute().data
        }
    }
    """
    import app.services.admin_service as admin_svc_module

    def _table(name):
        config = table_responses.get(name, {})
        data = (
            config.get("select_single")
            or config.get("select_many")
            or config.get("update")
            or config.get("insert")
            or config.get("delete")
            or config.get("upsert")
            or []
        )
        count = config.get(
            "select_count",
            len(data) if isinstance(data, list) else (0 if data is None else 1),
        )

        chain = _FluentChain(data, count)

        # Wrap in an outer MagicMock so .table(name).select / .update / etc. work
        m = MagicMock()
        m.select = lambda *a, **kw: chain
        m.update = lambda *a, **kw: chain
        m.insert = lambda *a, **kw: chain
        m.delete = lambda *a, **kw: chain
        m.upsert = lambda *a, **kw: chain
        return m

    mock_sb = MagicMock()
    mock_sb.table.side_effect = _table
    monkeypatch.setattr(admin_svc_module, "supabase", mock_sb)
    return mock_sb


# ===========================================================================
# §1  Platform Statistics
# ===========================================================================

class TestPlatformStats:

    def test_public_stats_no_auth_required(self, client, monkeypatch):
        """GET /api/platform/stats requires no auth."""
        import app.services.admin_service as svc
        # Clear cache
        svc._STATS_CACHE = {}
        _mock_admin_supabase(monkeypatch, {
            "profiles": {"select_count": 100},
            "companies": {"select_count": 50},
            "universities": {"select_count": 20},
            "applications": {"select_count": 10},
        })
        resp = client.get("/api/platform/stats")
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert "verified_students" in data
        assert "partner_companies" in data
        assert "partner_universities" in data
        assert "successful_placements" in data
        assert "last_updated" in data

    def test_stats_returns_cached_data(self, client, monkeypatch):
        """Stats should use cache within TTL."""
        import app.services.admin_service as svc
        from datetime import datetime, timedelta, timezone

        cached_data = {
            "verified_students": 999,
            "partner_companies": 888,
            "partner_universities": 777,
            "successful_placements": 666,
            "last_updated": "2026-01-01T00:00:00Z",
        }
        svc._STATS_CACHE = {
            "data": cached_data,
            "expires_at": datetime.now(tz=timezone.utc) + timedelta(hours=1),
        }
        resp = client.get("/api/platform/stats")
        assert resp.status_code == 200
        assert resp.get_json()["data"]["verified_students"] == 999
        # Clear cache for other tests
        svc._STATS_CACHE = {}


# ===========================================================================
# §1  Admin Dashboard
# ===========================================================================

class TestAdminDashboard:

    def test_dashboard_success(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "profiles": {
                "select_many": [
                    {"id": "1", "role": "student", "created_at": "2026-03-01T00:00:00Z"},
                    {"id": "2", "role": "admin", "created_at": "2026-03-01T00:00:00Z"},
                ],
            },
            "jobs": {"select_many": [{"id": "j1", "status": "published"}, {"id": "j2", "status": "draft"}]},
            "applications": {"select_count": 42},
            "content_flags": {"select_count": 3},
            "companies": {"select_count": 5},
        })
        resp = client.get("/api/admin/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert "users" in data
        assert "content" in data
        assert "system" in data
        assert "growth" in data
        assert data["users"]["total"] == 2
        assert data["content"]["active_jobs"] == 1
        assert data["content"]["draft_jobs"] == 1

    def test_dashboard_forbidden_for_student(self, client, auth_headers, monkeypatch):
        import app.middleware.auth as auth_module
        mock_user = MagicMock()
        mock_user.id = MOCK_USER_ID
        mock_user.user_metadata = {}
        monkeypatch.setattr(auth_module, "_get_user_from_token", lambda t: mock_user)
        monkeypatch.setattr(auth_module, "_get_profile", lambda uid: {"role": "student"})
        resp = client.get("/api/admin/dashboard", headers=auth_headers)
        assert resp.status_code == 403

    def test_dashboard_unauthorized_without_token(self, client):
        resp = client.get("/api/admin/dashboard")
        assert resp.status_code == 401


# ===========================================================================
# §2  User Management — List Users
# ===========================================================================

class TestListUsers:

    def test_list_users_default(self, client, auth_headers, mock_auth_admin, monkeypatch):
        users = [
            {"id": "u1", "full_name": "User One", "role": "student", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "u2", "full_name": "User Two", "role": "recruiter", "created_at": "2026-01-02T00:00:00Z"},
        ]
        _mock_admin_supabase(monkeypatch, {
            "profiles": {"select_many": users, "select_count": 2},
        })
        resp = client.get("/api/admin/users", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.get_json()
        assert "data" in body
        assert "meta" in body

    def test_list_users_with_role_filter(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "profiles": {"select_many": [{"id": "u1", "role": "student"}], "select_count": 1},
        })
        resp = client.get("/api/admin/users?role=student", headers=auth_headers)
        assert resp.status_code == 200

    def test_list_users_with_search(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "profiles": {"select_many": [], "select_count": 0},
        })
        resp = client.get("/api/admin/users?search=yoshida", headers=auth_headers)
        assert resp.status_code == 200

    def test_list_users_with_pagination(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "profiles": {"select_many": [], "select_count": 100},
        })
        resp = client.get("/api/admin/users?page=2&limit=10", headers=auth_headers)
        assert resp.status_code == 200

    def test_list_users_with_status_filter(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "profiles": {"select_many": [], "select_count": 0},
        })
        resp = client.get("/api/admin/users?status=suspended", headers=auth_headers)
        assert resp.status_code == 200


# ===========================================================================
# §2  User Management — Get User Detail
# ===========================================================================

class TestGetUserDetail:

    def test_get_user_success(self, client, auth_headers, mock_auth_admin, monkeypatch):
        user_data = {
            "id": MOCK_TARGET_USER_ID,
            "full_name": "Aiko Yamada",
            "role": "student",
            "created_at": "2026-01-01T00:00:00Z",
        }
        _mock_admin_supabase(monkeypatch, {
            "profiles": {"select_single": user_data},
        })
        resp = client.get(f"/api/admin/users/{MOCK_TARGET_USER_ID}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["data"]["full_name"] == "Aiko Yamada"

    def test_get_user_not_found(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "profiles": {"select_single": None},
        })
        resp = client.get("/api/admin/users/nonexistent-id", headers=auth_headers)
        assert resp.status_code == 404
        assert resp.get_json()["error"]["code"] == "NOT_FOUND"


# ===========================================================================
# §2  User Management — Suspend / Reactivate
# ===========================================================================

class TestUpdateUserStatus:

    def test_suspend_user_success(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "profiles": {
                "select_single": {"id": MOCK_TARGET_USER_ID, "role": "student", "status": "active"},
                "update": [{"id": MOCK_TARGET_USER_ID, "status": "suspended"}],
            },
            "admin_audit_log": {"insert": [{}]},
        })
        payload = {"status": "suspended", "reason": "ToS violation", "notify_user": True}
        resp = client.patch(f"/api/admin/users/{MOCK_TARGET_USER_ID}/status", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["status"] == "suspended"
        assert data["user_id"] == MOCK_TARGET_USER_ID

    def test_reactivate_user_success(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "profiles": {
                "select_single": {"id": MOCK_TARGET_USER_ID, "role": "student", "status": "suspended"},
                "update": [{"id": MOCK_TARGET_USER_ID, "status": "active"}],
            },
            "admin_audit_log": {"insert": [{}]},
        })
        payload = {"status": "active", "reason": "Reviewed and cleared"}
        resp = client.patch(f"/api/admin/users/{MOCK_TARGET_USER_ID}/status", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["data"]["status"] == "active"

    def test_cannot_suspend_admin(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "profiles": {"select_single": {"id": "other-admin", "role": "admin", "status": "active"}},
        })
        payload = {"status": "suspended", "reason": "Test"}
        resp = client.patch("/api/admin/users/other-admin/status", json=payload, headers=auth_headers)
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "CANNOT_SUSPEND_ADMIN"

    def test_already_suspended_returns_422(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "profiles": {"select_single": {"id": MOCK_TARGET_USER_ID, "role": "student", "status": "suspended"}},
        })
        payload = {"status": "suspended", "reason": "Again"}
        resp = client.patch(f"/api/admin/users/{MOCK_TARGET_USER_ID}/status", json=payload, headers=auth_headers)
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "ALREADY_SUSPENDED"

    def test_missing_status_field_returns_400(self, client, auth_headers, mock_auth_admin):
        payload = {"reason": "No status provided"}
        resp = client.patch(f"/api/admin/users/{MOCK_TARGET_USER_ID}/status", json=payload, headers=auth_headers)
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "MISSING_FIELDS"

    def test_missing_reason_field_returns_400(self, client, auth_headers, mock_auth_admin):
        payload = {"status": "suspended"}
        resp = client.patch(f"/api/admin/users/{MOCK_TARGET_USER_ID}/status", json=payload, headers=auth_headers)
        assert resp.status_code == 400

    def test_invalid_status_returns_400(self, client, auth_headers, mock_auth_admin):
        payload = {"status": "invalid", "reason": "Test"}
        resp = client.patch(f"/api/admin/users/{MOCK_TARGET_USER_ID}/status", json=payload, headers=auth_headers)
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "INVALID_STATUS"


# ===========================================================================
# §2  User Management — Change Role
# ===========================================================================

class TestUpdateUserRole:

    def test_role_change_success(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "profiles": {
                "select_single": {"id": MOCK_TARGET_USER_ID, "role": "student"},
                "update": [{"id": MOCK_TARGET_USER_ID, "role": "recruiter"}],
            },
            "admin_audit_log": {"insert": [{}]},
        })
        payload = {"role": "recruiter", "reason": "Promoted"}
        resp = client.patch(f"/api/admin/users/{MOCK_TARGET_USER_ID}/role", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["old_role"] == "student"
        assert data["new_role"] == "recruiter"

    def test_invalid_role_returns_400(self, client, auth_headers, mock_auth_admin):
        payload = {"role": "superadmin", "reason": "Test"}
        resp = client.patch(f"/api/admin/users/{MOCK_TARGET_USER_ID}/role", json=payload, headers=auth_headers)
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "INVALID_ROLE"

    def test_missing_role_returns_400(self, client, auth_headers, mock_auth_admin):
        payload = {"reason": "No role"}
        resp = client.patch(f"/api/admin/users/{MOCK_TARGET_USER_ID}/role", json=payload, headers=auth_headers)
        assert resp.status_code == 400

    def test_missing_reason_returns_400(self, client, auth_headers, mock_auth_admin):
        payload = {"role": "recruiter"}
        resp = client.patch(f"/api/admin/users/{MOCK_TARGET_USER_ID}/role", json=payload, headers=auth_headers)
        assert resp.status_code == 400

    def test_user_not_found(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "profiles": {"select_single": None},
        })
        payload = {"role": "recruiter", "reason": "Test"}
        resp = client.patch("/api/admin/users/nonexistent/role", json=payload, headers=auth_headers)
        assert resp.status_code == 404


# ===========================================================================
# §2  User Management — Delete User
# ===========================================================================

class TestDeleteUser:

    def test_soft_delete_success(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "profiles": {
                "select_single": {"id": MOCK_TARGET_USER_ID, "role": "student"},
                "update": [{"id": MOCK_TARGET_USER_ID, "status": "deleted"}],
            },
            "admin_audit_log": {"insert": [{}]},
        })
        resp = client.delete(f"/api/admin/users/{MOCK_TARGET_USER_ID}", headers=auth_headers)
        assert resp.status_code == 204

    def test_hard_delete_success(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "profiles": {
                "select_single": {"id": MOCK_TARGET_USER_ID, "role": "student"},
                "delete": [{"id": MOCK_TARGET_USER_ID}],
            },
            "admin_audit_log": {"insert": [{}]},
        })
        resp = client.delete(f"/api/admin/users/{MOCK_TARGET_USER_ID}?permanent=true", headers=auth_headers)
        assert resp.status_code == 204

    def test_cannot_delete_admin(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "profiles": {
                "select_single": {"id": "other-admin", "role": "admin"},
                "select_count": 5,
            },
        })
        resp = client.delete("/api/admin/users/other-admin", headers=auth_headers)
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "CANNOT_DELETE_ADMIN"

    def test_user_not_found(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "profiles": {"select_single": None},
        })
        resp = client.delete("/api/admin/users/nonexistent", headers=auth_headers)
        assert resp.status_code == 404


# ===========================================================================
# §3  Company Approval
# ===========================================================================

class TestPendingCompanies:

    def test_list_pending_companies(self, client, auth_headers, mock_auth_admin, monkeypatch):
        pending = [
            {"id": MOCK_COMPANY_ID, "name": "NewTech Corp", "status": "pending"},
        ]
        _mock_admin_supabase(monkeypatch, {
            "companies": {"select_many": pending},
        })
        resp = client.get("/api/admin/companies/pending", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.get_json()["data"], list)

    def test_list_pending_empty(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {"companies": {"select_many": []}})
        resp = client.get("/api/admin/companies/pending", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["data"] == []


class TestApproveCompany:

    def test_approve_success(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "companies": {
                "select_single": {"id": MOCK_COMPANY_ID, "status": "pending", "name": "NewTech"},
                "update": [{"id": MOCK_COMPANY_ID, "status": "approved"}],
            },
            "admin_audit_log": {"insert": [{}]},
        })
        resp = client.post(
            f"/api/admin/companies/{MOCK_COMPANY_ID}/approve",
            json={"note": "Verified docs"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["status"] == "approved"

    def test_already_approved_returns_422(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "companies": {"select_single": {"id": MOCK_COMPANY_ID, "status": "approved", "name": "OldCo"}},
        })
        resp = client.post(
            f"/api/admin/companies/{MOCK_COMPANY_ID}/approve",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "ALREADY_APPROVED"


class TestRejectCompany:

    def test_reject_success(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "companies": {
                "select_single": {"id": MOCK_COMPANY_ID, "status": "pending", "name": "BadCo"},
                "update": [{"id": MOCK_COMPANY_ID, "status": "rejected"}],
            },
            "admin_audit_log": {"insert": [{}]},
        })
        resp = client.post(
            f"/api/admin/companies/{MOCK_COMPANY_ID}/reject",
            json={"reason": "Incomplete docs", "note": "Resubmit please"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["status"] == "rejected"

    def test_reject_missing_reason_returns_400(self, client, auth_headers, mock_auth_admin):
        resp = client.post(
            f"/api/admin/companies/{MOCK_COMPANY_ID}/reject",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "MISSING_FIELDS"


# ===========================================================================
# §3  University Approval
# ===========================================================================

class TestPendingUniversities:

    def test_list_pending_universities(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "universities": {"select_many": [{"id": MOCK_UNIVERSITY_ID, "name": "Tokyo U", "status": "pending"}]},
        })
        resp = client.get("/api/admin/universities/pending", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.get_json()["data"], list)


class TestApproveUniversity:

    def test_approve_success(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "universities": {
                "select_single": {"id": MOCK_UNIVERSITY_ID, "status": "pending", "name": "Tokyo U"},
                "update": [{"id": MOCK_UNIVERSITY_ID, "status": "approved"}],
            },
            "admin_audit_log": {"insert": [{}]},
        })
        resp = client.post(
            f"/api/admin/universities/{MOCK_UNIVERSITY_ID}/approve",
            json={"note": "Verified"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["status"] == "approved"

    def test_already_approved_returns_422(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "universities": {"select_single": {"id": MOCK_UNIVERSITY_ID, "status": "approved", "name": "Tokyo U"}},
        })
        resp = client.post(
            f"/api/admin/universities/{MOCK_UNIVERSITY_ID}/approve",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 422


class TestRejectUniversity:

    def test_reject_success(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "universities": {
                "select_single": {"id": MOCK_UNIVERSITY_ID, "status": "pending", "name": "FakeU"},
                "update": [{"id": MOCK_UNIVERSITY_ID, "status": "rejected"}],
            },
            "admin_audit_log": {"insert": [{}]},
        })
        resp = client.post(
            f"/api/admin/universities/{MOCK_UNIVERSITY_ID}/reject",
            json={"reason": "Not accredited"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_reject_missing_reason_returns_400(self, client, auth_headers, mock_auth_admin):
        resp = client.post(
            f"/api/admin/universities/{MOCK_UNIVERSITY_ID}/reject",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 400


# ===========================================================================
# §4  Content Moderation — Flags
# ===========================================================================

class TestListFlags:

    def test_list_flags_default(self, client, auth_headers, mock_auth_admin, monkeypatch):
        flags = [{"id": MOCK_FLAG_ID, "type": "job", "status": "open", "created_at": "2026-03-01T00:00:00Z"}]
        _mock_admin_supabase(monkeypatch, {
            "content_flags": {"select_many": flags, "select_count": 1},
        })
        resp = client.get("/api/admin/flags", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.get_json()
        assert "data" in body
        assert "meta" in body

    def test_list_flags_with_type_filter(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "content_flags": {"select_many": [], "select_count": 0},
        })
        resp = client.get("/api/admin/flags?type=job&status=open", headers=auth_headers)
        assert resp.status_code == 200


class TestResolveFlag:

    def test_resolve_dismiss_success(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "content_flags": {
                "select_single": {"id": MOCK_FLAG_ID, "status": "open", "content_id": "c1", "type": "job"},
                "update": [{"id": MOCK_FLAG_ID, "status": "resolved"}],
            },
            "admin_audit_log": {"insert": [{}]},
        })
        resp = client.post(
            f"/api/admin/flags/{MOCK_FLAG_ID}/resolve",
            json={"action": "dismiss", "note": "False alarm"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["action"] == "dismiss"
        assert "resolved_at" in data

    def test_resolve_remove_content(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "content_flags": {
                "select_single": {"id": MOCK_FLAG_ID, "status": "open", "content_id": "c1", "type": "job"},
                "update": [{"id": MOCK_FLAG_ID, "status": "resolved"}],
            },
            "jobs": {"update": [{"id": "c1", "status": "archived"}]},
            "admin_audit_log": {"insert": [{}]},
        })
        resp = client.post(
            f"/api/admin/flags/{MOCK_FLAG_ID}/resolve",
            json={"action": "remove_content"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_resolve_already_resolved_returns_422(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "content_flags": {"select_single": {"id": MOCK_FLAG_ID, "status": "resolved"}},
        })
        resp = client.post(
            f"/api/admin/flags/{MOCK_FLAG_ID}/resolve",
            json={"action": "dismiss"},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "ALREADY_RESOLVED"

    def test_resolve_missing_action_returns_400(self, client, auth_headers, mock_auth_admin):
        resp = client.post(
            f"/api/admin/flags/{MOCK_FLAG_ID}/resolve",
            json={"note": "no action"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_resolve_invalid_action_returns_400(self, client, auth_headers, mock_auth_admin):
        resp = client.post(
            f"/api/admin/flags/{MOCK_FLAG_ID}/resolve",
            json={"action": "nuke_from_orbit"},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "INVALID_ACTION"


# ===========================================================================
# §5  AI Matching Configuration
# ===========================================================================

class TestGetAIConfig:

    def test_get_ai_config_success(self, client, auth_headers, mock_auth_admin, monkeypatch):
        config_data = {
            "default_weights": {
                "skill_alignment": 40,
                "research_similarity": 25,
                "language_readiness": 20,
                "learning_trajectory": 15,
            },
            "min_score_threshold": 60,
            "max_candidates_per_run": 5000,
            "model_version": "intern2job-match-v2",
            "updated_at": "2026-01-15T00:00:00Z",
            "updated_by": MOCK_ADMIN_ID,
        }
        _mock_admin_supabase(monkeypatch, {
            "ai_config": {"select_single": config_data},
        })
        resp = client.get("/api/admin/ai-config", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["default_weights"]["skill_alignment"] == 40
        assert data["model_version"] == "intern2job-match-v2"

    def test_get_ai_config_returns_defaults_on_error(self, client, auth_headers, mock_auth_admin, monkeypatch):
        import app.services.admin_service as svc
        mock_sb = MagicMock()
        mock_sb.table.side_effect = Exception("DB down")
        monkeypatch.setattr(svc, "supabase", mock_sb)

        resp = client.get("/api/admin/ai-config", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["default_weights"]["skill_alignment"] == 40
        assert data["min_score_threshold"] == 60


class TestUpdateAIConfig:

    def test_update_weights_success(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "ai_config": {"upsert": [{"updated_at": "2026-03-08T00:00:00Z"}]},
            "admin_audit_log": {"insert": [{}]},
        })
        payload = {
            "default_weights": {
                "skill_alignment": 35,
                "research_similarity": 30,
                "language_readiness": 20,
                "learning_trajectory": 15,
            }
        }
        resp = client.put("/api/admin/ai-config", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        assert "updated_at" in resp.get_json()["data"]

    def test_update_weights_not_sum_100_returns_400(self, client, auth_headers, mock_auth_admin):
        payload = {
            "default_weights": {
                "skill_alignment": 50,
                "research_similarity": 30,
                "language_readiness": 20,
                "learning_trajectory": 15,
            }
        }
        resp = client.put("/api/admin/ai-config", json=payload, headers=auth_headers)
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "INVALID_WEIGHTS"

    def test_update_weights_not_dict_returns_400(self, client, auth_headers, mock_auth_admin):
        payload = {"default_weights": "not-a-dict"}
        resp = client.put("/api/admin/ai-config", json=payload, headers=auth_headers)
        assert resp.status_code == 400

    def test_update_threshold_only(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "ai_config": {"upsert": [{}]},
            "admin_audit_log": {"insert": [{}]},
        })
        resp = client.put("/api/admin/ai-config", json={"min_score_threshold": 70}, headers=auth_headers)
        assert resp.status_code == 200


# ===========================================================================
# §6  Platform Analytics
# ===========================================================================

class TestPlatformAnalytics:

    def test_analytics_default_period(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "profiles": {"select_many": []},
        })
        resp = client.get("/api/admin/analytics/platform", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert "user_growth" in data
        assert "api_performance" in data

    def test_analytics_7d_period(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {"profiles": {"select_many": []}})
        resp = client.get("/api/admin/analytics/platform?period=7d", headers=auth_headers)
        assert resp.status_code == 200

    def test_analytics_90d_period(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {"profiles": {"select_many": []}})
        resp = client.get("/api/admin/analytics/platform?period=90d", headers=auth_headers)
        assert resp.status_code == 200

    def test_analytics_ytd_period(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {"profiles": {"select_many": []}})
        resp = client.get("/api/admin/analytics/platform?period=ytd", headers=auth_headers)
        assert resp.status_code == 200

    def test_analytics_all_period(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {"profiles": {"select_many": []}})
        resp = client.get("/api/admin/analytics/platform?period=all", headers=auth_headers)
        assert resp.status_code == 200

    def test_analytics_invalid_period_defaults(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {"profiles": {"select_many": []}})
        resp = client.get("/api/admin/analytics/platform?period=xyz", headers=auth_headers)
        assert resp.status_code == 200


# ===========================================================================
# §7  Data Export
# ===========================================================================

class TestCreateExport:

    def test_create_export_success(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "admin_exports": {"insert": [{"id": MOCK_EXPORT_ID, "status": "queued"}]},
            "admin_audit_log": {"insert": [{}]},
        })
        payload = {"type": "students", "format": "csv", "notify_email": "admin@intern2job.com"}
        resp = client.post("/api/admin/exports", json=payload, headers=auth_headers)
        assert resp.status_code == 202
        data = resp.get_json()["data"]
        assert data["status"] == "queued"

    def test_create_export_invalid_type_returns_400(self, client, auth_headers, mock_auth_admin):
        payload = {"type": "invalid_type"}
        resp = client.post("/api/admin/exports", json=payload, headers=auth_headers)
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "INVALID_EXPORT_TYPE"

    def test_create_export_invalid_format_returns_400(self, client, auth_headers, mock_auth_admin):
        payload = {"type": "students", "format": "xml"}
        resp = client.post("/api/admin/exports", json=payload, headers=auth_headers)
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "INVALID_FORMAT"

    def test_create_export_missing_type_returns_400(self, client, auth_headers, mock_auth_admin):
        resp = client.post("/api/admin/exports", json={}, headers=auth_headers)
        assert resp.status_code == 400


class TestGetExportStatus:

    def test_get_export_complete(self, client, auth_headers, mock_auth_admin, monkeypatch):
        export_data = {
            "id": MOCK_EXPORT_ID,
            "status": "complete",
            "rows_exported": 1000,
            "download_url": "https://storage.supabase.co/export.csv",
            "expires_at": "2026-03-10T00:00:00Z",
        }
        _mock_admin_supabase(monkeypatch, {
            "admin_exports": {"select_single": export_data},
        })
        resp = client.get(f"/api/admin/exports/{MOCK_EXPORT_ID}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["status"] == "complete"
        assert data["rows_exported"] == 1000

    def test_get_export_not_found(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "admin_exports": {"select_single": None},
        })
        resp = client.get("/api/admin/exports/nonexistent", headers=auth_headers)
        assert resp.status_code == 404


# ===========================================================================
# §8  Audit Log
# ===========================================================================

class TestAuditLog:

    def test_audit_log_default(self, client, auth_headers, mock_auth_admin, monkeypatch):
        logs = [
            {
                "id": "log1",
                "actor_id": MOCK_ADMIN_ID,
                "action": "user.suspend",
                "target_id": MOCK_TARGET_USER_ID,
                "created_at": "2026-03-08T14:00:00Z",
            }
        ]
        _mock_admin_supabase(monkeypatch, {
            "admin_audit_log": {"select_many": logs, "select_count": 1},
        })
        resp = client.get("/api/admin/audit-log", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.get_json()
        assert "data" in body
        assert "meta" in body

    def test_audit_log_with_filters(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "admin_audit_log": {"select_many": [], "select_count": 0},
        })
        resp = client.get(
            "/api/admin/audit-log?action_type=user.suspend&from_date=2026-03-01&to_date=2026-03-10",
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_audit_log_pagination(self, client, auth_headers, mock_auth_admin, monkeypatch):
        _mock_admin_supabase(monkeypatch, {
            "admin_audit_log": {"select_many": [], "select_count": 100},
        })
        resp = client.get("/api/admin/audit-log?page=3&limit=10", headers=auth_headers)
        assert resp.status_code == 200


# ===========================================================================
# Auth Guards — Verify all admin endpoints require admin role
# ===========================================================================

class TestAdminAuthGuards:
    """Ensure non-admin users are rejected from all admin endpoints."""

    ADMIN_ENDPOINTS = [
        ("GET", "/api/admin/dashboard"),
        ("GET", "/api/admin/users"),
        ("GET", f"/api/admin/users/{MOCK_TARGET_USER_ID}"),
        ("PATCH", f"/api/admin/users/{MOCK_TARGET_USER_ID}/status"),
        ("PATCH", f"/api/admin/users/{MOCK_TARGET_USER_ID}/role"),
        ("DELETE", f"/api/admin/users/{MOCK_TARGET_USER_ID}"),
        ("GET", "/api/admin/companies/pending"),
        ("POST", f"/api/admin/companies/{MOCK_COMPANY_ID}/approve"),
        ("POST", f"/api/admin/companies/{MOCK_COMPANY_ID}/reject"),
        ("GET", "/api/admin/universities/pending"),
        ("POST", f"/api/admin/universities/{MOCK_UNIVERSITY_ID}/approve"),
        ("POST", f"/api/admin/universities/{MOCK_UNIVERSITY_ID}/reject"),
        ("GET", "/api/admin/flags"),
        ("POST", f"/api/admin/flags/{MOCK_FLAG_ID}/resolve"),
        ("GET", "/api/admin/ai-config"),
        ("PUT", "/api/admin/ai-config"),
        ("GET", "/api/admin/analytics/platform"),
        ("POST", "/api/admin/exports"),
        ("GET", f"/api/admin/exports/{MOCK_EXPORT_ID}"),
        ("GET", "/api/admin/audit-log"),
    ]

    @pytest.mark.parametrize("method,url", ADMIN_ENDPOINTS)
    def test_returns_401_without_auth(self, client, method, url):
        """All admin endpoints return 401 without a Bearer token."""
        resp = getattr(client, method.lower())(url)
        assert resp.status_code == 401, f"{method} {url} should return 401"

    @pytest.mark.parametrize("method,url", ADMIN_ENDPOINTS)
    def test_returns_403_for_student(self, client, auth_headers, mock_auth, method, url, monkeypatch):
        """
        All admin endpoints return 403 for non-admin roles.
        mock_auth sets role=company_admin which is still not 'admin'.
        """
        resp = getattr(client, method.lower())(url, headers=auth_headers)
        assert resp.status_code == 403, f"{method} {url} should return 403 for company_admin"
