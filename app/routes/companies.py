"""
Company Admin API — /api/companies/*

Endpoints:
  GET  /api/companies/me                  — get company profile for authenticated admin
  PUT  /api/companies/me                  — update company profile
  POST /api/companies/me/logo             — upload company logo (multipart/form-data)
  GET  /api/companies/me/landing-page     — get landing page content
  PUT  /api/companies/me/landing-page     — save landing page content
  GET  /api/companies/me/settings         — get recruiter settings (profile + notifications + AI weights)
  PUT  /api/companies/me/settings         — update recruiter settings

All routes require role: company_admin or recruiter (unless noted).
The company is resolved via the recruiters table: profiles → recruiters → companies.
"""

import uuid
from flask import Blueprint, jsonify, request, g
from ..services.supabase_client import supabase
from ..middleware.auth import require_role



companies_bp = Blueprint("companies", __name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMPANY_UPDATABLE_FIELDS = {
    "name", "name_jp", "tagline", "logo_url", "website",
    "industry", "size", "location", "description",
    "mission", "culture", "values", "benefits", "founded_year",
}

ALLOWED_LOGO_TYPES = {"image/jpeg", "image/png", "image/webp", "image/svg+xml"}
MAX_LOGO_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _get_company_id(user_id: str):
    """Returns (company_id, None) or (None, error_response).

    Respects the X-Company-ID header for multi-company switcher — validates the
    user actually has recruiter access to the requested company before honouring it.
    """
    override_id = request.headers.get("X-Company-ID")
    if override_id:
        try:
            res = (
                supabase.table("recruiters")
                .select("company_id")
                .eq("id", user_id)
                .eq("company_id", override_id)
                .execute()
            )
            if res.data:
                return override_id, None
        except Exception:
            pass  # fall through to default lookup

    try:
        res = (
            supabase.table("recruiters")
            .select("company_id")
            .eq("id", user_id)
            .single()
            .execute()
        )
        if not res.data or not res.data.get("company_id"):
            return None, _err("NOT_FOUND", "No company linked to your account", 404)
        return res.data["company_id"], None
    except Exception:
        return None, _err("NOT_FOUND", "No company linked to your account", 404)


def _format_company(raw: dict) -> dict:
    """Map a raw companies row to the API response shape."""
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "name_jp": raw.get("name_jp"),
        "tagline": raw.get("tagline"),
        "logo_url": raw.get("logo_url"),
        "website": raw.get("website"),
        "industry": raw.get("industry"),
        "size": raw.get("size"),
        "location": raw.get("location"),
        "description": raw.get("description"),
        "mission": raw.get("mission"),
        "culture": raw.get("culture"),
        "values": raw.get("values") or [],
        "benefits": raw.get("benefits") or [],
        "founded_year": raw.get("founded_year"),
        "created_at": raw.get("created_at"),
        "updated_at": raw.get("updated_at"),
    }


def _validate_company_update(data: dict) -> list:
    errors = []
    if "name" in data and not str(data.get("name", "")).strip():
        errors.append("'name' cannot be empty")
    if "website" in data and data["website"]:
        if not str(data["website"]).startswith(("http://", "https://")):
            errors.append("'website' must start with http:// or https://")
    if "founded_year" in data and data["founded_year"] is not None:
        try:
            year = int(data["founded_year"])
            if year < 1800 or year > 2100:
                errors.append("'founded_year' must be a valid year between 1800 and 2100")
        except (ValueError, TypeError):
            errors.append("'founded_year' must be a number")
    if "values" in data and not isinstance(data["values"], list):
        errors.append("'values' must be an array")
    if "benefits" in data and not isinstance(data["benefits"], list):
        errors.append("'benefits' must be an array")
    return errors


# ---------------------------------------------------------------------------
# GET /api/companies/me
# ---------------------------------------------------------------------------

