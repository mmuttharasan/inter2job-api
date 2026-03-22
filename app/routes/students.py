"""
Students API — /api/students/*

Student-self endpoints:
  GET  /api/students/me                — student's own profile
  PUT  /api/students/me                — update own profile
  POST /api/students/me/ai-assist      — AI-assisted content generation (lite/pro)
  GET  /api/students/me/applications   — student's job applications

Recruiter/admin-facing endpoints:
  GET  /api/students/         — paginated list of verified students
  GET  /api/students/{id}     — full profile of one verified student
"""

import json
import os
import re
from flask import Blueprint, jsonify, request, g
from ..middleware.auth import require_role, require_auth
from ..services.student_service import (
    get_student_profile, update_student_profile,
    get_student_settings, update_student_settings,
)
from ..services.supabase_client import supabase

students_bp = Blueprint("students", __name__)


def _err(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


# ---------------------------------------------------------------------------
# GET /api/students/me
# ---------------------------------------------------------------------------

@students_bp.get("/me")
@require_role(["student"])
def get_my_profile():
    profile = get_student_profile(g.user_id, g.user_email)
    return jsonify({"data": profile})


# ---------------------------------------------------------------------------
# PUT /api/students/me
# ---------------------------------------------------------------------------

@students_bp.put("/me")
@require_role(["student"])
def update_my_profile():
    data = request.get_json() or {}
    try:
        result = update_student_profile(g.user_id, data)
    except ValueError as e:
        return jsonify({"error": {"code": "VALIDATION_ERROR", "message": str(e)}}), 400
    return jsonify({"data": result})


# ---------------------------------------------------------------------------
# POST /api/students/me/ai-assist
# ---------------------------------------------------------------------------

_AI_ASSIST_FIELDS = {"bio", "strengths", "skills", "awards"}
_AI_ASSIST_TIERS = {"lite", "pro"}


def _build_ai_prompt(field: str, tier: str, profile_context: dict) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the given field + tier."""
    name = profile_context.get("name") or "the student"
    department = profile_context.get("department") or "their program"
    university = profile_context.get("university") or "their university"
    skills = ", ".join(profile_context.get("skills") or []) or "not specified"
    strengths = ", ".join(profile_context.get("strengths") or []) or "not specified"
    bio = profile_context.get("bio") or ""
    gpa = profile_context.get("gpa") or "N/A"
    jp_level = profile_context.get("jp_level") or "None"
    graduation_year = profile_context.get("graduation_year") or "N/A"
    awards = ", ".join(profile_context.get("awards") or []) or "none yet"

    ctx_block = (
        f"Student: {name}\n"
        f"University: {university}\n"
        f"Department: {department}\n"
        f"GPA: {gpa}\n"
        f"JLPT Level: {jp_level}\n"
        f"Graduation Year: {graduation_year}\n"
        f"Current Skills: {skills}\n"
        f"Current Strengths: {strengths}\n"
        f"Current Bio: {bio[:300] if bio else 'empty'}\n"
        f"Awards: {awards}\n"
    )

    system = (
        "You are a career advisor helping international students in Japan craft "
        "compelling professional profiles for internship applications. "
        "Respond ONLY with valid JSON — no markdown fences, no extra text."
    )

    if field == "bio":
        if tier == "lite":
            user = (
                f"Write a short, professional bio (2-3 sentences, under 200 characters) "
                f"for this student. Keep it simple and direct.\n\n{ctx_block}\n"
                f'Respond with JSON: {{"bio": "the bio text", "tips": ["tip1", "tip2"]}}'
            )
        else:
            user = (
                f"Write 3 professional bio variations for this student. "
                f"Each should be 3-4 sentences, compelling, and highlight unique qualities. "
                f"Also provide 3 actionable tips to improve their bio.\n\n{ctx_block}\n"
                f'Respond with JSON: {{"bios": ["bio1", "bio2", "bio3"], '
                f'"tips": ["tip1", "tip2", "tip3"]}}'
            )

    elif field == "strengths":
        if tier == "lite":
            user = (
                f"Suggest 3 key strengths for this student based on their profile. "
                f"Each strength should be a concise phrase (5-10 words).\n\n{ctx_block}\n"
                f'Respond with JSON: {{"strengths": ["strength1", "strength2", "strength3"]}}'
            )
        else:
            user = (
                f"Suggest 5 compelling, specific strengths for this student. "
                f"Each should be a detailed phrase showing concrete capability "
                f"(e.g., 'Cross-cultural communication in Japanese business settings'). "
                f"Also explain why each strength matters for internship applications.\n\n{ctx_block}\n"
                f'Respond with JSON: {{"strengths": [{{"text": "strength", "why": "reason"}}]}}'
            )

    elif field == "skills":
        if tier == "lite":
            user = (
                f"Suggest 5 relevant skills this student should add to their profile "
                f"based on their department and background. Return skill names only.\n\n{ctx_block}\n"
                f'Respond with JSON: {{"skills": [{{"name": "skill", "category": "hard|soft"}}]}}'
            )
        else:
            user = (
                f"Suggest 8 skills (mix of technical and soft) this student should "
                f"highlight, based on their department, existing skills, and the Japanese "
                f"internship market. For each skill, explain relevance and suggest a proficiency level.\n\n{ctx_block}\n"
                f'Respond with JSON: {{"skills": [{{"name": "skill", "category": "hard|soft", '
                f'"relevance": "why this matters", "suggested_level": 70}}]}}'
            )

    elif field == "awards":
        if tier == "lite":
            user = (
                f"Help rephrase these awards to sound more professional and impactful. "
                f"If no awards exist, suggest 3 types of achievements the student "
                f"could highlight.\n\n{ctx_block}\n"
                f'Respond with JSON: {{"awards": ["award1", "award2", "award3"], '
                f'"tips": ["tip1"]}}'
            )
        else:
            user = (
                f"For each existing award, provide a polished version. Then suggest "
                f"5 additional achievements/activities the student could highlight based "
                f"on their background. Include tips on framing achievements.\n\n{ctx_block}\n"
                f'Respond with JSON: {{"improved_awards": ["polished1"], '
                f'"suggested_awards": ["suggestion1"], '
                f'"tips": ["tip1", "tip2"]}}'
            )
    else:
        user = ""

    return system, user


def _call_llm(system_prompt: str, user_prompt: str) -> dict:
    """Call Claude Haiku for AI assist. Returns parsed JSON dict."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key or api_key == "your-anthropic-api-key-here":
        # Fallback to Gemini
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        if not gemini_key or gemini_key == "your-gemini-api-key-here":
            raise RuntimeError("No LLM API key configured (ANTHROPIC_API_KEY or GEMINI_API_KEY)")
        from google import genai as _genai
        client = _genai.Client(api_key=gemini_key)
        resp = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"{system_prompt}\n\n{user_prompt}",
            config={"temperature": 0.7, "max_output_tokens": 1024},
        )
        text = resp.text.strip()
    else:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = msg.content[0].text.strip()

    # Strip markdown fences if present
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        text = m.group(1).strip()
    return json.loads(text)


