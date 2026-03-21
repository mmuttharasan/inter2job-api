"""
Platform Admin Service Layer — business logic for /api/admin/* endpoints.

All Supabase queries are encapsulated here so that:
  - Route handlers stay thin (extract params → call service → return JSON)
  - Unit tests can mock at the service or Supabase boundary

Functions are grouped by specification section (§1–§8).
"""

import json
import os
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError
from ..services.supabase_client import supabase
from ..services.email_service import send_company_admin_welcome


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

_STATS_CACHE: dict = {}
_STATS_TTL_SEC = 3600  # 1 hour


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _log_admin_action(
    actor_id: str,
    action: str,
    target_id: str | None = None,
    target_type: str | None = None,
    metadata: dict | None = None,
    ip_address: str | None = None,
):
    """Insert a row into admin_audit_log. Best-effort; never raises."""
    try:
        supabase.table("admin_audit_log").insert({
            "id": str(uuid.uuid4()),
            "actor_id": actor_id,
            "action": action,
            "target_id": target_id,
            "target_type": target_type,
            "metadata": metadata or {},
            "ip_address": ip_address,
            "created_at": _now_iso(),
        }).execute()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# §1  Platform Statistics
# ═══════════════════════════════════════════════════════════════════════════

def get_platform_stats() -> dict:
    """
    Public marketing stats. Cached for 1 hour.
    Returns verified student count, partner companies, universities, placements.
    """
    global _STATS_CACHE

    now = datetime.now(tz=timezone.utc)
    if _STATS_CACHE.get("data") and _STATS_CACHE.get("expires_at", now) > now:
        return _STATS_CACHE["data"]

    try:
        students = supabase.table("profiles").select("id", count="exact").eq("role", "student").execute()
        companies = supabase.table("companies").select("id", count="exact").eq("status", "approved").execute()
        universities = supabase.table("universities").select("id", count="exact").execute()
        # Placements: applications with status = 'accepted'
        placements = supabase.table("applications").select("id", count="exact").eq("status", "accepted").execute()
    except Exception:
        return {
            "verified_students": 0,
            "partner_companies": 0,
            "partner_universities": 0,
            "successful_placements": 0,
            "last_updated": _now_iso(),
        }

    data = {
        "verified_students": students.count or 0,
        "partner_companies": companies.count or 0,
        "partner_universities": universities.count or 0,
        "successful_placements": placements.count or 0,
        "last_updated": _now_iso(),
    }

    _STATS_CACHE = {"data": data, "expires_at": now + timedelta(seconds=_STATS_TTL_SEC)}
    return data


def get_admin_dashboard() -> dict:
    """
    Comprehensive admin dashboard KPIs.
    Returns user counts by role, content metrics, system info, growth.
    """
    now = datetime.now(tz=timezone.utc)
    week_ago = (now - timedelta(days=7)).isoformat()
    month_ago = (now - timedelta(days=30)).isoformat()

    # ── User counts ──
    try:
        all_profiles = supabase.table("profiles").select("id, role, created_at").execute()
        profiles = all_profiles.data or []
    except Exception:
        profiles = []

    role_counts = {}
    new_week = 0
    new_month = 0
    for p in profiles:
        role = p.get("role", "unknown")
        role_counts[role] = role_counts.get(role, 0) + 1
        created = p.get("created_at", "")
        if created >= week_ago:
            new_week += 1
        if created >= month_ago:
            new_month += 1

    users = {
        "total": len(profiles),
        "students": role_counts.get("student", 0),
        "recruiters": role_counts.get("recruiter", 0),
        "company_admins": role_counts.get("company_admin", 0),
        "university_admins": role_counts.get("university_admin", 0),
        "universities": role_counts.get("university", 0),
        "admins": role_counts.get("admin", 0),
        "new_this_week": new_week,
        "new_this_month": new_month,
    }

    # ── Content metrics ──
    try:
        jobs_res = supabase.table("jobs").select("id, status").execute()
        all_jobs = jobs_res.data or []
    except Exception:
        all_jobs = []

    active_jobs = sum(1 for j in all_jobs if j.get("status") == "published")
    draft_jobs = sum(1 for j in all_jobs if j.get("status") == "draft")

    try:
        apps_week = supabase.table("applications").select("id", count="exact").gte("created_at", week_ago).execute()
        apps_week_count = apps_week.count or 0
    except Exception:
        apps_week_count = 0

    try:
        flags_res = supabase.table("content_flags").select("id", count="exact").eq("status", "open").execute()
        flagged_count = flags_res.count or 0
    except Exception:
        flagged_count = 0

    try:
        pending_res = supabase.table("companies").select("id", count="exact").eq("status", "pending").execute()
        pending_count = pending_res.count or 0
    except Exception:
        pending_count = 0

    content = {
        "active_jobs": active_jobs,
        "draft_jobs": draft_jobs,
        "applications_this_week": apps_week_count,
        "ai_matches_this_week": 0,
        "pending_verifications": pending_count,
        "flagged_content": flagged_count,
    }

    system = {
        "api_requests_today": 0,
        "error_rate": 0.0,
        "avg_response_ms": 0,
        "supabase_storage_gb": 0.0,
        "active_sessions": 0,
    }

    growth = {"weekly_signups": []}

    return {
        "users": users,
        "content": content,
        "system": system,
        "growth": growth,
    }


# ═══════════════════════════════════════════════════════════════════════════
# §2  User Management
# ═══════════════════════════════════════════════════════════════════════════

def create_user_admin(actor_id: str, data: dict) -> dict:
    """
    Admin-only user creation. Supports all roles including 'admin'.
    Uses the service-role client to bypass email confirmation.
    """
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    name = (data.get("full_name") or "").strip()
    role = data.get("role", "student")

    if not email or not password:
        raise ValueError("MISSING_CREDENTIALS")

    valid_roles = {"student", "recruiter", "company_admin", "university_admin", "university", "admin"}
    if role not in valid_roles:
        raise ValueError("INVALID_ROLE")

    # Create auth user (service-role skips email confirmation)
    try:
        response = supabase.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"full_name": name, "role": role},
        })
        user = response.user
    except Exception as e:
        msg = str(e).lower()
        if "already registered" in msg or "already exists" in msg or "duplicate" in msg:
            raise ValueError("EMAIL_EXISTS")
        raise ValueError("CREATE_FAILED")

    if not user:
        raise ValueError("CREATE_FAILED")

    user_id = user.id

    # Ensure profile row has correct role and name
    try:
        supabase.table("profiles").upsert({
            "id": user_id,
            "full_name": name,
            "role": role,
            "updated_at": _now_iso(),
        }).execute()
    except Exception:
        pass

    # For recruiter / company_admin: ensure a recruiters row exists
    if role in ("recruiter", "company_admin"):
        try:
            company_id = None
            if role == "company_admin" and data.get("company_name"):
                company_res = supabase.table("companies").insert({
                    "name": data["company_name"],
                    "status": "approved",
                    "created_at": _now_iso(),
                    "updated_at": _now_iso(),
                }).execute()
                if company_res.data:
                    company_id = company_res.data[0]["id"]
            supabase.table("recruiters").insert({"id": user_id, "company_id": company_id}).execute()
        except Exception:
            pass

    _log_admin_action(
        actor_id=actor_id,
        action="user.create",
        target_id=user_id,
        target_type="user",
        metadata={"email": email, "role": role, "name": name},
    )

    return {"id": user_id, "email": email, "full_name": name, "role": role}


