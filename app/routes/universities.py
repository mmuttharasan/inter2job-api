"""
University Admin Routes — /api/universities/*

All endpoints require university_admin role. The university is resolved from the
authenticated user's profiles.university_id field.
"""

from flask import Blueprint, jsonify, request, g, send_file

from ..middleware.auth import require_role
from ..services.university_service import (
    get_my_university,
    update_my_university,
    list_my_departments,
    create_my_department,
    update_my_department,
    list_my_students,
    create_student,
    bulk_create_students,
    build_student_template,
    parse_student_excel,
    get_university_student_detail,
)
from ..services.admin_service import (
    list_university_verifications,
    approve_verification,
    reject_verification,
    create_verification_request,
)

universities_bp = Blueprint("universities", __name__)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _err(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _get_university_id():
    """Extract university_id from g.profile; returns (uni_id, None) or (None, error_response)."""
    university_id = g.profile.get("university_id")
    if not university_id:
        return None, _err("NO_UNIVERSITY", "No university linked to this account", 403)
    return university_id, None


# ══════════════════════════════════════════════════════════════════════════════
# §1  University Profile
# ══════════════════════════════════════════════════════════════════════════════

@universities_bp.get("/me")
@require_role(["university_admin"])
def get_profile():
    uni = get_my_university(g.user_id)
    if not uni:
        return _err("NOT_FOUND", "University not found", 404)
    return jsonify({"data": uni})


@universities_bp.put("/me")
@require_role(["university_admin"])
def update_profile():
    university_id, err = _get_university_id()
    if err:
        return err
    data = request.get_json() or {}
    try:
        result = update_my_university(university_id, data)
        return jsonify({"data": result})
    except ValueError as e:
        return _err("UPDATE_FAILED", str(e), 400)


# ══════════════════════════════════════════════════════════════════════════════
# §2  Departments
# ══════════════════════════════════════════════════════════════════════════════

@universities_bp.get("/me/departments")
@require_role(["university_admin"])
def list_departments():
    university_id, err = _get_university_id()
    if err:
        return err
    depts = list_my_departments(university_id)
    return jsonify({"data": depts})


@universities_bp.post("/me/departments")
@require_role(["university_admin"])
def create_department():
    university_id, err = _get_university_id()
    if err:
        return err
    data = request.get_json() or {}
    try:
        dept = create_my_department(university_id, g.user_id, data)
        return jsonify({"data": dept}), 201
    except ValueError as e:
        code = str(e)
        if code == "MISSING_FIELDS":
            return _err(code, "name and code are required", 400)
        if code == "DEPT_EXISTS":
            return _err(code, "A department with this code already exists", 409)
        return _err("CREATE_FAILED", code, 400)


@universities_bp.put("/me/departments/<string:dept_id>")
@require_role(["university_admin"])
def update_department(dept_id: str):
    university_id, err = _get_university_id()
    if err:
        return err
    data = request.get_json() or {}
    try:
        dept = update_my_department(university_id, dept_id, data)
        return jsonify({"data": dept})
    except ValueError as e:
        code = str(e)
        if code == "NOT_FOUND":
            return _err(code, "Department not found", 404)
        return _err("UPDATE_FAILED", code, 400)


# ══════════════════════════════════════════════════════════════════════════════
# §3  Student Management
# ══════════════════════════════════════════════════════════════════════════════

@universities_bp.get("/me/students")
@require_role(["university_admin"])
def list_students():
    university_id, err = _get_university_id()
    if err:
        return err
    params = {
        "page": request.args.get("page", 1),
        "limit": request.args.get("limit", 50),
        "search": request.args.get("search", ""),
        "department": request.args.get("department", ""),
    }
    result = list_my_students(university_id, params)
    return jsonify(result)


@universities_bp.post("/me/students")
@require_role(["university_admin"])
def create_one_student():
    university_id, err = _get_university_id()
    if err:
        return err
    data = request.get_json() or {}
    try:
        student = create_student(university_id, g.user_id, data)
        return jsonify({"data": student}), 201
    except ValueError as e:
        code = str(e)
        if code == "EMAIL_EXISTS":
            return _err(code, "Email is already registered", 409)
        if code == "MISSING_FIELDS":
            return _err(code, "full_name and email are required", 400)
        # code may be "CREATE_FAILED:actual supabase error"
        detail = code.split(":", 1)[1].strip() if ":" in code else code
        return _err("CREATE_FAILED", f"Failed to create student: {detail}", 400)


@universities_bp.post("/me/students/bulk")
@require_role(["university_admin"])
def bulk_create():
    university_id, err = _get_university_id()
    if err:
        return err
    data = request.get_json() or {}
    students = data.get("students") or []
    if not students:
        return _err("EMPTY_LIST", "No students provided", 400)
    if len(students) > 500:
        return _err("LIMIT_EXCEEDED", "Maximum 500 students per batch", 400)
    result = bulk_create_students(university_id, g.user_id, students)
    return jsonify(result), 207


@universities_bp.post("/me/students/upload")
@require_role(["university_admin"])
def upload_students():
    """Accept an .xlsx file, parse it, and bulk-create student accounts."""
    university_id, err = _get_university_id()
    if err:
        return err

    if "file" not in request.files:
        return _err("NO_FILE", "No file provided. Send as multipart field 'file'", 400)

    file = request.files["file"]
    filename = file.filename or ""
    if not filename.endswith(".xlsx"):
        return _err("INVALID_FILE", "Only .xlsx files are supported", 400)

    try:
        students = parse_student_excel(file.stream)
    except ImportError:
        return _err("MISSING_DEPENDENCY", "openpyxl is not installed on the server", 500)
    except Exception as e:
        return _err("PARSE_ERROR", f"Failed to parse file: {e}", 400)

    if not students:
        return _err("EMPTY_FILE", "No valid student rows found (rows start from row 3)", 400)
    if len(students) > 500:
        return _err("LIMIT_EXCEEDED", "Maximum 500 students per upload", 400)

    result = bulk_create_students(university_id, g.user_id, students)
    return jsonify(result), 207


@universities_bp.get("/me/students/<string:student_id>")
@require_role(["university_admin"])
def get_student_detail(student_id: str):
    """Get comprehensive student detail including applications, internships, job fit."""
    university_id, err = _get_university_id()
    if err:
        return err
    detail = get_university_student_detail(university_id, student_id)
    if not detail:
        return _err("NOT_FOUND", "Student not found or does not belong to this university", 404)
    return jsonify({"data": detail})


# ══════════════════════════════════════════════════════════════════════════════
# §4  Verification Workflow
# ══════════════════════════════════════════════════════════════════════════════

@universities_bp.get("/me/verifications")
@require_role(["university_admin"])
def list_verifications():
    """List verification requests. Optional ?status=pending|approved|rejected"""
    university_id, err = _get_university_id()
    if err:
        return err
    status_filter = request.args.get("status") or None
    items = list_university_verifications(university_id, status_filter)
    return jsonify({"data": items})


@universities_bp.get("/me/verifications/<string:req_id>")
@require_role(["university_admin"])
def get_verification(req_id: str):
    university_id, err = _get_university_id()
    if err:
        return err
    # Fetch via the list filtered by ID (avoids a separate query function)
    all_items = list_university_verifications(university_id)
    item = next((i for i in all_items if i["id"] == req_id), None)
    if not item:
        return _err("NOT_FOUND", "Verification request not found", 404)
    return jsonify({"data": item})


@universities_bp.post("/me/verifications")
@require_role(["university_admin"])
def create_verification():
    university_id, err = _get_university_id()
    if err:
        return err
    data = request.get_json() or {}
    try:
        item = create_verification_request(university_id, g.user_id, data)
        return jsonify({"data": item}), 201
    except ValueError as e:
        code = str(e)
        if code == "MISSING_FIELDS":
            return _err(code, "type is required", 400)
        return _err("CREATE_FAILED", code, 400)


@universities_bp.post("/me/verifications/<string:req_id>/approve")
@require_role(["university_admin"])
def approve_verification_route(req_id: str):
    university_id, err = _get_university_id()
    if err:
        return err
    data = request.get_json() or {}
    note = (data.get("note") or "").strip() or None
    try:
        result = approve_verification(req_id, g.user_id, note)
        return jsonify({"data": result})
    except ValueError as e:
        code = str(e)
        if code == "NOT_FOUND":
            return _err(code, "Verification request not found", 404)
        return _err("APPROVE_FAILED", code, 400)


@universities_bp.post("/me/verifications/<string:req_id>/reject")
@require_role(["university_admin"])
def reject_verification_route(req_id: str):
    university_id, err = _get_university_id()
    if err:
        return err
    data = request.get_json() or {}
    reason = (data.get("reason") or "").strip()
    if not reason:
        return _err("MISSING_REASON", "A rejection reason is required", 400)
    try:
        result = reject_verification(req_id, g.user_id, reason)
        return jsonify({"data": result})
    except ValueError as e:
        code = str(e)
        if code == "NOT_FOUND":
            return _err(code, "Verification request not found", 404)
        return _err("REJECT_FAILED", code, 400)


@universities_bp.get("/me/students/template")
@require_role(["university_admin"])
def download_template():
    """Stream the Excel template for bulk student import."""
    try:
        buf = build_student_template()
    except ImportError:
        return _err("MISSING_DEPENDENCY", "openpyxl is not installed on the server", 500)
    except Exception as e:
        return _err("TEMPLATE_ERROR", str(e), 500)

    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="students_import_template.xlsx",
    )
