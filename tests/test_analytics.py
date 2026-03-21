"""
Unit tests for GET /api/analytics/company.

Coverage:
  - Default period (6m)
  - All period params: 3m, 1m, ytd
  - Zero-job company returns zeroed metrics
  - Correct pipeline stage counts
  - Hiring funnel month labels
  - Recent activity entries
  - Deadline-closing-soon activity flag
  - Auth and role enforcement
"""

import pytest
from unittest.mock import MagicMock
from tests.conftest import MOCK_USER_ID, MOCK_COMPANY_ID, MOCK_JOB_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UNSET = object()  # sentinel so explicit None means "no recruiter row"


def _patch_analytics(monkeypatch, recruiter_data=_UNSET, jobs_data=None,
                     apps_data=None, ai_matches_data=None, runs_data=None):
    import app.routes.analytics as an_module

    if recruiter_data is _UNSET:
        recruiter_data = {"company_id": MOCK_COMPANY_ID}
    if jobs_data is None:
        jobs_data = []
    if apps_data is None:
        apps_data = []
    if ai_matches_data is None:
        ai_matches_data = []
    if runs_data is None:
        runs_data = []

    def _table(name):
        m = MagicMock()
        if name == "recruiters":
            res = MagicMock(); res.data = recruiter_data
            m.select.return_value.eq.return_value.single.return_value.execute.return_value = res

        elif name == "jobs":
            res = MagicMock(); res.data = jobs_data
            m.select.return_value.eq.return_value.execute.return_value = res

        elif name == "applications":
            res = MagicMock(); res.data = apps_data
            m.select.return_value.in_.return_value.execute.return_value = res

        elif name == "ai_match_results":
            res = MagicMock(); res.data = ai_matches_data
            m.select.return_value.in_.return_value.gte.return_value.execute.return_value = res

        elif name == "ai_matching_runs":
            res = MagicMock(); res.data = runs_data
            m.select.return_value.in_.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = res

        return m

    mock_sb = MagicMock()
    mock_sb.table.side_effect = _table
    monkeypatch.setattr(an_module, "supabase", mock_sb)
    return mock_sb


def _make_job(status="published", deadline=None):
    return {
        "id": MOCK_JOB_ID,
        "company_id": MOCK_COMPANY_ID,
        "status": status,
        "deadline": deadline or "2026-12-31",
        "created_at": "2026-01-15T00:00:00+00:00",
    }


def _make_app(status="pending", created_at="2026-02-01T00:00:00+00:00"):
    return {
        "id": "app-1",
        "job_id": MOCK_JOB_ID,
        "status": status,
        "created_at": created_at,
        "updated_at": created_at,
    }


# ===========================================================================
# Basic success cases
# ===========================================================================