def list_users(params: dict) -> dict:
    """Paginated, searchable, filterable user listing."""
    page = params.get("page", 1)
    limit = params.get("limit", 50)
    offset = (page - 1) * limit

    query = supabase.table("profiles").select(
        "id, full_name, role, avatar_url, university_id, created_at",
        count="exact",
    )

    if params.get("role"):
        query = query.eq("role", params["role"])
    if params.get("status"):
        query = query.eq("status", params["status"])
    if params.get("university_id"):
        query = query.eq("university_id", params["university_id"])
    if params.get("company_id"):
        query = query.eq("company_id", params["company_id"])
    if params.get("search"):
        query = query.ilike("full_name", f"%{params['search']}%")

    sort_field = params.get("sort", "created_at")
    if sort_field not in ("created_at", "full_name", "role"):
        sort_field = "created_at"
    query = query.order(sort_field, desc=(sort_field == "created_at"))

    query = query.range(offset, offset + limit - 1)

    try:
        res = query.execute()
    except Exception:
        return {"data": [], "meta": {"page": page, "total": 0}}

    rows = res.data or []
    data = []
    for r in rows:
        data.append({
            "id": r.get("id"),
            "email": r.get("email"),
            "full_name": r.get("full_name"),
            "role": r.get("role"),
            "status": r.get("status", "active"),
            "university": r.get("university_id"),
            "company": r.get("company_id"),
            "verification_status": r.get("verification_status"),
            "created_at": r.get("created_at"),
            "last_sign_in_at": r.get("last_sign_in_at"),
        })

    return {"data": data, "meta": {"page": page, "total": res.count or 0}}


def get_user_detail(user_id: str) -> dict | None:
    """Full profile for a single user."""
    try:
        res = (
            supabase.table("profiles")
            .select("*")
            .eq("id", user_id)
            .single()
            .execute()
        )
        if not res.data:
            return None
        return res.data
    except Exception:
        return None


def update_user_status(user_id: str, actor_id: str, data: dict) -> dict:
    """
    Suspend or reactivate a user.
    Returns result dict or raises ValueError on business rule violations.
    """
    status = data["status"]
    reason = data["reason"]

    # Check target is not admin
    try:
        target = (
            supabase.table("profiles")
            .select("id, role, status")
            .eq("id", user_id)
            .single()
            .execute()
        )
    except Exception:
        raise ValueError("USER_NOT_FOUND")

    if not target.data:
        raise ValueError("USER_NOT_FOUND")

    if target.data.get("role") == "admin":
        raise ValueError("CANNOT_SUSPEND_ADMIN")

    if target.data.get("status") == status:
        raise ValueError("ALREADY_SUSPENDED" if status == "suspended" else "ALREADY_ACTIVE")

    # Update profile status
    try:
        supabase.table("profiles").update({
            "status": status,
            "updated_at": _now_iso(),
        }).eq("id", user_id).execute()
    except Exception:
        raise ValueError("UPDATE_FAILED")

    _log_admin_action(
        actor_id=actor_id,
        action=f"user.{status}",
        target_id=user_id,
        target_type="user",
        metadata={"reason": reason, "old_status": target.data.get("status", "active")},
    )

    return {
        "user_id": user_id,
        "status": status,
        "reason": reason,
        "suspended_at": _now_iso() if status == "suspended" else None,
    }


def update_user_role(user_id: str, actor_id: str, data: dict) -> dict:
    """
    Change a user's role.
    Returns result dict or raises ValueError on violations.
    """
    new_role = data["role"]
    reason = data["reason"]

    valid_roles = {"student", "recruiter", "company_admin", "university_admin", "university"}
    if new_role not in valid_roles:
        raise ValueError("INVALID_ROLE")

    try:
        target = (
            supabase.table("profiles")
            .select("id, role")
            .eq("id", user_id)
            .single()
            .execute()
        )
    except Exception:
        raise ValueError("USER_NOT_FOUND")

    if not target.data:
        raise ValueError("USER_NOT_FOUND")

    old_role = target.data.get("role")

    try:
        supabase.table("profiles").update({
            "role": new_role,
            "updated_at": _now_iso(),
        }).eq("id", user_id).execute()
    except Exception:
        raise ValueError("UPDATE_FAILED")

    _log_admin_action(
        actor_id=actor_id,
        action="user.role_change",
        target_id=user_id,
        target_type="user",
        metadata={"old_role": old_role, "new_role": new_role, "reason": reason},
    )

    return {"user_id": user_id, "old_role": old_role, "new_role": new_role}


def delete_user(user_id: str, actor_id: str, permanent: bool = False) -> None:
    """
    Delete a user. Raises ValueError on business rule violations.
    """
    # Fetch target
    try:
        target = (
            supabase.table("profiles")
            .select("id, role")
            .eq("id", user_id)
            .single()
            .execute()
        )
    except Exception:
        raise ValueError("USER_NOT_FOUND")

    if not target.data:
        raise ValueError("USER_NOT_FOUND")

    if target.data.get("role") == "admin":
        # Check not last admin
        try:
            admins = (
                supabase.table("profiles")
                .select("id", count="exact")
                .eq("role", "admin")
                .execute()
            )
            if (admins.count or 0) <= 1:
                raise ValueError("LAST_ADMIN")
        except ValueError:
            raise
        except Exception:
            raise ValueError("CANNOT_DELETE_ADMIN")
        raise ValueError("CANNOT_DELETE_ADMIN")

    if permanent:
        # Hard delete — remove profile row
        try:
            supabase.table("profiles").delete().eq("id", user_id).execute()
        except Exception:
            raise ValueError("DELETE_FAILED")
    else:
        # Soft delete — mark as deleted
        try:
            supabase.table("profiles").update({
                "status": "deleted",
                "updated_at": _now_iso(),
            }).eq("id", user_id).execute()
        except Exception:
            raise ValueError("DELETE_FAILED")

    _log_admin_action(
        actor_id=actor_id,
        action="user.delete",
        target_id=user_id,
        target_type="user",
        metadata={"permanent": permanent},
    )


# ═══════════════════════════════════════════════════════════════════════════
# §3  Company & University Approval
# ═══════════════════════════════════════════════════════════════════════════