@companies_bp.get("/me")
@require_role(["company_admin", "recruiter"])
def get_my_company():
    """Return the company profile for the authenticated company_admin."""
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    try:
        res = (
            supabase.table("companies")
            .select("*")
            .eq("id", company_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Company not found", 404)

    if not res.data:
        return _err("NOT_FOUND", "Company not found", 404)

    return jsonify({"data": _format_company(res.data)})


# ---------------------------------------------------------------------------
# GET /api/companies/mine  — list all companies the user has recruiter access to
# ---------------------------------------------------------------------------

@companies_bp.get("/mine")
@require_role(["company_admin", "recruiter"])
def list_my_companies():
    """Return all companies the authenticated user is a recruiter for."""
    try:
        res = (
            supabase.table("recruiters")
            .select("company_id")
            .eq("id", g.user_id)
            .execute()
        )
        if not res.data:
            return jsonify({"data": []})

        company_ids = [row["company_id"] for row in res.data if row.get("company_id")]
        if not company_ids:
            return jsonify({"data": []})

        companies_res = (
            supabase.table("companies")
            .select("id, name, name_jp, logo_url, industry, location")
            .in_("id", company_ids)
            .execute()
        )
        companies = [
            {
                "id": c.get("id"),
                "name": c.get("name"),
                "name_jp": c.get("name_jp"),
                "logo_url": c.get("logo_url"),
                "industry": c.get("industry"),
                "location": c.get("location"),
            }
            for c in (companies_res.data or [])
        ]
        return jsonify({"data": companies})
    except Exception:
        return jsonify({"data": []})


# ---------------------------------------------------------------------------
# PUT /api/companies/me
# ---------------------------------------------------------------------------

@companies_bp.put("/me")
@require_role(["company_admin"])
def update_my_company():
    """Update the company profile for the authenticated company_admin."""
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    validation_errors = _validate_company_update(payload)
    if validation_errors:
        return (
            jsonify({
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": validation_errors[0],
                    "details": validation_errors,
                }
            }),
            400,
        )

    update_data = {k: v for k, v in payload.items() if k in COMPANY_UPDATABLE_FIELDS}
    if not update_data:
        return _err("VALIDATION_ERROR", "No valid fields provided for update", 400)

    try:
        res = (
            supabase.table("companies")
            .update(update_data)
            .eq("id", company_id)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to update company profile", 500)

    if not res.data:
        return _err("NOT_FOUND", "Company not found", 404)

    return jsonify({"data": _format_company(res.data[0])})


# ---------------------------------------------------------------------------
# POST /api/companies/me/logo
# ---------------------------------------------------------------------------

@companies_bp.post("/me/logo")
@require_role(["company_admin"])
def upload_logo():
    """Upload a new company logo. Accepts multipart/form-data with field 'logo'."""
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    if "logo" not in request.files:
        return _err("VALIDATION_ERROR", "No file uploaded. Use field name 'logo'", 400)

    file = request.files["logo"]
    if not file.filename:
        return _err("VALIDATION_ERROR", "File name is empty", 400)

    content_type = file.content_type or ""
    if content_type not in ALLOWED_LOGO_TYPES:
        return _err(
            "INVALID_FILE_TYPE",
            f"File type '{content_type}' not allowed. Accepted: jpeg, png, webp, svg",
            400,
        )

    file_bytes = file.read()
    if len(file_bytes) > MAX_LOGO_SIZE_BYTES:
        return _err("FILE_TOO_LARGE", "Logo must be smaller than 5 MB", 400)

    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "png"
    object_path = f"logos/{company_id}/{uuid.uuid4()}.{ext}"

    try:
        supabase.storage.from_("logos").upload(
            object_path,
            file_bytes,
            {"content-type": content_type, "upsert": "true"},
        )
        public_url_res = supabase.storage.from_("logos").get_public_url(object_path)
        logo_url = (
            public_url_res
            if isinstance(public_url_res, str)
            else public_url_res.get("publicUrl", "")
        )
    except Exception as exc:
        return _err("UPLOAD_FAILED", f"Logo upload failed: {exc}", 500)

    try:
        res = (
            supabase.table("companies")
            .update({"logo_url": logo_url})
            .eq("id", company_id)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Logo uploaded but failed to update company record", 500)

    if not res.data:
        return _err("NOT_FOUND", "Company not found", 404)

    return jsonify({"data": {"logo_url": logo_url}}), 201


# ---------------------------------------------------------------------------
# GET /api/companies/me/landing-page
# ---------------------------------------------------------------------------

_LANDING_EMPTY = lambda company_id: {
    "company_id": company_id,
    "headline": None,
    "subheadline": None,
    "hero_image_url": None,
    "sections": [],
    "cta_text": None,
    "published": False,
}


@companies_bp.get("/me/landing-page")
@require_role(["company_admin"])
def get_landing_page():
    """Return the landing page configuration for the company."""
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    try:
        res = (
            supabase.table("company_landing_pages")
            .select("*")
            .eq("company_id", company_id)
            .single()
            .execute()
        )
    except Exception:
        return jsonify({"data": _LANDING_EMPTY(company_id)})

    if not res.data:
        return jsonify({"data": _LANDING_EMPTY(company_id)})

    raw = res.data
    return jsonify({
        "data": {
            "company_id": raw.get("company_id"),
            "headline": raw.get("headline"),
            "subheadline": raw.get("subheadline"),
            "hero_image_url": raw.get("hero_image_url"),
            "sections": raw.get("sections") or [],
            "cta_text": raw.get("cta_text"),
            "published": raw.get("published", False),
            "updated_at": raw.get("updated_at"),
        }
    })


# ---------------------------------------------------------------------------
# PUT /api/companies/me/landing-page
# ---------------------------------------------------------------------------

_LANDING_PAGE_FIELDS = {"headline", "subheadline", "hero_image_url", "sections", "cta_text", "published"}


@companies_bp.put("/me/landing-page")
@require_role(["company_admin"])
def save_landing_page():
    """Upsert the landing page configuration for the company."""
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    payload = request.get_json(silent=True) or {}

    if "sections" in payload and not isinstance(payload["sections"], list):
        return _err("VALIDATION_ERROR", "'sections' must be an array", 400)

    upsert_data = {k: v for k, v in payload.items() if k in _LANDING_PAGE_FIELDS}
    upsert_data["company_id"] = company_id

    try:
        res = (
            supabase.table("company_landing_pages")
            .upsert(upsert_data, on_conflict="company_id")
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to save landing page", 500)

    if not res.data:
        return _err("SERVER_ERROR", "Failed to save landing page", 500)

    raw = res.data[0]
    return jsonify({
        "data": {
            "company_id": raw.get("company_id"),
            "headline": raw.get("headline"),
            "subheadline": raw.get("subheadline"),
            "hero_image_url": raw.get("hero_image_url"),
            "sections": raw.get("sections") or [],
            "cta_text": raw.get("cta_text"),
            "published": raw.get("published", False),
            "updated_at": raw.get("updated_at"),
        }
    })


# ---------------------------------------------------------------------------
# Helpers — settings
# ---------------------------------------------------------------------------

_DEFAULT_NOTIFICATIONS = {
    "match_alerts": True,
    "messages": True,
    "evaluation_reminders": True,
    "platform_updates": False,
}

_DEFAULT_AI_WEIGHTS = {
    "skills": 40,
    "research": 25,
    "language": 20,
    "growth": 15,
}


def _format_settings(profile: dict, recruiter: dict, company: dict) -> dict:
    """Merge profile + recruiter + company rows into a unified settings response."""
    notifs = recruiter.get("notification_preferences") or _DEFAULT_NOTIFICATIONS
    ai_weights = recruiter.get("ai_matching_weights") or _DEFAULT_AI_WEIGHTS
    return {
        "id": recruiter.get("id"),
        "email": profile.get("email"),
        "name": profile.get("full_name"),
        "avatar_url": profile.get("avatar_url"),
        "phone": recruiter.get("phone"),
        "department": recruiter.get("department"),
        "title": recruiter.get("title"),
        "company": {
            "id": company.get("id"),
            "name": company.get("name"),
            "plan": company.get("plan") or "free",
        },
        "notifications": notifs,
        "ai_matching_weights": ai_weights,
    }


# ---------------------------------------------------------------------------
# GET /api/companies/me/settings
# ---------------------------------------------------------------------------

@companies_bp.get("/me/settings")
@require_role(["company_admin", "recruiter"])
def get_settings():
    """Return the recruiter's settings (profile info + notifications + AI weights)."""
    user_id = g.user_id
    company_id, err = _get_company_id(user_id)
    if err:
        return err

    # Fetch recruiter row
    try:
        rec_res = (
            supabase.table("recruiters")
            .select("id, company_id, title, department, phone, notification_preferences, ai_matching_weights")
            .eq("id", user_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Recruiter record not found", 404)

    if not rec_res.data:
        return _err("NOT_FOUND", "Recruiter record not found", 404)

    # Fetch profile (name, email, avatar)
    try:
        prof_res = (
            supabase.table("profiles")
            .select("full_name, avatar_url")
            .eq("id", user_id)
            .single()
            .execute()
        )
        profile = prof_res.data or {}
    except Exception:
        profile = {}

    profile["email"] = g.user_email

    # Fetch company summary
    try:
        comp_res = (
            supabase.table("companies")
            .select("id, name, size")
            .eq("id", company_id)
            .single()
            .execute()
        )
        company = comp_res.data or {}
    except Exception:
        company = {}

    return jsonify({"data": _format_settings(profile, rec_res.data, company)})


# ---------------------------------------------------------------------------
# PUT /api/companies/me/settings
# ---------------------------------------------------------------------------

@companies_bp.put("/me/settings")
@require_role(["company_admin", "recruiter"])
def update_settings():
    """Update the recruiter's settings."""
    user_id = g.user_id

    payload = request.get_json(silent=True) or {}

    # Validate AI weights if provided
    ai_weights = payload.get("ai_matching_weights")
    if ai_weights is not None:
        if not isinstance(ai_weights, dict):
            return _err("VALIDATION_ERROR", "'ai_matching_weights' must be an object", 400)
        for key in ("skills", "research", "language", "growth"):
            if key in ai_weights:
                try:
                    val = int(ai_weights[key])
                    if val < 0 or val > 100:
                        return _err("VALIDATION_ERROR", f"Weight '{key}' must be between 0 and 100", 400)
                except (ValueError, TypeError):
                    return _err("VALIDATION_ERROR", f"Weight '{key}' must be a number", 400)

    # Validate notifications if provided
    notifs = payload.get("notifications")
    if notifs is not None:
        if not isinstance(notifs, dict):
            return _err("VALIDATION_ERROR", "'notifications' must be an object", 400)

    # Update profile fields (full_name)
    profile_data = {}
    if "name" in payload and payload["name"] is not None:
        profile_data["full_name"] = str(payload["name"]).strip()
    if profile_data:
        try:
            supabase.table("profiles").update(profile_data).eq("id", user_id).execute()
        except Exception:
            pass  # non-critical

    # Update recruiter fields
    recruiter_data = {}
    if "title" in payload:
        recruiter_data["title"] = payload["title"]
    if "department" in payload:
        recruiter_data["department"] = payload["department"]
    if "phone" in payload:
        recruiter_data["phone"] = payload["phone"]
    if notifs is not None:
        recruiter_data["notification_preferences"] = notifs
    if ai_weights is not None:
        recruiter_data["ai_matching_weights"] = ai_weights

    if recruiter_data:
        try:
            supabase.table("recruiters").update(recruiter_data).eq("id", user_id).execute()
        except Exception:
            return _err("SERVER_ERROR", "Failed to update settings", 500)

    if not profile_data and not recruiter_data:
        return _err("VALIDATION_ERROR", "No valid fields provided for update", 400)

    return jsonify({"data": {"id": user_id, "updated_at": "now"}})
