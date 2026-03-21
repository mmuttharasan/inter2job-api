"""
Student Service Layer — business logic for /api/students/me endpoints.

All Supabase queries are encapsulated here so route handlers stay thin.
"""

from datetime import datetime, timezone
from ..services.supabase_client import supabase


# ───────────────────────────────────────────────────────────────────────────
# Completeness
# ───────────────────────────────────────────────────────────────────────────

_COMPLETENESS_CHECKS = [
    lambda p, s: bool(p.get("full_name")),
    lambda p, s: bool(s.get("bio")),
    lambda p, s: bool(s.get("department")),
    lambda p, s: bool(s.get("graduation_year")),
    lambda p, s: bool(s.get("gpa") is not None),
    lambda p, s: bool(s.get("jp_level") and s.get("jp_level") != "None"),
    lambda p, s: len(s.get("skills") or []) >= 2,
    lambda p, s: bool(s.get("location")),
    lambda p, s: bool(s.get("linkedin") or s.get("github")),
    lambda p, s: bool(s.get("resume_url")),
]


def _compute_completeness(profile: dict, student: dict) -> float:
    passed = sum(1 for fn in _COMPLETENESS_CHECKS if fn(profile, student))
    return round(passed / len(_COMPLETENESS_CHECKS), 2)


# ───────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────

_PROFILE_FIELDS = {"full_name", "avatar_url"}
_STUDENT_FIELDS = {
    "department", "graduation_year", "gpa", "bio", "jp_level",
    "phone", "location", "linkedin", "github", "portfolio",
    "skills", "strengths", "awards",
}

_ALLOWED_JP_LEVELS = {"N1", "N2", "N3", "N4", "N5", "None"}


def _validate_update(data: dict) -> list[str]:
    errors = []
    if "graduation_year" in data:
        y = data["graduation_year"]
        now = datetime.now().year
        if not isinstance(y, int) or not (now <= y <= now + 6):
            errors.append(f"graduation_year must be an integer between {now} and {now + 6}")
    if "gpa" in data and data["gpa"] is not None:
        try:
            v = float(data["gpa"])
            if not (0.0 <= v <= 10.0):
                errors.append("gpa must be between 0.0 and 10.0")
        except (TypeError, ValueError):
            errors.append("gpa must be a numeric value")
    if "jp_level" in data and data["jp_level"] not in _ALLOWED_JP_LEVELS:
        errors.append(f"jp_level must be one of {sorted(_ALLOWED_JP_LEVELS)}")
    return errors


# ───────────────────────────────────────────────────────────────────────────
# Public API
# ───────────────────────────────────────────────────────────────────────────