def list_all_companies(params: dict) -> dict:
    """Paginated listing of ALL companies (any status)."""
    page = params.get("page", 1)
    limit = params.get("limit", 50)
    offset = (page - 1) * limit

    query = supabase.table("companies").select(
        "id, name, industry, size, status, location, website, logo_url, created_at",
        count="exact",
    )

    if params.get("status"):
        query = query.eq("status", params["status"])
    if params.get("search"):
        query = query.ilike("name", f"%{params['search']}%")

    query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

    try:
        res = query.execute()
    except Exception:
        return {"data": [], "meta": {"page": page, "total": 0}}

    return {"data": res.data or [], "meta": {"page": page, "total": res.count or 0}}


def create_company(actor_id: str, data: dict) -> dict:
    """Onboard a new company (admin-created, auto-approved)."""
    name = data.get("name")
    if not name:
        raise ValueError("MISSING_NAME")

    company_id = str(uuid.uuid4())

    try:
        supabase.table("companies").insert({
            "id": company_id,
            "name": name,
            "industry": data.get("industry"),
            "size": data.get("size"),
            "location": data.get("location"),
            "website": data.get("website"),
            "status": "approved",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }).execute()
    except Exception:
        raise ValueError("CREATE_FAILED")

    _log_admin_action(
        actor_id=actor_id,
        action="company.onboard",
        target_id=company_id,
        target_type="company",
        metadata={"name": name},
    )

    return {"id": company_id, "name": name, "status": "approved"}


def _generate_temp_password(length: int = 12) -> str:
    """Generate a secure temporary password with upper, lower, digit, and symbol chars."""
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.isupper() for c in pwd)
            and any(c.islower() for c in pwd)
            and any(c.isdigit() for c in pwd)
        ):
            return pwd


def register_company_with_admin(actor_id: str, data: dict) -> dict:
    """
    Register a new company and create its admin account in one step.

    Steps:
      1. Validate required fields
      2. Create company record (status=approved — admin-created)
      3. Generate a temporary password
      4. Create Supabase auth user with role=recruiter
      5. Upsert profile row linked to company via recruiters table
      6. Send welcome email via Resend (best-effort)
      7. Log audit action
    """
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("MISSING_COMPANY_NAME")

    admin_email = (data.get("admin_email") or "").strip()
    admin_name = (data.get("admin_name") or "").strip()
    if not admin_email:
        raise ValueError("MISSING_ADMIN_EMAIL")

    # 1. Create the company record
    company_id = str(uuid.uuid4())
    try:
        supabase.table("companies").insert({
            "id": company_id,
            "name": name,
            "industry": data.get("industry"),
            "size": data.get("size"),
            "location": data.get("location"),
            "website": data.get("website"),
            "description": data.get("description"),
            "status": "approved",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }).execute()
    except Exception:
        raise ValueError("CREATE_FAILED")

    # 2. Generate temp password
    temp_password = _generate_temp_password()

    # 3. Create Supabase auth user
    try:
        response = supabase.auth.admin.create_user({
            "email": admin_email,
            "password": temp_password,
            "email_confirm": True,
            "user_metadata": {"full_name": admin_name, "role": "recruiter"},
        })
        user = response.user
    except Exception as e:
        msg = str(e).lower()
        if "already registered" in msg or "already exists" in msg or "duplicate" in msg:
            raise ValueError("EMAIL_EXISTS")
        raise ValueError("CREATE_FAILED")

    if not user:
        raise ValueError("CREATE_FAILED")

    user_id = str(user.id)

    # 4. Upsert profile row
    try:
        supabase.table("profiles").upsert({
            "id": user_id,
            "full_name": admin_name,
            "email": admin_email,
            "role": "recruiter",
            "updated_at": _now_iso(),
        }).execute()
    except Exception:
        pass  # Non-fatal — profile trigger may handle this

    # 5. Create recruiter row linking user → company
    try:
        supabase.table("recruiters").insert({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "company_id": company_id,
            "created_at": _now_iso(),
        }).execute()
    except Exception:
        pass  # Non-fatal

    # 6. Send welcome email (best-effort)
    send_company_admin_welcome(admin_email, admin_name, name, temp_password)

    # 7. Audit log
    _log_admin_action(
        actor_id=actor_id,
        action="company.register_with_admin",
        target_id=company_id,
        target_type="company",
        metadata={"company_name": name, "admin_email": admin_email},
    )

    return {
        "company_id": company_id,
        "company_name": name,
        "admin_user_id": user_id,
        "admin_email": admin_email,
        "temp_password": temp_password,
        "status": "approved",
    }


def list_pending_companies() -> list:
    """Return companies with status='pending'."""
    try:
        res = (
            supabase.table("companies")
            .select("id, name, industry, size, status, created_at")
            .eq("status", "pending")
            .order("created_at", desc=False)
            .execute()
        )
        return res.data or []
    except Exception:
        return []


def approve_company(company_id: str, actor_id: str, note: str | None = None) -> dict:
    """Approve a pending company. Raises ValueError if already approved."""
    try:
        company = (
            supabase.table("companies")
            .select("id, status, name")
            .eq("id", company_id)
            .single()
            .execute()
        )
    except Exception:
        raise ValueError("COMPANY_NOT_FOUND")

    if not company.data:
        raise ValueError("COMPANY_NOT_FOUND")

    if company.data.get("status") == "approved":
        raise ValueError("ALREADY_APPROVED")

    try:
        supabase.table("companies").update({
            "status": "approved",
            "updated_at": _now_iso(),
        }).eq("id", company_id).execute()
    except Exception:
        raise ValueError("UPDATE_FAILED")

    _log_admin_action(
        actor_id=actor_id,
        action="company.approve",
        target_id=company_id,
        target_type="company",
        metadata={"note": note, "company_name": company.data.get("name")},
    )

    return {"company_id": company_id, "status": "approved"}


def reject_company(company_id: str, actor_id: str, reason: str, note: str | None = None) -> dict:
    """Reject a pending company."""
    try:
        company = (
            supabase.table("companies")
            .select("id, status, name")
            .eq("id", company_id)
            .single()
            .execute()
        )
    except Exception:
        raise ValueError("COMPANY_NOT_FOUND")

    if not company.data:
        raise ValueError("COMPANY_NOT_FOUND")

    if company.data.get("status") == "rejected":
        raise ValueError("ALREADY_REJECTED")

    try:
        supabase.table("companies").update({
            "status": "rejected",
            "rejection_reason": reason,
            "updated_at": _now_iso(),
        }).eq("id", company_id).execute()
    except Exception:
        raise ValueError("UPDATE_FAILED")

    _log_admin_action(
        actor_id=actor_id,
        action="company.reject",
        target_id=company_id,
        target_type="company",
        metadata={"reason": reason, "note": note},
    )

    return {"company_id": company_id, "status": "rejected", "reason": reason}


