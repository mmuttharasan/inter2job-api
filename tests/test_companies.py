"""
Unit tests for /api/companies/* (company admin endpoints).

Coverage:
  GET  /api/companies/me
  PUT  /api/companies/me
  POST /api/companies/me/logo
  GET  /api/companies/me/landing-page
  PUT  /api/companies/me/landing-page

Auth is bypassed via the `mock_auth` fixture.
Supabase is fully mocked per-test via monkeypatch.
"""

import io
import pytest
from unittest.mock import MagicMock, patch
from tests.conftest import MOCK_USER_ID, MOCK_COMPANY_ID


# ---------------------------------------------------------------------------
# Helper: build a recruiter+company double-table mock
# ---------------------------------------------------------------------------

def _make_mock(monkeypatch, recruiter_data, company_data, table_extras=None):
    """
    Patch app.routes.companies.supabase so that:
      - table("recruiters") → recruiter_data
      - table("companies")  → company_data
      - Any extra tables     → table_extras dict
    """
    import app.routes.companies as co_module

    def _table(name):
        m = MagicMock()
        if name == "recruiters":
            res = MagicMock()
            res.data = recruiter_data
            m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
        elif name == "companies":
            res = MagicMock()
            if isinstance(company_data, list):
                res.data = company_data
            else:
                res.data = company_data
            m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            m.update.return_value.eq.return_value.execute.return_value = res
            m.insert.return_value.execute.return_value = res
        elif table_extras and name in table_extras:
            res = MagicMock()
            res.data = table_extras[name]
            m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            m.select.return_value.eq.return_value.execute.return_value = res
            m.upsert.return_value.execute.return_value = res
        return m

    mock_sb = MagicMock()
    mock_sb.table.side_effect = _table
    monkeypatch.setattr(co_module, "supabase", mock_sb)
    return mock_sb


# ===========================================================================
# GET /api/companies/me
# ===========================================================================