@students_bp.post("/me/ai-assist")
@require_role(["student"])
def ai_assist_profile():
    """Generate AI-assisted content for student profile fields.

    Body JSON:
        field: "bio" | "strengths" | "skills" | "awards"
        tier:  "lite" | "pro"  (default: "lite")
    """
    body = request.get_json() or {}
    field = body.get("field", "").strip()
    tier = body.get("tier", "lite").strip()

    if field not in _AI_ASSIST_FIELDS:
        return _err("INVALID_FIELD", f"field must be one of {sorted(_AI_ASSIST_FIELDS)}", 400)
    if tier not in _AI_ASSIST_TIERS:
        return _err("INVALID_TIER", "tier must be 'lite' or 'pro'", 400)

    # Fetch current profile as context
    try:
        profile_context = get_student_profile(g.user_id, g.user_email)
    except Exception:
        profile_context = {}

    system_prompt, user_prompt = _build_ai_prompt(field, tier, profile_context)

    try:
        result = _call_llm(system_prompt, user_prompt)
    except Exception as exc:
        return _err("AI_ERROR", f"AI generation failed: {exc}", 502)

    return jsonify({"data": {"field": field, "tier": tier, "suggestions": result}})


# ---------------------------------------------------------------------------
# GET /api/students/me/settings
# ---------------------------------------------------------------------------

