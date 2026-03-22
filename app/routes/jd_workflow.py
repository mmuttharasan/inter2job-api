"""
University JD Workflow API — /api/universities/me/assigned-jobs/*

Endpoints:
  GET  /me/assigned-jobs                           — list jobs assigned to this university
  GET  /me/assigned-jobs/<job_id>                   — full JD detail
  POST /me/assigned-jobs/<job_id>/notify-students   — notify selected students about JD
  POST /me/assigned-jobs/<job_id>/apply-on-behalf   — apply on behalf of students
  GET  /me/assigned-jobs/<job_id>/my-students-applications — applications from this university
"""

from datetime import datetime
from flask import Blueprint, jsonify, request, g
from ..services.supabase_client import supabase
from ..middleware.auth import require_role
from ..services.notification_service import notify_bulk

jd_workflow_bp = Blueprint("jd_workflow", __name__)


def _err(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _get_university_id(user_id: str):
    """Get university_id from the user's profile."""
    try:
        res = (
            supabase.table("profiles")
            .select("university_id")
            .eq("id", user_id)
            .single()
            .execute()
        )
        uid = res.data.get("university_id") if res.data else None
        if not uid:
            return None, _err("NOT_FOUND", "No university linked to your account", 404)
        return uid, None
    except Exception:
        return None, _err("NOT_FOUND", "No university linked to your account", 404)


# ---------------------------------------------------------------------------
# GET /me/assigned-jobs
# ---------------------------------------------------------------------------

@jd_workflow_bp.get("/me/assigned-jobs")
@require_role(["university_admin"])
def list_assigned_jobs():
    """List all jobs assigned to this university by platform admin."""
    university_id, err = _get_university_id(g.user_id)
    if err:
        return err

    try:
        assign_res = (
            supabase.table("job_university_assignments")
            .select("job_id, assigned_at, student_ids, department_ids, apply_on_behalf")
            .eq("university_id", university_id)
            .order("assigned_at", desc=True)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to fetch assignments", 500)

    assignments = assign_res.data or []
    if not assignments:
        return jsonify({"data": [], "meta": {"total": 0}})

    job_ids = [a["job_id"] for a in assignments]
    assign_map = {a["job_id"]: a for a in assignments}

    # Fetch job details
    try:
        jobs_res = (
            supabase.table("jobs")
            .select("id, title, department, location, status, lifecycle_stage, "
                    "deadline, priority, skills, openings, company_id, created_at, "
                    "description, employment_type, is_remote, salary_min, salary_max")
            .in_("id", job_ids)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to fetch job details", 500)

    jobs = jobs_res.data or []

    # Attach company names
    company_ids = list({j.get("company_id") for j in jobs if j.get("company_id")})
    companies_map = {}
    if company_ids:
        try:
            comp_res = (
                supabase.table("companies")
                .select("id, name, logo_url, industry")
                .in_("id", company_ids)
                .execute()
            )
            for c in (comp_res.data or []):
                companies_map[c["id"]] = c
        except Exception:
            pass

    # Count applications from this university's students per job
    app_counts = {}
    try:
        # Get all student IDs at this university
        students_res = (
            supabase.table("students")
            .select("id")
            .eq("university_id", university_id)
            .execute()
        )
        student_ids = [s["id"] for s in (students_res.data or [])]
        if student_ids:
            for jid in job_ids:
                try:
                    count_res = (
                        supabase.table("applications")
                        .select("id", count="exact")
                        .eq("job_id", jid)
                        .in_("student_id", student_ids)
                        .execute()
                    )
                    app_counts[jid] = count_res.count if hasattr(count_res, "count") and count_res.count is not None else len(count_res.data or [])
                except Exception:
                    app_counts[jid] = 0
    except Exception:
        pass

    formatted = []
    for j in jobs:
        comp = companies_map.get(j.get("company_id"), {})
        assignment = assign_map.get(j["id"], {})
        formatted.append({
            **j,
            "company_name": comp.get("name"),
            "company_logo_url": comp.get("logo_url"),
            "company_industry": comp.get("industry"),
            "assigned_at": assignment.get("assigned_at"),
            "notified_student_ids": assignment.get("student_ids", []),
            "notified_department_ids": assignment.get("department_ids", []),
            "apply_on_behalf": assignment.get("apply_on_behalf", False),
            "university_applications_count": app_counts.get(j["id"], 0),
        })

    return jsonify({"data": formatted, "meta": {"total": len(formatted)}})


# ---------------------------------------------------------------------------
# GET /me/assigned-jobs/<job_id>
# ---------------------------------------------------------------------------

@jd_workflow_bp.get("/me/assigned-jobs/<string:job_id>")
@require_role(["university_admin"])
def get_assigned_job_detail(job_id):
    """Full JD detail for an assigned job."""
    university_id, err = _get_university_id(g.user_id)
    if err:
        return err

    # Verify assignment
    try:
        assign_res = (
            supabase.table("job_university_assignments")
            .select("*")
            .eq("job_id", job_id)
            .eq("university_id", university_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not assigned to your university", 404)

    if not assign_res.data:
        return _err("NOT_FOUND", "Job not assigned to your university", 404)

    # Acknowledge if first time viewing
    if not assign_res.data.get("acknowledged_at"):
        try:
            supabase.table("job_university_assignments").update({
                "acknowledged_at": datetime.utcnow().isoformat(),
            }).eq("id", assign_res.data["id"]).execute()
        except Exception:
            pass

    # Fetch job
    try:
        job_res = (
            supabase.table("jobs")
            .select("*")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not job_res.data:
        return _err("NOT_FOUND", "Job not found", 404)

    job = job_res.data

    # Fetch company
    company = {}
    if job.get("company_id"):
        try:
            comp_res = (
                supabase.table("companies")
                .select("id, name, logo_url, industry, location, website, description")
                .eq("id", job["company_id"])
                .maybe_single()
                .execute()
            )
            company = comp_res.data or {}
        except Exception:
            pass

    return jsonify({
        "data": {
            **job,
            "company": company,
            "assignment": assign_res.data,
        }
    })


# ---------------------------------------------------------------------------
# POST /me/assigned-jobs/<job_id>/notify-students
# ---------------------------------------------------------------------------

@jd_workflow_bp.post("/me/assigned-jobs/<string:job_id>/notify-students")
@require_role(["university_admin"])
def notify_students_about_jd(job_id):
    """Notify selected students or departments about a JD opportunity."""
    university_id, err = _get_university_id(g.user_id)
    if err:
        return err

    # Verify assignment
    try:
        assign_res = (
            supabase.table("job_university_assignments")
            .select("id")
            .eq("job_id", job_id)
            .eq("university_id", university_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not assigned to your university", 404)

    if not assign_res.data:
        return _err("NOT_FOUND", "Job not assigned to your university", 404)

    payload = request.get_json(silent=True) or {}
    student_ids = payload.get("student_ids", [])
    department_ids = payload.get("department_ids", [])
    message = payload.get("message", "")

    # If department_ids provided, gather students from those departments
    if department_ids and not student_ids:
        try:
            dept_students = (
                supabase.table("students")
                .select("id")
                .eq("university_id", university_id)
                .in_("department_id", department_ids)
                .execute()
            )
            student_ids = [s["id"] for s in (dept_students.data or [])]
        except Exception:
            pass

    if not student_ids:
        return _err("VALIDATION_ERROR", "No students to notify", 400)

    # Update assignment record
    try:
        supabase.table("job_university_assignments").update({
            "student_ids": student_ids,
            "department_ids": department_ids,
            "notified_at": datetime.utcnow().isoformat(),
        }).eq("id", assign_res.data["id"]).execute()
    except Exception:
        pass

    # Fetch job title for notification
    title = ""
    try:
        job_res = (
            supabase.table("jobs")
            .select("title")
            .eq("id", job_id)
            .single()
            .execute()
        )
        title = job_res.data.get("title", "") if job_res.data else ""
    except Exception:
        pass

    # Create notifications
    body = message or f"A new opportunity '{title}' is available. Check your portal to apply."
    notify_bulk(
        student_ids, "jd_available",
        f"New Opportunity: {title}",
        body,
        "job", job_id,
    )

    return jsonify({
        "data": {"notified": len(student_ids)},
    })


# ---------------------------------------------------------------------------
# POST /me/assigned-jobs/<job_id>/apply-on-behalf
# ---------------------------------------------------------------------------

@jd_workflow_bp.post("/me/assigned-jobs/<string:job_id>/apply-on-behalf")
@require_role(["university_admin"])
def apply_on_behalf(job_id):
    """University admin applies to a job on behalf of selected students."""
    university_id, err = _get_university_id(g.user_id)
    if err:
        return err

    # Verify assignment
    try:
        assign_res = (
            supabase.table("job_university_assignments")
            .select("id")
            .eq("job_id", job_id)
            .eq("university_id", university_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not assigned to your university", 404)

    if not assign_res.data:
        return _err("NOT_FOUND", "Job not assigned to your university", 404)

    payload = request.get_json(silent=True) or {}
    student_ids = payload.get("student_ids", [])
    cover_letter_template = payload.get("cover_letter_template", "")

    if not student_ids:
        return _err("VALIDATION_ERROR", "'student_ids' must be a non-empty array", 400)

    applied = 0
    skipped = 0
    for sid in student_ids:
        # Check if already applied
        try:
            existing = (
                supabase.table("applications")
                .select("id")
                .eq("job_id", job_id)
                .eq("student_id", sid)
                .maybe_single()
                .execute()
            )
            if existing.data:
                skipped += 1
                continue
        except Exception:
            pass

        try:
            supabase.table("applications").insert({
                "job_id": job_id,
                "student_id": sid,
                "status": "pending",
                "cover_letter": cover_letter_template,
                "note": f"Applied on behalf by university admin ({g.user_id})",
            }).execute()
            applied += 1
        except Exception:
            skipped += 1

    # Mark assignment
    try:
        supabase.table("job_university_assignments").update({
            "apply_on_behalf": True,
        }).eq("id", assign_res.data["id"]).execute()
    except Exception:
        pass

    # Notify applied students
    if student_ids:
        notify_bulk(
            student_ids, "application_submitted_on_behalf",
            "Application submitted on your behalf",
            "Your university has submitted an application on your behalf. Check your portal.",
            "job", job_id,
        )

    return jsonify({
        "data": {"applied": applied, "skipped": skipped},
    })


# ---------------------------------------------------------------------------
# GET /me/assigned-jobs/<job_id>/my-students-applications
# ---------------------------------------------------------------------------

@jd_workflow_bp.get("/me/assigned-jobs/<string:job_id>/my-students-applications")
@require_role(["university_admin"])
def list_university_student_applications(job_id):
    """List applications from this university's students for a job."""
    university_id, err = _get_university_id(g.user_id)
    if err:
        return err

    # Get all students at this university
    try:
        students_res = (
            supabase.table("students")
            .select("id")
            .eq("university_id", university_id)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to fetch students", 500)

    student_ids = [s["id"] for s in (students_res.data or [])]
    if not student_ids:
        return jsonify({"data": [], "meta": {"total": 0}})

    try:
        apps_res = (
            supabase.table("applications")
            .select(
                "id, student_id, status, ai_score, cover_letter, created_at,"
                "students(profiles(full_name))"
            )
            .eq("job_id", job_id)
            .in_("student_id", student_ids)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception:
        try:
            apps_res = (
                supabase.table("applications")
                .select("id, student_id, status, ai_score, created_at")
                .eq("job_id", job_id)
                .in_("student_id", student_ids)
                .order("created_at", desc=True)
                .execute()
            )
        except Exception:
            return _err("SERVER_ERROR", "Failed to fetch applications", 500)

    apps = apps_res.data or []
    formatted = []
    for a in apps:
        student_data = a.get("students") or {}
        profile = student_data.get("profiles") or {}
        formatted.append({
            "id": a["id"],
            "student_id": a.get("student_id"),
            "student_name": profile.get("full_name"),
            "status": a.get("status"),
            "ai_score": a.get("ai_score"),
            "applied_at": a.get("created_at"),
        })

    return jsonify({"data": formatted, "meta": {"total": len(formatted)}})


# ---------------------------------------------------------------------------
# GET /me/assigned-jobs/<job_id>/interview-schedules
# ---------------------------------------------------------------------------

@jd_workflow_bp.get("/me/assigned-jobs/<string:job_id>/interview-schedules")
@require_role(["university_admin"])
def get_job_interview_schedules(job_id):
    """Get interview schedules for a job's students from this university."""
    university_id, err = _get_university_id(g.user_id)
    if err:
        return err

    # Verify assignment
    try:
        assign_res = (
            supabase.table("job_university_assignments")
            .select("id")
            .eq("job_id", job_id)
            .eq("university_id", university_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not assigned to your university", 404)

    if not assign_res.data:
        return _err("NOT_FOUND", "Job not assigned to your university", 404)

    # Get all students at this university
    try:
        students_res = (
            supabase.table("students")
            .select("id")
            .eq("university_id", university_id)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to fetch students", 500)

    student_ids = [s["id"] for s in (students_res.data or [])]
    if not student_ids:
        return jsonify({"data": {"rounds": [], "schedules": []}, "meta": {"total": 0}})

    # Fetch interview rounds for this job
    try:
        rounds_res = (
            supabase.table("interview_rounds")
            .select("*")
            .eq("job_id", job_id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception:
        return jsonify({"data": {"rounds": [], "schedules": []}, "meta": {"total": 0}})

    rounds = rounds_res.data or []
    round_ids = [r["id"] for r in rounds]

    if not round_ids:
        return jsonify({"data": {"rounds": rounds, "schedules": []}, "meta": {"total": 0}})

    # Fetch schedules only for this university's students
    try:
        sched_res = (
            supabase.table("interview_schedules")
            .select("*")
            .in_("round_id", round_ids)
            .in_("student_id", student_ids)
            .order("created_at", desc=False)
            .execute()
        )
    except Exception:
        return jsonify({"data": {"rounds": rounds, "schedules": []}, "meta": {"total": 0}})

    schedules = sched_res.data or []

    # Enrich with student names
    sched_student_ids = list({s["student_id"] for s in schedules})
    names_map = {}
    if sched_student_ids:
        try:
            profiles_res = (
                supabase.table("profiles")
                .select("id, full_name")
                .in_("id", sched_student_ids)
                .execute()
            )
            for p in (profiles_res.data or []):
                names_map[p["id"]] = p.get("full_name")
        except Exception:
            pass

    formatted_schedules = []
    for s in schedules:
        formatted_schedules.append({
            **s,
            "student_name": names_map.get(s["student_id"]),
        })

    return jsonify({
        "data": {"rounds": rounds, "schedules": formatted_schedules},
        "meta": {"total": len(formatted_schedules)},
    })