class TestGetMyCompany:

    def test_success_returns_company(self, client, auth_headers, mock_auth, monkeypatch, sample_company):
        _make_mock(monkeypatch, {"company_id": MOCK_COMPANY_ID}, sample_company)
        resp = client.get("/api/companies/me", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert "data" in data
        assert data["data"]["id"] == MOCK_COMPANY_ID
        assert data["data"]["name"] == "Sony Group Corporation"
        assert data["data"]["name_jp"] == "ソニーグループ株式会社"
        assert data["data"]["values"] == ["Innovation", "Creativity"]
        assert data["data"]["benefits"] == ["Health insurance", "Remote work"]

    def test_no_recruiter_row_returns_404(self, client, auth_headers, mock_auth, monkeypatch):
        _make_mock(monkeypatch, None, None)
        resp = client.get("/api/companies/me", headers=auth_headers)
        assert resp.status_code == 404
        assert resp.get_json()["error"]["code"] == "NOT_FOUND"

    def test_recruiter_has_no_company_id_returns_404(self, client, auth_headers, mock_auth, monkeypatch):
        _make_mock(monkeypatch, {"company_id": None}, None)
        resp = client.get("/api/companies/me", headers=auth_headers)
        assert resp.status_code == 404

    def test_missing_auth_header_returns_401(self, client):
        resp = client.get("/api/companies/me")
        assert resp.status_code == 401
        assert resp.get_json()["error"]["code"] == "UNAUTHORIZED"

    def test_wrong_role_returns_403(self, client, auth_headers, monkeypatch):
        import app.middleware.auth as auth_module
        mock_user = MagicMock()
        mock_user.id = MOCK_USER_ID
        mock_user.user_metadata = {}
        monkeypatch.setattr(auth_module, "_get_user_from_token", lambda t: mock_user)
        monkeypatch.setattr(auth_module, "_get_profile", lambda uid: {"role": "student"})
        resp = client.get("/api/companies/me", headers=auth_headers)
        assert resp.status_code == 403
        assert resp.get_json()["error"]["code"] == "FORBIDDEN"

    def test_values_defaults_to_empty_list_when_null(self, client, auth_headers, mock_auth, monkeypatch, sample_company):
        sample_company["values"] = None
        sample_company["benefits"] = None
        _make_mock(monkeypatch, {"company_id": MOCK_COMPANY_ID}, sample_company)
        resp = client.get("/api/companies/me", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["data"]["values"] == []
        assert resp.get_json()["data"]["benefits"] == []


# ===========================================================================
# PUT /api/companies/me
# ===========================================================================

class TestUpdateMyCompany:

    def test_success_updates_company(self, client, auth_headers, mock_auth, monkeypatch, sample_company):
        updated = {**sample_company, "name": "Sony Corporation Updated"}
        import app.routes.companies as co_module

        def _table(name):
            m = MagicMock()
            if name == "recruiters":
                res = MagicMock(); res.data = {"company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "companies":
                res = MagicMock(); res.data = [updated]
                m.update.return_value.eq.return_value.execute.return_value = res
            return m

        mock_sb = MagicMock(); mock_sb.table.side_effect = _table
        monkeypatch.setattr(co_module, "supabase", mock_sb)

        payload = {"name": "Sony Corporation Updated", "tagline": "New tagline"}
        resp = client.put("/api/companies/me", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["data"]["name"] == "Sony Corporation Updated"

    def test_empty_name_returns_400(self, client, auth_headers, mock_auth, monkeypatch, sample_company):
        _make_mock(monkeypatch, {"company_id": MOCK_COMPANY_ID}, sample_company)
        resp = client.put("/api/companies/me", json={"name": "  "}, headers=auth_headers)
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "VALIDATION_ERROR"

    def test_invalid_website_returns_400(self, client, auth_headers, mock_auth, monkeypatch, sample_company):
        _make_mock(monkeypatch, {"company_id": MOCK_COMPANY_ID}, sample_company)
        resp = client.put("/api/companies/me", json={"website": "not-a-url"}, headers=auth_headers)
        assert resp.status_code == 400
        assert "website" in resp.get_json()["error"]["message"]

    def test_invalid_founded_year_returns_400(self, client, auth_headers, mock_auth, monkeypatch, sample_company):
        _make_mock(monkeypatch, {"company_id": MOCK_COMPANY_ID}, sample_company)
        resp = client.put("/api/companies/me", json={"founded_year": 1700}, headers=auth_headers)
        assert resp.status_code == 400

    def test_values_not_list_returns_400(self, client, auth_headers, mock_auth, monkeypatch, sample_company):
        _make_mock(monkeypatch, {"company_id": MOCK_COMPANY_ID}, sample_company)
        resp = client.put("/api/companies/me", json={"values": "not-a-list"}, headers=auth_headers)
        assert resp.status_code == 400

    def test_no_valid_fields_returns_400(self, client, auth_headers, mock_auth, monkeypatch, sample_company):
        _make_mock(monkeypatch, {"company_id": MOCK_COMPANY_ID}, sample_company)
        resp = client.put("/api/companies/me", json={"unknown_field": "value"}, headers=auth_headers)
        assert resp.status_code == 400

    def test_only_company_admin_can_update(self, client, auth_headers, mock_auth_recruiter, monkeypatch):
        resp = client.put("/api/companies/me", json={"name": "X"}, headers=auth_headers)
        assert resp.status_code == 403

    def test_valid_website_with_https_passes(self, client, auth_headers, mock_auth, monkeypatch, sample_company):
        updated = {**sample_company, "website": "https://new.sony.com"}
        import app.routes.companies as co_module

        def _table(name):
            m = MagicMock()
            if name == "recruiters":
                res = MagicMock(); res.data = {"company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "companies":
                res = MagicMock(); res.data = [updated]
                m.update.return_value.eq.return_value.execute.return_value = res
            return m

        mock_sb = MagicMock(); mock_sb.table.side_effect = _table
        monkeypatch.setattr(co_module, "supabase", mock_sb)
        resp = client.put("/api/companies/me", json={"website": "https://new.sony.com"}, headers=auth_headers)
        assert resp.status_code == 200


# ===========================================================================
# POST /api/companies/me/logo
# ===========================================================================

class TestUploadLogo:

    def _setup_recruiter_mock(self, monkeypatch):
        import app.routes.companies as co_module
        mock_sb = MagicMock()
        recruiter_res = MagicMock()
        recruiter_res.data = {"company_id": MOCK_COMPANY_ID}
        company_res = MagicMock()
        company_res.data = [{"id": MOCK_COMPANY_ID, "logo_url": "https://cdn.example.com/logo.png"}]

        def _table(name):
            m = MagicMock()
            if name == "recruiters":
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = recruiter_res
            elif name == "companies":
                m.update.return_value.eq.return_value.execute.return_value = company_res
            return m

        mock_sb.table.side_effect = _table
        mock_sb.storage.from_.return_value.upload.return_value = None
        mock_sb.storage.from_.return_value.get_public_url.return_value = "https://cdn.example.com/logo.png"
        monkeypatch.setattr(co_module, "supabase", mock_sb)
        return mock_sb

    def test_success_returns_logo_url(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup_recruiter_mock(monkeypatch)
        data = {"logo": (io.BytesIO(b"fake-image-bytes"), "logo.png", "image/png")}
        resp = client.post("/api/companies/me/logo", data=data, headers=auth_headers,
                           content_type="multipart/form-data")
        assert resp.status_code == 201
        assert "logo_url" in resp.get_json()["data"]

    def test_no_file_returns_400(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup_recruiter_mock(monkeypatch)
        resp = client.post("/api/companies/me/logo", data={}, headers=auth_headers,
                           content_type="multipart/form-data")
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "VALIDATION_ERROR"

    def test_invalid_file_type_returns_400(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup_recruiter_mock(monkeypatch)
        data = {"logo": (io.BytesIO(b"not-an-image"), "doc.pdf", "application/pdf")}
        resp = client.post("/api/companies/me/logo", data=data, headers=auth_headers,
                           content_type="multipart/form-data")
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "INVALID_FILE_TYPE"

    def test_file_too_large_returns_400(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup_recruiter_mock(monkeypatch)
        big_data = b"x" * (6 * 1024 * 1024)  # 6 MB
        data = {"logo": (io.BytesIO(big_data), "big.png", "image/png")}
        resp = client.post("/api/companies/me/logo", data=data, headers=auth_headers,
                           content_type="multipart/form-data")
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "FILE_TOO_LARGE"

    def test_jpeg_file_accepted(self, client, auth_headers, mock_auth, monkeypatch):
        self._setup_recruiter_mock(monkeypatch)
        data = {"logo": (io.BytesIO(b"fake-jpeg"), "logo.jpg", "image/jpeg")}
        resp = client.post("/api/companies/me/logo", data=data, headers=auth_headers,
                           content_type="multipart/form-data")
        assert resp.status_code == 201

    def test_only_company_admin_can_upload(self, client, auth_headers, mock_auth_recruiter, monkeypatch):
        resp = client.post("/api/companies/me/logo", data={}, headers=auth_headers,
                           content_type="multipart/form-data")
        assert resp.status_code == 403


# ===========================================================================
# GET /api/companies/me/landing-page
# ===========================================================================

class TestGetLandingPage:

    def test_returns_existing_landing_page(self, client, auth_headers, mock_auth, monkeypatch):
        lp_data = {
            "company_id": MOCK_COMPANY_ID,
            "headline": "Join Us",
            "subheadline": "Build the future",
            "hero_image_url": None,
            "sections": [{"type": "text", "content": "Hello"}],
            "cta_text": "Apply Now",
            "published": True,
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        import app.routes.companies as co_module

        def _table(name):
            m = MagicMock()
            if name == "recruiters":
                res = MagicMock(); res.data = {"company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "company_landing_pages":
                res = MagicMock(); res.data = lp_data
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            return m

        mock_sb = MagicMock(); mock_sb.table.side_effect = _table
        monkeypatch.setattr(co_module, "supabase", mock_sb)

        resp = client.get("/api/companies/me/landing-page", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["headline"] == "Join Us"
        assert data["published"] is True
        assert len(data["sections"]) == 1

    def test_returns_empty_scaffold_when_no_page_exists(self, client, auth_headers, mock_auth, monkeypatch):
        import app.routes.companies as co_module

        def _table(name):
            m = MagicMock()
            if name == "recruiters":
                res = MagicMock(); res.data = {"company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "company_landing_pages":
                res = MagicMock(); res.data = None
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            return m

        mock_sb = MagicMock(); mock_sb.table.side_effect = _table
        monkeypatch.setattr(co_module, "supabase", mock_sb)

        resp = client.get("/api/companies/me/landing-page", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["headline"] is None
        assert data["published"] is False
        assert data["sections"] == []


# ===========================================================================
# PUT /api/companies/me/landing-page
# ===========================================================================

class TestSaveLandingPage:

    def test_success_upserts_landing_page(self, client, auth_headers, mock_auth, monkeypatch):
        saved = {
            "company_id": MOCK_COMPANY_ID,
            "headline": "Join Us",
            "subheadline": "Build the future",
            "hero_image_url": None,
            "sections": [],
            "cta_text": "Apply Now",
            "published": False,
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        import app.routes.companies as co_module

        def _table(name):
            m = MagicMock()
            if name == "recruiters":
                res = MagicMock(); res.data = {"company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "company_landing_pages":
                res = MagicMock(); res.data = [saved]
                m.upsert.return_value.execute.return_value = res
            return m

        mock_sb = MagicMock(); mock_sb.table.side_effect = _table
        monkeypatch.setattr(co_module, "supabase", mock_sb)

        payload = {"headline": "Join Us", "cta_text": "Apply Now", "sections": []}
        resp = client.put("/api/companies/me/landing-page", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["data"]["headline"] == "Join Us"

    def test_sections_not_list_returns_400(self, client, auth_headers, mock_auth, monkeypatch):
        import app.routes.companies as co_module

        def _table(name):
            m = MagicMock()
            if name == "recruiters":
                res = MagicMock(); res.data = {"company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            return m

        mock_sb = MagicMock(); mock_sb.table.side_effect = _table
        monkeypatch.setattr(co_module, "supabase", mock_sb)

        resp = client.put("/api/companies/me/landing-page", json={"sections": "not-a-list"}, headers=auth_headers)
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "VALIDATION_ERROR"

    def test_published_flag_saved_correctly(self, client, auth_headers, mock_auth, monkeypatch):
        saved = {
            "company_id": MOCK_COMPANY_ID, "headline": None, "subheadline": None,
            "hero_image_url": None, "sections": [], "cta_text": None, "published": True,
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        import app.routes.companies as co_module

        def _table(name):
            m = MagicMock()
            if name == "recruiters":
                res = MagicMock(); res.data = {"company_id": MOCK_COMPANY_ID}
                m.select.return_value.eq.return_value.single.return_value.execute.return_value = res
            elif name == "company_landing_pages":
                res = MagicMock(); res.data = [saved]
                m.upsert.return_value.execute.return_value = res
            return m

        mock_sb = MagicMock(); mock_sb.table.side_effect = _table
        monkeypatch.setattr(co_module, "supabase", mock_sb)

        resp = client.put("/api/companies/me/landing-page", json={"published": True}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()["data"]["published"] is True