@students_bp.get("/me/settings")
@require_role(["student"])
def get_my_settings():
    settings = get_student_settings(g.user_id, g.user_email)
    return jsonify({"data": settings})


# ---------------------------------------------------------------------------
# PUT /api/students/me/settings
# ---------------------------------------------------------------------------

@students_bp.put("/me/settings")
@require_role(["student"])
def update_my_settings():
    data = request.get_json() or {}
    try:
        result = update_student_settings(g.user_id, data)
    except ValueError as e:
        return jsonify({"error": {"code": "VALIDATION_ERROR", "message": str(e)}}), 400
    return jsonify({"data": result})


# ---------------------------------------------------------------------------
# GET /api/students/me/applications
# ---------------------------------------------------------------------------

@students_bp.get("/me/applications")
@require_role(["student"])
def get_my_applications():
    """Return all job applications for the authenticated student."""
    status_filter = request.args.get("status", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    limit = min(100, max(1, int(request.args.get("limit", 50))))

    try:
        query = (
            supabase.table("applications")
            .select("id, job_id, status, ai_score, cover_letter, created_at, updated_at")
            .eq("student_id", g.user_id)
            .order("created_at", desc=True)
        )
        if status_filter and status_filter != "all":
            query = query.eq("status", status_filter)

        result = query.execute()
        rows = result.data or []
    except Exception as exc:
        return _err("SERVER_ERROR", f"Failed to fetch applications: {exc}", 500)

    # Gather job_ids to fetch job + company info
    job_ids = list({r["job_id"] for r in rows if r.get("job_id")})
    jobs_map = {}
    if job_ids:
        try:
            jobs_res = (
                supabase.table("jobs")
                .select("id, title, location, company_id, status, deadline")
                .in_("id", job_ids)
                .execute()
            )
            for j in (jobs_res.data or []):
                jobs_map[j["id"]] = j
        except Exception:
            pass

    # Gather company_ids
    company_ids = list({j.get("company_id") for j in jobs_map.values() if j.get("company_id")})
    companies_map = {}
    if company_ids:
        try:
            comp_res = (
                supabase.table("companies")
                .select("id, name, logo_url, location")
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
        job = jobs_map.get(r.get("job_id")) or {}
        company = companies_map.get(job.get("company_id")) or {}
        data.append({
            "id": r["id"],
            "job_id": r.get("job_id"),
            "job_title": job.get("title"),
            "company_name": company.get("name"),
            "company_logo_url": company.get("logo_url"),
            "location": job.get("location") or company.get("location"),
            "status": r.get("status", "pending"),
            "ai_score": r.get("ai_score"),
            "cover_letter": r.get("cover_letter"),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
        })

    # Count by status
    by_status = {}
    for r in rows:
        s = r.get("status", "pending")
        by_status[s] = by_status.get(s, 0) + 1

    return jsonify({
        "data": data,
        "meta": {"total": total, "page": page, "limit": limit, "by_status": by_status},
    })


# ---------------------------------------------------------------------------
# GET /api/students/  (paginated, filtered list for recruiters/admins)
# ---------------------------------------------------------------------------

@students_bp.get("/")
@require_auth
def list_students():
    allowed = {"recruiter", "university_admin", "university", "admin", "super_admin"}
    if g.user_role not in allowed:
        return _err("FORBIDDEN", "Not allowed", 403)

    page          = max(1, int(request.args.get("page", 1)))
    limit         = min(100, max(1, int(request.args.get("limit", 20))))
    search        = request.args.get("search", "").strip()
    jp_level      = request.args.get("jp_level", "").strip()
    university_id = request.args.get("university_id", "").strip()
    sort          = request.args.get("sort", "gpa")
    order         = request.args.get("order", "desc")
    status_filter = request.args.get("status", "active")

    try:
        query = (
            supabase.table("students")
            .select(
                "id, university_id, department, graduation_year, gpa, "
                "skills, verification_status, jp_level, bio, research_title, "
                "badges, profile_completeness, "
                "profiles!inner(full_name, avatar_url, status)"
            )
            .eq("verification_status", "verified")
        )

        if jp_level:
            query = query.eq("jp_level", jp_level)
        if university_id:
            query = query.eq("university_id", university_id)

        asc = (order == "asc")
        if sort == "name":
            query = query.order("profiles.full_name", desc=not asc)
        else:
            query = query.order("gpa", desc=not asc)

        result = query.execute()
        rows = result.data or []

    except Exception as exc:
        return _err("SERVER_ERROR", f"Failed to fetch students: {exc}", 500)

    # In-memory search by name or skill
    if search:
        sl = search.lower()
        rows = [
            r for r in rows
            if sl in (((r.get("profiles") or {}).get("full_name")) or "").lower()
            or any(sl in s.lower() for s in (r.get("skills") or []))
        ]

    # Filter by profile status
    if status_filter == "active":
        rows = [r for r in rows if (r.get("profiles") or {}).get("status") == "active"]

    total = len(rows)
    page_rows = rows[(page - 1) * limit : page * limit]

    data = []
    for r in page_rows:
        profile = r.get("profiles") or {}
        full_name = profile.get("full_name") or ""
        initials = "".join(p[0].upper() for p in full_name.split() if p)[:2] or "??"
        data.append({
            "id": r["id"],
            "name": full_name,
            "initials": initials,
            "avatar_url": profile.get("avatar_url"),
            "department": r.get("department"),
            "graduation_year": r.get("graduation_year"),
            "gpa": str(r["gpa"]) if r.get("gpa") is not None else None,
            "skills": (r.get("skills") or [])[:5],
            "jp_level": r.get("jp_level"),
            "verified": True,
            "status": "Active" if profile.get("status") == "active" else "Inactive",
            "bio": r.get("bio"),
            "research_title": r.get("research_title"),
            "badges": r.get("badges") or [],
        })

    return jsonify({"data": data, "meta": {"page": page, "limit": limit, "total": total}})


# ---------------------------------------------------------------------------
# GET /api/students/{student_id}
# ---------------------------------------------------------------------------

@students_bp.get("/<string:student_id>")
@require_auth
def get_student(student_id: str):
    allowed = {"recruiter", "university_admin", "university", "admin", "super_admin", "student"}
    if g.user_role not in allowed:
        return _err("FORBIDDEN", "Not allowed", 403)

    try:
        profile_res = (
            supabase.table("profiles")
            .select("full_name, avatar_url, university_id, status")
            .eq("id", student_id)
            .maybe_single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Student not found", 404)

    if not profile_res.data:
        return _err("NOT_FOUND", "Student not found", 404)

    try:
        student_res = (
            supabase.table("students")
            .select("*")
            .eq("id", student_id)
            .maybe_single()
            .execute()
        )
    except Exception:
        student_res = type("R", (), {"data": None})()

    student = student_res.data or {}
    profile = profile_res.data
    verification = student.get("verification_status", "unverified")

    if g.user_role not in {"admin", "super_admin"} and verification != "verified":
        return _err("STUDENT_NOT_VERIFIED", "Student profile is not verified", 403)

    # Fetch university name
    university_name = None
    university_id = profile.get("university_id") or student.get("university_id")
    if university_id:
        try:
            uni_res = (
                supabase.table("universities")
                .select("name")
                .eq("id", university_id)
                .maybe_single()
                .execute()
            )
            if uni_res.data:
                university_name = uni_res.data.get("name")
        except Exception:
            pass

    # Normalize skills to [{name, level, verified}]
    skills_raw = student.get("skills") or []
    skills = [
        s if isinstance(s, dict)
        else {"name": str(s), "level": 75, "verified": verification == "verified"}
        for s in skills_raw
    ]

    return jsonify({
        "data": {
            "id": student_id,
            "name": profile.get("full_name"),
            "avatar_url": profile.get("avatar_url"),
            "school": university_name,
            "department": student.get("department"),
            "graduation_year": student.get("graduation_year"),
            "gpa": str(student["gpa"]) if student.get("gpa") is not None else None,
            "bio": student.get("bio"),
            "jp_level": student.get("jp_level"),
            "location": student.get("location"),
            "phone": student.get("phone"),
            "linkedin": student.get("linkedin"),
            "github": student.get("github"),
            "portfolio": student.get("portfolio"),
            "skills": skills,
            "strengths": student.get("strengths") or [],
            "awards": student.get("awards") or [],
            "experiences": student.get("experiences") or [],
            "research_title": student.get("research_title"),
            "badges": student.get("badges") or [],
            "resume_url": student.get("resume_url"),
            "verification_status": verification,
            "profile_completeness": float(student.get("profile_completeness") or 0),
        }
    })


# ═══════════════════════════════════════════════════════════════════════════
# JD Lifecycle — Student job discovery & offer management
# ═══════════════════════════════════════════════════════════════════════════

from datetime import datetime
from ..services.notification_service import notify, notify_admins


# ---------------------------------------------------------------------------
# GET /api/students/available-jobs
# ---------------------------------------------------------------------------

@students_bp.get("/available-jobs")
@require_auth
def available_jobs():
    """Jobs available to the student via university assignment."""
    page = max(1, int(request.args.get("page", 1)))
    limit = min(100, max(1, int(request.args.get("limit", 20))))

    # Get student's university
    uni_id = None
    try:
        profile_res = (
            supabase.table("profiles")
            .select("university_id")
            .eq("id", g.user_id)
            .single()
            .execute()
        )
        uni_id = profile_res.data.get("university_id") if profile_res.data else None
    except Exception:
        pass

    if not uni_id:
        return jsonify({"data": [], "meta": {"total": 0, "page": page, "limit": limit, "pages": 0}})

    # Find jobs assigned to this university
    try:
        assign_res = (
            supabase.table("job_university_assignments")
            .select("job_id, student_ids")
            .eq("university_id", uni_id)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to fetch available jobs", 500)

    assignments = assign_res.data or []
    if not assignments:
        return jsonify({"data": [], "meta": {"total": 0, "page": page, "limit": limit, "pages": 0}})

    job_ids = [a["job_id"] for a in assignments]
    # Track if student was specifically notified
    notified_job_ids = set()
    for a in assignments:
        if g.user_id in (a.get("student_ids") or []):
            notified_job_ids.add(a["job_id"])

    # Fetch jobs that are open for applications
    try:
        jobs_res = (
            supabase.table("jobs")
            .select("id, title, department, location, description, skills, "
                    "salary_min, salary_max, deadline, employment_type, is_remote, "
                    "openings, company_id, created_at, lifecycle_stage")
            .in_("id", job_ids)
            .in_("lifecycle_stage", ["university_assigned", "collecting_applications"])
            .order("created_at", desc=True)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to fetch jobs", 500)

    rows = jobs_res.data or []

    # Attach company info
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

    # Check which jobs the student has already applied to
    already_applied = set()
    try:
        app_res = (
            supabase.table("applications")
            .select("job_id")
            .eq("student_id", g.user_id)
            .in_("job_id", job_ids)
            .execute()
        )
        already_applied = {a["job_id"] for a in (app_res.data or [])}
    except Exception:
        pass

    total = len(rows)
    page_rows = rows[(page - 1) * limit : page * limit]

    data = []
    for r in page_rows:
        company = companies_map.get(r.get("company_id"), {})
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
            "company_id": r.get("company_id"),
            "company_name": company.get("name"),
            "company_logo_url": company.get("logo_url"),
            "company_industry": company.get("industry"),
            "created_at": r.get("created_at"),
            "lifecycle_stage": r.get("lifecycle_stage"),
            "is_notified": r["id"] in notified_job_ids,
            "has_applied": r["id"] in already_applied,
        })

    return jsonify({
        "data": data,
        "meta": {"total": total, "page": page, "limit": limit,
                 "pages": (total + limit - 1) // limit if limit else 1},
    })


# ---------------------------------------------------------------------------
# POST /api/students/jobs/<job_id>/apply
# ---------------------------------------------------------------------------

@students_bp.post("/jobs/<string:job_id>/apply")
@require_auth
def apply_to_job(job_id):
    """Student applies to a job."""
    payload = request.get_json(silent=True) or {}
    cover_letter = payload.get("cover_letter", "")

    # Verify job exists and is open
    try:
        job_res = (
            supabase.table("jobs")
            .select("id, lifecycle_stage, title")
            .eq("id", job_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)

    if not job_res.data:
        return _err("NOT_FOUND", "Job not found", 404)

    stage = job_res.data.get("lifecycle_stage")
    if stage not in ("university_assigned", "collecting_applications", "under_curation"):
        return _err("VALIDATION_ERROR", "This job is not currently accepting applications", 400)

    # Check for duplicate application
    try:
        dup_res = (
            supabase.table("applications")
            .select("id")
            .eq("job_id", job_id)
            .eq("student_id", g.user_id)
            .maybe_single()
            .execute()
        )
        if dup_res.data:
            return _err("CONFLICT", "You have already applied to this job", 409)
    except Exception:
        pass

    # Create application
    try:
        app_res = supabase.table("applications").insert({
            "job_id": job_id,
            "student_id": g.user_id,
            "status": "pending",
            "cover_letter": cover_letter,
        }).execute()
    except Exception:
        return _err("SERVER_ERROR", "Failed to submit application", 500)

    if not app_res.data:
        return _err("SERVER_ERROR", "Failed to submit application", 500)

    # Transition lifecycle stage to collecting_applications if still university_assigned
    if stage == "university_assigned":
        try:
            supabase.table("jobs").update({
                "lifecycle_stage": "collecting_applications",
            }).eq("id", job_id).execute()
        except Exception:
            pass  # non-critical — don't block the application

    # Notify platform admins
    notify_admins(
        "student_applied",
        "New application received",
        f"A student has applied to '{job_res.data.get('title')}'.",
        "job", job_id,
    )

    return jsonify({"data": app_res.data[0]}), 201


# ---------------------------------------------------------------------------
# GET /api/students/my-offers
# ---------------------------------------------------------------------------

@students_bp.get("/my-offers")
@require_auth
def get_my_offers():
    """Get all offers for the authenticated student."""
    try:
        res = (
            supabase.table("offers")
            .select("*, jobs(title, company_id, companies(name, logo_url))")
            .eq("student_id", g.user_id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception:
        try:
            res = (
                supabase.table("offers")
                .select("*")
                .eq("student_id", g.user_id)
                .order("created_at", desc=True)
                .execute()
            )
        except Exception:
            return _err("SERVER_ERROR", "Failed to fetch offers", 500)

    offers = res.data or []
    formatted = []
    for o in offers:
        job_data = o.get("jobs") or {}
        company_data = job_data.get("companies") or {}
        formatted.append({
            "id": o["id"],
            "job_id": o.get("job_id"),
            "job_title": job_data.get("title"),
            "company_name": company_data.get("name"),
            "company_logo_url": company_data.get("logo_url"),
            "offer_details": o.get("offer_details", {}),
            "status": o.get("status"),
            "sent_at": o.get("sent_at"),
            "response_deadline": o.get("response_deadline"),
            "responded_at": o.get("responded_at"),
            "created_at": o.get("created_at"),
        })

    return jsonify({"data": formatted, "meta": {"total": len(formatted)}})


# ---------------------------------------------------------------------------
# POST /api/students/offers/<offer_id>/respond
# ---------------------------------------------------------------------------

@students_bp.post("/offers/<string:offer_id>/respond")
@require_auth
def respond_to_offer(offer_id):
    """Student accepts or rejects an offer."""
    payload = request.get_json(silent=True) or {}
    decision = payload.get("decision")
    note = payload.get("note", "")

    if decision not in ("accepted", "rejected"):
        return _err("VALIDATION_ERROR", "'decision' must be 'accepted' or 'rejected'", 400)

    # Fetch offer
    try:
        offer_res = (
            supabase.table("offers")
            .select("id, student_id, job_id, application_id, company_id, status")
            .eq("id", offer_id)
            .single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Offer not found", 404)

    if not offer_res.data:
        return _err("NOT_FOUND", "Offer not found", 404)

    if offer_res.data.get("student_id") != g.user_id:
        return _err("FORBIDDEN", "Not your offer", 403)

    if offer_res.data.get("status") != "sent":
        return _err("INVALID_TRANSITION", "Can only respond to 'sent' offers", 422)

    now = datetime.utcnow().isoformat()

    # Update offer
    try:
        supabase.table("offers").update({
            "status": decision,
            "responded_at": now,
            "rejection_reason": note if decision == "rejected" else None,
        }).eq("id", offer_id).execute()
    except Exception:
        return _err("SERVER_ERROR", "Failed to update offer", 500)

    # Update application status
    app_status = "accepted" if decision == "accepted" else "rejected"
    try:
        supabase.table("applications").update({
            "status": app_status,
        }).eq("id", offer_res.data.get("application_id")).execute()
    except Exception:
        pass

    # If accepted, create internship record
    if decision == "accepted":
        offer_details = {}
        try:
            full_offer = (
                supabase.table("offers")
                .select("offer_details")
                .eq("id", offer_id)
                .single()
                .execute()
            )
            offer_details = (full_offer.data or {}).get("offer_details", {})
        except Exception:
            pass

        start_date = offer_details.get("start_date", datetime.utcnow().strftime("%Y-%m-%d"))
        end_date = offer_details.get("end_date", "2026-12-31")

        try:
            supabase.table("internships").insert({
                "application_id": offer_res.data.get("application_id"),
                "student_id": g.user_id,
                "job_id": offer_res.data.get("job_id"),
                "company_id": offer_res.data.get("company_id"),
                "status": "pre_boarding",
                "start_date": start_date,
                "end_date": end_date,
            }).execute()
        except Exception:
            pass

    # Notify platform admin
    notify_admins(
        "offer_accepted" if decision == "accepted" else "offer_rejected",
        f"Offer {decision}",
        f"Student has {decision} the internship offer.",
        "job", offer_res.data.get("job_id"),
    )

    return jsonify({
        "data": {"id": offer_id, "status": decision},
    })


# ---------------------------------------------------------------------------
# GET /api/students/my-interviews
# ---------------------------------------------------------------------------

@students_bp.get("/my-interviews")
@require_auth
def get_my_interviews():
    """Get all interview schedules for the authenticated student."""
    try:
        sched_res = (
            supabase.table("interview_schedules")
            .select("*")
            .eq("student_id", g.user_id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to fetch interview schedules", 500)

    schedules = sched_res.data or []
    if not schedules:
        return jsonify({"data": [], "meta": {"total": 0}})

    # Gather round_ids to fetch round info
    round_ids = list({s["round_id"] for s in schedules})
    rounds_map = {}
    try:
        rounds_res = (
            supabase.table("interview_rounds")
            .select("id, job_id, round_number, status, proposed_slots")
            .in_("id", round_ids)
            .execute()
        )
        for r in (rounds_res.data or []):
            rounds_map[r["id"]] = r
    except Exception:
        pass

    # Gather job_ids to fetch job + company info
    job_ids = list({r.get("job_id") for r in rounds_map.values() if r.get("job_id")})
    jobs_map = {}
    if job_ids:
        try:
            jobs_res = (
                supabase.table("jobs")
                .select("id, title, company_id, location, lifecycle_stage, deadline")
                .in_("id", job_ids)
                .execute()
            )
            for j in (jobs_res.data or []):
                jobs_map[j["id"]] = j
        except Exception:
            pass

    company_ids = list({j.get("company_id") for j in jobs_map.values() if j.get("company_id")})
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

    formatted = []
    for s in schedules:
        round_info = rounds_map.get(s.get("round_id"), {})
        job_info = jobs_map.get(round_info.get("job_id"), {})
        company_info = companies_map.get(job_info.get("company_id"), {})
        formatted.append({
            "id": s["id"],
            "round_id": s.get("round_id"),
            "application_id": s.get("application_id"),
            "scheduled_slot": s.get("scheduled_slot"),
            "result": s.get("result", "pending"),
            "result_note": s.get("result_note"),
            "created_at": s.get("created_at"),
            "round_number": round_info.get("round_number"),
            "round_status": round_info.get("round_status", round_info.get("status")),
            "job_id": round_info.get("job_id"),
            "job_title": job_info.get("title"),
            "job_location": job_info.get("location"),
            "job_lifecycle_stage": job_info.get("lifecycle_stage"),
            "job_deadline": job_info.get("deadline"),
            "company_name": company_info.get("name"),
            "company_logo_url": company_info.get("logo_url"),
        })

    return jsonify({"data": formatted, "meta": {"total": len(formatted)}})
