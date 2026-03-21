"""
Company Analytics API — /api/analytics/*

Endpoints:
  GET /api/analytics/company   — aggregated dashboard metrics for company_admin

Query params:
  period : 6m | 3m | 1m | ytd   (default: 6m)

Returns:
  active_jobs, total_applicants, ai_matches_today, offers_extended,
  offers_accepted, hiring_funnel[], pipeline{}, recent_activity[]
"""

from datetime import datetime, timedelta, timezone, date
from calendar import month_abbr
from flask import Blueprint, jsonify, request, g
from ..services.supabase_client import supabase
from ..middleware.auth import require_role

analytics_bp = Blueprint("analytics", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _err(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _get_company_id(user_id: str):
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


def _period_start(period: str) -> datetime:
    now = datetime.now(tz=timezone.utc)
    if period == "1m":
        return now - timedelta(days=30)
    if period == "3m":
        return now - timedelta(days=90)
    if period == "ytd":
        return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    # default 6m
    return now - timedelta(days=180)


def _month_labels(period: str) -> list:
    """Return ordered (year, month) tuples for the period."""
    now = datetime.now(tz=timezone.utc)
    if period == "1m":
        n_months = 1
    elif period == "3m":
        n_months = 3
    elif period == "ytd":
        n_months = now.month
    else:
        n_months = 6

    months = []
    for i in range(n_months - 1, -1, -1):
        d = now - timedelta(days=30 * i)
        months.append((d.year, d.month))
    return months


# ---------------------------------------------------------------------------
# GET /api/analytics/company
# ---------------------------------------------------------------------------

@analytics_bp.get("/company")
@require_role(["company_admin", "recruiter"])
def company_analytics():
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    period = request.args.get("period", "6m")
    if period not in ("6m", "3m", "1m", "ytd"):
        period = "6m"

    period_start = _period_start(period)
    period_start_str = period_start.isoformat()
    today_start = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    # ── Fetch all company job IDs ─────────────────────────────────────────
    try:
        jobs_res = (
            supabase.table("jobs")
            .select("id, status, created_at")
            .eq("company_id", company_id)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to fetch company jobs", 500)

    all_jobs = jobs_res.data or []
    all_job_ids = [j["id"] for j in all_jobs]
    active_jobs = sum(1 for j in all_jobs if j.get("status") == "published")

    if not all_job_ids:
        # Company has no jobs — return zero metrics
        return jsonify({
            "data": {
                "period": period,
                "active_jobs": 0,
                "total_applicants": 0,
                "ai_matches_today": 0,
                "offers_extended": 0,
                "offers_accepted": 0,
                "hiring_funnel": [],
                "pipeline": {
                    "screening": 0,
                    "interview": 0,
                    "assessment": 0,
                    "offer_stage": 0,
                },
                "recent_activity": [],
            }
        })

    # ── Applications ──────────────────────────────────────────────────────
    try:
        apps_res = (
            supabase.table("applications")
            .select("id, job_id, status, created_at, updated_at")
            .in_("job_id", all_job_ids)
            .execute()
        )
    except Exception:
        apps_res = type("R", (), {"data": []})()

    all_apps = apps_res.data or []
    total_applicants = len(all_apps)
    offers_extended = sum(1 for a in all_apps if a.get("status") in ("offered", "accepted"))
    offers_accepted = sum(1 for a in all_apps if a.get("status") == "accepted")

    # Pipeline (current snapshot across all published jobs)
    pipeline = {
        "screening": sum(1 for a in all_apps if a.get("status") == "pending"),
        "interview": sum(1 for a in all_apps if a.get("status") == "shortlisted"),
        "assessment": 0,  # no distinct DB status; placeholder
        "offer_stage": sum(1 for a in all_apps if a.get("status") == "offered"),
    }

    # ── AI Matches Today ──────────────────────────────────────────────────
    ai_matches_today = 0
    try:
        ai_res = (
            supabase.table("ai_match_results")
            .select("id")
            .in_("job_id", all_job_ids)
            .gte("created_at", today_start)
            .execute()
        )
        ai_matches_today = len(ai_res.data or [])
    except Exception:
        pass

    # ── Hiring Funnel (month-by-month) ────────────────────────────────────
    month_tuples = _month_labels(period)

    def _apps_in_month(apps, yr, mo, status_filter=None):
        count = 0
        for a in apps:
            created = a.get("created_at", "")
            try:
                dt = datetime.fromisoformat(created)
                if dt.year == yr and dt.month == mo:
                    if status_filter is None or a.get("status") in status_filter:
                        count += 1
            except Exception:
                pass
        return count

    hiring_funnel = []
    for yr, mo in month_tuples:
        apps_in_m = _apps_in_month(all_apps, yr, mo)
        shortlisted_in_m = _apps_in_month(all_apps, yr, mo, {"shortlisted", "offered", "accepted"})
        hired_in_m = _apps_in_month(all_apps, yr, mo, {"accepted"})
        hiring_funnel.append({
            "month": month_abbr[mo],
            "year": yr,
            "applications": apps_in_m,
            "shortlisted": shortlisted_in_m,
            "hired": hired_in_m,
        })

    # ── Recent Activity ───────────────────────────────────────────────────
    recent_activity = []

    # Latest AI matching run
    try:
        run_res = (
            supabase.table("ai_matching_runs")
            .select("id, job_id, total_analyzed, created_at, status")
            .in_("job_id", all_job_ids)
            .eq("status", "complete")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if run_res.data:
            run = run_res.data[0]
            recent_activity.append({
                "type": "match",
                "message": f"{run.get('total_analyzed', 0)} new AI matches generated",
                "time": run.get("created_at"),
                "urgent": False,
            })
    except Exception:
        pass

    # Recent applications (last 24h)
    recent_apps = [
        a for a in all_apps
        if a.get("created_at", "") >= today_start
    ]
    if recent_apps:
        recent_activity.append({
            "type": "application",
            "message": f"{len(recent_apps)} new application{'s' if len(recent_apps) != 1 else ''} received today",
            "time": recent_apps[0].get("created_at"),
            "urgent": False,
        })

    # Jobs closing within 3 days
    three_days_later = (datetime.now(tz=timezone.utc) + timedelta(days=3)).date()
    today_date = date.today()
    closing_soon = []
    for j in all_jobs:
        if j.get("status") == "published" and j.get("deadline"):
            try:
                dl = date.fromisoformat(str(j["deadline"]))
                if today_date <= dl <= three_days_later:
                    closing_soon.append(j)
            except Exception:
                pass
    if closing_soon:
        recent_activity.append({
            "type": "deadline",
            "message": f"{len(closing_soon)} job posting{'s' if len(closing_soon) != 1 else ''} closing within 3 days",
            "time": datetime.now(tz=timezone.utc).isoformat(),
            "urgent": True,
        })

    return jsonify({
        "data": {
            "period": period,
            "active_jobs": active_jobs,
            "total_applicants": total_applicants,
            "ai_matches_today": ai_matches_today,
            "offers_extended": offers_extended,
            "offers_accepted": offers_accepted,
            "hiring_funnel": hiring_funnel,
            "pipeline": pipeline,
            "recent_activity": recent_activity,
        }
    })


# ---------------------------------------------------------------------------
# GET /api/analytics/recruiter
# ---------------------------------------------------------------------------

@analytics_bp.get("/recruiter")
@require_role(["company_admin", "recruiter"])
def recruiter_analytics():
    company_id, err = _get_company_id(g.user_id)
    if err:
        return err

    all_job_ids: list = []
    active_jds = 0
    try:
        jr = supabase.table("jobs").select("id, status").eq("company_id", company_id).execute()
        all_jobs = jr.data or []
        all_job_ids = [j["id"] for j in all_jobs]
        active_jds = sum(1 for j in all_jobs if j.get("status") == "published")
    except Exception:
        pass

    if not all_job_ids:
        return jsonify({
            "data": {
                "active_jds": 0, "total_matches_this_week": 0,
                "shortlisted_total": 0, "interviews_scheduled": 0,
                "placement_rate": 0.0, "top_skill_matches": [], "monthly_pipeline": [],
            }
        })

    shortlisted_total = 0
    try:
        sl = supabase.table("applications").select("id").in_("job_id", all_job_ids).eq("status", "shortlisted").execute()
        shortlisted_total = len(sl.data or [])
    except Exception:
        pass

    week_start = (datetime.now(tz=timezone.utc) - timedelta(days=7)).isoformat()
    total_matches_this_week = 0
    try:
        mw = supabase.table("ai_match_results").select("id").in_("job_id", all_job_ids).gte("created_at", week_start).execute()
        total_matches_this_week = len(mw.data or [])
    except Exception:
        pass

    interviews_scheduled = 0
    try:
        iv = supabase.table("applications").select("id").in_("job_id", all_job_ids).in_("status", ["shortlisted", "offered"]).gte("updated_at", week_start).execute()
        interviews_scheduled = len(iv.data or [])
    except Exception:
        pass

    placement_rate = 0.0
    try:
        ap = supabase.table("applications").select("status").in_("job_id", all_job_ids).execute()
        apps = ap.data or []
        total_apps = len(apps)
        accepted = sum(1 for a in apps if a.get("status") == "accepted")
        placement_rate = round(accepted / total_apps, 2) if total_apps > 0 else 0.0
    except Exception:
        pass

    top_skill_matches: list = []
    try:
        mr = supabase.table("ai_match_results").select("student_id").in_("job_id", all_job_ids).order("score", desc=True).limit(50).execute()
        top_ids = [r["student_id"] for r in (mr.data or [])]
        if top_ids:
            st = supabase.table("students").select("skills").in_("id", top_ids[:30]).execute()
            skill_counts: dict = {}
            for s in (st.data or []):
                for sk in (s.get("skills") or []):
                    skill_counts[sk] = skill_counts.get(sk, 0) + 1
            top_skill_matches = sorted(
                [{"skill": k, "match_count": v} for k, v in skill_counts.items()],
                key=lambda x: x["match_count"], reverse=True
            )[:5]
    except Exception:
        pass

    monthly_pipeline: list = []
    try:
        ap2 = supabase.table("applications").select("id, status, created_at").in_("job_id", all_job_ids).execute()
        all_apps_data = ap2.data or []
        for yr, mo in _month_labels("6m"):
            m_apps = []
            for a in all_apps_data:
                try:
                    dt = datetime.fromisoformat(a.get("created_at", ""))
                    if dt.year == yr and dt.month == mo:
                        m_apps.append(a)
                except Exception:
                    pass
            monthly_pipeline.append({
                "month": month_abbr[mo],
                "applications": len(m_apps),
                "shortlisted": sum(1 for a in m_apps if a.get("status") in ("shortlisted", "offered", "accepted")),
                "hired": sum(1 for a in m_apps if a.get("status") == "accepted"),
            })
    except Exception:
        pass

    return jsonify({
        "data": {
            "active_jds": active_jds,
            "total_matches_this_week": total_matches_this_week,
            "shortlisted_total": shortlisted_total,
            "interviews_scheduled": interviews_scheduled,
            "placement_rate": placement_rate,
            "top_skill_matches": top_skill_matches,
            "monthly_pipeline": monthly_pipeline,
        }
    })
