"""
Internship & Certificate Service Layer — business logic for internship tracking
and certificate issuance.
"""

import uuid
import secrets
import string
from datetime import datetime, timezone
from ..services.supabase_client import supabase


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _generate_verification_code(company_name: str) -> str:
    """Generate a unique verification code: CERT-{year}-{prefix}-{random6}"""
    year = datetime.now(tz=timezone.utc).year
    prefix = "".join(c for c in company_name[:3].upper() if c.isalpha()) or "INT"
    chars = string.ascii_uppercase + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(6))
    return f"CERT-{year}-{prefix}-{random_part}"


# ═══════════════════════════════════════════════════════════════════════════
# Internships
# ═══════════════════════════════════════════════════════════════════════════

def get_student_internships(student_id: str) -> list[dict]:
    """Get all internships for a student with milestones and certificate info."""
    res = (
        supabase.table("internships")
        .select("*, jobs(title), companies(name, logo_url)")
        .eq("student_id", student_id)
        .order("created_at", desc=True)
        .execute()
    )
    internships = res.data or []

    for intern in internships:
        # Flatten joined data
        intern["job_title"] = intern.pop("jobs", {}).get("title", "")
        company = intern.pop("companies", {})
        intern["company_name"] = company.get("name", "")
        intern["company_logo_url"] = company.get("logo_url")

        # Fetch milestones
        ms_res = (
            supabase.table("internship_milestones")
            .select("*")
            .eq("internship_id", intern["id"])
            .order("sort_order")
            .execute()
        )
        intern["milestones"] = ms_res.data or []

        # Fetch certificate if exists
        cert_res = (
            supabase.table("certificates")
            .select("id, verification_code, issued_at")
            .eq("internship_id", intern["id"])
            .execute()
        )
        certs = cert_res.data or []
        intern["certificate"] = certs[0] if certs else None

    return internships


def get_internship_detail(student_id: str, internship_id: str) -> dict | None:
    """Get a single internship with milestones."""
    res = (
        supabase.table("internships")
        .select("*, jobs(title), companies(name, logo_url)")
        .eq("id", internship_id)
        .eq("student_id", student_id)
        .single()
        .execute()
    )
    if not res.data:
        return None

    intern = res.data
    intern["job_title"] = intern.pop("jobs", {}).get("title", "")
    company = intern.pop("companies", {})
    intern["company_name"] = company.get("name", "")
    intern["company_logo_url"] = company.get("logo_url")

    ms_res = (
        supabase.table("internship_milestones")
        .select("*")
        .eq("internship_id", internship_id)
        .order("sort_order")
        .execute()
    )
    intern["milestones"] = ms_res.data or []

    cert_res = (
        supabase.table("certificates")
        .select("id, verification_code, issued_at")
        .eq("internship_id", internship_id)
        .execute()
    )
    certs = cert_res.data or []
    intern["certificate"] = certs[0] if certs else None

    return intern


def complete_milestone(student_id: str, internship_id: str, milestone_id: str) -> dict | None:
    """Mark a student-actionable milestone as completed."""
    # Verify ownership
    intern_res = (
        supabase.table("internships")
        .select("id")
        .eq("id", internship_id)
        .eq("student_id", student_id)
        .execute()
    )
    if not (intern_res.data):
        return None

    # Verify milestone exists, is actionable, and not already completed
    ms_res = (
        supabase.table("internship_milestones")
        .select("*")
        .eq("id", milestone_id)
        .eq("internship_id", internship_id)
        .single()
        .execute()
    )
    if not ms_res.data:
        return None

    milestone = ms_res.data
    if not milestone.get("student_actionable"):
        return {"error": "NOT_ACTIONABLE"}
    if milestone.get("status") == "completed":
        return {"error": "ALREADY_COMPLETED"}

    # Update
    update_res = (
        supabase.table("internship_milestones")
        .update({"status": "completed", "completed_at": _now_iso()})
        .eq("id", milestone_id)
        .execute()
    )
    return (update_res.data or [{}])[0]


# ═══════════════════════════════════════════════════════════════════════════
# Certificates
# ═══════════════════════════════════════════════════════════════════════════

def get_student_certificates(student_id: str) -> list[dict]:
    """Get all certificates for a student."""
    res = (
        supabase.table("certificates")
        .select("*")
        .eq("student_id", student_id)
        .order("issued_at", desc=True)
        .execute()
    )
    certs = res.data or []
    for cert in certs:
        cert["verification_url"] = f"/verify/{cert['verification_code']}"
        cert["download_url"] = f"/api/certificates/{cert['verification_code']}/download"
    return certs


def verify_certificate(verification_code: str) -> dict | None:
    """Public verification — look up certificate by code."""
    res = (
        supabase.table("certificates")
        .select("verification_code, student_name, company_name, job_title, start_date, end_date, issued_at, skills_demonstrated, mentor_name")
        .eq("verification_code", verification_code)
        .execute()
    )
    certs = res.data or []
    if not certs:
        return None

    cert = certs[0]
    return {
        "valid": True,
        "student_name": cert["student_name"],
        "company_name": cert["company_name"],
        "job_title": cert["job_title"],
        "duration": f"{cert['start_date']} to {cert['end_date']}",
        "issued_at": cert["issued_at"],
        "verification_code": cert["verification_code"],
        "skills_demonstrated": cert.get("skills_demonstrated", []),
        "mentor_name": cert.get("mentor_name"),
    }


def issue_certificate(internship_id: str, issuer_id: str, data: dict) -> dict:
    """Issue a certificate for a completed internship (company/admin action)."""
    # Verify internship exists and is completed
    intern_res = (
        supabase.table("internships")
        .select("*, jobs(title), companies(name), students!inner(id, profiles!inner(full_name))")
        .eq("id", internship_id)
        .single()
        .execute()
    )
    if not intern_res.data:
        return {"error": "INTERNSHIP_NOT_FOUND"}

    intern = intern_res.data
    if intern["status"] != "completed":
        return {"error": "INTERNSHIP_NOT_COMPLETED"}

    # Check no existing certificate
    existing = (
        supabase.table("certificates")
        .select("id")
        .eq("internship_id", internship_id)
        .execute()
    )
    if existing.data:
        return {"error": "CERTIFICATE_EXISTS"}

    company_name = intern.get("companies", {}).get("name", "")
    student_name = intern.get("students", {}).get("profiles", {}).get("full_name", "")
    job_title = intern.get("jobs", {}).get("title", "")

    verification_code = _generate_verification_code(company_name)

    cert_data = {
        "id": str(uuid.uuid4()),
        "internship_id": internship_id,
        "student_id": intern["student_id"],
        "company_id": intern["company_id"],
        "verification_code": verification_code,
        "student_name": student_name,
        "company_name": company_name,
        "job_title": job_title,
        "start_date": intern["start_date"],
        "end_date": intern["end_date"],
        "skills_demonstrated": data.get("skills_demonstrated", []),
        "performance_summary": data.get("performance_summary"),
        "mentor_name": data.get("mentor_name"),
        "issued_at": _now_iso(),
    }

    res = supabase.table("certificates").insert(cert_data).execute()
    cert = (res.data or [cert_data])[0]
    cert["verification_url"] = f"/verify/{verification_code}"
    return cert


def get_certificate_for_download(verification_code: str) -> dict | None:
    """Get full certificate data for PDF generation."""
    res = (
        supabase.table("certificates")
        .select("*")
        .eq("verification_code", verification_code)
        .execute()
    )
    certs = res.data or []
    return certs[0] if certs else None