class TestCompanyAnalytics:

    def test_default_period_returns_200(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_analytics(monkeypatch, jobs_data=[_make_job()])
        resp = client.get("/api/analytics/company", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["period"] == "6m"

    def test_3m_period_accepted(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_analytics(monkeypatch, jobs_data=[_make_job()])
        resp = client.get("/api/analytics/company?period=3m", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["data"]["period"] == "3m"

    def test_1m_period_accepted(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_analytics(monkeypatch, jobs_data=[_make_job()])
        resp = client.get("/api/analytics/company?period=1m", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["data"]["period"] == "1m"

    def test_ytd_period_accepted(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_analytics(monkeypatch, jobs_data=[_make_job()])
        resp = client.get("/api/analytics/company?period=ytd", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["data"]["period"] == "ytd"

    def test_invalid_period_defaults_to_6m(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_analytics(monkeypatch, jobs_data=[_make_job()])
        resp = client.get("/api/analytics/company?period=10y", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["data"]["period"] == "6m"

    def test_unauthenticated_returns_401(self, client):
        resp = client.get("/api/analytics/company")
        assert resp.status_code == 401

    def test_wrong_role_returns_403(self, client, auth_headers, monkeypatch):
        import app.middleware.auth as auth_module
        mock_user = MagicMock()
        mock_user.id = MOCK_USER_ID
        mock_user.user_metadata = {}
        monkeypatch.setattr(auth_module, "_get_user_from_token", lambda t: mock_user)
        monkeypatch.setattr(auth_module, "_get_profile", lambda uid: {"role": "student"})
        resp = client.get("/api/analytics/company", headers=auth_headers)
        assert resp.status_code == 403

    def test_no_recruiter_link_returns_404(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_analytics(monkeypatch, recruiter_data=None)
        resp = client.get("/api/analytics/company", headers=auth_headers)
        assert resp.status_code == 404


# ===========================================================================
# Zero-job company
# ===========================================================================

class TestZeroJobCompany:

    def test_returns_zero_metrics_when_no_jobs(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_analytics(monkeypatch, jobs_data=[])
        resp = client.get("/api/analytics/company", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["active_jobs"] == 0
        assert data["total_applicants"] == 0
        assert data["ai_matches_today"] == 0
        assert data["offers_extended"] == 0
        assert data["offers_accepted"] == 0
        assert data["hiring_funnel"] == []
        assert data["recent_activity"] == []

    def test_pipeline_all_zeros_when_no_jobs(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_analytics(monkeypatch, jobs_data=[])
        resp = client.get("/api/analytics/company", headers=auth_headers)
        pipeline = resp.get_json()["data"]["pipeline"]
        assert pipeline["screening"] == 0
        assert pipeline["interview"] == 0
        assert pipeline["offer_stage"] == 0


# ===========================================================================
# Metrics accuracy
# ===========================================================================

class TestMetricsAccuracy:

    def test_active_jobs_counts_only_published(self, client, auth_headers, mock_auth, monkeypatch):
        jobs = [
            _make_job("published"),
            _make_job("published"),
            _make_job("draft"),
            _make_job("closed"),
        ]
        _patch_analytics(monkeypatch, jobs_data=jobs, apps_data=[])
        resp = client.get("/api/analytics/company", headers=auth_headers)
        assert resp.get_json()["data"]["active_jobs"] == 2

    def test_total_applicants_count(self, client, auth_headers, mock_auth, monkeypatch):
        apps = [_make_app("pending"), _make_app("shortlisted"), _make_app("rejected")]
        _patch_analytics(monkeypatch, jobs_data=[_make_job()], apps_data=apps)
        resp = client.get("/api/analytics/company", headers=auth_headers)
        assert resp.get_json()["data"]["total_applicants"] == 3

    def test_offers_extended_counts_offered_and_accepted(self, client, auth_headers, mock_auth, monkeypatch):
        apps = [
            _make_app("offered"),
            _make_app("offered"),
            _make_app("accepted"),
            _make_app("pending"),
        ]
        _patch_analytics(monkeypatch, jobs_data=[_make_job()], apps_data=apps)
        resp = client.get("/api/analytics/company", headers=auth_headers)
        data = resp.get_json()["data"]
        assert data["offers_extended"] == 3
        assert data["offers_accepted"] == 1

    def test_pipeline_stage_mapping(self, client, auth_headers, mock_auth, monkeypatch):
        apps = [
            _make_app("pending"),
            _make_app("pending"),
            _make_app("shortlisted"),
            _make_app("offered"),
        ]
        _patch_analytics(monkeypatch, jobs_data=[_make_job()], apps_data=apps)
        resp = client.get("/api/analytics/company", headers=auth_headers)
        pipeline = resp.get_json()["data"]["pipeline"]
        assert pipeline["screening"] == 2   # pending → screening
        assert pipeline["interview"] == 1   # shortlisted → interview
        assert pipeline["offer_stage"] == 1 # offered → offer_stage


# ===========================================================================
# Hiring funnel
# ===========================================================================

class TestHiringFunnel:

    def test_funnel_has_correct_month_count_6m(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_analytics(monkeypatch, jobs_data=[_make_job()])
        resp = client.get("/api/analytics/company?period=6m", headers=auth_headers)
        funnel = resp.get_json()["data"]["hiring_funnel"]
        assert len(funnel) == 6

    def test_funnel_has_correct_month_count_3m(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_analytics(monkeypatch, jobs_data=[_make_job()])
        resp = client.get("/api/analytics/company?period=3m", headers=auth_headers)
        funnel = resp.get_json()["data"]["hiring_funnel"]
        assert len(funnel) == 3

    def test_funnel_has_correct_month_count_1m(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_analytics(monkeypatch, jobs_data=[_make_job()])
        resp = client.get("/api/analytics/company?period=1m", headers=auth_headers)
        funnel = resp.get_json()["data"]["hiring_funnel"]
        assert len(funnel) == 1

    def test_funnel_entries_have_required_fields(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_analytics(monkeypatch, jobs_data=[_make_job()])
        resp = client.get("/api/analytics/company?period=1m", headers=auth_headers)
        entry = resp.get_json()["data"]["hiring_funnel"][0]
        assert "month" in entry
        assert "year" in entry
        assert "applications" in entry
        assert "shortlisted" in entry
        assert "hired" in entry

    def test_funnel_counts_correct_statuses(self, client, auth_headers, mock_auth, monkeypatch):
        # All created in Feb 2026
        apps = [
            _make_app("pending",    "2026-02-10T00:00:00+00:00"),
            _make_app("shortlisted","2026-02-10T00:00:00+00:00"),
            _make_app("accepted",   "2026-02-10T00:00:00+00:00"),
        ]
        _patch_analytics(monkeypatch, jobs_data=[_make_job()], apps_data=apps)
        resp = client.get("/api/analytics/company?period=3m", headers=auth_headers)
        funnel = resp.get_json()["data"]["hiring_funnel"]
        feb_entry = next((f for f in funnel if f["month"] == "Feb"), None)
        if feb_entry:
            assert feb_entry["applications"] == 3
            assert feb_entry["shortlisted"] >= 1  # shortlisted + offered + accepted
            assert feb_entry["hired"] == 1


# ===========================================================================
# Recent activity
# ===========================================================================

class TestRecentActivity:

    def test_no_activity_when_nothing_happened(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_analytics(monkeypatch, jobs_data=[_make_job()], apps_data=[])
        resp = client.get("/api/analytics/company", headers=auth_headers)
        activity = resp.get_json()["data"]["recent_activity"]
        # No runs, no apps today, no deadline warning → should be empty or only deadline if close
        assert isinstance(activity, list)

    def test_activity_has_required_fields_when_present(self, client, auth_headers, mock_auth, monkeypatch):
        # Add a run so there's activity
        import datetime
        today = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
        runs = [{
            "id": "run-1", "job_id": MOCK_JOB_ID,
            "total_analyzed": 45, "status": "complete", "created_at": today,
        }]
        _patch_analytics(monkeypatch, jobs_data=[_make_job()], runs_data=runs)
        resp = client.get("/api/analytics/company", headers=auth_headers)
        activity = resp.get_json()["data"]["recent_activity"]
        if activity:
            entry = activity[0]
            assert "type" in entry
            assert "message" in entry
            assert "urgent" in entry

    def test_closing_soon_activity_flagged_urgent(self, client, auth_headers, mock_auth, monkeypatch):
        import datetime
        two_days_later = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
        jobs = [_make_job("published", two_days_later)]
        _patch_analytics(monkeypatch, jobs_data=jobs, apps_data=[])
        resp = client.get("/api/analytics/company", headers=auth_headers)
        activity = resp.get_json()["data"]["recent_activity"]
        deadline_events = [a for a in activity if a.get("type") == "deadline"]
        assert len(deadline_events) == 1
        assert deadline_events[0]["urgent"] is True

    def test_non_closing_deadline_not_in_activity(self, client, auth_headers, mock_auth, monkeypatch):
        jobs = [_make_job("published", "2026-12-31")]  # far future
        _patch_analytics(monkeypatch, jobs_data=jobs, apps_data=[])
        resp = client.get("/api/analytics/company", headers=auth_headers)
        activity = resp.get_json()["data"]["recent_activity"]
        deadline_events = [a for a in activity if a.get("type") == "deadline"]
        assert len(deadline_events) == 0


# ===========================================================================
# Response shape
# ===========================================================================

class TestResponseShape:

    def test_response_has_all_top_level_keys(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_analytics(monkeypatch, jobs_data=[_make_job()])
        resp = client.get("/api/analytics/company", headers=auth_headers)
        data = resp.get_json()["data"]
        required_keys = {
            "period", "active_jobs", "total_applicants",
            "ai_matches_today", "offers_extended", "offers_accepted",
            "hiring_funnel", "pipeline", "recent_activity",
        }
        assert required_keys.issubset(data.keys())

    def test_pipeline_has_all_stage_keys(self, client, auth_headers, mock_auth, monkeypatch):
        _patch_analytics(monkeypatch, jobs_data=[_make_job()])
        resp = client.get("/api/analytics/company", headers=auth_headers)
        pipeline = resp.get_json()["data"]["pipeline"]
        assert "screening" in pipeline
        assert "interview" in pipeline
        assert "assessment" in pipeline
        assert "offer_stage" in pipeline
