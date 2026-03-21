"""
Notification service — creates in-app notifications for lifecycle events.

Usage:
    from ..services.notification_service import notify, notify_bulk, notify_admins
"""

from ..services.supabase_client import supabase


def notify(user_id: str, type: str, title: str, body: str = "",
           entity_type: str = None, entity_id: str = None):
    """Create a single notification."""
    row = {
        "user_id": user_id,
        "type": type,
        "title": title,
        "body": body,
    }
    if entity_type:
        row["entity_type"] = entity_type
    if entity_id:
        row["entity_id"] = entity_id
    try:
        supabase.table("notifications").insert(row).execute()
    except Exception:
        pass  # best-effort; don't block the caller


def notify_bulk(user_ids: list, type: str, title: str, body: str = "",
                entity_type: str = None, entity_id: str = None):
    """Create notifications for multiple users."""
    if not user_ids:
        return
    rows = []
    for uid in user_ids:
        row = {
            "user_id": uid,
            "type": type,
            "title": title,
            "body": body,
        }
        if entity_type:
            row["entity_type"] = entity_type
        if entity_id:
            row["entity_id"] = entity_id
        rows.append(row)
    try:
        supabase.table("notifications").insert(rows).execute()
    except Exception:
        pass


def notify_admins(type: str, title: str, body: str = "",
                  entity_type: str = None, entity_id: str = None):
    """Notify all platform admins (super_admin role)."""
    try:
        res = (
            supabase.table("profiles")
            .select("id")
            .eq("role", "super_admin")
            .execute()
        )
        admin_ids = [r["id"] for r in (res.data or [])]
        if admin_ids:
            notify_bulk(admin_ids, type, title, body, entity_type, entity_id)
    except Exception:
        pass


def notify_university_admins_for_job(job_id: str, type: str, title: str,
                                     body: str = ""):
    """Notify university admins for all universities assigned to a job."""
    try:
        # Get assigned university IDs
        assign_res = (
            supabase.table("job_university_assignments")
            .select("university_id")
            .eq("job_id", job_id)
            .execute()
        )
        uni_ids = [r["university_id"] for r in (assign_res.data or [])]
        if not uni_ids:
            return

        # Find profiles with university_admin role at those universities
        profiles_res = (
            supabase.table("profiles")
            .select("id")
            .eq("role", "university_admin")
            .in_("university_id", uni_ids)
            .execute()
        )
        admin_ids = [r["id"] for r in (profiles_res.data or [])]
        if admin_ids:
            notify_bulk(admin_ids, type, title, body, "job", job_id)
    except Exception:
        pass


def notify_company_admins_for_job(job_id: str, type: str, title: str,
                                  body: str = ""):
    """Notify company admin / recruiters for a job."""
    try:
        job_res = (
            supabase.table("jobs")
            .select("company_id, recruiter_id")
            .eq("id", job_id)
            .single()
            .execute()
        )
        if not job_res.data:
            return
        company_id = job_res.data.get("company_id")
        # Find all recruiters for this company
        rec_res = (
            supabase.table("recruiters")
            .select("id")
            .eq("company_id", company_id)
            .execute()
        )
        user_ids = [r["id"] for r in (rec_res.data or [])]
        if user_ids:
            notify_bulk(user_ids, type, title, body, "job", job_id)
    except Exception:
        pass