def list_all_universities(params: dict) -> dict:
    """Paginated listing of ALL universities (any status)."""
    page = params.get("page", 1)
    limit = params.get("limit", 50)
    offset = (page - 1) * limit

    query = supabase.table("universities").select(
        "id, name, status, location, created_at",
        count="exact",
    )

    if params.get("status"):
        query = query.eq("status", params["status"])
    if params.get("search"):
        query = query.ilike("name", f"%{params['search']}%")

    query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

    try:
        res = query.execute()
    except Exception:
        return {"data": [], "meta": {"page": page, "total": 0}}

    return {"data": res.data or [], "meta": {"page": page, "total": res.count or 0}}


def create_university(actor_id: str, data: dict) -> dict:
    """
    Onboard a new university (admin-created, auto-approved).
    Also creates a university_admin auth user and sends a welcome email via Resend.
    """
    name = data.get("name")
    if not name:
        raise ValueError("MISSING_NAME")

    admin_email = (data.get("admin_email") or "").strip()
    admin_name = (data.get("admin_name") or "").strip()
    admin_password = data.get("admin_password") or ""

    if not admin_email or not admin_password:
        raise ValueError("MISSING_ADMIN_CREDENTIALS")

    # 1. Create the university_admin auth user
    try:
        response = supabase.auth.admin.create_user({
            "email": admin_email,
            "password": admin_password,
            "email_confirm": True,
            "user_metadata": {"full_name": admin_name, "role": "university_admin"},
        })
        user = response.user
    except Exception as e:
        msg = str(e).lower()
        if "already registered" in msg or "already exists" in msg or "duplicate" in msg:
            raise ValueError("EMAIL_EXISTS")
        raise ValueError("CREATE_FAILED")

    if not user:
        raise ValueError("CREATE_FAILED")

    user_id = user.id

    # 2. Create the university record
    university_id = str(uuid.uuid4())
    row: dict = {
        "id": university_id,
        "name": name,
        "status": "approved",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    if data.get("location"):
        row["location"] = data["location"]
    if data.get("domain"):
        row["domain"] = data["domain"]

    try:
        supabase.table("universities").insert(row).execute()
    except Exception:
        raise ValueError("CREATE_FAILED")

    # 3. Link the admin user profile to this university
    try:
        supabase.table("profiles").upsert({
            "id": user_id,
            "full_name": admin_name,
            "role": "university_admin",
            "university_id": university_id,
            "updated_at": _now_iso(),
        }).execute()
    except Exception:
        pass  # Non-fatal — profile trigger may handle it

    # 4. Send welcome email via Resend (best-effort)
    _send_university_welcome_email(admin_email, admin_name, name, admin_password)

    _log_admin_action(
        actor_id=actor_id,
        action="university.onboard",
        target_id=university_id,
        target_type="university",
        metadata={"name": name, "admin_email": admin_email},
    )

    return {
        "id": university_id,
        "name": name,
        "status": "approved",
        "admin_user_id": user_id,
        "admin_email": admin_email,
    }


def _send_university_welcome_email(
    to_email: str, admin_name: str, university_name: str, password: str
) -> None:
    """Send a welcome email to the new university admin via Resend API. Best-effort, never raises."""
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        return

    display_name = admin_name or "University Admin"
    html_body = f"""
<!DOCTYPE html>
<html>
<body style="font-family:sans-serif;color:#1e293b;max-width:560px;margin:0 auto;padding:24px">
  <div style="background:#4f46e5;border-radius:12px;padding:24px;text-align:center;margin-bottom:24px">
    <h1 style="color:#fff;margin:0;font-size:22px">Welcome to InternToJob</h1>
  </div>
  <p>Hi {display_name},</p>
  <p>Your university admin account for <strong>{university_name}</strong> has been created.</p>
  <p>Use the credentials below to log in and complete your university profile:</p>
  <div style="background:#f1f5f9;border-radius:8px;padding:16px;margin:16px 0">
    <p style="margin:4px 0"><strong>Email:</strong> {to_email}</p>
    <p style="margin:4px 0"><strong>Password:</strong> {password}</p>
  </div>
  <p>Once you log in you can add more details about your university, manage students, and connect with companies.</p>
  <p style="color:#64748b;font-size:13px;margin-top:32px">
    If you did not expect this email, please contact your platform administrator.
  </p>
</body>
</html>"""

    payload = json.dumps({
        "from": "InternToJob <noreply@intern2job.com>",
        "to": [to_email],
        "subject": f"Welcome to InternToJob — Your Admin Account for {university_name}",
        "html": html_body,
    }).encode("utf-8")

    try:
        req = Request(
            "https://api.resend.com/emails",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        urlopen(req, timeout=10)
    except (URLError, Exception):
        pass  # Non-blocking — email failure must not block onboarding


def list_pending_universities() -> list:
    """Return universities with status='pending'."""
    try:
        res = (
            supabase.table("universities")
            .select("id, name, status, created_at")
            .eq("status", "pending")
            .order("created_at", desc=False)
            .execute()
        )
        return res.data or []
    except Exception:
        return []


def approve_university(university_id: str, actor_id: str, note: str | None = None) -> dict:
    """Approve a pending university."""
    try:
        uni = (
            supabase.table("universities")
            .select("id, status, name")
            .eq("id", university_id)
            .single()
            .execute()
        )
    except Exception:
        raise ValueError("UNIVERSITY_NOT_FOUND")

    if not uni.data:
        raise ValueError("UNIVERSITY_NOT_FOUND")

    if uni.data.get("status") == "approved":
        raise ValueError("ALREADY_APPROVED")

    try:
        supabase.table("universities").update({
            "status": "approved",
            "updated_at": _now_iso(),
        }).eq("id", university_id).execute()
    except Exception:
        raise ValueError("UPDATE_FAILED")

    _log_admin_action(
        actor_id=actor_id,
        action="university.approve",
        target_id=university_id,
        target_type="university",
        metadata={"note": note},
    )

    return {"university_id": university_id, "status": "approved"}


def reject_university(university_id: str, actor_id: str, reason: str, note: str | None = None) -> dict:
    """Reject a pending university."""
    try:
        uni = (
            supabase.table("universities")
            .select("id, status, name")
            .eq("id", university_id)
            .single()
            .execute()
        )
    except Exception:
        raise ValueError("UNIVERSITY_NOT_FOUND")

    if not uni.data:
        raise ValueError("UNIVERSITY_NOT_FOUND")

    if uni.data.get("status") == "rejected":
        raise ValueError("ALREADY_REJECTED")

    try:
        supabase.table("universities").update({
            "status": "rejected",
            "rejection_reason": reason,
            "updated_at": _now_iso(),
        }).eq("id", university_id).execute()
    except Exception:
        raise ValueError("UPDATE_FAILED")

    _log_admin_action(
        actor_id=actor_id,
        action="university.reject",
        target_id=university_id,
        target_type="university",
        metadata={"reason": reason, "note": note},
    )

    return {"university_id": university_id, "status": "rejected", "reason": reason}


# ═══════════════════════════════════════════════════════════════════════════
# §3b  Company Detail (admin view)
# ═══════════════════════════════════════════════════════════════════════════

def get_company_detail_admin(company_id: str) -> dict | None:
    """Company overview + aggregate stats for admin."""
    try:
        company_res = (
            supabase.table("companies")
            .select("id, name, industry, size, status, location, website, logo_url, description, created_at")
            .eq("id", company_id)
            .single()
            .execute()
        )
        if not company_res.data:
            return None
        company = company_res.data
    except Exception:
        return None

    # Aggregate job + application stats
    try:
        jobs_res = supabase.table("jobs").select("id, status").eq("company_id", company_id).execute()
        jobs = jobs_res.data or []
    except Exception:
        jobs = []

    total_jobs = len(jobs)
    active_jobs = sum(1 for j in jobs if j.get("status") == "published")
    job_ids = [j["id"] for j in jobs]

    total_apps = 0
    selected_count = 0
    if job_ids:
        try:
            apps_res = supabase.table("applications").select("id, status").in_("job_id", job_ids).execute()
            apps = apps_res.data or []
            total_apps = len(apps)
            selected_count = sum(1 for a in apps if a.get("status") in ("shortlisted", "offered", "accepted"))
        except Exception:
            pass

    return {
        **company,
        "stats": {
            "total_jobs": total_jobs,
            "active_jobs": active_jobs,
            "total_applications": total_apps,
            "selected_candidates": selected_count,
        },
    }


def list_company_jobs_admin(company_id: str) -> list:
    """All jobs for a company with per-job application counts."""
    try:
        jobs_res = (
            supabase.table("jobs")
            .select("id, title, status, department, location, deadline, openings, created_at")
            .eq("company_id", company_id)
            .order("created_at", desc=True)
            .execute()
        )
        jobs = jobs_res.data or []
    except Exception:
        return []

    if not jobs:
        return []

    job_ids = [j["id"] for j in jobs]

    # Single batch fetch for all applications
    try:
        apps_res = supabase.table("applications").select("id, job_id, status").in_("job_id", job_ids).execute()
        all_apps = apps_res.data or []
    except Exception:
        all_apps = []

    counts: dict = {jid: {"total": 0, "selected": 0} for jid in job_ids}
    for app in all_apps:
        jid = app.get("job_id")
        if jid in counts:
            counts[jid]["total"] += 1
            if app.get("status") in ("shortlisted", "offered", "accepted"):
                counts[jid]["selected"] += 1

    return [
        {
            **job,
            "total_applications": counts[job["id"]]["total"],
            "selected_count": counts[job["id"]]["selected"],
        }
        for job in jobs
    ]


def list_job_applications_admin(job_id: str) -> list:
    """Applications for a job with applicant profile details."""
    try:
        apps_res = (
            supabase.table("applications")
            .select("id, student_id, status, ai_score, cover_letter, applied_at, updated_at")
            .eq("job_id", job_id)
            .order("applied_at", desc=True)
            .execute()
        )
        apps = apps_res.data or []
    except Exception:
        return []

    if not apps:
        return []

    student_ids = list({a["student_id"] for a in apps if a.get("student_id")})

    profiles_by_id: dict = {}
    if student_ids:
        try:
            profiles_res = (
                supabase.table("profiles")
                .select("id, full_name, university_id")
                .in_("id", student_ids)
                .execute()
            )
            for p in (profiles_res.data or []):
                profiles_by_id[p["id"]] = p
        except Exception:
            pass

    return [
        {
            **app,
            "student_name": profiles_by_id.get(app.get("student_id", ""), {}).get("full_name"),
        }
        for app in apps
    ]


# ═══════════════════════════════════════════════════════════════════════════
# §4  Content Moderation
# ═══════════════════════════════════════════════════════════════════════════

def list_flags(params: dict) -> dict:
    """Return flagged content with filters."""
    page = params.get("page", 1)
    limit = params.get("limit", 50)
    offset = (page - 1) * limit

    query = supabase.table("content_flags").select("*", count="exact")

    if params.get("type"):
        query = query.eq("type", params["type"])
    if params.get("status"):
        query = query.eq("status", params["status"])

    query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

    try:
        res = query.execute()
    except Exception:
        return {"data": [], "meta": {"page": page, "total": 0}}

    return {"data": res.data or [], "meta": {"page": page, "total": res.count or 0}}


def resolve_flag(flag_id: str, actor_id: str, action: str, note: str | None = None) -> dict:
    """
    Resolve a content flag.
    Actions: dismiss, remove_content, suspend_author, escalate
    """
    try:
        flag = (
            supabase.table("content_flags")
            .select("id, status, content_id, type, flagged_by")
            .eq("id", flag_id)
            .single()
            .execute()
        )
    except Exception:
        raise ValueError("FLAG_NOT_FOUND")

    if not flag.data:
        raise ValueError("FLAG_NOT_FOUND")

    if flag.data.get("status") == "resolved":
        raise ValueError("ALREADY_RESOLVED")

    resolved_at = _now_iso()

    # Update flag status
    try:
        supabase.table("content_flags").update({
            "status": "resolved",
            "resolved_by": actor_id,
            "resolution_action": action,
            "resolution_note": note,
            "resolved_at": resolved_at,
        }).eq("id", flag_id).execute()
    except Exception:
        raise ValueError("UPDATE_FAILED")

    # Side effects based on action
    if action == "remove_content":
        content_id = flag.data.get("content_id")
        content_type = flag.data.get("type")
        if content_id and content_type:
            _remove_flagged_content(content_id, content_type)

    if action == "suspend_author":
        content_id = flag.data.get("content_id")
        if content_id:
            _suspend_content_author(content_id, flag.data.get("type"), actor_id)

    _log_admin_action(
        actor_id=actor_id,
        action="flag.resolve",
        target_id=flag_id,
        target_type="content_flag",
        metadata={"action": action, "note": note},
    )

    return {"flag_id": flag_id, "action": action, "resolved_at": resolved_at}


def _remove_flagged_content(content_id: str, content_type: str):
    """Set flagged content status to archived."""
    table_map = {"job": "jobs", "profile": "profiles", "message": "messages"}
    table = table_map.get(content_type)
    if table:
        try:
            supabase.table(table).update({"status": "archived"}).eq("id", content_id).execute()
        except Exception:
            pass


def _suspend_content_author(content_id: str, content_type: str, actor_id: str):
    """Find and suspend the author of flagged content."""
    # Simplified — in production this would look up the author
    pass


# ═══════════════════════════════════════════════════════════════════════════
# §5  AI Matching Configuration
# ═══════════════════════════════════════════════════════════════════════════

def get_ai_config() -> dict:
    """Return global AI matching configuration."""
    try:
        res = (
            supabase.table("ai_config")
            .select("*")
            .order("updated_at", desc=True)
            .limit(1)
            .single()
            .execute()
        )
        if res.data:
            return res.data
    except Exception:
        pass

    # Default config
    return {
        "default_weights": {
            "skill_alignment": 40,
            "research_similarity": 25,
            "language_readiness": 20,
            "learning_trajectory": 15,
        },
        "min_score_threshold": 60,
        "max_candidates_per_run": 5000,
        "model_version": "intern2job-match-v2",
        "updated_at": None,
        "updated_by": None,
    }


def update_ai_config(actor_id: str, data: dict) -> dict:
    """Update global AI configuration."""
    update_payload = {}

    if "default_weights" in data:
        weights = data["default_weights"]
        if isinstance(weights, dict):
            total = sum(weights.values())
            if total != 100:
                raise ValueError("INVALID_WEIGHTS")
            update_payload["default_weights"] = weights

    if "min_score_threshold" in data:
        update_payload["min_score_threshold"] = data["min_score_threshold"]
    if "max_candidates_per_run" in data:
        update_payload["max_candidates_per_run"] = data["max_candidates_per_run"]
    if "model_version" in data:
        update_payload["model_version"] = data["model_version"]

    update_payload["updated_at"] = _now_iso()
    update_payload["updated_by"] = actor_id

    try:
        res = (
            supabase.table("ai_config")
            .upsert(update_payload, on_conflict="id")
            .execute()
        )
    except Exception:
        raise ValueError("UPDATE_FAILED")

    _log_admin_action(
        actor_id=actor_id,
        action="ai_config.update",
        target_type="ai_config",
        metadata={"changes": update_payload},
    )

    return {"updated_at": update_payload["updated_at"], "updated_by": actor_id}


# ═══════════════════════════════════════════════════════════════════════════
# §6  Platform Analytics
# ═══════════════════════════════════════════════════════════════════════════

def get_platform_analytics(period: str) -> dict:
    """Platform-wide analytics for the admin dashboard."""
    now = datetime.now(tz=timezone.utc)

    period_map = {
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
        "ytd": now - now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
    }

    if period == "all":
        start = "2020-01-01T00:00:00Z"
    elif period in period_map:
        delta = period_map[period]
        start = (now - delta).isoformat() if isinstance(delta, timedelta) else (now - delta).isoformat()
    else:
        start = (now - timedelta(days=30)).isoformat()

    # User growth
    try:
        profiles_res = supabase.table("profiles").select("id, role, created_at").gte("created_at", start).execute()
        profiles = profiles_res.data or []
    except Exception:
        profiles = []

    user_growth = _aggregate_growth(profiles)

    # Top universities (placeholder — would require joins)
    top_universities = []
    top_companies = []

    return {
        "user_growth": user_growth,
        "matching_activity": [],
        "verification_throughput": [],
        "top_universities_by_placement": top_universities,
        "top_companies_by_hires": top_companies,
        "api_performance": {
            "avg_response_ms": 0,
            "p95_response_ms": 0,
            "error_rate": 0.0,
            "requests_today": 0,
        },
    }


def _aggregate_growth(profiles: list) -> list:
    """Group profiles by date for growth chart."""
    by_date: dict[str, dict] = {}
    for p in profiles:
        created = p.get("created_at", "")[:10]  # YYYY-MM-DD
        role = p.get("role", "unknown")
        if created not in by_date:
            by_date[created] = {"date": created, "students": 0, "companies": 0, "universities": 0}
        if role == "student":
            by_date[created]["students"] += 1
        elif role in ("company_admin", "recruiter"):
            by_date[created]["companies"] += 1
        elif role in ("university_admin", "university"):
            by_date[created]["universities"] += 1

    return sorted(by_date.values(), key=lambda x: x["date"])


# ═══════════════════════════════════════════════════════════════════════════
# §7  Data Export
# ═══════════════════════════════════════════════════════════════════════════

def create_export(actor_id: str, data: dict) -> dict:
    """Create a data export job."""
    export_type = data["type"]
    valid_types = {"students", "companies", "jobs", "applications", "verifications", "analytics"}
    if export_type not in valid_types:
        raise ValueError("INVALID_EXPORT_TYPE")

    export_id = str(uuid.uuid4())

    try:
        supabase.table("admin_exports").insert({
            "id": export_id,
            "type": export_type,
            "filters": data.get("filters", {}),
            "format": data.get("format", "csv"),
            "status": "queued",
            "requested_by": actor_id,
            "notify_email": data.get("notify_email"),
            "created_at": _now_iso(),
        }).execute()
    except Exception:
        raise ValueError("EXPORT_CREATION_FAILED")

    _log_admin_action(
        actor_id=actor_id,
        action="export.create",
        target_id=export_id,
        target_type="export",
        metadata={"type": export_type, "format": data.get("format", "csv")},
    )

    return {"export_id": export_id, "status": "queued", "estimated_rows": 0}


def get_export_status(export_id: str) -> dict | None:
    """Get export job status."""
    try:
        res = (
            supabase.table("admin_exports")
            .select("*")
            .eq("id", export_id)
            .single()
            .execute()
        )
        if not res.data:
            return None
        row = res.data
        return {
            "export_id": row.get("id"),
            "status": row.get("status"),
            "rows_exported": row.get("rows_exported"),
            "download_url": row.get("download_url"),
            "expires_at": row.get("expires_at"),
        }
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════
# §8  Audit Log
# ═══════════════════════════════════════════════════════════════════════════

def get_audit_log(params: dict) -> dict:
    """Paginated audit log with optional filters."""
    page = params.get("page", 1)
    limit = params.get("limit", 50)
    offset = (page - 1) * limit

    query = supabase.table("admin_audit_log").select("*", count="exact")

    if params.get("action_type"):
        query = query.eq("action", params["action_type"])
    if params.get("actor_id"):
        query = query.eq("actor_id", params["actor_id"])
    if params.get("from_date"):
        query = query.gte("created_at", params["from_date"])
    if params.get("to_date"):
        query = query.lte("created_at", params["to_date"])

    query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

    try:
        res = query.execute()
    except Exception:
        return {"data": [], "meta": {"page": page, "total": 0}}

    return {"data": res.data or [], "meta": {"page": page, "total": res.count or 0}}


# ═══════════════════════════════════════════════════════════════════════════
# §9  University Departments
# ═══════════════════════════════════════════════════════════════════════════

def list_university_departments(university_id: str) -> list:
    """List all departments for a university."""
    try:
        res = (
            supabase.table("university_departments")
            .select("*")
            .eq("university_id", university_id)
            .order("created_at")
            .execute()
        )
        return res.data or []
    except Exception:
        return []


def create_department(university_id: str, actor_id: str, data: dict) -> dict:
    """Create a new department for a university."""
    if not data.get("name") or not data.get("code"):
        raise ValueError("MISSING_FIELDS")

    row = {
        "id": str(uuid.uuid4()),
        "university_id": university_id,
        "name": data["name"],
        "code": data["code"].upper(),
        "head": data.get("head"),
        "students_count": int(data.get("students_count") or 0),
        "placed_count": int(data.get("placed_count") or 0),
        "faculty_count": int(data.get("faculty_count") or 0),
        "labs_count": int(data.get("labs_count") or 0),
        "avg_package": data.get("avg_package"),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    try:
        res = supabase.table("university_departments").insert(row).execute()
        _log_admin_action(actor_id, "department_created", row["id"], "department",
                          {"university_id": university_id, "name": data["name"]})
        return res.data[0]
    except Exception as e:
        raise ValueError("CREATE_FAILED") from e


def update_department(dept_id: str, actor_id: str, data: dict) -> dict:
    """Update an existing department."""
    allowed = {"name", "code", "head", "students_count", "placed_count",
               "faculty_count", "labs_count", "avg_package"}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        raise ValueError("NO_FIELDS")
    if "code" in updates:
        updates["code"] = updates["code"].upper()
    updates["updated_at"] = _now_iso()
    try:
        res = supabase.table("university_departments").update(updates).eq("id", dept_id).execute()
        if not res.data:
            raise ValueError("NOT_FOUND")
        _log_admin_action(actor_id, "department_updated", dept_id, "department")
        return res.data[0]
    except ValueError:
        raise
    except Exception as e:
        raise ValueError("UPDATE_FAILED") from e


def delete_department(dept_id: str, actor_id: str) -> None:
    """Delete a department."""
    try:
        supabase.table("university_departments").delete().eq("id", dept_id).execute()
        _log_admin_action(actor_id, "department_deleted", dept_id, "department")
    except Exception as e:
        raise ValueError("DELETE_FAILED") from e


# ═══════════════════════════════════════════════════════════════════════════
# §10  Verification Requests
# ═══════════════════════════════════════════════════════════════════════════

def list_university_verifications(university_id: str, status: str | None = None) -> list:
    """List verification requests for a university."""
    try:
        query = (
            supabase.table("verification_requests")
            .select("*")
            .eq("university_id", university_id)
        )
        if status:
            query = query.eq("status", status)
        res = query.order("created_at", desc=True).execute()
        return res.data or []
    except Exception:
        return []


def create_verification_request(university_id: str, actor_id: str, data: dict) -> dict:
    """Create a verification request (admin can add on behalf of students)."""
    if not data.get("type"):
        raise ValueError("MISSING_FIELDS")
    row = {
        "id": str(uuid.uuid4()),
        "university_id": university_id,
        "student_id": data.get("student_id"),
        "student_name": data.get("student_name"),
        "roll_no": data.get("roll_no"),
        "department": data.get("department"),
        "type": data["type"],
        "urgency": data.get("urgency", "Medium"),
        "status": "pending",
        "submitted_date": data.get("submitted_date", _now_iso()[:10]),
        "documents": data.get("documents", []),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    try:
        res = supabase.table("verification_requests").insert(row).execute()
        return res.data[0]
    except Exception as e:
        raise ValueError("CREATE_FAILED") from e


def approve_verification(req_id: str, actor_id: str, note: str | None = None) -> dict:
    """Approve a verification request."""
    updates = {
        "status": "approved",
        "reviewed_by": actor_id,
        "reviewed_at": _now_iso(),
        "review_note": note,
        "updated_at": _now_iso(),
    }
    try:
        res = supabase.table("verification_requests").update(updates).eq("id", req_id).execute()
        if not res.data:
            raise ValueError("NOT_FOUND")
        _log_admin_action(actor_id, "verification_approved", req_id, "verification_request")
        return res.data[0]
    except ValueError:
        raise
    except Exception as e:
        raise ValueError("APPROVE_FAILED") from e


def reject_verification(req_id: str, actor_id: str, reason: str) -> dict:
    """Reject a verification request."""
    updates = {
        "status": "rejected",
        "reviewed_by": actor_id,
        "reviewed_at": _now_iso(),
        "review_note": reason,
        "updated_at": _now_iso(),
    }
    try:
        res = supabase.table("verification_requests").update(updates).eq("id", req_id).execute()
        if not res.data:
            raise ValueError("NOT_FOUND")
        _log_admin_action(actor_id, "verification_rejected", req_id, "verification_request")
        return res.data[0]
    except ValueError:
        raise
    except Exception as e:
        raise ValueError("REJECT_FAILED") from e


# ═══════════════════════════════════════════════════════════════════════════
# §11  Create University Student
# ═══════════════════════════════════════════════════════════════════════════

def create_university_student(university_id: str, actor_id: str, data: dict) -> dict:
    """Create a student auth account and link to a university."""
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    full_name = (data.get("full_name") or "").strip()

    if not email or not password:
        raise ValueError("MISSING_CREDENTIALS")

    # 1. Create Supabase auth user
    try:
        response = supabase.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"full_name": full_name, "role": "student"},
        })
        user_id = response.user.id
    except Exception as e:
        err = str(e).lower()
        if "already" in err or "exists" in err or "duplicate" in err:
            raise ValueError("EMAIL_EXISTS")
        raise ValueError("CREATE_FAILED")

    # 2. Upsert profile
    supabase.table("profiles").upsert({
        "id": user_id,
        "role": "student",
        "full_name": full_name,
        "university_id": university_id,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }).execute()

    # 3. Upsert student record
    student_row: dict = {
        "id": user_id,
        "university_id": university_id,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    if data.get("department"):
        student_row["department"] = data["department"]
    if data.get("graduation_year"):
        student_row["graduation_year"] = int(data["graduation_year"])

    supabase.table("students").upsert(student_row).execute()

    _log_admin_action(actor_id, "student_created", user_id, "student",
                      {"email": email, "university_id": university_id})

    return {
        "id": user_id,
        "email": email,
        "full_name": full_name,
        "university_id": university_id,
    }


# ═══════════════════════════════════════════════════════════════════════════
# §12  Company Internships & Certificates (Admin View)
# ═══════════════════════════════════════════════════════════════════════════

def list_company_internships_admin(company_id: str) -> list:
    """
    All internships at a company for admin view.
    Returns internship + student name + job title + milestone progress + certificate status.
    """
    try:
        res = (
            supabase.table("internships")
            .select("id, student_id, job_id, company_id, status, start_date, end_date, mentor_name, team, created_at")
            .eq("company_id", company_id)
            .order("created_at", desc=True)
            .execute()
        )
        internships = res.data or []
    except Exception:
        return []

    if not internships:
        return []

    # Batch-fetch student profiles
    student_ids = list({i["student_id"] for i in internships if i.get("student_id")})
    profiles_map: dict = {}
    if student_ids:
        try:
            p_res = supabase.table("profiles").select("id, full_name").in_("id", student_ids).execute()
            for p in (p_res.data or []):
                profiles_map[p["id"]] = p.get("full_name", "")
        except Exception:
            pass

    # Batch-fetch job titles
    job_ids = list({i["job_id"] for i in internships if i.get("job_id")})
    jobs_map: dict = {}
    if job_ids:
        try:
            j_res = supabase.table("jobs").select("id, title").in_("id", job_ids).execute()
            for j in (j_res.data or []):
                jobs_map[j["id"]] = j.get("title", "")
        except Exception:
            pass

    # Batch-fetch milestones (all at once, group in Python)
    internship_ids = [i["id"] for i in internships]
    milestones_map: dict[str, list] = {iid: [] for iid in internship_ids}
    try:
        ms_res = (
            supabase.table("internship_milestones")
            .select("internship_id, status")
            .in_("internship_id", internship_ids)
            .execute()
        )
        for ms in (ms_res.data or []):
            iid = ms.get("internship_id")
            if iid in milestones_map:
                milestones_map[iid].append(ms)
    except Exception:
        pass

    # Batch-fetch certificates
    certs_map: dict[str, dict | None] = {iid: None for iid in internship_ids}
    try:
        cert_res = (
            supabase.table("certificates")
            .select("internship_id, id, verification_code, issued_at")
            .in_("internship_id", internship_ids)
            .execute()
        )
        for cert in (cert_res.data or []):
            iid = cert.get("internship_id")
            if iid in certs_map:
                certs_map[iid] = cert
    except Exception:
        pass

    result = []
    for intern in internships:
        iid = intern["id"]
        all_ms = milestones_map.get(iid, [])
        total_ms = len(all_ms)
        done_ms = sum(1 for ms in all_ms if ms.get("status") == "completed")
        result.append({
            **intern,
            "student_name": profiles_map.get(intern.get("student_id", ""), ""),
            "job_title": jobs_map.get(intern.get("job_id", ""), ""),
            "milestone_total": total_ms,
            "milestone_done": done_ms,
            "certificate": certs_map.get(iid),
        })

    return result


def list_company_certificates_admin(company_id: str) -> list:
    """All certificates issued by a company."""
    try:
        res = (
            supabase.table("certificates")
            .select("id, internship_id, student_id, student_name, job_title, start_date, end_date, issued_at, verification_code, skills_demonstrated, mentor_name, performance_summary")
            .eq("company_id", company_id)
            .order("issued_at", desc=True)
            .execute()
        )
        certs = res.data or []
    except Exception:
        return []

    for cert in certs:
        cert["verification_url"] = f"/verify/{cert.get('verification_code', '')}"

    return certs


def list_completed_internships_pending_certificate() -> list:
    """
    All completed internships that do NOT yet have a certificate.
    Returns enriched rows: student name, company name, job title, milestone progress.
    """
    try:
        res = (
            supabase.table("internships")
            .select("id, student_id, job_id, company_id, status, start_date, end_date, mentor_name, team, created_at")
            .eq("status", "completed")
            .order("end_date", desc=True)
            .execute()
        )
        internships = res.data or []
    except Exception:
        return []

    if not internships:
        return []

    internship_ids = [i["id"] for i in internships]

    # Filter out those that already have a certificate
    try:
        cert_res = (
            supabase.table("certificates")
            .select("internship_id")
            .in_("internship_id", internship_ids)
            .execute()
        )
        certified_ids = {c["internship_id"] for c in (cert_res.data or [])}
    except Exception:
        certified_ids = set()

    pending = [i for i in internships if i["id"] not in certified_ids]
    if not pending:
        return []

    pending_ids = [i["id"] for i in pending]

    # Batch-fetch student profiles
    student_ids = list({i["student_id"] for i in pending if i.get("student_id")})
    profiles_map: dict = {}
    if student_ids:
        try:
            p_res = supabase.table("profiles").select("id, full_name").in_("id", student_ids).execute()
            for p in (p_res.data or []):
                profiles_map[p["id"]] = p.get("full_name", "")
        except Exception:
            pass

    # Batch-fetch job titles
    job_ids = list({i["job_id"] for i in pending if i.get("job_id")})
    jobs_map: dict = {}
    if job_ids:
        try:
            j_res = supabase.table("jobs").select("id, title").in_("id", job_ids).execute()
            for j in (j_res.data or []):
                jobs_map[j["id"]] = j.get("title", "")
        except Exception:
            pass

    # Batch-fetch company names
    company_ids = list({i["company_id"] for i in pending if i.get("company_id")})
    companies_map: dict = {}
    if company_ids:
        try:
            c_res = supabase.table("companies").select("id, name").in_("id", company_ids).execute()
            for c in (c_res.data or []):
                companies_map[c["id"]] = c.get("name", "")
        except Exception:
            pass

    # Batch-fetch milestone progress
    milestones_map: dict[str, list] = {iid: [] for iid in pending_ids}
    try:
        ms_res = (
            supabase.table("internship_milestones")
            .select("internship_id, status")
            .in_("internship_id", pending_ids)
            .execute()
        )
        for ms in (ms_res.data or []):
            iid = ms.get("internship_id")
            if iid in milestones_map:
                milestones_map[iid].append(ms)
    except Exception:
        pass

    result = []
    for intern in pending:
        iid = intern["id"]
        all_ms = milestones_map.get(iid, [])
        total_ms = len(all_ms)
        done_ms = sum(1 for ms in all_ms if ms.get("status") == "completed")
        result.append({
            **intern,
            "student_name": profiles_map.get(intern.get("student_id", ""), ""),
            "company_name":  companies_map.get(intern.get("company_id", ""), ""),
            "job_title":     jobs_map.get(intern.get("job_id", ""), ""),
            "milestone_total": total_ms,
            "milestone_done":  done_ms,
        })

    return result


def list_all_issued_certificates_admin() -> list:
    """All certificates issued across the platform, newest first."""
    try:
        res = (
            supabase.table("certificates")
            .select("id, internship_id, student_id, company_id, student_name, company_name, job_title, start_date, end_date, issued_at, verification_code, skills_demonstrated, mentor_name, performance_summary")
            .order("issued_at", desc=True)
            .execute()
        )
        certs = res.data or []
    except Exception:
        return []

    for cert in certs:
        cert["verification_url"] = f"/verify/{cert.get('verification_code', '')}"
    return certs


def list_job_matching_admin(job_id: str) -> list:
    """AI matching results for a job (admin view)."""
    try:
        res = (
            supabase.table("ai_matching_results")
            .select("id, student_id, job_id, score, skill_match, research_sim, lang_readiness, learning_traj, explanation, matched_at")
            .eq("job_id", job_id)
            .order("score", desc=True)
            .execute()
        )
        results = res.data or []
    except Exception:
        return []

    if not results:
        return []

    # Batch-fetch student names
    student_ids = list({r["student_id"] for r in results if r.get("student_id")})
    profiles_map: dict = {}
    if student_ids:
        try:
            p_res = supabase.table("profiles").select("id, full_name").in_("id", student_ids).execute()
            for p in (p_res.data or []):
                profiles_map[p["id"]] = p.get("full_name", "")
        except Exception:
            pass

    for r in results:
        r["student_name"] = profiles_map.get(r.get("student_id", ""), "")

    return results
