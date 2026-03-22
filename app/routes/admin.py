"""
Platform Admin API — /api/admin/* and /api/platform/*

Endpoints (§1–§8 per 06_platform_admin.md):
  GET  /api/platform/stats                           — public platform stats
  GET  /api/admin/dashboard                           — admin KPI dashboard
  GET  /api/admin/users                               — list all users
  GET  /api/admin/users/<user_id>                     — user detail
  PATCH /api/admin/users/<user_id>/status             — suspend/reactivate
  PATCH /api/admin/users/<user_id>/role               — change role
  DELETE /api/admin/users/<user_id>                   — delete user
  GET  /api/admin/companies/pending                   — pending companies
  POST /api/admin/companies/<id>/approve              — approve company
  POST /api/admin/companies/<id>/reject               — reject company
  GET  /api/admin/universities/pending                — pending universities
  POST /api/admin/universities/<id>/approve           — approve university
  POST /api/admin/universities/<id>/reject            — reject university
  GET  /api/admin/flags                               — flagged content
  POST /api/admin/flags/<flag_id>/resolve             — resolve flag
  GET  /api/admin/ai-config                           — AI config
  PUT  /api/admin/ai-config                           — update AI config
  POST /api/admin/exports                             — create export
  GET  /api/admin/exports/<export_id>                 — export status
  GET  /api/admin/audit-log                           — audit log

Uses require_role(["admin"]) except for the public stats endpoint.
"""

from flask import Blueprint, jsonify, request, g
from ..middleware.auth import require_role
from ..services.supabase_client import supabase, supabase_admin
from ..services.admin_service import (
    get_platform_stats,
    get_admin_dashboard,
    create_user_admin,
    list_users,
    get_user_detail,
    update_user_status,
    update_user_role,
    delete_user,
    list_all_companies,
    create_company,
    register_company_with_admin,
    list_pending_companies,
    approve_company,
    reject_company,
    get_company_detail_admin,
    list_company_jobs_admin,
    list_job_applications_admin,
    list_all_universities,
    create_university,
    list_pending_universities,
    approve_university,
    reject_university,
    list_flags,
    resolve_flag,
    get_ai_config,
    update_ai_config,
    get_platform_analytics,
    create_export,
    get_export_status,
    get_audit_log,
    # §9 Departments
    list_university_departments,
    create_department,
    update_department,
    delete_department,
    # §10 Verifications
    list_university_verifications,
    create_verification_request,
    approve_verification,
    reject_verification,
    # §11 Students
    create_university_student,
    # §12 Company Internships & Certificates
    list_company_internships_admin,
    list_company_certificates_admin,
    list_job_matching_admin,
    # §13 Certificate Issuance Workflow
    list_completed_internships_pending_certificate,
    list_all_issued_certificates_admin,
)

# ---------------------------------------------------------------------------
# Blueprints
# ---------------------------------------------------------------------------

