"""
Unit tests for /api/jobs/* (job lifecycle API).

Coverage:
  GET    /api/jobs                                     — list jobs
  GET    /api/jobs/<job_id>                             — job detail
  POST   /api/jobs                                     — create job
  PUT    /api/jobs/<job_id>                             — update job
  PATCH  /api/jobs/<job_id>/status                     — status transition
  DELETE /api/jobs/<job_id>                            — soft-delete
  GET    /api/jobs/<job_id>/applications               — list applications
  PATCH  /api/jobs/<job_id>/applications/<id>/status   — update app status
  GET    /api/jobs/<job_id>/matching-results           — AI match results
  GET    /api/jobs/<job_id>/matching-runs              — AI match run history
  GET    /api/jobs/<job_id>/shortlist                  — shortlisted candidates
  POST   /api/jobs/<job_id>/shortlist/compare          — compare candidates
"""

import pytest
from unittest.mock import MagicMock
from tests.conftest import (
    MOCK_USER_ID, MOCK_COMPANY_ID, MOCK_JOB_ID,
    MOCK_APP_ID, MOCK_STUDENT_ID, MOCK_RUN_ID,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

_UNSET = object()  # sentinel: distinguish "not passed" from explicitly-None


def _patch_jobs(monkeypatch, recruiter_data=_UNSET, table_map=None):
    """
    Patch app.routes.jobs.supabase.

    recruiter_data : dict  – returned for table("recruiters") lookup.
                    Pass _UNSET (default) for the happy-path company_admin.
                    Pass None to simulate "no recruiter row" → 404.
    table_map      : dict of { table_name: {"data": ..., "count": ...} }
    """
    import app.routes.jobs as jobs_module

    if recruiter_data is _UNSET:
        recruiter_data = {"company_id": MOCK_COMPANY_ID}
    table_map = table_map or {}

    def _table(name):
        m = MagicMock()
        if name == "recruiters":
            res = MagicMock()
            res.data = recruiter_data
            m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
        elif name in table_map:
            cfg = table_map[name]
            res = MagicMock()
            res.data = cfg.get("data")
            res.count = cfg.get("count")
            # Cover typical Supabase chain patterns used in jobs.py
            chain = m.select.return_value
            chain.eq.return_value.single.return_value.execute.return_value = res
            chain.eq.return_value.execute.return_value = res
            chain.eq.return_value.eq.return_value.single.return_value.execute.return_value = res
            chain.eq.return_value.eq.return_value.execute.return_value = res
            chain.eq.return_value.in_.return_value.execute.return_value = res
            chain.in_.return_value.execute.return_value = res
            chain.eq.return_value.order.return_value.execute.return_value = res
            chain.eq.return_value.order.return_value.range.return_value.execute.return_value = res
            chain.eq.return_value.eq.return_value.order.return_value.execute.return_value = res
            chain.eq.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value = res
            chain.eq.return_value.gte.return_value.execute.return_value = res
            chain.eq.return_value.order.return_value.limit.return_value.execute.return_value = res
            chain.in_.return_value.eq.return_value.execute.return_value = res
            chain.in_.return_value.order.return_value.execute.return_value = res
            chain.in_.return_value.in_.return_value.execute.return_value = res
            m.insert.return_value.execute.return_value = res
            m.update.return_value.eq.return_value.execute.return_value = res
            m.delete.return_value.eq.return_value.execute.return_value = res
        return m

    mock_sb = MagicMock()
    mock_sb.table.side_effect = _table
    monkeypatch.setattr(jobs_module, "supabase", mock_sb)
    return mock_sb


# ===========================================================================
# GET /api/jobs
# ===========================================================================

class TestListJobs:

    def test_returns_job_list(self, client, auth_headers, mock_auth, monkeypatch, sample_job):
        _patch_jobs(monkeypatch, table_map={"jobs": {"data": [sample_job], "count": 1}})
        resp = client.get("/api/jobs/", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.get_json()
        assert "data" in body
        assert "meta" in body
        assert body["meta"]["total"] == 1
        assert body["data"][0]["id"] == MOCK_JOB_ID
        assert body["data"][0]["title"] == "Senior AI Research Engineer"

    def test_status_filter_accepted(self, client, auth_headers, mock_auth, monkeypatch, sample_job):
        _patch_jobs(monkeypatch, table_map={"jobs": {"data": [sample_job], "count": 1}})
        resp = client.get("/api/jobs/?status=published", headers=auth_headers)
        assert resp.status_code == 200

    def test_invalid_status_filter_returns_400(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_jobs(monkeypatch)
        resp = client.get("/api/jobs/?status=invalid_status", headers=auth_headers)
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "VALIDATION_ERROR"

    def test_pagination_params_accepted(self, client, auth_headers, mock_auth, monkeypatch, sample_job):
        _patch_jobs(monkeypatch, table_map={"jobs": {"data": [sample_job], "count": 1}})
        resp = client.get("/api/jobs/?page=1&limit=10&sort=title&order=asc", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["meta"]["page"] == 1

    def test_empty_list_when_no_jobs(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_jobs(monkeypatch, table_map={"jobs": {"data": [], "count": 0}})
        resp = client.get("/api/jobs/", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["data"] == []

    def test_no_recruiter_returns_404(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_jobs(monkeypatch, recruiter_data=None)
        resp = client.get("/api/jobs/", headers=auth_headers)
        assert resp.status_code == 404

    def test_unauthenticated_returns_401(self, client):
        resp = client.get("/api/jobs/")
        assert resp.status_code == 401


# ===========================================================================
# GET /api/jobs/<job_id>
# ===========================================================================

class TestGetJob:

    def test_returns_job_detail(self, client, auth_headers, mock_auth, monkeypatch, sample_job):
        _patch_jobs(monkeypatch, table_map={"jobs": {"data": sample_job}})
        resp = client.get(f"/api/jobs/{MOCK_JOB_ID}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["id"] == MOCK_JOB_ID
        assert data["description"] == "Work on cutting-edge AI research."
        assert data["skills"] == ["Python", "PyTorch", "NLP"]

    def test_wrong_company_returns_403(self, client, auth_headers, mock_auth, monkeypatch, sample_job):
        wrong_job = {**sample_job, "company_id": "other-company-id"}
        _patch_jobs(monkeypatch, table_map={"jobs": {"data": wrong_job}})
        resp = client.get(f"/api/jobs/{MOCK_JOB_ID}", headers=auth_headers)
        assert resp.status_code == 403

    def test_not_found_returns_404(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_jobs(monkeypatch, table_map={"jobs": {"data": None}})
        resp = client.get(f"/api/jobs/{MOCK_JOB_ID}", headers=auth_headers)
        assert resp.status_code == 404


# ===========================================================================
# POST /api/jobs
# ===========================================================================

class TestCreateJob:

    def test_creates_draft_job(self, client, auth_headers, mock_auth, monkeypatch, sample_job):
        new_job = {**sample_job, "status": "draft"}
        _patch_jobs(monkeypatch, table_map={"jobs": {"data": [new_job]}})
        payload = {
            "title": "Senior AI Research Engineer",
            "skills": ["Python", "PyTorch"],
            "salary_min": 8000000,
            "salary_max": 12000000,
            "deadline": "2026-12-31",
        }
        resp = client.post("/api/jobs/", json=payload, headers=auth_headers)
        assert resp.status_code == 201
        assert resp.get_json()["data"]["title"] == "Senior AI Research Engineer"

    def test_missing_title_returns_400(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_jobs(monkeypatch)
        resp = client.post("/api/jobs/", json={"skills": ["Python"]}, headers=auth_headers)
        assert resp.status_code == 400
        assert "title" in resp.get_json()["error"]["message"]

    def test_salary_min_gte_max_returns_400(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_jobs(monkeypatch)
        payload = {
            "title": "Engineer",
            "salary_min": 10000000,
            "salary_max": 8000000,
            "deadline": "2026-12-31",
        }
        resp = client.post("/api/jobs/", json=payload, headers=auth_headers)
        assert resp.status_code == 400
        assert "salary_min" in resp.get_json()["error"]["message"]

    def test_past_deadline_returns_400(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_jobs(monkeypatch)
        payload = {"title": "Engineer", "deadline": "2020-01-01"}
        resp = client.post("/api/jobs/", json=payload, headers=auth_headers)
        assert resp.status_code == 400
        assert "deadline" in resp.get_json()["error"]["message"]

    def test_invalid_date_format_returns_400(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_jobs(monkeypatch)
        payload = {"title": "Engineer", "deadline": "not-a-date"}
        resp = client.post("/api/jobs/", json=payload, headers=auth_headers)
        assert resp.status_code == 400

    def test_title_too_long_returns_400(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_jobs(monkeypatch)
        payload = {"title": "A" * 201, "deadline": "2026-12-31"}
        resp = client.post("/api/jobs/", json=payload, headers=auth_headers)
        assert resp.status_code == 400

    def test_default_status_is_draft(self, client, auth_headers, mock_auth, monkeypatch, sample_job):
        draft_job = {**sample_job, "status": "draft"}
        _patch_jobs(monkeypatch, table_map={"jobs": {"data": [draft_job]}})
        resp = client.post("/api/jobs/", json={"title": "Engineer"}, headers=auth_headers)
        assert resp.status_code == 201


# ===========================================================================
# PUT /api/jobs/<job_id>
# ===========================================================================

class TestUpdateJob:

    def _setup(self, monkeypatch, existing_job, updated_job=None):
        import app.routes.jobs as jobs_module
        mock_sb = MagicMock()

        def _table(name):
            m = MagicMock()
            if name == "recruiters":
                res = MagicMock(); res.data = {"company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "jobs":
                existing_res = MagicMock(); existing_res.data = existing_job
                updated_res = MagicMock(); updated_res.data = [updated_job or existing_job]
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = existing_res
                m.update.return_value.eq.return_value.execute.return_value = updated_res
            return m

        mock_sb.table.side_effect = _table
        monkeypatch.setattr(jobs_module, "supabase", mock_sb)
        return mock_sb

    def test_updates_job_successfully(self, client, auth_headers, mock_auth, monkeypatch, sample_job):
        updated = {**sample_job, "title": "Lead AI Engineer"}
        self._setup(monkeypatch, sample_job, updated)
        resp = client.put(f"/api/jobs/{MOCK_JOB_ID}", json={"title": "Lead AI Engineer"}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["data"]["title"] == "Lead AI Engineer"

    def test_status_ignored_in_put(self, client, auth_headers, mock_auth, monkeypatch, sample_job):
        # PUT should not allow status change (use PATCH /status instead)
        self._setup(monkeypatch, sample_job, sample_job)
        resp = client.put(f"/api/jobs/{MOCK_JOB_ID}", json={"title": "X", "status": "closed"}, headers=auth_headers)
        assert resp.status_code == 200  # Should succeed, status change ignored

    def test_no_valid_fields_returns_400(self, client, auth_headers, mock_auth, monkeypatch, sample_job):
        self._setup(monkeypatch, sample_job)
        resp = client.put(f"/api/jobs/{MOCK_JOB_ID}", json={"unknown_key": "x"}, headers=auth_headers)
        assert resp.status_code == 400

    def test_wrong_company_ownership_returns_403(self, client, auth_headers, mock_auth, monkeypatch, sample_job):
        wrong_job = {**sample_job, "company_id": "other-co"}
        self._setup(monkeypatch, wrong_job)
        resp = client.put(f"/api/jobs/{MOCK_JOB_ID}", json={"title": "New"}, headers=auth_headers)
        assert resp.status_code == 403


# ===========================================================================
# PATCH /api/jobs/<job_id>/status
# ===========================================================================

class TestUpdateJobStatus:

    def _setup(self, monkeypatch, current_status):
        import app.routes.jobs as jobs_module
        mock_sb = MagicMock()

        def _table(name):
            m = MagicMock()
            if name == "recruiters":
                res = MagicMock(); res.data = {"company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "jobs":
                job_res = MagicMock()
                job_res.data = {"id": MOCK_JOB_ID, "company_id": MOCK_COMPANY_ID, "status": current_status}
                update_res = MagicMock()
                update_res.data = [{"id": MOCK_JOB_ID, "status": "published"}]
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = job_res
                m.update.return_value.eq.return_value.execute.return_value = update_res
            return m

        mock_sb.table.side_effect = _table
        monkeypatch.setattr(jobs_module, "supabase", mock_sb)

    def test_draft_to_published_succeeds(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, "draft")
        resp = client.patch(f"/api/jobs/{MOCK_JOB_ID}/status", json={"status": "published"}, headers=auth_headers)
        assert resp.status_code == 200
        body = resp.get_json()["data"]
        assert body["previous_status"] == "draft"

    def test_published_to_closed_succeeds(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, "published")
        resp = client.patch(f"/api/jobs/{MOCK_JOB_ID}/status", json={"status": "closed"}, headers=auth_headers)
        assert resp.status_code == 200

    def test_closed_to_archived_succeeds(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, "closed")
        resp = client.patch(f"/api/jobs/{MOCK_JOB_ID}/status", json={"status": "archived"}, headers=auth_headers)
        assert resp.status_code == 200

    def test_invalid_transition_returns_422(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, "closed")
        resp = client.patch(f"/api/jobs/{MOCK_JOB_ID}/status", json={"status": "draft"}, headers=auth_headers)
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "INVALID_TRANSITION"

    def test_archived_to_anything_returns_422(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, "archived")
        resp = client.patch(f"/api/jobs/{MOCK_JOB_ID}/status", json={"status": "published"}, headers=auth_headers)
        assert resp.status_code == 422

    def test_missing_status_field_returns_400(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, "draft")
        resp = client.patch(f"/api/jobs/{MOCK_JOB_ID}/status", json={}, headers=auth_headers)
        assert resp.status_code == 400

    def test_unknown_status_value_returns_400(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, "draft")
        resp = client.patch(f"/api/jobs/{MOCK_JOB_ID}/status", json={"status": "flying"}, headers=auth_headers)
        assert resp.status_code == 400

    def test_draft_to_archived_succeeds(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, "draft")
        resp = client.patch(f"/api/jobs/{MOCK_JOB_ID}/status", json={"status": "archived"}, headers=auth_headers)
        assert resp.status_code == 200


# ===========================================================================
# DELETE /api/jobs/<job_id>
# ===========================================================================

class TestDeleteJob:

    def _setup(self, monkeypatch):
        import app.routes.jobs as jobs_module
        mock_sb = MagicMock()

        def _table(name):
            m = MagicMock()
            if name == "recruiters":
                res = MagicMock(); res.data = {"company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "jobs":
                job_res = MagicMock()
                job_res.data = {"id": MOCK_JOB_ID, "company_id": MOCK_COMPANY_ID, "status": "published"}
                update_res = MagicMock(); update_res.data = [{"id": MOCK_JOB_ID}]
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = job_res
                m.update.return_value.eq.return_value.execute.return_value = update_res
            return m

        mock_sb.table.side_effect = _table
        monkeypatch.setattr(jobs_module, "supabase", mock_sb)

    def test_soft_delete_returns_204(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch)
        resp = client.delete(f"/api/jobs/{MOCK_JOB_ID}", headers=auth_headers)
        assert resp.status_code == 204

    def test_only_company_admin_can_delete(self, client, auth_headers, mock_auth_recruiter, monkeypatch):
        resp = client.delete(f"/api/jobs/{MOCK_JOB_ID}", headers=auth_headers)
        assert resp.status_code == 403

    def test_wrong_company_returns_403(self, client, auth_headers, mock_auth, monkeypatch):
        import app.routes.jobs as jobs_module
        mock_sb = MagicMock()

        def _table(name):
            m = MagicMock()
            if name == "recruiters":
                res = MagicMock(); res.data = {"company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "jobs":
                res = MagicMock(); res.data = {"id": MOCK_JOB_ID, "company_id": "other-co", "status": "published"}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            return m

        mock_sb.table.side_effect = _table
        monkeypatch.setattr(jobs_module, "supabase", mock_sb)
        resp = client.delete(f"/api/jobs/{MOCK_JOB_ID}", headers=auth_headers)
        assert resp.status_code == 403


# ===========================================================================
# GET /api/jobs/<job_id>/applications
# ===========================================================================

class TestListApplications:

    def _setup(self, monkeypatch, apps_data):
        import app.routes.jobs as jobs_module
        mock_sb = MagicMock()

        def _table(name):
            m = MagicMock()
            if name == "recruiters":
                res = MagicMock(); res.data = {"company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "jobs":
                res = MagicMock(); res.data = {"id": MOCK_JOB_ID, "company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "applications":
                res = MagicMock(); res.data = apps_data
                chain = m.select.return_value.eq.return_value
                chain.order.return_value.range.return_value.execute.return_value = res
                chain.eq.return_value.order.return_value.range.return_value.execute.return_value = res
            return m

        mock_sb.table.side_effect = _table
        monkeypatch.setattr(jobs_module, "supabase", mock_sb)

    def test_returns_application_list(self, client, auth_headers, mock_auth, monkeypatch, sample_application):
        self._setup(monkeypatch, [sample_application])
        resp = client.get(f"/api/jobs/{MOCK_JOB_ID}/applications", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body["data"]) == 1
        assert body["data"][0]["id"] == MOCK_APP_ID
        assert body["data"][0]["status"] == "pending"
        assert "by_status" in body["meta"]

    def test_status_breakdown_in_meta(self, client, auth_headers, mock_auth, monkeypatch, sample_application):
        self._setup(monkeypatch, [sample_application])
        resp = client.get(f"/api/jobs/{MOCK_JOB_ID}/applications", headers=auth_headers)
        assert resp.status_code == 200
        by_status = resp.get_json()["meta"]["by_status"]
        assert "pending" in by_status
        assert "shortlisted" in by_status
        assert by_status["pending"] == 1

    def test_empty_applications(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, [])
        resp = client.get(f"/api/jobs/{MOCK_JOB_ID}/applications", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["data"] == []


# ===========================================================================
# PATCH /api/jobs/<job_id>/applications/<app_id>/status
# ===========================================================================

class TestUpdateApplicationStatus:

    def _setup(self, monkeypatch, current_app_status):
        import app.routes.jobs as jobs_module
        mock_sb = MagicMock()

        def _table(name):
            m = MagicMock()
            if name == "recruiters":
                res = MagicMock(); res.data = {"company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "jobs":
                res = MagicMock(); res.data = {"id": MOCK_JOB_ID, "company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "applications":
                app_res = MagicMock()
                app_res.data = {"id": MOCK_APP_ID, "job_id": MOCK_JOB_ID, "status": current_app_status}
                update_res = MagicMock()
                update_res.data = [{"id": MOCK_APP_ID, "status": "shortlisted"}]
                m.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value = app_res
                m.update.return_value.eq.return_value.execute.return_value = update_res
            return m

        mock_sb.table.side_effect = _table
        monkeypatch.setattr(jobs_module, "supabase", mock_sb)

    def test_pending_to_shortlisted(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, "pending")
        resp = client.patch(
            f"/api/jobs/{MOCK_JOB_ID}/applications/{MOCK_APP_ID}/status",
            json={"status": "shortlisted"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["previous_status"] == "pending"

    def test_pending_to_rejected(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, "pending")
        resp = client.patch(
            f"/api/jobs/{MOCK_JOB_ID}/applications/{MOCK_APP_ID}/status",
            json={"status": "rejected"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_shortlisted_to_offered(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, "shortlisted")
        resp = client.patch(
            f"/api/jobs/{MOCK_JOB_ID}/applications/{MOCK_APP_ID}/status",
            json={"status": "offered"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_invalid_transition_returns_422(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, "pending")
        resp = client.patch(
            f"/api/jobs/{MOCK_JOB_ID}/applications/{MOCK_APP_ID}/status",
            json={"status": "accepted"},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert resp.get_json()["error"]["code"] == "INVALID_TRANSITION"

    def test_accepted_to_anything_returns_422(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, "accepted")
        resp = client.patch(
            f"/api/jobs/{MOCK_JOB_ID}/applications/{MOCK_APP_ID}/status",
            json={"status": "rejected"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_missing_status_field_returns_400(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, "pending")
        resp = client.patch(
            f"/api/jobs/{MOCK_JOB_ID}/applications/{MOCK_APP_ID}/status",
            json={},
            headers=auth_headers,
        )
        assert resp.status_code == 400


# ===========================================================================
# GET /api/jobs/<job_id>/matching-results
# ===========================================================================

class TestMatchingResults:

    def _setup(self, monkeypatch, results_data):
        import app.routes.jobs as jobs_module
        mock_sb = MagicMock()

        def _table(name):
            m = MagicMock()
            if name == "recruiters":
                res = MagicMock(); res.data = {"company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "jobs":
                res = MagicMock(); res.data = {"id": MOCK_JOB_ID, "company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "ai_match_results":
                res = MagicMock(); res.data = results_data
                m.select.return_value.eq.return_value.order.return_value.execute.return_value = res
            return m

        mock_sb.table.side_effect = _table
        monkeypatch.setattr(jobs_module, "supabase", mock_sb)

    def test_returns_match_results(self, client, auth_headers, mock_auth, monkeypatch):
        results = [
            {
                "id": "r1", "student_id": MOCK_STUDENT_ID, "score": 92.5,
                "explanation": {"skill_match": 95, "lang_readiness": 88},
                "created_at": "2026-02-01T00:00:00+00:00",
            }
        ]
        self._setup(monkeypatch, results)
        resp = client.get(f"/api/jobs/{MOCK_JOB_ID}/matching-results", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body["data"]) == 1
        assert body["data"][0]["score"] == 92.5
        assert body["data"][0]["skill_match"] == 95

    def test_empty_results_returns_200(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, [])
        resp = client.get(f"/api/jobs/{MOCK_JOB_ID}/matching-results", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["data"] == []
        assert resp.get_json()["meta"]["total"] == 0


# ===========================================================================
# GET /api/jobs/<job_id>/matching-runs
# ===========================================================================

class TestMatchingRuns:

    def _setup(self, monkeypatch, runs_data):
        import app.routes.jobs as jobs_module
        mock_sb = MagicMock()

        def _table(name):
            m = MagicMock()
            if name == "recruiters":
                res = MagicMock(); res.data = {"company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "jobs":
                res = MagicMock(); res.data = {"id": MOCK_JOB_ID, "company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "ai_matching_runs":
                res = MagicMock(); res.data = runs_data
                m.select.return_value.eq.return_value.order.return_value.execute.return_value = res
            return m

        mock_sb.table.side_effect = _table
        monkeypatch.setattr(jobs_module, "supabase", mock_sb)

    def test_returns_run_history(self, client, auth_headers, mock_auth, monkeypatch):
        runs = [
            {
                "id": MOCK_RUN_ID, "triggered_by": MOCK_USER_ID,
                "status": "complete", "total_analyzed": 150, "top_score": 94.2,
                "created_at": "2026-02-01T00:00:00+00:00",
                "updated_at": "2026-02-01T00:00:00+00:00",
            }
        ]
        self._setup(monkeypatch, runs)
        resp = client.get(f"/api/jobs/{MOCK_JOB_ID}/matching-runs", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body["data"]) == 1
        assert body["data"][0]["run_id"] == MOCK_RUN_ID
        assert body["data"][0]["total_analyzed"] == 150

    def test_no_runs_returns_empty(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, [])
        resp = client.get(f"/api/jobs/{MOCK_JOB_ID}/matching-runs", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["data"] == []


# ===========================================================================
# GET /api/jobs/<job_id>/shortlist
# ===========================================================================

class TestShortlist:

    def _setup(self, monkeypatch, apps_data, match_data=None):
        import app.routes.jobs as jobs_module
        mock_sb = MagicMock()

        def _table(name):
            m = MagicMock()
            if name == "recruiters":
                res = MagicMock(); res.data = {"company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "jobs":
                res = MagicMock(); res.data = {"id": MOCK_JOB_ID, "company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "applications":
                res = MagicMock(); res.data = apps_data
                m.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = res
            elif name == "ai_match_results":
                res = MagicMock(); res.data = match_data or []
                m.select.return_value.eq.return_value.in_.return_value.order.return_value.execute.return_value = res
            return m

        mock_sb.table.side_effect = _table
        monkeypatch.setattr(jobs_module, "supabase", mock_sb)

    def test_returns_shortlisted_candidates(self, client, auth_headers, mock_auth, monkeypatch):
        apps = [{
            "id": MOCK_APP_ID, "student_id": MOCK_STUDENT_ID,
            "status": "shortlisted", "ai_score": 87.5,
            "created_at": "2026-02-01T00:00:00+00:00",
            "updated_at": "2026-02-01T00:00:00+00:00",
            "shortlisted_at": "2026-02-05T00:00:00+00:00",
        }]
        self._setup(monkeypatch, apps)
        resp = client.get(f"/api/jobs/{MOCK_JOB_ID}/shortlist", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.get_json()
        assert len(body["data"]) == 1
        assert body["data"][0]["application_id"] == MOCK_APP_ID

    def test_empty_shortlist(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, [])
        resp = client.get(f"/api/jobs/{MOCK_JOB_ID}/shortlist", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["data"] == []


# ===========================================================================
# POST /api/jobs/<job_id>/shortlist/compare
# ===========================================================================

class TestCompare:

    def _setup(self, monkeypatch, apps_data, match_data=None):
        import app.routes.jobs as jobs_module
        mock_sb = MagicMock()

        def _table(name):
            m = MagicMock()
            if name == "recruiters":
                res = MagicMock(); res.data = {"company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "jobs":
                res = MagicMock(); res.data = {"id": MOCK_JOB_ID, "company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "applications":
                res = MagicMock(); res.data = apps_data
                m.select.return_value.eq.return_value.in_.return_value.execute.return_value = res
            elif name == "ai_match_results":
                res = MagicMock(); res.data = match_data or []
                m.select.return_value.eq.return_value.in_.return_value.execute.return_value = res
            return m

        mock_sb.table.side_effect = _table
        monkeypatch.setattr(jobs_module, "supabase", mock_sb)

    def test_compare_2_candidates(self, client, auth_headers, mock_auth, monkeypatch):
        sid2 = "77777777-7777-7777-7777-777777777777"
        apps = [
            {"id": MOCK_APP_ID, "student_id": MOCK_STUDENT_ID, "status": "shortlisted", "ai_score": 88},
            {"id": "app-2", "student_id": sid2, "status": "shortlisted", "ai_score": 72},
        ]
        self._setup(monkeypatch, apps)
        payload = {"candidate_ids": [MOCK_STUDENT_ID, sid2]}
        resp = client.post(f"/api/jobs/{MOCK_JOB_ID}/shortlist/compare", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        candidates = resp.get_json()["data"]["candidates"]
        assert len(candidates) == 2

    def test_compare_3_candidates(self, client, auth_headers, mock_auth, monkeypatch):
        ids = [MOCK_STUDENT_ID, "sid-2", "sid-3"]
        apps = [{"id": f"app-{i}", "student_id": sid, "status": "shortlisted", "ai_score": 80} for i, sid in enumerate(ids)]
        self._setup(monkeypatch, apps)
        resp = client.post(
            f"/api/jobs/{MOCK_JOB_ID}/shortlist/compare",
            json={"candidate_ids": ids},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert len(resp.get_json()["data"]["candidates"]) == 3

    def test_more_than_3_candidates_returns_400(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, [])
        payload = {"candidate_ids": ["a", "b", "c", "d"]}
        resp = client.post(f"/api/jobs/{MOCK_JOB_ID}/shortlist/compare", json=payload, headers=auth_headers)
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "VALIDATION_ERROR"

    def test_fewer_than_2_candidates_returns_400(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup(monkeypatch, [])
        resp = client.post(
            f"/api/jobs/{MOCK_JOB_ID}/shortlist/compare",
            json={"candidate_ids": ["only-one"]},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_radar_data_present_in_response(self, client, auth_headers, mock_auth, monkeypatch):
        sid2 = "88888888-8888-8888-8888-888888888888"
        apps = [
            {"id": MOCK_APP_ID, "student_id": MOCK_STUDENT_ID, "status": "shortlisted", "ai_score": 88},
            {"id": "app-2", "student_id": sid2, "status": "shortlisted", "ai_score": 72},
        ]
        matches = [
            {
                "student_id": MOCK_STUDENT_ID,
                "score": 88,
                "explanation": {"skill_match": 90, "research_sim": 80, "lang_readiness": 85, "learning_traj": 75},
            }
        ]
        self._setup(monkeypatch, apps, matches)
        resp = client.post(
            f"/api/jobs/{MOCK_JOB_ID}/shortlist/compare",
            json={"candidate_ids": [MOCK_STUDENT_ID, sid2]},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        candidate = resp.get_json()["data"]["candidates"][0]
        assert "radar_data" in candidate
        assert "dimensions" in candidate
        assert len(candidate["radar_data"]) == 4
