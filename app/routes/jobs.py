"""
Job Lifecycle API — /api/jobs/*

Endpoints:
  GET    /api/jobs                                           — list company jobs
  GET    /api/jobs/<job_id>                                  — get job detail
  POST   /api/jobs                                           — create job
  PUT    /api/jobs/<job_id>                                  — update job
  PATCH  /api/jobs/<job_id>/status                           — change job status
  DELETE /api/jobs/<job_id>                                  — soft-delete (archive)

  GET    /api/jobs/<job_id>/applications                     — list applications
  PATCH  /api/jobs/<job_id>/applications/<app_id>/status     — update application status

  GET    /api/jobs/<job_id>/matching-results                 — latest AI match results
  GET    /api/jobs/<job_id>/matching-runs                    — AI match run history

  GET    /api/jobs/<job_id>/shortlist                        — shortlisted candidates
  POST   /api/jobs/<job_id>/shortlist/compare               — compare up to 3 candidates
"""

from datetime import date, datetime
from flask import Blueprint, jsonify, request, g
from ..services.supabase_client import supabase
from ..middleware.auth import require_role, require_auth

jobs_bp = Blueprint("jobs", __name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_STATUSES = {"draft", "published", "closed", "archived"}

VALID_STATUS_TRANSITIONS = {
    "draft":     ["published", "archived"],
    "published": ["closed"],
    "closed":    ["archived"],
    "archived":  [],
}

# Lifecycle stage machine — the new governed workflow
VALID_LIFECYCLE_TRANSITIONS = {
    "draft":                    ["pending_approval"],
    "pending_approval":         ["draft", "approved_assigning"],       # reject → draft, approve → assigning
    "approved_assigning":       ["university_assigned"],
    "university_assigned":      ["collecting_applications"],
    "collecting_applications":  ["under_curation"],
    "under_curation":           ["forwarded_to_company"],
    "forwarded_to_company":     ["interview_scheduling"],
    "interview_scheduling":     ["interviewing"],
    "interviewing":             ["results_pending"],
    "results_pending":          ["offer_stage"],
    "offer_stage":              ["completed"],
    "completed":                [],
}

# application_status valid transitions
VALID_APP_TRANSITIONS = {
    "pending":    ["shortlisted", "rejected"],
    "shortlisted": ["offered", "rejected"],
    "offered":    ["accepted", "withdrawn"],
    "accepted":   [],
    "rejected":   [],
    "withdrawn":  [],
}

JOB_UPDATABLE_FIELDS = {
    "title", "department", "description", "responsibilities", "qualifications",
    "skills", "requirements", "location", "is_remote", "salary_min", "salary_max",
    "deadline", "employment_type", "experience_level", "openings",
    "required_language", "ai_matching_enabled", "target_universities",
    "priority", "job_benefits",
}

MAX_COMPARE_CANDIDATES = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _get_company_id(user_id: str):
    """Returns (company_id, None) or (None, error_response)."""
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


def _validate_job(data: dict, is_update: bool = False) -> list:
    errors = []
    if not is_update:
        if not str(data.get("title", "")).strip():
            errors.append("'title' is required")
    if "title" in data and data["title"] and len(str(data["title"])) > 200:
        errors.append("'title' must be at most 200 characters")
    if not is_update and "skills" in data:
        if not isinstance(data["skills"], list) or len(data["skills"]) < 1:
            errors.append("'skills' must be a non-empty array")
    if data.get("salary_min") is not None and data.get("salary_max") is not None:
        try:
            if int(data["salary_min"]) >= int(data["salary_max"]):
                errors.append("'salary_min' must be less than 'salary_max'")
        except (ValueError, TypeError):
            errors.append("'salary_min' and 'salary_max' must be numbers")
    if data.get("deadline"):
        try:
            dl = date.fromisoformat(str(data["deadline"]))
            if dl <= date.today():
                errors.append("'deadline' must be a future date")
        except ValueError:
            errors.append("'deadline' must be a valid date (YYYY-MM-DD)")
    if "status" in data and data["status"] not in VALID_STATUSES:
        errors.append(f"'status' must be one of: {sorted(VALID_STATUSES)}")
    return errors


def _format_job_list(raw: dict) -> dict:
    """Compact job shape for the list endpoint."""
    created = raw.get("created_at", "")
    posted_days_ago = None
    if created:
        try:
            delta = datetime.now().astimezone() - datetime.fromisoformat(created)
            posted_days_ago = delta.days
        except Exception:
            pass

    return {
        "id": raw.get("id"),
        "title": raw.get("title"),
        "department": raw.get("department"),
        "location": raw.get("location"),
        "status": raw.get("status"),
        "lifecycle_stage": raw.get("lifecycle_stage", "draft"),
        "approval_status": raw.get("approval_status", "not_submitted"),
        "priority": raw.get("priority", "medium"),
        "deadline": raw.get("deadline"),
        "applications_count": raw.get("applications_count", 0),
        "ai_matches_count": raw.get("ai_matches_count", 0),
        "posted_days_ago": posted_days_ago,
        "created_at": raw.get("created_at"),
    }


def _format_job_detail(raw: dict) -> dict:
    """Full job shape for the detail endpoint."""
    base = _format_job_list(raw)
    base.update({
        "company_id": raw.get("company_id"),
        "recruiter_id": raw.get("recruiter_id"),
        "description": raw.get("description"),
        "responsibilities": raw.get("responsibilities") or [],
        "qualifications": raw.get("qualifications") or [],
        "skills": raw.get("skills") or [],
        "requirements": raw.get("requirements") or [],
        "job_benefits": raw.get("job_benefits") or [],
        "is_remote": raw.get("is_remote", False),
        "salary_min": raw.get("salary_min"),
        "salary_max": raw.get("salary_max"),
        "employment_type": raw.get("employment_type"),
        "experience_level": raw.get("experience_level"),
        "openings": raw.get("openings", 1),
        "required_language": raw.get("required_language"),
        "ai_matching_enabled": raw.get("ai_matching_enabled", False),
        "target_universities": raw.get("target_universities") or [],
        "updated_at": raw.get("updated_at"),
        "closed_at": raw.get("closed_at"),
    })
    return base


def _assert_job_ownership(job_data: dict, company_id: str):
    """Returns error response if job doesn't belong to the company, else None."""
    if job_data.get("company_id") != company_id:
        return _err("FORBIDDEN", "You do not have access to this job posting", 403)
    return None


def _paginate(query, page: int, limit: int, sort: str, order: str):
    """Apply pagination and ordering to a Supabase query builder."""
    offset = (page - 1) * limit
    ascending = order.lower() != "desc"
    return query.order(sort, desc=not ascending).range(offset, offset + limit - 1)


# ---------------------------------------------------------------------------
# GET /api/jobs/browse  (student-facing: published jobs with company info)
# ---------------------------------------------------------------------------

@jobs_bp.get("/browse")
@require_auth
def browse_jobs():
    """Return published jobs that students can browse and apply to."""
    page = max(1, int(request.args.get("page", 1)))
    limit = min(100, max(1, int(request.args.get("limit", 20))))
    search = request.args.get("search", "").strip()
    location = request.args.get("location", "").strip()
    sort = request.args.get("sort", "created_at")
    order = request.args.get("order", "desc")

    try:
        query = (
            supabase.table("jobs")
            .select("id, title, department, location, description, skills, "
                    "salary_min, salary_max, deadline, employment_type, "
                    "is_remote, openings, company_id, created_at")
            .eq("status", "published")
        )
        ascending = order.lower() != "desc"
        if sort in ("created_at", "deadline", "title"):
            query = query.order(sort, desc=not ascending)
        else:
            query = query.order("created_at", desc=True)

        result = query.execute()
        rows = result.data or []
    except Exception as exc:
        return _err("SERVER_ERROR", f"Failed to fetch jobs: {exc}", 500)

    # In-memory search
    if search:
        sl = search.lower()
        rows = [
            r for r in rows
            if sl in (r.get("title") or "").lower()
            or sl in (r.get("department") or "").lower()
            or any(sl in s.lower() for s in (r.get("skills") or []))
        ]

    if location:
        ll = location.lower()
        rows = [r for r in rows if ll in (r.get("location") or "").lower()]

    # Gather company info
    company_ids = list({r.get("company_id") for r in rows if r.get("company_id")})
    companies_map = {}
    if company_ids:
        try:
            comp_res = (
                supabase.table("companies")
                .select("id, name, logo_url, industry, location")
                .in_("id", company_ids)
                .execute()
            )
            for c in (comp_res.data or []):
                companies_map[c["id"]] = c
        except Exception:
            pass

    total = len(rows)
    page_rows = rows[(page - 1) * limit : page * limit]

    data = []
    for r in page_rows:
        company = companies_map.get(r.get("company_id")) or {}
        created = r.get("created_at", "")
        posted_days_ago = None
        if created:
            try:
                delta = datetime.now().astimezone() - datetime.fromisoformat(created)
                posted_days_ago = delta.days
            except Exception:
                pass

        data.append({
            "id": r["id"],
            "title": r.get("title"),
            "department": r.get("department"),
            "location": r.get("location") or company.get("location"),
            "description": (r.get("description") or "")[:200],
            "skills": r.get("skills") or [],
            "salary_min": r.get("salary_min"),
            "salary_max": r.get("salary_max"),
            "deadline": r.get("deadline"),
            "employment_type": r.get("employment_type"),
            "is_remote": r.get("is_remote", False),
            "openings": r.get("openings", 1),
            "posted_days_ago": posted_days_ago,
            "company_id": r.get("company_id"),
            "company_name": company.get("name"),
            "company_logo_url": company.get("logo_url"),
            "company_industry": company.get("industry"),
            "created_at": r.get("created_at"),
        })

    return jsonify({
        "data": data,
        "meta": {"total": total, "page": page, "limit": limit,
                 "pages": (total + limit - 1) // limit if limit else 1},
    })


# ---------------------------------------------------------------------------
# GET /api/jobs/browse/<job_id>  (student-facing: full detail of a published job)
# ---------------------------------------------------------------------------

@jobs_bp.get("/browse/<string:job_id>")
@require_auth
def browse_job_detail(job_id: str):
    """Return full details of a published job for any authenticated user."""
    try:
        job_res = (
            supabase.table("jobs")
            .select("*")
            .eq("id", job_id)
            .eq("status", "published")
            .maybe_single()
            .execute()
        )
    except Exception as exc:
        return _err("SERVER_ERROR", f"Failed to fetch job: {exc}", 500)

    if not job_res.data:
        return _err("NOT_FOUND", "Job not found or not published", 404)

    raw = job_res.data

    # Fetch company info
    company = {}
    if raw.get("company_id"):
        try:
            comp_res = (
                supabase.table("companies")
                .select("id, name, logo_url, industry, location, website, description, size")
                .eq("id", raw["company_id"])
                .maybe_single()
                .execute()
            )
            company = comp_res.data or {}
        except Exception:
            pass

    created = raw.get("created_at", "")
    posted_days_ago = None
    if created:
        try:
            delta = datetime.now().astimezone() - datetime.fromisoformat(created)
            posted_days_ago = delta.days
        except Exception:
            pass

    return jsonify({
        "data": {
            "id": raw["id"],
            "title": raw.get("title"),
            "department": raw.get("department"),
            "location": raw.get("location") or company.get("location"),
            "description": raw.get("description"),
            "responsibilities": raw.get("responsibilities") or [],
            "qualifications": raw.get("qualifications") or [],
            "skills": raw.get("skills") or [],
            "requirements": raw.get("requirements") or [],
            "job_benefits": raw.get("job_benefits") or [],
            "salary_min": raw.get("salary_min"),
            "salary_max": raw.get("salary_max"),
            "deadline": raw.get("deadline"),
            "employment_type": raw.get("employment_type"),
            "experience_level": raw.get("experience_level"),
            "is_remote": raw.get("is_remote", False),
            "openings": raw.get("openings", 1),
            "required_language": raw.get("required_language"),
            "posted_days_ago": posted_days_ago,
            "created_at": raw.get("created_at"),
            "company_id": raw.get("company_id"),
            "company_name": company.get("name"),
            "company_logo_url": company.get("logo_url"),
            "company_industry": company.get("industry"),
            "company_location": company.get("location"),
            "company_website": company.get("website"),
            "company_description": company.get("description"),
            "company_size": company.get("size"),
        }
    })


# ---------------------------------------------------------------------------
# GET /api/jobs
# ---------------------------------------------------------------------------

@jobs_bp.get("/")
@require_role(["company_admin", "recruiter"])
def list_jobs():
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    status_filter = request.args.get("status")
    page = max(1, int(request.args.get("page", 1)))
    limit = min(100, max(1, int(request.args.get("limit", 20))))
    sort = request.args.get("sort", "created_at")
    order = request.args.get("order", "desc")

    if status_filter and status_filter not in VALID_STATUSES:
        return _err("VALIDATION_ERROR", f"Invalid status filter: {status_filter}", 400)

    allowed_sort_fields = {"created_at", "updated_at", "title", "deadline", "status"}
    if sort not in allowed_sort_fields:
        sort = "created_at"

    try:
        query = (
            supabase.table("jobs")
            .select("*, applications(count), ai_match_results(count)", count="exact")
            .eq("company_id", company_id)
        )
        if status_filter:
            query = query.eq("status", status_filter)

        offset = (page - 1) * limit
        ascending = order.lower() != "desc"
        query = query.order(sort, desc=not ascending).range(offset, offset + limit - 1)

        res = query.execute()
    except Exception:
        # Fallback: simpler query without embedded counts
        try:
            query = (
                supabase.table("jobs")
                .select("*")
                .eq("company_id", company_id)
            )
            if status_filter:
                query = query.eq("status", status_filter)
            offset = (page - 1) * limit
            ascending = order.lower() != "desc"
            query = query.order(sort, desc=not ascending).range(offset, offset + limit - 1)
            res = query.execute()
        except Exception:
            return _err("SERVER_ERROR", "Failed to fetch job listings", 500)

    jobs = res.data or []
    try:
        raw_count = res.count if hasattr(res, "count") else None
        total = int(raw_count) if raw_count is not None else len(jobs)
    except (TypeError, ValueError):
        total = len(jobs)

    return jsonify({
        "data": [_format_job_list(j) for j in jobs],
        "meta": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": max(1, -(-total // limit)),  # ceiling division
        },
    })


# ---------------------------------------------------------------------------
# GET /api/jobs/<job_id>
# ---------------------------------------------------------------------------

@jobs_bp.get("/<string:job_id>")
@require_role(["company_admin", "recruiter"])
def get_job(job_id):
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    try:
        res = (
            supabase.table("jobs")
            .select("*")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not res.data:
        return _err("NOT_FOUND", "Job not found", 404)

    ownership_err = _assert_job_ownership(res.data, company_id)
    if ownership_err:
        return ownership_err

    return jsonify({"data": _format_job_detail(res.data)})


# ---------------------------------------------------------------------------
# POST /api/jobs
# ---------------------------------------------------------------------------

@jobs_bp.post("/")
@require_role(["company_admin", "recruiter"])
def create_job():
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    validation_errors = _validate_job(payload, is_update=False)
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

    insert_data = {k: v for k, v in payload.items() if k in JOB_UPDATABLE_FIELDS}
    insert_data["company_id"] = company_id
    insert_data["recruiter_id"] = g.user_id
    insert_data.setdefault("status", "draft")

    try:
        res = supabase.table("jobs").insert(insert_data).execute()
    except Exception:
        return _err("SERVER_ERROR", "Failed to create job posting", 500)

    if not res.data:
        return _err("SERVER_ERROR", "Failed to create job posting", 500)

    return jsonify({"data": _format_job_detail(res.data[0])}), 201


# ---------------------------------------------------------------------------
# PUT /api/jobs/<job_id>
# ---------------------------------------------------------------------------

@jobs_bp.put("/<string:job_id>")
@require_role(["company_admin", "recruiter"])
def update_job(job_id):
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    try:
        existing = (
            supabase.table("jobs")
            .select("id, company_id, status")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not existing.data:
        return _err("NOT_FOUND", "Job not found", 404)

    ownership_err = _assert_job_ownership(existing.data, company_id)
    if ownership_err:
        return ownership_err

    payload = request.get_json(silent=True) or {}
    # Disallow direct status change via PUT — use PATCH /status instead
    payload.pop("status", None)

    validation_errors = _validate_job(payload, is_update=True)
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

    update_data = {k: v for k, v in payload.items() if k in JOB_UPDATABLE_FIELDS}
    if not update_data:
        return _err("VALIDATION_ERROR", "No valid fields provided for update", 400)

    try:
        res = (
            supabase.table("jobs")
            .update(update_data)
            .eq("id", job_id)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to update job posting", 500)

    if not res.data:
        return _err("NOT_FOUND", "Job not found", 404)

    return jsonify({"data": _format_job_detail(res.data[0])})


# ---------------------------------------------------------------------------
# PATCH /api/jobs/<job_id>/status
# ---------------------------------------------------------------------------

@jobs_bp.patch("/<string:job_id>/status")
@require_role(["company_admin", "recruiter"])
def update_job_status(job_id):
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    new_status = payload.get("status")
    if not new_status:
        return _err("VALIDATION_ERROR", "'status' is required", 400)
    if new_status not in VALID_STATUSES:
        return _err("VALIDATION_ERROR", f"Invalid status. Must be one of: {sorted(VALID_STATUSES)}", 400)

    try:
        existing = (
            supabase.table("jobs")
            .select("id, company_id, status")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not existing.data:
        return _err("NOT_FOUND", "Job not found", 404)

    ownership_err = _assert_job_ownership(existing.data, company_id)
    if ownership_err:
        return ownership_err

    current_status = existing.data.get("status", "draft")
    allowed = VALID_STATUS_TRANSITIONS.get(current_status, [])
    if new_status not in allowed:
        return (
            jsonify({
                "error": {
                    "code": "INVALID_TRANSITION",
                    "message": (
                        f"Cannot transition from '{current_status}' to '{new_status}'. "
                        f"Allowed: {allowed or 'none'}"
                    ),
                }
            }),
            422,
        )

    update_data = {"status": new_status}
    if new_status == "closed":
        update_data["closed_at"] = datetime.utcnow().isoformat()

    try:
        res = (
            supabase.table("jobs")
            .update(update_data)
            .eq("id", job_id)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to update job status", 500)

    if not res.data:
        return _err("NOT_FOUND", "Job not found", 404)

    return jsonify({
        "data": {
            "id": job_id,
            "status": new_status,
            "previous_status": current_status,
        }
    })


# ---------------------------------------------------------------------------
# DELETE /api/jobs/<job_id>  (soft-delete → archive)
# ---------------------------------------------------------------------------

@jobs_bp.delete("/<string:job_id>")
@require_role(["company_admin"])
def delete_job(job_id):
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    try:
        existing = (
            supabase.table("jobs")
            .select("id, company_id, status")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not existing.data:
        return _err("NOT_FOUND", "Job not found", 404)

    ownership_err = _assert_job_ownership(existing.data, company_id)
    if ownership_err:
        return ownership_err

    try:
        supabase.table("jobs").update({"status": "archived"}).eq("id", job_id).execute()
    except Exception:
        return _err("SERVER_ERROR", "Failed to archive job posting", 500)

    return "", 204


# ---------------------------------------------------------------------------
# GET /api/jobs/<job_id>/applications
# ---------------------------------------------------------------------------

@jobs_bp.get("/<string:job_id>/applications")
@require_role(["company_admin", "recruiter"])
def list_applications(job_id):
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    # Verify job belongs to company
    try:
        job_res = (
            supabase.table("jobs")
            .select("id, company_id")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not job_res.data:
        return _err("NOT_FOUND", "Job not found", 404)

    ownership_err = _assert_job_ownership(job_res.data, company_id)
    if ownership_err:
        return ownership_err

    status_filter = request.args.get("status")
    page = max(1, int(request.args.get("page", 1)))
    limit = min(100, max(1, int(request.args.get("limit", 20))))

    try:
        query = (
            supabase.table("applications")
            .select(
                "id, student_id, status, ai_score, cover_letter, created_at, updated_at, note,"
                "students(profiles(full_name, university_id, universities(name)))"
            )
            .eq("job_id", job_id)
        )
        if status_filter:
            query = query.eq("status", status_filter)

        offset = (page - 1) * limit
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        res = query.execute()
    except Exception:
        # Fallback: simple query without joins
        try:
            query = (
                supabase.table("applications")
                .select("id, student_id, status, ai_score, cover_letter, created_at, updated_at, note")
                .eq("job_id", job_id)
            )
            if status_filter:
                query = query.eq("status", status_filter)
            offset = (page - 1) * limit
            res = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
        except Exception:
            return _err("SERVER_ERROR", "Failed to fetch applications", 500)

    apps = res.data or []

    formatted = []
    for app in apps:
        student_data = app.get("students") or {}
        profile_data = student_data.get("profiles") or {}
        uni_data = profile_data.get("universities") or {}
        formatted.append({
            "id": app.get("id"),
            "student_id": app.get("student_id"),
            "student_name": profile_data.get("full_name"),
            "student_school": uni_data.get("name"),
            "status": app.get("status"),
            "ai_score": app.get("ai_score"),
            "cover_letter": app.get("cover_letter"),
            "note": app.get("note"),
            "applied_at": app.get("created_at"),
            "updated_at": app.get("updated_at"),
        })

    # Status breakdown counts
    all_statuses = ["pending", "shortlisted", "rejected", "offered", "accepted", "withdrawn"]
    by_status = {s: sum(1 for a in formatted if a["status"] == s) for s in all_statuses}

    return jsonify({
        "data": formatted,
        "meta": {
            "page": page,
            "limit": limit,
            "total": len(formatted),
            "by_status": by_status,
        },
    })


# ---------------------------------------------------------------------------
# PATCH /api/jobs/<job_id>/applications/<app_id>/status
# ---------------------------------------------------------------------------

@jobs_bp.patch("/<string:job_id>/applications/<string:app_id>/status")
@require_role(["company_admin", "recruiter"])
def update_application_status(job_id, app_id):
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    new_status = payload.get("status")
    if not new_status:
        return _err("VALIDATION_ERROR", "'status' is required", 400)

    # Verify job ownership
    try:
        job_res = (
            supabase.table("jobs")
            .select("id, company_id")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not job_res.data:
        return _err("NOT_FOUND", "Job not found", 404)

    ownership_err = _assert_job_ownership(job_res.data, company_id)
    if ownership_err:
        return ownership_err

    # Fetch application
    try:
        app_res = (
            supabase.table("applications")
            .select("id, job_id, status")
            .eq("id", app_id)
            .eq("job_id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Application not found", 404)

    if not app_res.data:
        return _err("NOT_FOUND", "Application not found", 404)

    current_status = app_res.data.get("status", "pending")
    allowed = VALID_APP_TRANSITIONS.get(current_status, [])
    if new_status not in allowed:
        return (
            jsonify({
                "error": {
                    "code": "INVALID_TRANSITION",
                    "message": (
                        f"Cannot move application from '{current_status}' to '{new_status}'. "
                        f"Allowed: {allowed or 'none'}"
                    ),
                }
            }),
            422,
        )

    update_data = {"status": new_status}
    if new_status == "shortlisted":
        update_data["shortlisted_at"] = datetime.utcnow().isoformat()
    if payload.get("note"):
        update_data["note"] = payload["note"]

    try:
        res = (
            supabase.table("applications")
            .update(update_data)
            .eq("id", app_id)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to update application status", 500)

    if not res.data:
        return _err("NOT_FOUND", "Application not found", 404)

    return jsonify({
        "data": {
            "id": app_id,
            "job_id": job_id,
            "status": new_status,
            "previous_status": current_status,
        }
    })


# ---------------------------------------------------------------------------
# GET /api/jobs/<job_id>/matching-results
# ---------------------------------------------------------------------------

@jobs_bp.get("/<string:job_id>/matching-results")
@require_role(["company_admin", "recruiter"])
def get_matching_results(job_id):
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    try:
        job_res = (
            supabase.table("jobs")
            .select("id, company_id")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not job_res.data:
        return _err("NOT_FOUND", "Job not found", 404)

    ownership_err = _assert_job_ownership(job_res.data, company_id)
    if ownership_err:
        return ownership_err

    try:
        res = (
            supabase.table("ai_match_results")
            .select("id, student_id, score, explanation, created_at, students(profiles(full_name, university_id))")
            .eq("job_id", job_id)
            .order("score", desc=True)
            .execute()
        )
    except Exception:
        # Fallback without join
        try:
            res = (
                supabase.table("ai_match_results")
                .select("id, student_id, score, explanation, created_at")
                .eq("job_id", job_id)
                .order("score", desc=True)
                .execute()
            )
        except Exception:
            return _err("SERVER_ERROR", "Failed to fetch matching results", 500)

    results = res.data or []
    formatted = []
    for r in results:
        student_data = r.get("students") or {}
        profile_data = student_data.get("profiles") or {}
        explanation = r.get("explanation") or {}
        formatted.append({
            "id": r.get("id"),
            "student_id": r.get("student_id"),
            "student_name": profile_data.get("full_name"),
            "score": r.get("score"),
            "skill_match": explanation.get("skill_match"),
            "research_sim": explanation.get("research_sim"),
            "lang_readiness": explanation.get("lang_readiness"),
            "learning_traj": explanation.get("learning_traj"),
            "explanation": explanation,
            "matched_at": r.get("created_at"),
        })

    return jsonify({
        "data": formatted,
        "meta": {"total": len(formatted)},
    })


# ---------------------------------------------------------------------------
# GET /api/jobs/<job_id>/matching-runs
# ---------------------------------------------------------------------------

@jobs_bp.get("/<string:job_id>/matching-runs")
@require_role(["company_admin", "recruiter"])
def get_matching_runs(job_id):
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    try:
        job_res = (
            supabase.table("jobs")
            .select("id, company_id")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not job_res.data:
        return _err("NOT_FOUND", "Job not found", 404)

    ownership_err = _assert_job_ownership(job_res.data, company_id)
    if ownership_err:
        return ownership_err

    try:
        res = (
            supabase.table("ai_matching_runs")
            .select("id, triggered_by, status, total_analyzed, top_score, created_at, updated_at")
            .eq("job_id", job_id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to fetch matching runs", 500)

    runs = res.data or []
    formatted = [
        {
            "run_id": r.get("id"),
            "triggered_by": r.get("triggered_by"),
            "triggered_at": r.get("created_at"),
            "status": r.get("status"),
            "total_analyzed": r.get("total_analyzed", 0),
            "top_score": r.get("top_score"),
        }
        for r in runs
    ]

    return jsonify({"data": formatted, "meta": {"total": len(formatted)}})


# ---------------------------------------------------------------------------
# GET /api/jobs/<job_id>/shortlist
# ---------------------------------------------------------------------------

@jobs_bp.get("/<string:job_id>/shortlist")
@require_role(["company_admin", "recruiter"])
def get_shortlist(job_id):
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    try:
        job_res = (
            supabase.table("jobs")
            .select("id, company_id")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not job_res.data:
        return _err("NOT_FOUND", "Job not found", 404)

    ownership_err = _assert_job_ownership(job_res.data, company_id)
    if ownership_err:
        return ownership_err

    try:
        apps_res = (
            supabase.table("applications")
            .select(
                "id, student_id, status, ai_score, created_at, updated_at, shortlisted_at,"
                "students(skills, profiles(full_name, university_id, universities(name)))"
            )
            .eq("job_id", job_id)
            .eq("status", "shortlisted")
            .order("ai_score", desc=True)
            .execute()
        )
    except Exception:
        try:
            apps_res = (
                supabase.table("applications")
                .select("id, student_id, status, ai_score, created_at, updated_at, shortlisted_at")
                .eq("job_id", job_id)
                .eq("status", "shortlisted")
                .order("ai_score", desc=True)
                .execute()
            )
        except Exception:
            return _err("SERVER_ERROR", "Failed to fetch shortlist", 500)

    # Fetch AI match details for each student
    student_ids = [a.get("student_id") for a in (apps_res.data or []) if a.get("student_id")]
    match_map = {}
    if student_ids:
        try:
            match_res = (
                supabase.table("ai_match_results")
                .select("student_id, score, explanation")
                .eq("job_id", job_id)
                .in_("student_id", student_ids)
                .order("created_at", desc=True)
                .execute()
            )
            for m in (match_res.data or []):
                sid = m.get("student_id")
                if sid not in match_map:
                    match_map[sid] = m
        except Exception:
            pass

    formatted = []
    for app in (apps_res.data or []):
        sid = app.get("student_id")
        student_data = app.get("students") or {}
        profile_data = student_data.get("profiles") or {}
        uni_data = profile_data.get("universities") or {}
        match_data = match_map.get(sid, {})
        explanation = match_data.get("explanation") or {}

        formatted.append({
            "application_id": app.get("id"),
            "student_id": sid,
            "name": profile_data.get("full_name"),
            "school": uni_data.get("name"),
            "skills": student_data.get("skills") or [],
            "ai_score": app.get("ai_score") or match_data.get("score"),
            "skill_match": explanation.get("skill_match"),
            "research_sim": explanation.get("research_sim"),
            "lang_readiness": explanation.get("lang_readiness"),
            "learning_traj": explanation.get("learning_traj"),
            "status": app.get("status"),
            "shortlisted_at": app.get("shortlisted_at") or app.get("updated_at"),
        })

    return jsonify({"data": formatted, "meta": {"total": len(formatted)}})


# ---------------------------------------------------------------------------
# POST /api/jobs/<job_id>/shortlist/compare
# ---------------------------------------------------------------------------

@jobs_bp.post("/<string:job_id>/shortlist/compare")
@require_role(["company_admin", "recruiter"])
def compare_candidates(job_id):
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    candidate_ids = payload.get("candidate_ids", [])

    if not isinstance(candidate_ids, list) or len(candidate_ids) < 2:
        return _err("VALIDATION_ERROR", "Provide 2–3 candidate IDs in 'candidate_ids'", 400)
    if len(candidate_ids) > MAX_COMPARE_CANDIDATES:
        return _err(
            "VALIDATION_ERROR",
            f"Cannot compare more than {MAX_COMPARE_CANDIDATES} candidates at once",
            400,
        )

    try:
        job_res = (
            supabase.table("jobs")
            .select("id, company_id")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not job_res.data:
        return _err("NOT_FOUND", "Job not found", 404)

    ownership_err = _assert_job_ownership(job_res.data, company_id)
    if ownership_err:
        return ownership_err

    try:
        apps_res = (
            supabase.table("applications")
            .select(
                "id, student_id, status, ai_score,"
                "students(skills, profiles(full_name, university_id, universities(name)))"
            )
            .eq("job_id", job_id)
            .in_("student_id", candidate_ids)
            .execute()
        )
    except Exception:
        try:
            apps_res = (
                supabase.table("applications")
                .select("id, student_id, status, ai_score")
                .eq("job_id", job_id)
                .in_("student_id", candidate_ids)
                .execute()
            )
        except Exception:
            return _err("SERVER_ERROR", "Failed to fetch candidates for comparison", 500)

    match_map = {}
    try:
        match_res = (
            supabase.table("ai_match_results")
            .select("student_id, score, explanation")
            .eq("job_id", job_id)
            .in_("student_id", candidate_ids)
            .execute()
        )
        for m in (match_res.data or []):
            sid = m.get("student_id")
            if sid not in match_map:
                match_map[sid] = m
    except Exception:
        pass

    candidates = []
    for app in (apps_res.data or []):
        sid = app.get("student_id")
        student_data = app.get("students") or {}
        profile_data = student_data.get("profiles") or {}
        uni_data = profile_data.get("universities") or {}
        match_data = match_map.get(sid, {})
        explanation = match_data.get("explanation") or {}

        skill_match = explanation.get("skill_match", 0)
        research_sim = explanation.get("research_sim", 0)
        lang_readiness = explanation.get("lang_readiness", 0)
        learning_traj = explanation.get("learning_traj", 0)

        candidates.append({
            "application_id": app.get("id"),
            "student_id": sid,
            "name": profile_data.get("full_name"),
            "school": uni_data.get("name"),
            "skills": student_data.get("skills") or [],
            "ai_score": app.get("ai_score") or match_data.get("score"),
            "dimensions": {
                "skill_match": skill_match,
                "research_sim": research_sim,
                "lang_readiness": lang_readiness,
                "learning_traj": learning_traj,
            },
            "radar_data": [
                {"axis": "Skill Match", "value": skill_match},
                {"axis": "Research Sim", "value": research_sim},
                {"axis": "Lang Readiness", "value": lang_readiness},
                {"axis": "Learning Traj", "value": learning_traj},
            ],
        })

    return jsonify({"data": {"candidates": candidates}})


# ---------------------------------------------------------------------------
# POST /api/jobs/<job_id>/submit-for-approval
# ---------------------------------------------------------------------------

@jobs_bp.post("/<string:job_id>/submit-for-approval")
@require_role(["company_admin", "recruiter"])
def submit_for_approval(job_id):
    """Company admin submits a draft JD for platform admin review."""
    from ..services.notification_service import notify_admins

    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    try:
        existing = (
            supabase.table("jobs")
            .select("id, company_id, status, lifecycle_stage, title")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not existing.data:
        return _err("NOT_FOUND", "Job not found", 404)

    ownership_err = _assert_job_ownership(existing.data, company_id)
    if ownership_err:
        return ownership_err

    current_stage = existing.data.get("lifecycle_stage", "draft")
    if current_stage != "draft":
        return _err(
            "INVALID_TRANSITION",
            f"Can only submit for approval from 'draft' stage, currently '{current_stage}'",
            422,
        )

    try:
        supabase.table("jobs").update({
            "lifecycle_stage": "pending_approval",
            "approval_status": "pending",
            "submitted_for_approval_at": datetime.utcnow().isoformat(),
        }).eq("id", job_id).execute()
    except Exception:
        return _err("SERVER_ERROR", "Failed to submit for approval", 500)

    # Notify platform admins
    title = existing.data.get("title", "Untitled Job")
    notify_admins(
        "jd_submitted_for_approval",
        "New JD submitted for approval",
        f"'{title}' has been submitted for review.",
        "job", job_id,
    )

    return jsonify({
        "data": {
            "id": job_id,
            "lifecycle_stage": "pending_approval",
            "approval_status": "pending",
        }
    })


# ---------------------------------------------------------------------------
# GET /api/jobs/<job_id>/curated-candidates
# ---------------------------------------------------------------------------

@jobs_bp.get("/<string:job_id>/curated-candidates")
@require_role(["company_admin", "recruiter"])
def get_curated_candidates(job_id):
    """Get candidates forwarded by the platform admin."""
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    try:
        job_res = (
            supabase.table("jobs")
            .select("id, company_id")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not job_res.data:
        return _err("NOT_FOUND", "Job not found", 404)

    ownership_err = _assert_job_ownership(job_res.data, company_id)
    if ownership_err:
        return ownership_err

    # Get forwarded curation entries
    try:
        curation_res = (
            supabase.table("admin_application_curation")
            .select("application_id, curation_note, forwarded_at")
            .eq("job_id", job_id)
            .eq("curation_status", "included")
            .not_.is_("forwarded_at", "null")
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to fetch curated candidates", 500)

    curated = curation_res.data or []
    if not curated:
        return jsonify({"data": [], "meta": {"total": 0}})

    app_ids = [c["application_id"] for c in curated]
    curation_map = {c["application_id"]: c for c in curated}

    # Fetch applications
    try:
        apps_res = (
            supabase.table("applications")
            .select("id, student_id, status, ai_score, cover_letter, created_at")
            .in_("id", app_ids)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to fetch applications", 500)

    apps = apps_res.data or []
    student_ids = list({a["student_id"] for a in apps if a.get("student_id")})

    # Fetch student details (students + profiles + universities) separately
    students_map = {}
    profiles_map = {}
    universities_map = {}

    if student_ids:
        try:
            stu_res = (
                supabase.table("students")
                .select("id, department, gpa, graduation_year, skills, university_id")
                .in_("id", student_ids)
                .execute()
            )
            for s in (stu_res.data or []):
                students_map[s["id"]] = s
        except Exception:
            pass

        try:
            prof_res = (
                supabase.table("profiles")
                .select("id, full_name, avatar_url, university_id")
                .in_("id", student_ids)
                .execute()
            )
            for p in (prof_res.data or []):
                profiles_map[p["id"]] = p
        except Exception:
            pass

        uni_ids = list({s.get("university_id") for s in students_map.values() if s.get("university_id")})
        if uni_ids:
            try:
                uni_res = (
                    supabase.table("universities")
                    .select("id, name, location")
                    .in_("id", uni_ids)
                    .execute()
                )
                for u in (uni_res.data or []):
                    universities_map[u["id"]] = u
            except Exception:
                pass

    formatted = []
    for app in apps:
        sid = app.get("student_id")
        stu = students_map.get(sid, {})
        prof = profiles_map.get(sid, {})
        uni = universities_map.get(stu.get("university_id", ""), {})
        cur = curation_map.get(app["id"], {})
        formatted.append({
            "application_id": app["id"],
            "student_id": sid,
            "student_name": prof.get("full_name"),
            "student_avatar_url": prof.get("avatar_url"),
            "student_school": uni.get("name"),
            "student_school_location": uni.get("location"),
            "student_department": stu.get("department"),
            "student_gpa": stu.get("gpa"),
            "student_graduation_year": stu.get("graduation_year"),
            "skills": stu.get("skills") or [],
            "ai_score": app.get("ai_score"),
            "cover_letter": app.get("cover_letter"),
            "status": app.get("status"),
            "curation_note": cur.get("curation_note"),
            "forwarded_at": cur.get("forwarded_at"),
            "applied_at": app.get("created_at"),
        })

    return jsonify({"data": formatted, "meta": {"total": len(formatted)}})


# ---------------------------------------------------------------------------
# POST /api/jobs/<job_id>/interview-slots
# ---------------------------------------------------------------------------

@jobs_bp.post("/<string:job_id>/interview-slots")
@require_role(["company_admin", "recruiter"])
def submit_interview_slots(job_id):
    """Company admin submits proposed interview time slots."""
    from ..services.notification_service import notify_admins

    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    try:
        existing = (
            supabase.table("jobs")
            .select("id, company_id, lifecycle_stage, title")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not existing.data:
        return _err("NOT_FOUND", "Job not found", 404)

    ownership_err = _assert_job_ownership(existing.data, company_id)
    if ownership_err:
        return ownership_err

    current_stage = existing.data.get("lifecycle_stage")
    if current_stage != "forwarded_to_company":
        return _err(
            "INVALID_TRANSITION",
            f"Interview slots can only be submitted at 'forwarded_to_company' stage, currently '{current_stage}'",
            422,
        )

    payload = request.get_json(silent=True) or {}
    slots = payload.get("slots", [])
    note = payload.get("note", "")

    if not slots or not isinstance(slots, list):
        return _err("VALIDATION_ERROR", "'slots' must be a non-empty array", 400)

    # Create interview round
    try:
        round_res = supabase.table("interview_rounds").insert({
            "job_id": job_id,
            "proposed_slots": slots,
            "company_slot_note": note,
            "status": "slots_submitted",
        }).execute()
    except Exception:
        return _err("SERVER_ERROR", "Failed to create interview round", 500)

    # Advance lifecycle
    try:
        supabase.table("jobs").update({
            "lifecycle_stage": "interview_scheduling",
        }).eq("id", job_id).execute()
    except Exception:
        pass

    notify_admins(
        "interview_slots_submitted",
        "Interview slots submitted",
        f"Company has submitted interview slots for '{existing.data.get('title')}'.",
        "job", job_id,
    )

    return jsonify({
        "data": round_res.data[0] if round_res.data else {},
        "lifecycle_stage": "interview_scheduling",
    }), 201


# ---------------------------------------------------------------------------
# GET /api/jobs/<job_id>/interview-slots
# ---------------------------------------------------------------------------

@jobs_bp.get("/<string:job_id>/interview-slots")
@require_role(["company_admin", "recruiter"])
def get_interview_slots(job_id):
    """Get interview rounds and schedules for a job."""
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    try:
        job_res = (
            supabase.table("jobs")
            .select("id, company_id")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not job_res.data:
        return _err("NOT_FOUND", "Job not found", 404)

    ownership_err = _assert_job_ownership(job_res.data, company_id)
    if ownership_err:
        return ownership_err

    try:
        rounds_res = (
            supabase.table("interview_rounds")
            .select("*")
            .eq("job_id", job_id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to fetch interview rounds", 500)

    rounds = rounds_res.data or []
    round_ids = [r["id"] for r in rounds]

    schedules = []
    if round_ids:
        try:
            sched_res = (
                supabase.table("interview_schedules")
                .select("*, students(profiles(full_name))")
                .in_("round_id", round_ids)
                .order("created_at", desc=False)
                .execute()
            )
            schedules = sched_res.data or []
        except Exception:
            try:
                sched_res = (
                    supabase.table("interview_schedules")
                    .select("*")
                    .in_("round_id", round_ids)
                    .execute()
                )
                schedules = sched_res.data or []
            except Exception:
                pass

    return jsonify({"data": {"rounds": rounds, "schedules": schedules}})


# ---------------------------------------------------------------------------
# POST /api/jobs/<job_id>/interview-results
# ---------------------------------------------------------------------------

@jobs_bp.post("/<string:job_id>/interview-results")
@require_role(["company_admin", "recruiter"])
def submit_interview_results(job_id):
    """Company admin submits interview results and offer decisions."""
    from ..services.notification_service import notify_admins

    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    try:
        existing = (
            supabase.table("jobs")
            .select("id, company_id, lifecycle_stage, title")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not existing.data:
        return _err("NOT_FOUND", "Job not found", 404)

    ownership_err = _assert_job_ownership(existing.data, company_id)
    if ownership_err:
        return ownership_err

    current_stage = existing.data.get("lifecycle_stage")
    if current_stage != "results_pending":
        return _err(
            "INVALID_TRANSITION",
            f"Results can only be submitted at 'results_pending' stage, currently '{current_stage}'",
            422,
        )

    payload = request.get_json(silent=True) or {}
    results = payload.get("results", [])
    if not results or not isinstance(results, list):
        return _err("VALIDATION_ERROR", "'results' must be a non-empty array", 400)

    # Update interview schedules and create offers for accepted
    created_offers = []
    for r in results:
        schedule_id = r.get("schedule_id")
        result = r.get("result", "pending")
        offer_decision = r.get("offer_decision")
        note = r.get("note", "")

        if schedule_id:
            try:
                supabase.table("interview_schedules").update({
                    "result": result,
                    "result_note": note,
                    "offer_decision": offer_decision,
                    "result_submitted_at": datetime.utcnow().isoformat(),
                }).eq("id", schedule_id).execute()
            except Exception:
                pass

        # Create offer if decision is "offer"
        if offer_decision == "offer":
            app_id = r.get("application_id")
            student_id = r.get("student_id")
            if app_id and student_id:
                # Build offer_details with offer_type and expected_start_date
                offer_details = r.get("offer_details", {})
                if r.get("offer_type"):
                    offer_details["offer_type"] = r["offer_type"]
                if r.get("expected_start_date"):
                    offer_details["expected_start_date"] = r["expected_start_date"]
                try:
                    offer_res = supabase.table("offers").insert({
                        "job_id": job_id,
                        "application_id": app_id,
                        "student_id": student_id,
                        "company_id": company_id,
                        "offer_details": offer_details,
                        "status": "pending",
                        "response_deadline": r.get("response_deadline"),
                    }).execute()
                    if offer_res.data:
                        created_offers.append(offer_res.data[0])
                except Exception:
                    pass

    # Update interview round status
    try:
        rounds_res = (
            supabase.table("interview_rounds")
            .select("id")
            .eq("job_id", job_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if rounds_res.data:
            supabase.table("interview_rounds").update({
                "status": "results_submitted",
                "results_submitted_at": datetime.utcnow().isoformat(),
            }).eq("id", rounds_res.data[0]["id"]).execute()
    except Exception:
        pass

    # Advance lifecycle
    try:
        supabase.table("jobs").update({
            "lifecycle_stage": "offer_stage",
        }).eq("id", job_id).execute()
    except Exception:
        pass

    notify_admins(
        "interview_results_submitted",
        "Interview results submitted",
        f"Company has submitted interview results for '{existing.data.get('title')}'.",
        "job", job_id,
    )

    return jsonify({
        "data": {"offers_created": len(created_offers), "offers": created_offers},
        "lifecycle_stage": "offer_stage",
    })


# ---------------------------------------------------------------------------
# POST /api/jobs/<job_id>/internship-conclusion
# ---------------------------------------------------------------------------

@jobs_bp.post("/<string:job_id>/internship-conclusion")
@require_role(["company_admin", "recruiter"])
def conclude_internship(job_id):
    """Company admin concludes an internship: convert, extend, or complete with cert."""
    from ..services.notification_service import notify, notify_admins

    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    internship_id = payload.get("internship_id")
    conclusion_type = payload.get("conclusion_type")
    note = payload.get("note", "")
    extension_end_date = payload.get("extension_end_date")

    if not internship_id:
        return _err("VALIDATION_ERROR", "'internship_id' is required", 400)
    if conclusion_type not in ("converted_to_employee", "extended", "completed_with_certificate"):
        return _err("VALIDATION_ERROR", "Invalid conclusion_type", 400)

    # Verify internship belongs to this company
    try:
        intern_res = (
            supabase.table("internships")
            .select("id, company_id, student_id, job_id, status")
            .eq("id", internship_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Internship not found", 404)

    if not intern_res.data:
        return _err("NOT_FOUND", "Internship not found", 404)

    if intern_res.data.get("company_id") != company_id:
        return _err("FORBIDDEN", "Not authorized for this internship", 403)

    update_data = {
        "conclusion_type": conclusion_type,
        "conclusion_note": note,
        "concluded_at": datetime.utcnow().isoformat(),
        "concluded_by": g.user_id,
    }

    if conclusion_type == "extended":
        if not extension_end_date:
            return _err("VALIDATION_ERROR", "'extension_end_date' is required for extension", 400)
        update_data["extension_end_date"] = extension_end_date
        # keep status as in_progress
    elif conclusion_type == "completed_with_certificate":
        update_data["status"] = "completed"
    elif conclusion_type == "converted_to_employee":
        update_data["status"] = "completed"

    try:
        res = (
            supabase.table("internships")
            .update(update_data)
            .eq("id", internship_id)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to update internship", 500)

    # Notify student
    student_id = intern_res.data.get("student_id")
    if student_id:
        msg_map = {
            "converted_to_employee": "Your internship has been converted to full-time employment!",
            "extended": f"Your internship has been extended until {extension_end_date}.",
            "completed_with_certificate": "Your internship is complete. A certificate will be issued.",
        }
        notify(student_id, "internship_concluded", "Internship Update", msg_map.get(conclusion_type, ""),
               "internship", internship_id)

    notify_admins(
        "internship_concluded",
        "Internship concluded",
        f"Internship concluded as '{conclusion_type}'.",
        "internship", internship_id,
    )

    return jsonify({"data": res.data[0] if res.data else {}})