admin_bp = Blueprint("admin", __name__)
platform_bp = Blueprint("platform", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _parse_int(val, default: int) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


# ═══════════════════════════════════════════════════════════════════════════
# §1  Platform Statistics
# ═══════════════════════════════════════════════════════════════════════════

@platform_bp.get("/stats")
def platform_stats():
    """Public endpoint — no auth required."""
    data = get_platform_stats()
    return jsonify({"data": data})


@admin_bp.get("/dashboard")
@require_role(["admin"])
def dashboard():
    """Comprehensive admin dashboard data."""
    data = get_admin_dashboard()
    return jsonify({"data": data})


# ═══════════════════════════════════════════════════════════════════════════
# §2  User Management
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.post("/users")
@require_role(["admin"])
def create_user():
    """Admin-only: create a new user with any role."""
    body = request.get_json(silent=True) or {}
    if not body.get("email") or not body.get("password"):
        return _err("MISSING_FIELDS", "'email' and 'password' are required", 400)

    try:
        result = create_user_admin(g.user_id, body)
    except ValueError as e:
        code = str(e)
        status_map = {
            "MISSING_CREDENTIALS": (400, "Email and password are required"),
            "INVALID_ROLE": (400, "Invalid role specified"),
            "EMAIL_EXISTS": (422, "A user with this email already exists"),
            "CREATE_FAILED": (500, "Failed to create user"),
        }
        http_status, msg = status_map.get(code, (500, "Failed to create user"))
        return _err(code, msg, http_status)

    return jsonify({"data": result}), 201


@admin_bp.get("/users")
@require_role(["admin"])
def list_all_users():
    """List all users with pagination, search, and filters."""
    params = {
        "page": _parse_int(request.args.get("page"), 1),
        "limit": _parse_int(request.args.get("limit"), 50),
        "search": request.args.get("search"),
        "role": request.args.get("role"),
        "status": request.args.get("status"),
        "university_id": request.args.get("university_id"),
        "company_id": request.args.get("company_id"),
        "sort": request.args.get("sort", "created_at"),
    }
    result = list_users(params)
    return jsonify(result)


@admin_bp.get("/users/<user_id>")
@require_role(["admin"])
def get_user(user_id):
    """Full user detail."""
    data = get_user_detail(user_id)
    if data is None:
        return _err("NOT_FOUND", "User not found", 404)
    return jsonify({"data": data})


@admin_bp.patch("/users/<user_id>/status")
@require_role(["admin"])
def change_user_status(user_id):
    """Suspend or reactivate a user."""
    body = request.get_json(silent=True) or {}
    if not body.get("status") or not body.get("reason"):
        return _err("MISSING_FIELDS", "Both 'status' and 'reason' are required", 400)

    if body["status"] not in ("active", "suspended"):
        return _err("INVALID_STATUS", "Status must be 'active' or 'suspended'", 400)

    try:
        result = update_user_status(user_id, g.user_id, body)
    except ValueError as e:
        code = str(e)
        status_map = {
            "CANNOT_SUSPEND_ADMIN": (403, "Cannot suspend an admin user"),
            "ALREADY_SUSPENDED": (422, "User is already suspended"),
            "ALREADY_ACTIVE": (422, "User is already active"),
            "USER_NOT_FOUND": (404, "User not found"),
        }
        http_status, msg = status_map.get(code, (500, "Failed to update user status"))
        return _err(code, msg, http_status)

    return jsonify({"data": result})


@admin_bp.patch("/users/<user_id>/role")
@require_role(["admin"])
def change_user_role(user_id):
    """Change a user's role."""
    body = request.get_json(silent=True) or {}
    if not body.get("role") or not body.get("reason"):
        return _err("MISSING_FIELDS", "Both 'role' and 'reason' are required", 400)

    valid_roles = {"student", "recruiter", "company_admin", "university_admin", "university"}
    if body["role"] not in valid_roles:
        return _err("INVALID_ROLE", f"Invalid role: {body['role']}", 400)

    try:
        result = update_user_role(user_id, g.user_id, body)
    except ValueError as e:
        code = str(e)
        status_map = {
            "INVALID_ROLE": (400, "Invalid role specified"),
            "USER_NOT_FOUND": (404, "User not found"),
        }
        http_status, msg = status_map.get(code, (500, "Failed to update user role"))
        return _err(code, msg, http_status)

    return jsonify({"data": result})


@admin_bp.delete("/users/<user_id>")
@require_role(["admin"])
def remove_user(user_id):
    """Delete a user account."""
    permanent = request.args.get("permanent", "false").lower() == "true"

    try:
        delete_user(user_id, g.user_id, permanent)
    except ValueError as e:
        code = str(e)
        status_map = {
            "CANNOT_DELETE_ADMIN": (403, "Cannot delete an admin user"),
            "LAST_ADMIN": (422, "Cannot delete the last admin"),
            "USER_NOT_FOUND": (404, "User not found"),
        }
        http_status, msg = status_map.get(code, (500, "Failed to delete user"))
        return _err(code, msg, http_status)

    return "", 204


# ═══════════════════════════════════════════════════════════════════════════
# §3  Company & University Approval
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.get("/companies")
@require_role(["admin"])
def all_companies():
    """List all companies with pagination and filters."""
    params = {
        "page": _parse_int(request.args.get("page"), 1),
        "limit": _parse_int(request.args.get("limit"), 50),
        "search": request.args.get("search"),
        "status": request.args.get("status"),
    }
    result = list_all_companies(params)
    return jsonify(result)


@admin_bp.post("/companies")
@require_role(["admin"])
def onboard_company():
    """Onboard a new company."""
    body = request.get_json(silent=True) or {}
    if not body.get("name"):
        return _err("MISSING_FIELDS", "'name' is required", 400)
    try:
        result = create_company(g.user_id, body)
    except ValueError as e:
        code = str(e)
        return _err(code, "Failed to create company", 500)
    return jsonify({"data": result}), 201


@admin_bp.post("/companies/register")
@require_role(["admin"])
def register_company():
    """Register a new company and create its admin account in one step."""
    body = request.get_json(silent=True) or {}
    if not body.get("name"):
        return _err("MISSING_FIELDS", "'name' is required", 400)
    if not body.get("admin_email"):
        return _err("MISSING_FIELDS", "'admin_email' is required", 400)

    try:
        result = register_company_with_admin(g.user_id, body)
    except ValueError as e:
        code = str(e)
        status_map = {
            "MISSING_COMPANY_NAME": (400, "'name' is required"),
            "MISSING_ADMIN_EMAIL": (400, "'admin_email' is required"),
            "EMAIL_EXISTS": (422, "A user with this email already exists"),
            "CREATE_FAILED": (500, "Failed to register company"),
        }
        http_status, msg = status_map.get(code, (500, "Failed to register company"))
        return _err(code, msg, http_status)

    return jsonify({"data": result}), 201


@admin_bp.get("/companies/pending")
@require_role(["admin"])
def pending_companies():
    """List companies awaiting approval."""
    data = list_pending_companies()
    return jsonify({"data": data})


@admin_bp.post("/companies/<company_id>/approve")
@require_role(["admin"])
def company_approve(company_id):
    """Approve a company registration."""
    body = request.get_json(silent=True) or {}
    try:
        result = approve_company(company_id, g.user_id, body.get("note"))
    except ValueError as e:
        code = str(e)
        status_map = {
            "ALREADY_APPROVED": (422, "Company is already approved"),
            "COMPANY_NOT_FOUND": (404, "Company not found"),
        }
        http_status, msg = status_map.get(code, (500, "Failed to approve company"))
        return _err(code, msg, http_status)
    return jsonify({"data": result})


@admin_bp.post("/companies/<company_id>/reject")
@require_role(["admin"])
def company_reject(company_id):
    """Reject a company registration."""
    body = request.get_json(silent=True) or {}
    if not body.get("reason"):
        return _err("MISSING_FIELDS", "'reason' is required", 400)
    try:
        result = reject_company(company_id, g.user_id, body["reason"], body.get("note"))
    except ValueError as e:
        code = str(e)
        status_map = {
            "ALREADY_REJECTED": (422, "Company is already rejected"),
            "COMPANY_NOT_FOUND": (404, "Company not found"),
        }
        http_status, msg = status_map.get(code, (500, "Failed to reject company"))
        return _err(code, msg, http_status)
    return jsonify({"data": result})


@admin_bp.get("/companies/<company_id>")
@require_role(["admin"])
def company_detail(company_id):
    """Company overview with aggregate JD and application stats."""
    data = get_company_detail_admin(company_id)
    if data is None:
        return _err("NOT_FOUND", "Company not found", 404)
    return jsonify({"data": data})


@admin_bp.get("/companies/<company_id>/jobs")
@require_role(["admin"])
def company_jobs(company_id):
    """All JDs posted by a company with per-job application counts."""
    data = list_company_jobs_admin(company_id)
    return jsonify({"data": data})


@admin_bp.get("/companies/<company_id>/jobs/<job_id>/applications")
@require_role(["admin"])
def company_job_applications(company_id, job_id):
    """Applications for a specific job with applicant details."""
    data = list_job_applications_admin(job_id)
    return jsonify({"data": data})


@admin_bp.get("/universities")
@require_role(["admin"])
def all_universities():
    """List all universities with pagination and filters."""
    params = {
        "page": _parse_int(request.args.get("page"), 1),
        "limit": _parse_int(request.args.get("limit"), 50),
        "search": request.args.get("search"),
        "status": request.args.get("status"),
    }
    result = list_all_universities(params)
    return jsonify(result)


@admin_bp.post("/universities")
@require_role(["admin"])
def onboard_university():
    """Onboard a new university with an admin user account."""
    body = request.get_json(silent=True) or {}
    if not body.get("name"):
        return _err("MISSING_FIELDS", "'name' is required", 400)
    if not body.get("admin_email") or not body.get("admin_password"):
        return _err("MISSING_FIELDS", "'admin_email' and 'admin_password' are required", 400)
    try:
        result = create_university(g.user_id, body)
    except ValueError as e:
        code = str(e)
        status_map = {
            "MISSING_NAME": (400, "'name' is required"),
            "MISSING_ADMIN_CREDENTIALS": (400, "Admin email and password are required"),
            "EMAIL_EXISTS": (422, "A user with this email already exists"),
            "CREATE_FAILED": (500, "Failed to create university"),
        }
        http_status, msg = status_map.get(code, (500, "Failed to create university"))
        return _err(code, msg, http_status)
    return jsonify({"data": result}), 201


@admin_bp.get("/universities/pending")
@require_role(["admin"])
def pending_universities():
    """List universities awaiting approval."""
    data = list_pending_universities()
    return jsonify({"data": data})


@admin_bp.post("/universities/<university_id>/approve")
@require_role(["admin"])
def university_approve(university_id):
    """Approve a university registration."""
    body = request.get_json(silent=True) or {}
    try:
        result = approve_university(university_id, g.user_id, body.get("note"))
    except ValueError as e:
        code = str(e)
        status_map = {
            "ALREADY_APPROVED": (422, "University is already approved"),
            "UNIVERSITY_NOT_FOUND": (404, "University not found"),
        }
        http_status, msg = status_map.get(code, (500, "Failed to approve university"))
        return _err(code, msg, http_status)
    return jsonify({"data": result})


@admin_bp.post("/universities/<university_id>/reject")
@require_role(["admin"])
def university_reject(university_id):
    """Reject a university registration."""
    body = request.get_json(silent=True) or {}
    if not body.get("reason"):
        return _err("MISSING_FIELDS", "'reason' is required", 400)
    try:
        result = reject_university(university_id, g.user_id, body["reason"], body.get("note"))
    except ValueError as e:
        code = str(e)
        status_map = {
            "ALREADY_REJECTED": (422, "University is already rejected"),
            "UNIVERSITY_NOT_FOUND": (404, "University not found"),
        }
        http_status, msg = status_map.get(code, (500, "Failed to reject university"))
        return _err(code, msg, http_status)
    return jsonify({"data": result})


# ═══════════════════════════════════════════════════════════════════════════
# §4  Content Moderation
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.get("/flags")
@require_role(["admin"])
def list_content_flags():
    """List flagged content."""
    params = {
        "page": _parse_int(request.args.get("page"), 1),
        "limit": _parse_int(request.args.get("limit"), 50),
        "type": request.args.get("type"),
        "status": request.args.get("status"),
    }
    result = list_flags(params)
    return jsonify(result)


@admin_bp.post("/flags/<flag_id>/resolve")
@require_role(["admin"])
def resolve_content_flag(flag_id):
    """Resolve a content flag."""
    body = request.get_json(silent=True) or {}
    if not body.get("action"):
        return _err("MISSING_FIELDS", "'action' is required", 400)

    valid_actions = {"dismiss", "remove_content", "suspend_author", "escalate"}
    if body["action"] not in valid_actions:
        return _err("INVALID_ACTION", f"Invalid action: {body['action']}", 400)

    try:
        result = resolve_flag(flag_id, g.user_id, body["action"], body.get("note"))
    except ValueError as e:
        code = str(e)
        status_map = {
            "ALREADY_RESOLVED": (422, "Flag is already resolved"),
            "FLAG_NOT_FOUND": (404, "Flag not found"),
        }
        http_status, msg = status_map.get(code, (500, "Failed to resolve flag"))
        return _err(code, msg, http_status)
    return jsonify({"data": result})


# ═══════════════════════════════════════════════════════════════════════════
# §5  AI Matching Configuration
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.get("/ai-config")
@require_role(["admin"])
def ai_config_get():
    """Return global AI matching configuration."""
    data = get_ai_config()
    return jsonify({"data": data})


@admin_bp.put("/ai-config")
@require_role(["admin"])
def ai_config_update():
    """Update global AI matching configuration."""
    body = request.get_json(silent=True) or {}

    # Validate weights sum if provided
    if "default_weights" in body:
        weights = body["default_weights"]
        if not isinstance(weights, dict):
            return _err("VALIDATION_ERROR", "'default_weights' must be an object", 400)
        total = sum(weights.values())
        if total != 100:
            return _err("INVALID_WEIGHTS", f"Weights must sum to 100, got {total}", 400)

    try:
        result = update_ai_config(g.user_id, body)
    except ValueError as e:
        code = str(e)
        if code == "INVALID_WEIGHTS":
            return _err(code, "Weights must sum to 100", 400)
        return _err("SERVER_ERROR", "Failed to update AI config", 500)

    return jsonify({"data": result})


# ═══════════════════════════════════════════════════════════════════════════
# §6  Platform Analytics (registered under /api/analytics prefix separately)
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.get("/analytics/platform")
@require_role(["admin"])
def platform_analytics():
    """Platform-wide analytics."""
    period = request.args.get("period", "30d")
    if period not in ("7d", "30d", "90d", "ytd", "all"):
        period = "30d"
    data = get_platform_analytics(period)
    return jsonify({"data": data})


# ═══════════════════════════════════════════════════════════════════════════
# §7  Data Export
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.post("/exports")
@require_role(["admin"])
def create_data_export():
    """Trigger a data export job."""
    body = request.get_json(silent=True) or {}
    if not body.get("type"):
        return _err("MISSING_FIELDS", "'type' is required", 400)

    valid_types = {"students", "companies", "jobs", "applications", "verifications", "analytics"}
    if body["type"] not in valid_types:
        return _err("INVALID_EXPORT_TYPE", f"Invalid export type: {body['type']}", 400)

    valid_formats = {"csv", "json"}
    if body.get("format") and body["format"] not in valid_formats:
        return _err("INVALID_FORMAT", f"Invalid format: {body['format']}. Use 'csv' or 'json'", 400)

    try:
        result = create_export(g.user_id, body)
    except ValueError as e:
        code = str(e)
        return _err(code, "Failed to create export", 500)

    return jsonify({"data": result}), 202


@admin_bp.get("/exports/<export_id>")
@require_role(["admin"])
def export_status(export_id):
    """Check export status."""
    data = get_export_status(export_id)
    if data is None:
        return _err("NOT_FOUND", "Export not found", 404)
    return jsonify({"data": data})


# ═══════════════════════════════════════════════════════════════════════════
# §8  Audit Log
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.get("/audit-log")
@require_role(["admin"])
def audit_log():
    """Chronological audit log of admin actions."""
    params = {
        "page": _parse_int(request.args.get("page"), 1),
        "limit": _parse_int(request.args.get("limit"), 50),
        "action_type": request.args.get("action_type"),
        "actor_id": request.args.get("actor_id"),
        "from_date": request.args.get("from_date"),
        "to_date": request.args.get("to_date"),
    }
    result = get_audit_log(params)
    return jsonify(result)

# ═══════════════════════════════════════════════════════════════════════════
# §9  University Departments
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.get("/universities/<university_id>/departments")
@require_role(["admin"])
def uni_list_departments(university_id):
    """List all departments for a university."""
    data = list_university_departments(university_id)
    return jsonify({"data": data})


@admin_bp.post("/universities/<university_id>/departments")
@require_role(["admin"])
def uni_create_department(university_id):
    """Create a new department."""
    body = request.get_json(silent=True) or {}
    if not body.get("name") or not body.get("code"):
        return _err("MISSING_FIELDS", "'name' and 'code' are required", 400)
    try:
        result = create_department(university_id, g.user_id, body)
    except ValueError as e:
        return _err(str(e), "Failed to create department", 500)
    return jsonify({"data": result}), 201


@admin_bp.put("/universities/<university_id>/departments/<dept_id>")
@require_role(["admin"])
def uni_update_department(university_id, dept_id):
    """Update a department."""
    body = request.get_json(silent=True) or {}
    try:
        result = update_department(dept_id, g.user_id, body)
    except ValueError as e:
        code = str(e)
        if code == "NOT_FOUND":
            return _err(code, "Department not found", 404)
        if code == "NO_FIELDS":
            return _err(code, "No updatable fields provided", 400)
        return _err(code, "Failed to update department", 500)
    return jsonify({"data": result})


@admin_bp.delete("/universities/<university_id>/departments/<dept_id>")
@require_role(["admin"])
def uni_delete_department(university_id, dept_id):
    """Delete a department."""
    try:
        delete_department(dept_id, g.user_id)
    except ValueError as e:
        return _err(str(e), "Failed to delete department", 500)
    return "", 204


# ═══════════════════════════════════════════════════════════════════════════
# §10  University Verification Requests
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.get("/universities/<university_id>/verifications")
@require_role(["admin"])
def uni_list_verifications(university_id):
    """List verification requests for a university."""
    status = request.args.get("status")
    data = list_university_verifications(university_id, status)
    return jsonify({"data": data})


@admin_bp.post("/universities/<university_id>/verifications")
@require_role(["admin"])
def uni_create_verification(university_id):
    """Create a verification request on behalf of a student."""
    body = request.get_json(silent=True) or {}
    if not body.get("type"):
        return _err("MISSING_FIELDS", "'type' is required", 400)
    try:
        result = create_verification_request(university_id, g.user_id, body)
    except ValueError as e:
        return _err(str(e), "Failed to create verification request", 500)
    return jsonify({"data": result}), 201


@admin_bp.post("/universities/<university_id>/verifications/<req_id>/approve")
@require_role(["admin"])
def uni_approve_verification(university_id, req_id):
    """Approve a verification request."""
    body = request.get_json(silent=True) or {}
    try:
        result = approve_verification(req_id, g.user_id, body.get("note"))
    except ValueError as e:
        code = str(e)
        if code == "NOT_FOUND":
            return _err(code, "Verification request not found", 404)
        return _err(code, "Failed to approve", 500)
    return jsonify({"data": result})


@admin_bp.post("/universities/<university_id>/verifications/<req_id>/reject")
@require_role(["admin"])
def uni_reject_verification(university_id, req_id):
    """Reject a verification request."""
    body = request.get_json(silent=True) or {}
    if not body.get("reason"):
        return _err("MISSING_FIELDS", "'reason' is required", 400)
    try:
        result = reject_verification(req_id, g.user_id, body["reason"])
    except ValueError as e:
        code = str(e)
        if code == "NOT_FOUND":
            return _err(code, "Verification request not found", 404)
        return _err(code, "Failed to reject", 500)
    return jsonify({"data": result})


# ═══════════════════════════════════════════════════════════════════════════
# §11  University Student Creation
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.post("/universities/<university_id>/students")
@require_role(["admin"])
def uni_create_student(university_id):
    """Create a student account and link to a university."""
    body = request.get_json(silent=True) or {}
    if not body.get("email") or not body.get("password"):
        return _err("MISSING_FIELDS", "'email' and 'password' are required", 400)
    try:
        result = create_university_student(university_id, g.user_id, body)
    except ValueError as e:
        code = str(e)
        status_map = {
            "MISSING_CREDENTIALS": (400, "Email and password are required"),
            "EMAIL_EXISTS": (422, "A user with this email already exists"),
            "CREATE_FAILED": (500, "Failed to create student"),
        }
        http_status, msg = status_map.get(code, (500, "Failed to create student"))
        return _err(code, msg, http_status)
    return jsonify({"data": result}), 201


# ═══════════════════════════════════════════════════════════════════════════
# §12  Company Internships & Certificates (Admin)
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.get("/companies/<company_id>/internships")
@require_role(["admin"])
def company_internships_admin(company_id):
    """All internships at a company with student, milestone, and certificate data."""
    data = list_company_internships_admin(company_id)
    return jsonify({"data": data})


@admin_bp.get("/companies/<company_id>/certificates")
@require_role(["admin"])
def company_certificates_admin(company_id):
    """All certificates issued by a company."""
    data = list_company_certificates_admin(company_id)
    return jsonify({"data": data})


@admin_bp.get("/companies/<company_id>/jobs/<job_id>/matching")
@require_role(["admin"])
def company_job_matching_admin(company_id, job_id):
    """AI matching results for a specific job (admin view)."""
    data = list_job_matching_admin(job_id)
    return jsonify({"data": data})


# ═══════════════════════════════════════════════════════════════════════════
# §13  Certificate Issuance Workflow (Admin)
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.get("/internships/pending-certificates")
@require_role(["admin"])
def pending_certificates():
    """All completed internships that do not yet have a certificate."""
    data = list_completed_internships_pending_certificate()
    return jsonify({"data": data})


@admin_bp.get("/internships/issued-certificates")
@require_role(["admin"])
def issued_certificates():
    """All certificates issued across the platform."""
    data = list_all_issued_certificates_admin()
    return jsonify({"data": data})


# ═══════════════════════════════════════════════════════════════════════════
# §14  JD Lifecycle Workflow (Admin)
# ═══════════════════════════════════════════════════════════════════════════

from datetime import datetime
from ..services.supabase_client import supabase, supabase_admin
from ..services.notification_service import (
    notify, notify_bulk, notify_admins,
    notify_university_admins_for_job, notify_company_admins_for_job,
)


@admin_bp.get("/jobs/pending-approval")
@require_role(["admin"])
def list_pending_approval_jobs():
    """List all JDs submitted for approval."""
    page = _parse_int(request.args.get("page"), 1)
    limit = min(100, _parse_int(request.args.get("limit"), 20))

    try:
        query = (
            supabase.table("jobs")
            .select("id, title, department, location, status, lifecycle_stage, "
                    "approval_status, approval_note, submitted_for_approval_at, "
                    "company_id, recruiter_id, created_at, deadline, priority, "
                    "description, skills, openings")
            .eq("approval_status", "pending")
        )
        offset = (page - 1) * limit
        query = query.order("submitted_for_approval_at", desc=True).range(offset, offset + limit - 1)
        res = query.execute()
    except Exception:
        return _err("SERVER_ERROR", "Failed to fetch pending jobs", 500)

    jobs = res.data or []

    # Attach company names
    company_ids = list({j.get("company_id") for j in jobs if j.get("company_id")})
    companies_map = {}
    if company_ids:
        try:
            comp_res = (
                supabase.table("companies")
                .select("id, name, logo_url")
                .in_("id", company_ids)
                .execute()
            )
            for c in (comp_res.data or []):
                companies_map[c["id"]] = c
        except Exception:
            pass

    for j in jobs:
        comp = companies_map.get(j.get("company_id"), {})
        j["company_name"] = comp.get("name")
        j["company_logo_url"] = comp.get("logo_url")

    return jsonify({"data": jobs, "meta": {"page": page, "limit": limit, "total": len(jobs)}})


@admin_bp.get("/jobs")
@require_role(["admin"])
def list_all_jobs_admin():
    """List all jobs with lifecycle stage filtering."""
    page = _parse_int(request.args.get("page"), 1)
    limit = min(100, _parse_int(request.args.get("limit"), 20))
    lifecycle_stage = request.args.get("lifecycle_stage")
    company_id_filter = request.args.get("company_id")

    try:
        query = (
            supabase.table("jobs")
            .select("id, title, department, location, status, lifecycle_stage, "
                    "approval_status, company_id, deadline, priority, created_at, "
                    "submitted_for_approval_at")
        )
        if lifecycle_stage:
            stages = [s.strip() for s in lifecycle_stage.split(",") if s.strip()]
            if len(stages) == 1:
                query = query.eq("lifecycle_stage", stages[0])
            else:
                query = query.in_("lifecycle_stage", stages)
        if company_id_filter:
            query = query.eq("company_id", company_id_filter)

        offset = (page - 1) * limit
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        res = query.execute()
    except Exception:
        return _err("SERVER_ERROR", "Failed to fetch jobs", 500)

    jobs = res.data or []

    # Attach company names
    company_ids = list({j.get("company_id") for j in jobs if j.get("company_id")})
    companies_map = {}
    if company_ids:
        try:
            comp_res = (
                supabase.table("companies")
                .select("id, name, logo_url")
                .in_("id", company_ids)
                .execute()
            )
            for c in (comp_res.data or []):
                companies_map[c["id"]] = c
        except Exception:
            pass

    for j in jobs:
        comp = companies_map.get(j.get("company_id"), {})
        j["company_name"] = comp.get("name")
        j["company_logo_url"] = comp.get("logo_url")

    return jsonify({"data": jobs, "meta": {"page": page, "limit": limit, "total": len(jobs)}})


@admin_bp.get("/jobs/<job_id>/tracking")
@require_role(["admin"])
def get_job_tracking(job_id):
    """Get full tracking details for a JD: lifecycle, universities, applications, interviews, offers."""
    try:
        job_res = (
            supabase.table("jobs")
            .select("id, title, department, location, status, lifecycle_stage, "
                    "approval_status, approval_note, approved_by, approved_at, "
                    "submitted_for_approval_at, company_id, recruiter_id, "
                    "created_at, deadline, priority, description, skills, openings")
            .eq("id", job_id)
            .maybe_single()
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to fetch job", 500)

    if not job_res.data:
        return _err("NOT_FOUND", "Job not found", 404)

    job = job_res.data

    # Company info
    company = {}
    if job.get("company_id"):
        try:
            comp_res = (
                supabase.table("companies")
                .select("id, name, logo_url, industry, location")
                .eq("id", job["company_id"])
                .maybe_single()
                .execute()
            )
            company = comp_res.data or {}
        except Exception:
            pass

    # Assigned universities
    universities = []
    try:
        uni_res = (
            supabase.table("job_university_assignments")
            .select("id, university_id, assigned_at, notified_at, acknowledged_at, "
                    "student_ids, department_ids, apply_on_behalf")
            .eq("job_id", job_id)
            .order("assigned_at", desc=False)
            .execute()
        )
        uni_ids = list({a["university_id"] for a in (uni_res.data or [])})
        uni_names = {}
        if uni_ids:
            try:
                names_res = (
                    supabase.table("universities")
                    .select("id, name, location")
                    .in_("id", uni_ids)
                    .execute()
                )
                for u in (names_res.data or []):
                    uni_names[u["id"]] = u
            except Exception:
                pass
        for a in (uni_res.data or []):
            info = uni_names.get(a["university_id"], {})
            universities.append({
                **a,
                "university_name": info.get("name"),
                "university_location": info.get("location"),
                "student_count": len(a.get("student_ids") or []),
            })
    except Exception:
        pass

    # Applications with student info
    applications = []
    try:
        app_res = (
            supabase.table("applications")
            .select("id, student_id, status, created_at, updated_at")
            .eq("job_id", job_id)
            .order("created_at", desc=True)
            .execute()
        )
        student_ids = list({a["student_id"] for a in (app_res.data or [])})
        student_names = {}
        if student_ids:
            try:
                stu_res = (
                    supabase.table("profiles")
                    .select("id, full_name, email")
                    .in_("id", student_ids)
                    .execute()
                )
                for s in (stu_res.data or []):
                    student_names[s["id"]] = s
            except Exception:
                pass
        for a in (app_res.data or []):
            stu = student_names.get(a["student_id"], {})
            applications.append({
                **a,
                "student_name": stu.get("full_name"),
                "student_email": stu.get("email"),
            })
    except Exception:
        pass

    # Curation status
    curations = []
    try:
        cur_res = (
            supabase.table("admin_application_curation")
            .select("id, application_id, curation_status, curation_note, forwarded_at, curated_at")
            .eq("job_id", job_id)
            .order("curated_at", desc=True)
            .execute()
        )
        curations = cur_res.data or []
    except Exception:
        pass

    # Interview rounds & schedules
    interviews = []
    try:
        round_res = (
            supabase.table("interview_rounds")
            .select("id, round_number, status, proposed_slots, "
                    "results_requested_at, results_submitted_at, created_at")
            .eq("job_id", job_id)
            .order("round_number", desc=False)
            .execute()
        )
        for r in (round_res.data or []):
            schedules = []
            try:
                sched_res = (
                    supabase.table("interview_schedules")
                    .select("id, application_id, student_id, scheduled_slot, "
                            "result, result_note, offer_decision, created_at")
                    .eq("round_id", r["id"])
                    .order("created_at", desc=False)
                    .execute()
                )
                sched_data = sched_res.data or []
                # Attach student names
                sched_student_ids = list({s["student_id"] for s in sched_data})
                sched_student_names = {}
                if sched_student_ids:
                    try:
                        sn_res = (
                            supabase.table("profiles")
                            .select("id, full_name")
                            .in_("id", sched_student_ids)
                            .execute()
                        )
                        for s in (sn_res.data or []):
                            sched_student_names[s["id"]] = s.get("full_name")
                    except Exception:
                        pass
                for s in sched_data:
                    schedules.append({
                        **s,
                        "student_name": sched_student_names.get(s["student_id"]),
                    })
            except Exception:
                pass
            interviews.append({**r, "schedules": schedules})
    except Exception:
        pass

    # Offers
    offers = []
    try:
        offer_res = (
            supabase.table("offers")
            .select("id, application_id, student_id, status, offer_details, "
                    "sent_at, response_deadline, responded_at, rejection_reason, created_at")
            .eq("job_id", job_id)
            .order("created_at", desc=True)
            .execute()
        )
        offer_student_ids = list({o["student_id"] for o in (offer_res.data or [])})
        offer_student_names = {}
        if offer_student_ids:
            try:
                osn_res = (
                    supabase.table("profiles")
                    .select("id, full_name")
                    .in_("id", offer_student_ids)
                    .execute()
                )
                for s in (osn_res.data or []):
                    offer_student_names[s["id"]] = s.get("full_name")
            except Exception:
                pass
        for o in (offer_res.data or []):
            offers.append({
                **o,
                "student_name": offer_student_names.get(o["student_id"]),
            })
    except Exception:
        pass

    # Build timeline from available data
    timeline = []
    if job.get("created_at"):
        timeline.append({"event": "JD Created", "timestamp": job["created_at"], "stage": "draft"})
    if job.get("submitted_for_approval_at"):
        timeline.append({"event": "Submitted for Approval", "timestamp": job["submitted_for_approval_at"], "stage": "pending_approval"})
    if job.get("approved_at"):
        timeline.append({"event": "Approved by Admin", "timestamp": job["approved_at"], "stage": "approved_assigning"})
    for u in universities:
        if u.get("assigned_at"):
            timeline.append({"event": f"Assigned to {u.get('university_name', 'University')}", "timestamp": u["assigned_at"], "stage": "university_assigned"})
        if u.get("notified_at"):
            timeline.append({"event": f"Students notified at {u.get('university_name', 'University')}", "timestamp": u["notified_at"], "stage": "collecting_applications"})
    for a in applications:
        if a.get("created_at"):
            timeline.append({"event": f"{a.get('student_name', 'Student')} applied", "timestamp": a["created_at"], "stage": "collecting_applications"})
    for c in curations:
        if c.get("forwarded_at"):
            timeline.append({"event": "Curated applications forwarded to company", "timestamp": c["forwarded_at"], "stage": "forwarded_to_company"})
            break
    for r in interviews:
        if r.get("created_at"):
            timeline.append({"event": f"Interview Round {r.get('round_number', '?')} created", "timestamp": r["created_at"], "stage": "interview_scheduling"})
        if r.get("results_requested_at"):
            timeline.append({"event": f"Results requested for Round {r.get('round_number', '?')}", "timestamp": r["results_requested_at"], "stage": "results_pending"})
        if r.get("results_submitted_at"):
            timeline.append({"event": f"Results submitted for Round {r.get('round_number', '?')}", "timestamp": r["results_submitted_at"], "stage": "results_pending"})
    for o in offers:
        if o.get("sent_at"):
            timeline.append({"event": f"Offer sent to {o.get('student_name', 'Student')}", "timestamp": o["sent_at"], "stage": "offer_stage"})
        if o.get("responded_at"):
            timeline.append({"event": f"Offer {o.get('status', 'responded')} by {o.get('student_name', 'Student')}", "timestamp": o["responded_at"], "stage": "offer_stage"})

    timeline.sort(key=lambda x: x.get("timestamp") or "")

    return jsonify({
        "data": {
            "job": {**job, "company": company},
            "universities": universities,
            "applications": applications,
            "curations": curations,
            "interviews": interviews,
            "offers": offers,
            "timeline": timeline,
            "summary": {
                "total_universities": len(universities),
                "total_applications": len(applications),
                "included_applications": sum(1 for c in curations if c.get("curation_status") == "included"),
                "excluded_applications": sum(1 for c in curations if c.get("curation_status") == "excluded"),
                "total_interviews": sum(len(r.get("schedules", [])) for r in interviews),
                "passed_interviews": sum(
                    1 for r in interviews for s in r.get("schedules", []) if s.get("result") == "pass"
                ),
                "total_offers": len(offers),
                "accepted_offers": sum(1 for o in offers if o.get("status") == "accepted"),
                "pending_offers": sum(1 for o in offers if o.get("status") in ("pending", "sent")),
            },
        }
    })


@admin_bp.post("/jobs/<job_id>/approve")
@require_role(["admin"])
def approve_jd(job_id):
    """Approve a JD and assign it to universities."""
    payload = request.get_json(silent=True) or {}
    university_ids = payload.get("university_ids", [])
    note = payload.get("note", "")

    if not university_ids or not isinstance(university_ids, list):
        return _err("VALIDATION_ERROR", "'university_ids' must be a non-empty array", 400)

    # Verify job is pending approval
    try:
        job_res = (
            supabase.table("jobs")
            .select("id, approval_status, title")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not job_res.data:
        return _err("NOT_FOUND", "Job not found", 404)

    if job_res.data.get("approval_status") != "pending":
        return _err("INVALID_TRANSITION",
                     f"Job is not pending approval (current: {job_res.data.get('approval_status')})", 422)

    # Update job
    try:
        supabase.table("jobs").update({
            "approval_status": "approved",
            "approval_note": note,
            "approved_by": g.user_id,
            "approved_at": datetime.utcnow().isoformat(),
            "lifecycle_stage": "university_assigned",
            "status": "published",
        }).eq("id", job_id).execute()
    except Exception:
        return _err("SERVER_ERROR", "Failed to approve job", 500)

    # Create university assignments
    assignments = []
    for uni_id in university_ids:
        assignments.append({
            "job_id": job_id,
            "university_id": uni_id,
            "assigned_by": g.user_id,
        })

    try:
        supabase.table("job_university_assignments").insert(assignments).execute()
    except Exception:
        pass  # best-effort

    # Notify university admins
    title = job_res.data.get("title", "")
    notify_university_admins_for_job(
        job_id, "jd_assigned",
        "New Job Description assigned",
        f"'{title}' has been assigned to your university for review.",
    )

    return jsonify({
        "data": {
            "id": job_id,
            "approval_status": "approved",
            "lifecycle_stage": "university_assigned",
            "assigned_universities": len(university_ids),
        }
    })


@admin_bp.post("/jobs/<job_id>/reject")
@require_role(["admin"])
def reject_jd(job_id):
    """Reject a JD and send it back to draft."""
    payload = request.get_json(silent=True) or {}
    reason = payload.get("reason", "")
    if not reason:
        return _err("VALIDATION_ERROR", "'reason' is required", 400)

    try:
        job_res = (
            supabase.table("jobs")
            .select("id, approval_status, title, recruiter_id")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not job_res.data:
        return _err("NOT_FOUND", "Job not found", 404)

    if job_res.data.get("approval_status") != "pending":
        return _err("INVALID_TRANSITION", "Job is not pending approval", 422)

    try:
        supabase.table("jobs").update({
            "approval_status": "rejected",
            "approval_note": reason,
            "approved_by": g.user_id,
            "approved_at": datetime.utcnow().isoformat(),
            "lifecycle_stage": "draft",
        }).eq("id", job_id).execute()
    except Exception:
        return _err("SERVER_ERROR", "Failed to reject job", 500)

    # Notify the recruiter
    recruiter_id = job_res.data.get("recruiter_id")
    if recruiter_id:
        notify(recruiter_id, "jd_rejected", "JD Rejected",
               f"'{job_res.data.get('title')}' was rejected: {reason}",
               "job", job_id)

    return jsonify({
        "data": {"id": job_id, "approval_status": "rejected", "lifecycle_stage": "draft"}
    })


@admin_bp.get("/jobs/<job_id>/applications")
@require_role(["admin"])
def list_job_applications_for_curation(job_id):
    """List all applications for a job (admin curation view)."""
    try:
        apps_res = (
            supabase.table("applications")
            .select(
                "id, student_id, status, ai_score, cover_letter, created_at, note,"
                "students(skills, profiles(full_name, university_id, universities(name)))"
            )
            .eq("job_id", job_id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception:
        try:
            apps_res = (
                supabase.table("applications")
                .select("id, student_id, status, ai_score, cover_letter, created_at, note")
                .eq("job_id", job_id)
                .order("created_at", desc=True)
                .execute()
            )
        except Exception:
            return _err("SERVER_ERROR", "Failed to fetch applications", 500)

    apps = apps_res.data or []

    # Get existing curation entries
    curation_map = {}
    try:
        cur_res = (
            supabase.table("admin_application_curation")
            .select("application_id, curation_status, curation_note, forwarded_at")
            .eq("job_id", job_id)
            .execute()
        )
        for c in (cur_res.data or []):
            curation_map[c["application_id"]] = c
    except Exception:
        pass

    formatted = []
    for app in apps:
        student_data = app.get("students") or {}
        profile_data = student_data.get("profiles") or {}
        uni_data = profile_data.get("universities") or {}
        cur = curation_map.get(app["id"], {})
        formatted.append({
            "id": app["id"],
            "application_id": app["id"],
            "student_id": app.get("student_id"),
            "student_name": profile_data.get("full_name"),
            "student_school": uni_data.get("name"),
            "skills": student_data.get("skills") or [],
            "status": app.get("status"),
            "ai_score": app.get("ai_score"),
            "cover_letter": app.get("cover_letter"),
            "note": app.get("note"),
            "applied_at": app.get("created_at"),
            "curation_status": cur.get("curation_status", "pending"),
            "curation_note": cur.get("curation_note"),
            "forwarded_at": cur.get("forwarded_at"),
        })

    return jsonify({"data": formatted, "meta": {"total": len(formatted)}})


@admin_bp.post("/jobs/<job_id>/curate")
@require_role(["admin"])
def curate_applications(job_id):
    """Platform admin curates (include/exclude) applications."""
    payload = request.get_json(silent=True) or {}
    curated = payload.get("curated", [])
    if not curated or not isinstance(curated, list):
        return _err("VALIDATION_ERROR", "'curated' must be a non-empty array", 400)

    # Update lifecycle stage
    try:
        supabase.table("jobs").update({
            "lifecycle_stage": "under_curation",
        }).eq("id", job_id).execute()
    except Exception:
        pass

    updated = 0
    for item in curated:
        app_id = item.get("application_id")
        status = item.get("status")  # included / excluded
        note = item.get("note", "")

        if not app_id or status not in ("included", "excluded"):
            continue

        row = {
            "job_id": job_id,
            "application_id": app_id,
            "curated_by": g.user_id,
            "curation_status": status,
            "curation_note": note,
        }

        try:
            # Try upsert
            supabase.table("admin_application_curation").upsert(
                row, on_conflict="job_id,application_id"
            ).execute()
            updated += 1
        except Exception:
            pass

    return jsonify({"data": {"updated": updated}})


@admin_bp.post("/jobs/<job_id>/forward-to-company")
@require_role(["admin"])
def forward_to_company(job_id):
    """Forward curated applications to the company admin."""
    payload = request.get_json(silent=True) or {}
    application_ids = payload.get("application_ids", [])

    # If specific IDs provided, ensure curation entries exist for them
    if application_ids:
        for app_id in application_ids:
            try:
                supabase.table("admin_application_curation").upsert({
                    "job_id": job_id,
                    "application_id": app_id,
                    "curation_status": "included",
                    "curated_by": g.user_id,
                }, on_conflict="job_id,application_id").execute()
            except Exception:
                pass

    # If no specific IDs, forward all included
    if not application_ids:
        try:
            inc_res = (
                supabase.table("admin_application_curation")
                .select("application_id")
                .eq("job_id", job_id)
                .eq("curation_status", "included")
                .is_("forwarded_at", "null")
                .execute()
            )
            application_ids = [r["application_id"] for r in (inc_res.data or [])]
        except Exception:
            pass

    # Still empty? Forward all applications for this job
    if not application_ids:
        try:
            all_apps = (
                supabase.table("applications")
                .select("id")
                .eq("job_id", job_id)
                .execute()
            )
            application_ids = [a["id"] for a in (all_apps.data or [])]
            # Create curation entries for these
            for app_id in application_ids:
                try:
                    supabase.table("admin_application_curation").upsert({
                        "job_id": job_id,
                        "application_id": app_id,
                        "curation_status": "included",
                        "curated_by": g.user_id,
                    }, on_conflict="job_id,application_id").execute()
                except Exception:
                    pass
        except Exception:
            pass

    if not application_ids:
        return _err("VALIDATION_ERROR", "No applications to forward", 400)

    now = datetime.utcnow().isoformat()

    # Mark as forwarded
    for app_id in application_ids:
        try:
            supabase.table("admin_application_curation").update({
                "forwarded_at": now,
            }).eq("job_id", job_id).eq("application_id", app_id).execute()
        except Exception:
            pass

        # Update application status to shortlisted
        try:
            supabase.table("applications").update({
                "status": "shortlisted",
                "shortlisted_at": now,
            }).eq("id", app_id).execute()
        except Exception:
            pass

    # Advance lifecycle
    try:
        supabase.table("jobs").update({
            "lifecycle_stage": "forwarded_to_company",
        }).eq("id", job_id).execute()
    except Exception:
        pass

    # Notify company
    notify_company_admins_for_job(
        job_id, "curated_list_forwarded",
        "Curated candidates available",
        f"{len(application_ids)} candidates have been forwarded for your review.",
    )

    return jsonify({
        "data": {
            "forwarded": len(application_ids),
            "lifecycle_stage": "forwarded_to_company",
        }
    })


@admin_bp.post("/jobs/<job_id>/approve-slots")
@require_role(["admin"])
def approve_interview_slots(job_id):
    """Platform admin approves company-submitted interview slots.

    Once approved, the slots become visible to shortlisted students
    who can then select their preferred slot.
    """
    # Find the latest interview round
    try:
        round_res = (
            supabase.table("interview_rounds")
            .select("id, status, proposed_slots")
            .eq("job_id", job_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to fetch interview round", 500)

    if not round_res.data:
        return _err("NOT_FOUND", "No interview round found. Company must submit slots first.", 404)

    rnd = round_res.data[0]
    if rnd["status"] != "slots_submitted":
        return _err(
            "INVALID_STATUS",
            f"Round is in '{rnd['status']}' status — only 'slots_submitted' rounds can be approved",
            400,
        )

    # Update round status to slots_approved
    try:
        supabase.table("interview_rounds").update({
            "status": "slots_approved",
        }).eq("id", rnd["id"]).execute()
    except Exception:
        return _err("SERVER_ERROR", "Failed to approve slots", 500)

    # Create interview_schedule rows for all shortlisted candidates
    # (so they can see the round and select a slot)
    try:
        apps_res = (
            supabase.table("applications")
            .select("id, student_id")
            .eq("job_id", job_id)
            .eq("status", "shortlisted")
            .execute()
        )
    except Exception:
        apps_res = type("R", (), {"data": []})()

    created = 0
    student_ids = []
    for app in (apps_res.data or []):
        try:
            supabase.table("interview_schedules").insert({
                "round_id": rnd["id"],
                "application_id": app["id"],
                "student_id": app["student_id"],
                "scheduled_slot": None,
                "student_selected_slot": None,
            }).execute()
            created += 1
            student_ids.append(app["student_id"])
        except Exception:
            pass

    # Notify students that slots are available to select
    if student_ids:
        notify_bulk(
            student_ids, "interview_slots_available",
            "Interview slots available",
            "Interview time slots are now available. Please select your preferred slot.",
            "job", job_id,
        )

    # Notify company that slots were approved
    notify_company_admins_for_job(
        job_id, "slots_approved",
        "Interview slots approved",
        "Your proposed interview slots have been approved by the platform admin.",
    )

    return jsonify({
        "data": {
            "approved": True,
            "candidates_notified": created,
            "proposed_slots": rnd.get("proposed_slots", []),
        },
    })


@admin_bp.post("/jobs/<job_id>/schedule-interviews")
@require_role(["admin"])
def schedule_interviews(job_id):
    """Platform admin schedules interviews for candidates."""
    payload = request.get_json(silent=True) or {}
    schedules = payload.get("schedules", [])
    if not schedules or not isinstance(schedules, list):
        return _err("VALIDATION_ERROR", "'schedules' must be a non-empty array", 400)

    # Find the latest interview round
    try:
        rounds_res = (
            supabase.table("interview_rounds")
            .select("id")
            .eq("job_id", job_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "No interview round found", 500)

    if not rounds_res.data:
        return _err("NOT_FOUND", "No interview round found. Company must submit slots first.", 404)

    round_id = rounds_res.data[0]["id"]

    # Update round status
    try:
        supabase.table("interview_rounds").update({
            "status": "scheduled",
            "scheduled_by": g.user_id,
        }).eq("id", round_id).execute()
    except Exception:
        pass

    created = 0
    student_ids = []
    for s in schedules:
        app_id = s.get("application_id")
        student_id = s.get("student_id")
        slot = s.get("scheduled_slot", {})

        if not app_id or not student_id:
            continue

        try:
            supabase.table("interview_schedules").insert({
                "round_id": round_id,
                "application_id": app_id,
                "student_id": student_id,
                "scheduled_slot": slot,
                "scheduled_by": g.user_id,
            }).execute()
            created += 1
            student_ids.append(student_id)
        except Exception:
            pass

    # Advance lifecycle
    try:
        supabase.table("jobs").update({
            "lifecycle_stage": "interviewing",
        }).eq("id", job_id).execute()
    except Exception:
        pass

    # Notify students
    if student_ids:
        notify_bulk(
            student_ids, "interview_scheduled_student",
            "Interview scheduled",
            "You have been scheduled for an interview. Check your portal for details.",
            "job", job_id,
        )

    # Notify university admins
    notify_university_admins_for_job(
        job_id, "interview_scheduled",
        "Interviews scheduled",
        f"{created} students have been scheduled for interviews.",
    )

    return jsonify({
        "data": {"scheduled": created, "lifecycle_stage": "interviewing"},
    })


@admin_bp.post("/jobs/<job_id>/advance-to-interviewing")
@require_role(["admin"])
def advance_to_interviewing(job_id):
    """Advance job stage to 'interviewing' — interviews handled outside the system.

    Auto-creates an interview round and interview_schedules for all
    shortlisted candidates so the company can later submit results.
    """
    # Verify job exists and is in a valid stage
    try:
        job_res = (
            supabase.table("jobs")
            .select("id, lifecycle_stage")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not job_res.data:
        return _err("NOT_FOUND", "Job not found", 404)

    current_stage = job_res.data.get("lifecycle_stage")
    if current_stage not in ("interview_scheduling", "forwarded_to_company"):
        return _err(
            "INVALID_STAGE",
            f"Job is in '{current_stage}' stage, cannot advance to interviewing",
            400,
        )

    # Create an interview round (or reuse existing)
    round_id = None
    try:
        existing = (
            supabase.table("interview_rounds")
            .select("id")
            .eq("job_id", job_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if existing.data:
            round_id = existing.data[0]["id"]
            supabase.table("interview_rounds").update({
                "status": "scheduled",
                "scheduled_by": g.user_id,
            }).eq("id", round_id).execute()
    except Exception:
        pass

    if not round_id:
        try:
            round_res = supabase.table("interview_rounds").insert({
                "job_id": job_id,
                "round_number": 1,
                "proposed_slots": [],
                "status": "scheduled",
                "scheduled_by": g.user_id,
            }).execute()
            round_id = round_res.data[0]["id"]
        except Exception:
            return _err("SERVER_ERROR", "Failed to create interview round", 500)

    # Fetch all shortlisted candidates for this job
    try:
        apps_res = (
            supabase.table("applications")
            .select("id, student_id")
            .eq("job_id", job_id)
            .eq("status", "shortlisted")
            .execute()
        )
    except Exception:
        apps_res = type("R", (), {"data": []})()

    # Create interview_schedules for each candidate
    created = 0
    student_ids = []
    for app in (apps_res.data or []):
        try:
            supabase.table("interview_schedules").insert({
                "round_id": round_id,
                "application_id": app["id"],
                "student_id": app["student_id"],
                "scheduled_slot": {"note": "Scheduled outside platform"},
                "scheduled_by": g.user_id,
            }).execute()
            created += 1
            student_ids.append(app["student_id"])
        except Exception:
            pass

    # Advance lifecycle
    try:
        supabase.table("jobs").update({
            "lifecycle_stage": "interviewing",
        }).eq("id", job_id).execute()
    except Exception:
        return _err("SERVER_ERROR", "Failed to update job stage", 500)

    # Notify students
    if student_ids:
        notify_bulk(
            student_ids, "interview_scheduled_student",
            "Interview scheduled",
            "You have been scheduled for an interview. Details will be shared separately.",
            "job", job_id,
        )

    # Notify company
    notify_company_admins_for_job(
        job_id, "interview_stage_advanced",
        "Interviews in progress",
        f"The job has been advanced to the interviewing stage with {created} candidates. Interviews will be coordinated outside the platform.",
    )

    return jsonify({
        "data": {"lifecycle_stage": "interviewing", "candidates_scheduled": created},
    })


@admin_bp.post("/jobs/<job_id>/request-results")
@require_role(["admin"])
def request_interview_results(job_id):
    """Platform admin requests interview results from company."""
    now = datetime.utcnow().isoformat()

    # Update latest round
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
                "status": "results_requested",
                "results_requested_at": now,
            }).eq("id", rounds_res.data[0]["id"]).execute()
    except Exception:
        pass

    # Advance lifecycle
    try:
        supabase.table("jobs").update({
            "lifecycle_stage": "results_pending",
        }).eq("id", job_id).execute()
    except Exception:
        pass

    # Notify company
    notify_company_admins_for_job(
        job_id, "results_requested",
        "Interview results requested",
        "Platform admin is requesting interview results. Please submit your feedback.",
    )

    return jsonify({
        "data": {"lifecycle_stage": "results_pending"},
    })


@admin_bp.get("/jobs/<job_id>/offers")
@require_role(["admin"])
def list_job_offers(job_id):
    """List all offers for a job."""
    try:
        res = (
            supabase.table("offers")
            .select("*, students(profiles(full_name, university_id, universities(name)))")
            .eq("job_id", job_id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception:
        try:
            res = (
                supabase.table("offers")
                .select("*")
                .eq("job_id", job_id)
                .order("created_at", desc=True)
                .execute()
            )
        except Exception:
            return _err("SERVER_ERROR", "Failed to fetch offers", 500)

    offers = res.data or []
    formatted = []
    for o in offers:
        student_data = o.get("students") or {}
        profile_data = student_data.get("profiles") or {}
        uni_data = profile_data.get("universities") or {}
        formatted.append({
            "id": o["id"],
            "job_id": o.get("job_id"),
            "application_id": o.get("application_id"),
            "student_id": o.get("student_id"),
            "student_name": profile_data.get("full_name"),
            "student_school": uni_data.get("name"),
            "offer_details": o.get("offer_details", {}),
            "status": o.get("status"),
            "sent_at": o.get("sent_at"),
            "response_deadline": o.get("response_deadline"),
            "responded_at": o.get("responded_at"),
            "created_at": o.get("created_at"),
        })

    return jsonify({"data": formatted, "meta": {"total": len(formatted)}})


@admin_bp.post("/jobs/<job_id>/send-offers")
@require_role(["admin"])
def send_offers(job_id):
    """Send pending offers to students and notify university admins."""
    payload = request.get_json(silent=True) or {}
    offer_ids = payload.get("offer_ids", [])

    if not offer_ids:
        # Send all pending offers for this job
        try:
            pending_res = (
                supabase.table("offers")
                .select("id")
                .eq("job_id", job_id)
                .eq("status", "pending")
                .execute()
            )
            offer_ids = [r["id"] for r in (pending_res.data or [])]
        except Exception:
            pass

    if not offer_ids:
        return _err("VALIDATION_ERROR", "No offers to send", 400)

    now = datetime.utcnow().isoformat()
    sent_count = 0
    student_ids = []

    for oid in offer_ids:
        try:
            res = (
                supabase.table("offers")
                .update({"status": "sent", "sent_at": now, "issued_by": g.user_id})
                .eq("id", oid)
                .execute()
            )
            if res.data:
                sent_count += 1
                student_ids.append(res.data[0].get("student_id"))

                # Update application status
                supabase.table("applications").update({
                    "status": "offered",
                }).eq("id", res.data[0].get("application_id")).execute()
        except Exception:
            pass

    # Notify students
    if student_ids:
        notify_bulk(
            student_ids, "offer_received",
            "You received an internship offer!",
            "An internship offer is waiting for your response. Check your portal.",
            "job", job_id,
        )

    # Notify university admins
    notify_university_admins_for_job(
        job_id, "offer_sent_to_students",
        "Offers sent to students",
        f"{sent_count} offers have been sent to students.",
    )

    return jsonify({
        "data": {"sent": sent_count, "lifecycle_stage": "offer_stage"},
    })


# ---------------------------------------------------------------------------
# GET /api/admin/students/<student_id>/profile
# Full student profile for Platform Admin — includes evaluations,
# certificates, internships, and application history.
# ---------------------------------------------------------------------------

@admin_bp.get("/students/<string:student_id>/profile")
@require_role(["admin", "super_admin"])
def get_admin_student_profile(student_id: str):
    def _err(code, msg, status):
        return jsonify({"error": {"code": code, "message": msg}}), status

    # 1. Profile + student row
    profile_data = {}
    try:
        pr = supabase.table("profiles").select(
            "id, full_name, avatar_url, role"
        ).eq("id", student_id).maybe_single().execute()
        if not pr.data:
            return _err("NOT_FOUND", "Student not found", 404)
        profile_data = pr.data
    except Exception:
        return _err("NOT_FOUND", "Student not found", 404)

    # Get email from auth.users via admin API
    user_email = None
    try:
        user_resp = supabase_admin.auth.admin.get_user_by_id(student_id)
        if user_resp and user_resp.user:
            user_email = user_resp.user.email
    except Exception:
        pass

    student_data = {}
    try:
        sr = supabase.table("students").select("*").eq("id", student_id).maybe_single().execute()
        if sr.data:
            student_data = sr.data
    except Exception:
        pass

    # University name
    university_name = None
    if student_data.get("university_id"):
        try:
            ur = supabase.table("universities").select("name").eq(
                "id", student_data["university_id"]
            ).maybe_single().execute()
            if ur.data:
                university_name = ur.data.get("name")
        except Exception:
            pass

    # 2. Evaluation sessions + scores
    evaluations = []
    try:
        ev_res = supabase.table("evaluation_sessions").select(
            "id, job_id, interview_type, status, recommendation, "
            "total_score, max_score, overall_notes, created_at, updated_at"
        ).eq("student_id", student_id).order("created_at", desc=True).execute()

        for ev in (ev_res.data or []):
            # Job title
            job_title = None
            try:
                jr = supabase.table("jobs").select("title, department").eq(
                    "id", ev["job_id"]
                ).maybe_single().execute()
                if jr.data:
                    job_title = jr.data.get("title")
            except Exception:
                pass

            # Scores by dimension
            scores_by_dimension = {}
            try:
                sc_res = supabase.table("evaluation_scores").select(
                    "score, max_score, dimension, notes"
                ).eq("session_id", ev["id"]).execute()
                for sc in (sc_res.data or []):
                    dim = sc.get("dimension", "technical")
                    if dim not in scores_by_dimension:
                        scores_by_dimension[dim] = {"total": 0, "max_total": 0, "count": 0}
                    scores_by_dimension[dim]["total"] += sc.get("score", 0)
                    scores_by_dimension[dim]["max_total"] += sc.get("max_score", 5)
                    scores_by_dimension[dim]["count"] += 1
            except Exception:
                pass

            dimension_scores = {}
            for dim, vals in scores_by_dimension.items():
                pct = round((vals["total"] / vals["max_total"]) * 100) if vals["max_total"] else 0
                dimension_scores[dim] = pct

            overall_pct = round((ev.get("total_score", 0) / ev.get("max_score", 1)) * 100) if ev.get("max_score") else 0

            evaluations.append({
                "session_id": ev["id"],
                "job_title": job_title,
                "interview_type": ev.get("interview_type"),
                "status": ev.get("status"),
                "recommendation": ev.get("recommendation"),
                "overall_score": overall_pct,
                "dimension_scores": dimension_scores,
                "overall_notes": ev.get("overall_notes"),
                "created_at": ev.get("created_at"),
            })
    except Exception:
        pass

    # 3. Certificates
    certificates = []
    try:
        cert_res = supabase.table("certificates").select(
            "id, student_name, company_name, job_title, start_date, end_date, "
            "skills_demonstrated, performance_summary, mentor_name, "
            "verification_code, issued_at"
        ).eq("student_id", student_id).order("issued_at", desc=True).execute()
        certificates = cert_res.data or []
    except Exception:
        pass

    # 4. Internships
    internships = []
    try:
        intern_res = supabase.table("internships").select(
            "id, job_id, company_id, status, start_date, end_date, "
            "mentor_name, team, conclusion_type, conclusion_note, concluded_at"
        ).eq("student_id", student_id).order("start_date", desc=True).execute()

        for intern in (intern_res.data or []):
            # Get company name + job title
            company_name = None
            job_title = None
            try:
                if intern.get("company_id"):
                    cr = supabase.table("companies").select("name").eq(
                        "id", intern["company_id"]
                    ).maybe_single().execute()
                    if cr.data:
                        company_name = cr.data.get("name")
            except Exception:
                pass
            try:
                if intern.get("job_id"):
                    jr = supabase.table("jobs").select("title").eq(
                        "id", intern["job_id"]
                    ).maybe_single().execute()
                    if jr.data:
                        job_title = jr.data.get("title")
            except Exception:
                pass

            internships.append({
                **intern,
                "company_name": company_name,
                "job_title": job_title,
            })
    except Exception:
        pass

    # 5. Applications history
    applications = []
    try:
        apps_res = supabase.table("applications").select(
            "id, job_id, status, ai_score, created_at"
        ).eq("student_id", student_id).order("created_at", desc=True).execute()

        for app in (apps_res.data or []):
            job_title = None
            company_name = None
            try:
                jr = supabase.table("jobs").select(
                    "title, companies(name)"
                ).eq("id", app["job_id"]).maybe_single().execute()
                if jr.data:
                    job_title = jr.data.get("title")
                    co = jr.data.get("companies")
                    if isinstance(co, dict):
                        company_name = co.get("name")
            except Exception:
                pass
            applications.append({
                **app,
                "job_title": job_title,
                "company_name": company_name,
            })
    except Exception:
        pass

    # Build skills with levels from student record
    skills_raw = student_data.get("skills") or []
    skills = [{"name": s, "level": 0, "verified": False} for s in skills_raw]

    return jsonify({
        "data": {
            "id": student_id,
            "name": profile_data.get("full_name"),
            "email": user_email,
            "avatar_url": profile_data.get("avatar_url"),
            "school": university_name,
            "department": student_data.get("department"),
            "graduation_year": student_data.get("graduation_year"),
            "gpa": student_data.get("gpa"),
            "bio": student_data.get("bio"),
            "jp_level": student_data.get("jp_level"),
            "location": student_data.get("location"),
            "phone": student_data.get("phone"),
            "linkedin": student_data.get("linkedin"),
            "github": student_data.get("github"),
            "portfolio": student_data.get("portfolio"),
            "skills": skills,
            "strengths": student_data.get("strengths") or [],
            "awards": student_data.get("awards") or [],
            "experiences": student_data.get("experiences") or [],
            "research_title": student_data.get("research_title"),
            "badges": student_data.get("badges") or [],
            "resume_url": student_data.get("resume_url"),
            "verification_status": student_data.get("verification_status", "unverified"),
            "profile_completeness": float(student_data.get("profile_completeness") or 0),
            # Admin-specific data
            "evaluations": evaluations,
            "certificates": certificates,
            "internships": internships,
            "applications": applications,
        }
    })


# ---------------------------------------------------------------------------
# POST /api/admin/students/<student_id>/ai-analysis
# Uses Claude to analyse a student against a specific JD and produce
# Analytical score, Cultural Fitment score, and recommendations.
# ---------------------------------------------------------------------------

@admin_bp.post("/students/<string:student_id>/ai-analysis")
@require_role(["admin", "super_admin"])
def admin_student_ai_analysis(student_id: str):
    def _err(code, msg, status):
        return jsonify({"error": {"code": code, "message": msg}}), status

    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    if not job_id:
        return _err("VALIDATION_ERROR", "job_id is required", 400)

    # Fetch job
    job_data = {}
    try:
        jr = supabase.table("jobs").select(
            "id, title, department, description, skills, "
            "responsibilities, qualifications, required_language, "
            "experience_level, employment_type, location"
        ).eq("id", job_id).maybe_single().execute()
        if not jr.data:
            return _err("NOT_FOUND", "Job not found", 404)
        job_data = jr.data
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    # Fetch student
    student_data = {}
    try:
        sr = supabase.table("students").select("*").eq("id", student_id).maybe_single().execute()
        if sr.data:
            student_data = sr.data
    except Exception:
        pass

    # Fetch profile
    profile_name = "Unknown"
    try:
        pr = supabase.table("profiles").select("full_name").eq("id", student_id).maybe_single().execute()
        if pr.data:
            profile_name = pr.data.get("full_name", "Unknown")
    except Exception:
        pass

    # University name
    university_name = "Unknown"
    if student_data.get("university_id"):
        try:
            ur = supabase.table("universities").select("name").eq(
                "id", student_data["university_id"]
            ).maybe_single().execute()
            if ur.data:
                university_name = ur.data.get("name", "Unknown")
        except Exception:
            pass

    # Build student dict for LLM
    student_for_llm = {
        "name": profile_name,
        "university_name": university_name,
        "department": student_data.get("department"),
        "gpa": str(student_data.get("gpa") or "N/A"),
        "skills": student_data.get("skills") or [],
        "jp_level": student_data.get("jp_level"),
        "research_title": student_data.get("research_title"),
        "graduation_year": student_data.get("graduation_year"),
        "bio": student_data.get("bio"),
        "strengths": student_data.get("strengths") or [],
        "experiences": student_data.get("experiences") or [],
        "awards": student_data.get("awards") or [],
    }

    # Check for existing AI match score
    scores = {"total": 0, "skill_match": 0, "research_sim": 0, "lang_readiness": 0, "learning_traj": 0}
    try:
        # Look for application ai_score
        app_res = supabase.table("applications").select(
            "ai_score"
        ).eq("student_id", student_id).eq("job_id", job_id).maybe_single().execute()
        if app_res.data and app_res.data.get("ai_score"):
            scores["total"] = int(app_res.data["ai_score"])
    except Exception:
        pass

    # Call Claude LLM
    try:
        from ..services.llm_service import LLMService
        svc = LLMService("claude")
        analysis = svc.analyze_one(job_data, student_for_llm, scores)
        if not analysis:
            return _err("LLM_ERROR", "AI analysis failed — no response", 500)
    except ValueError as ve:
        return _err("CONFIG_ERROR", str(ve), 500)
    except Exception as exc:
        return _err("LLM_ERROR", f"AI analysis failed: {exc}", 500)

    return jsonify({
        "data": {
            "student_id": student_id,
            "job_id": job_id,
            "job_title": job_data.get("title"),
            "analysis": analysis,
        }
    })