def get_student_profile(user_id: str, user_email: str) -> dict:
    """Return combined profile + student data for the authenticated student."""

    profile_res = (
        supabase.table("profiles")
        .select("full_name, avatar_url, university_id")
        .eq("id", user_id)
        .single()
        .execute()
    )
    profile = profile_res.data or {}

    student_res = (
        supabase.table("students")
        .select("*")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    student = student_res.data or {}

    # University name
    university_id = profile.get("university_id") or student.get("university_id")
    university_name = None
    if university_id:
        uni_res = (
            supabase.table("universities")
            .select("name")
            .eq("id", university_id)
            .maybe_single()
            .execute()
        )
        if uni_res.data:
            university_name = uni_res.data.get("name")

    completeness = _compute_completeness(profile, student)

    return {
        "id": user_id,
        "name": profile.get("full_name"),
        "email": user_email,
        "avatar_url": profile.get("avatar_url"),
        "university": university_name,
        "university_id": university_id,
        "department": student.get("department"),
        "graduation_year": student.get("graduation_year"),
        "gpa": str(student["gpa"]) if student.get("gpa") is not None else None,
        "bio": student.get("bio"),
        "jp_level": student.get("jp_level"),
        "phone": student.get("phone"),
        "location": student.get("location"),
        "linkedin": student.get("linkedin"),
        "github": student.get("github"),
        "portfolio": student.get("portfolio"),
        "skills": student.get("skills") or [],
        "strengths": student.get("strengths") or [],
        "awards": student.get("awards") or [],
        "verification_status": student.get("verification_status", "unverified"),
        "resume_url": student.get("resume_url"),
        "profile_completeness": completeness,
    }


def update_student_profile(user_id: str, data: dict) -> dict:
    """Update student profile fields across profiles + students tables."""

    errors = _validate_update(data)
    if errors:
        raise ValueError(errors)

    profile_data = {k: v for k, v in data.items() if k in _PROFILE_FIELDS}
    student_data = {k: v for k, v in data.items() if k in _STUDENT_FIELDS}

    if profile_data:
        supabase.table("profiles").update(profile_data).eq("id", user_id).execute()

    if student_data:
        # Upsert so new students without a students row are handled
        supabase.table("students").upsert({"id": user_id, **student_data}).execute()

    # Recompute completeness
    profile_res = (
        supabase.table("profiles")
        .select("full_name, avatar_url")
        .eq("id", user_id)
        .single()
        .execute()
    )
    student_res = (
        supabase.table("students")
        .select("*")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    completeness = _compute_completeness(profile_res.data or {}, student_res.data or {})
    supabase.table("students").update({"profile_completeness": completeness}).eq("id", user_id).execute()

    return {
        "id": user_id,
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        "profile_completeness": completeness,
    }


# ───────────────────────────────────────────────────────────────────────────
# Student Settings
# ───────────────────────────────────────────────────────────────────────────

_DEFAULT_NOTIFICATIONS = {
    "job_matches": True,
    "application_updates": True,
    "internship_reminders": True,
    "messages": True,
    "platform_updates": False,
    "email_digest": "weekly",
}

_DEFAULT_PRIVACY = {
    "profile_visibility": "verified_recruiters",
    "show_email": False,
    "show_phone": False,
    "show_gpa": True,
    "show_resume": True,
    "allow_ai_matching": True,
}

_VALID_VISIBILITY = {"public", "verified_recruiters", "university_only", "private"}
_VALID_DIGEST = {"daily", "weekly", "monthly", "none"}


def get_student_settings(user_id: str, user_email: str) -> dict:
    """Return combined settings (notifications, privacy, account) for the student."""
    profile_res = (
        supabase.table("profiles")
        .select("full_name, avatar_url, university_id")
        .eq("id", user_id)
        .single()
        .execute()
    )
    profile = profile_res.data or {}

    student_res = (
        supabase.table("students")
        .select("notification_preferences, privacy_settings, preferred_language, timezone")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    student = student_res.data or {}

    return {
        "id": user_id,
        "email": user_email,
        "name": profile.get("full_name"),
        "avatar_url": profile.get("avatar_url"),
        "notifications": student.get("notification_preferences") or _DEFAULT_NOTIFICATIONS,
        "privacy": student.get("privacy_settings") or _DEFAULT_PRIVACY,
        "preferred_language": student.get("preferred_language") or "en",
        "timezone": student.get("timezone") or "Asia/Tokyo",
    }


def update_student_settings(user_id: str, data: dict) -> dict:
    """Update student settings (notifications, privacy, language, timezone)."""
    errors = []
    update_payload: dict = {}

    if "notifications" in data:
        notifs = data["notifications"]
        if not isinstance(notifs, dict):
            errors.append("notifications must be an object")
        else:
            digest = notifs.get("email_digest")
            if digest and digest not in _VALID_DIGEST:
                errors.append(f"email_digest must be one of {sorted(_VALID_DIGEST)}")
            merged = {**_DEFAULT_NOTIFICATIONS, **notifs}
            update_payload["notification_preferences"] = merged

    if "privacy" in data:
        priv = data["privacy"]
        if not isinstance(priv, dict):
            errors.append("privacy must be an object")
        else:
            vis = priv.get("profile_visibility")
            if vis and vis not in _VALID_VISIBILITY:
                errors.append(f"profile_visibility must be one of {sorted(_VALID_VISIBILITY)}")
            merged = {**_DEFAULT_PRIVACY, **priv}
            update_payload["privacy_settings"] = merged

    if "preferred_language" in data:
        lang = data["preferred_language"]
        if lang not in {"en", "ja"}:
            errors.append("preferred_language must be 'en' or 'ja'")
        else:
            update_payload["preferred_language"] = lang

    if "timezone" in data:
        update_payload["timezone"] = data["timezone"]

    if errors:
        raise ValueError(errors)

    if update_payload:
        supabase.table("students").upsert({"id": user_id, **update_payload}).execute()

    return {
        "id": user_id,
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }
