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
