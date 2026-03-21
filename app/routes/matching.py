"""
AI Matching Engine — /api/matching/*

Endpoints:
  POST /api/matching/run                                         — trigger matching run
  GET  /api/matching/runs/{run_id}/status                        — poll run status
  GET  /api/matching/results/{run_id}                            — ranked results
  POST /api/matching/results/{run_id}/shortlist                  — add/remove shortlist
  GET  /api/matching/results/{run_id}/candidates/{id}/explain    — explainability
"""

import uuid
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, g
from ..middleware.auth import require_role
from ..services.supabase_client import supabase
from ..services.llm_service import LLMService

matching_bp = Blueprint("matching", __name__)


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

_JP_SCORE = {"N1": 100, "N2": 90, "N3": 70, "N4": 50, "N5": 30, "None": 40, None: 40}
_JP_ORDER = {"N1": 5, "N2": 4, "N3": 3, "N4": 2, "N5": 1, "None": 0, None: 0}
_STATUS_LABELS = [(90, "Top Match"), (85, "Strong Fit"), (78, "Good Fit"), (70, "Potential"), (0, "Moderate")]


def _status_label(score: float) -> str:
    for threshold, label in _STATUS_LABELS:
        if score >= threshold:
            return label
    return "Moderate"


def _skill_alignment(student_skills: list, job_skills: list) -> int:
    if not job_skills:
        return 80
    student_set = {s.lower() for s in (student_skills or [])}
    job_set = {s.lower() for s in job_skills}
    matched = len(student_set & job_set)
    raw = (matched / len(job_set)) * 100
    return round(min(100, raw + max(0, 30 - matched * 5)))


def _research_similarity(research_title, job_desc) -> int:
    if not research_title or not job_desc:
        return 60
    stop = {"the", "a", "an", "for", "in", "of", "to", "and", "or", "is", "with"}
    rt_words = set(research_title.lower().split()) - stop
    jd_words = set(job_desc.lower().split()) - stop
    overlap = len(rt_words & jd_words)
    return round(min(100, overlap * 8 + 40))


def _language_readiness(jp_level, required_lang) -> int:
    base = _JP_SCORE.get(jp_level, 40)
    if not required_lang:
        return base
    req_order = _JP_ORDER.get(required_lang, 0)
    student_order = _JP_ORDER.get(jp_level, 0)
    if student_order >= req_order:
        return base
    gap = req_order - student_order
    return max(20, base - gap * 15)


def _learning_trajectory(gpa, skills_count: int) -> int:
    gpa_score = round((float(gpa) / 4.0) * 100) if gpa else 65
    return round(min(100, gpa_score + min(20, skills_count * 4)))


def _composite_score(student: dict, job: dict, weights: dict):
    w1 = weights.get("skill_alignment", 40) / 100
    w2 = weights.get("research_similarity", 25) / 100
    w3 = weights.get("language_readiness", 20) / 100
    w4 = weights.get("learning_trajectory", 15) / 100
    s1 = _skill_alignment(student.get("skills") or [], job.get("skills") or [])
    s2 = _research_similarity(student.get("research_title"), job.get("description"))
    s3 = _language_readiness(student.get("jp_level"), job.get("required_language"))
    s4 = _learning_trajectory(student.get("gpa"), len(student.get("skills") or []))
    total = round(s1 * w1 + s2 * w2 + s3 * w3 + s4 * w4)
    return total, s1, s2, s3, s4


def _flag_constraint(student: dict, job: dict, lang_score: int, score: int):
    req_lang = job.get("required_language")
    if req_lang and lang_score < 80:
        student_jp = student.get("jp_level") or "None"
        months = max(0, (_JP_ORDER.get(req_lang, 0) - _JP_ORDER.get(student_jp, 0)) * 6)
        return "Language Gap", f"Language requirement: JLPT {req_lang} ({months}mo away)"
    if score < 70:
        return "Skill Gap", "Skill gap: some required skills not found in student profile"
    return None, None


def _err(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


# ---------------------------------------------------------------------------
# POST /api/matching/run
# ---------------------------------------------------------------------------

@matching_bp.post("/run")
@require_role(["recruiter", "company_admin", "admin", "super_admin"])
def trigger_match():
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    config = data.get("config") or {}
    weights = config.get("weights") or {
        "skill_alignment": 40, "research_similarity": 25,
        "language_readiness": 20, "learning_trajectory": 15,
    }
    llm_provider = config.get("llm_provider")   # "claude" | "gemini" | None
    llm_top_n    = int(config.get("llm_top_n", 10))

    if not job_id:
        return _err("VALIDATION_ERROR", "job_id is required", 400)
    if sum(weights.values()) != 100:
        return _err("INVALID_WEIGHTS", "Weights must sum to 100", 400)
    if llm_provider and llm_provider not in ("claude", "gemini"):
        return _err("VALIDATION_ERROR", "llm_provider must be 'claude' or 'gemini'", 400)

    try:
        job_res = supabase.table("jobs").select("*").eq("id", job_id).maybe_single().execute()
    except Exception:
        return _err("NOT_FOUND", "Job not found", 404)
    if not job_res.data:
        return _err("NOT_FOUND", "Job not found", 404)
    job = job_res.data

    run_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()

    try:
        supabase.table("ai_matching_runs").insert({
            "id": run_id, "job_id": job_id, "triggered_by": g.user_id,
            "status": "running", "total_analyzed": 0,
            "llm_provider": llm_provider,
            "llm_analyzed_count": 0,
            "created_at": now, "updated_at": now,
        }).execute()
    except Exception as exc:
        return _err("SERVER_ERROR", f"Failed to create run: {exc}", 500)

    # ── Phase 1: Fetch eligible students ────────────────────────────────────
    try:
        sq = (
            supabase.table("students")
            .select("id, university_id, department, graduation_year, gpa, skills, "
                    "jp_level, research_title, verification_status, "
                    "profiles!inner(full_name, avatar_url, status)")
            .eq("verification_status", "verified")
        )
        min_jp = config.get("min_jp_level")
        if min_jp and min_jp in _JP_ORDER:
            min_ord = _JP_ORDER[min_jp]
            valid = [lv for lv, o in _JP_ORDER.items() if o >= min_ord and lv is not None]
            if valid:
                sq = sq.in_("jp_level", valid)
        grad_years = config.get("graduation_years")
        if grad_years:
            sq = sq.in_("graduation_year", grad_years)
        students = sq.execute().data or []
    except Exception as exc:
        supabase.table("ai_matching_runs").update({"status": "failed"}).eq("id", run_id).execute()
        return _err("SERVER_ERROR", f"Failed to fetch students: {exc}", 500)

    # ── Phase 2: Rule-based scoring ─────────────────────────────────────────
    min_score = config.get("min_score", 0)
    to_insert = []
    student_map: dict = {}        # student_id -> student dict (for LLM phase)
    now_ts = datetime.now(tz=timezone.utc).isoformat()

    for student in students:
        total, s1, s2, s3, s4 = _composite_score(student, job, weights)
        if total < min_score:
            continue
        profile = student.get("profiles") or {}
        flag, constraint = _flag_constraint(student, job, s3, total)
        full_name = profile.get("full_name") or ""
        student_map[student["id"]] = student
        to_insert.append({
            "job_id": job_id, "run_id": run_id, "student_id": student["id"],
            "score": total,
            "explanation": {
                "summary": f"{full_name}'s composite score is {total}/100.",
                "skill_notes": "Matched skills for this role.",
                "research_notes": f"Research relevance: {s2}/100",
                "language_notes": (
                    f"Language readiness: {s3}/100 "
                    f"(current: {student.get('jp_level') or 'N/A'})"
                ),
                "skill_match": s1, "research_sim": s2,
                "lang_readiness": s3, "learning_traj": s4,
                "flag": flag, "constraint": constraint,
                "llm_analysis": None,
            },
            "created_at": now_ts,
        })

    top_score = max((r["score"] for r in to_insert), default=0)

    try:
        if to_insert:
            supabase.table("ai_match_results").delete().eq("run_id", run_id).execute()
            supabase.table("ai_match_results").insert(to_insert).execute()
    except Exception:
        pass

    # ── Phase 3: LLM deep analysis (top N candidates) ───────────────────────
    llm_analyzed_count = 0
    if llm_provider and to_insert:
        try:
            llm_svc = LLMService(llm_provider)

            # Sort by rule-based score, take top N
            top_records = sorted(to_insert, key=lambda x: x["score"], reverse=True)[:llm_top_n]

            # Fetch university names for richer prompts
            uni_ids = list({student_map[r["student_id"]].get("university_id")
                            for r in top_records
                            if student_map.get(r["student_id"], {}).get("university_id")})
            uni_name_map: dict = {}
            if uni_ids:
                try:
                    ur = supabase.table("universities").select("id, name").in_("id", uni_ids).execute()
                    uni_name_map = {u["id"]: u["name"] for u in (ur.data or [])}
                except Exception:
                    pass

            # Build tasks for parallel LLM calls
            tasks = []
            for record in top_records:
                sid = record["student_id"]
                s = student_map.get(sid, {})
                uni_name = uni_name_map.get(s.get("university_id"), "Unknown")
                student_for_llm = {**s, "university_name": uni_name}
                scores_for_llm = {
                    "total": record["score"],
                    "skill_match":    record["explanation"]["skill_match"],
                    "research_sim":   record["explanation"]["research_sim"],
                    "lang_readiness": record["explanation"]["lang_readiness"],
                    "learning_traj":  record["explanation"]["learning_traj"],
                }
                tasks.append((sid, student_for_llm, scores_for_llm))

            llm_results = llm_svc.analyze_batch(tasks, job, max_workers=5)

            # Update DB records with LLM analysis
            for record in top_records:
                sid = record["student_id"]
                if sid not in llm_results:
                    continue
                updated_exp = {**record["explanation"], "llm_analysis": llm_results[sid]}
                try:
                    supabase.table("ai_match_results").update(
                        {"explanation": updated_exp}
                    ).eq("run_id", run_id).eq("student_id", sid).execute()
                    llm_analyzed_count += 1
                except Exception:
                    pass

        except Exception:
            # LLM failure is non-fatal — rule-based results are already stored
            pass

    # ── Finalise run record ──────────────────────────────────────────────────
    try:
        supabase.table("ai_matching_runs").update({
            "status": "complete",
            "total_analyzed": len(students),
            "top_score": top_score,
            "llm_analyzed_count": llm_analyzed_count,
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
        }).eq("id", run_id).execute()
    except Exception:
        pass

    return jsonify({
        "data": {
            "run_id": run_id,
            "status": "complete",
            "estimated_seconds": 0,
            "llm_provider": llm_provider,
            "llm_analyzed_count": llm_analyzed_count,
            "poll_url": f"/api/matching/runs/{run_id}/status",
        }
    }), 202


# ---------------------------------------------------------------------------
# GET /api/matching/runs/{run_id}/status
# ---------------------------------------------------------------------------

@matching_bp.get("/runs/<string:run_id>/status")
@require_role(["recruiter", "company_admin", "admin", "super_admin"])
def run_status(run_id: str):
    try:
        res = supabase.table("ai_matching_runs").select("*").eq("id", run_id).maybe_single().execute()
    except Exception:
        return _err("NOT_FOUND", "Run not found", 404)
    if not res.data:
        return _err("RUN_NOT_FOUND", "Run not found", 404)

    run = res.data
    status = run.get("status", "pending")
    progress = 100 if status == "complete" else (50 if status == "running" else 0)
    steps = (
        ["skill_alignment", "research_similarity", "language_readiness", "learning_trajectory",
         "ranking", "llm_analysis"] if status == "complete" else []
    )
    return jsonify({
        "data": {
            "run_id": run_id, "status": status, "progress": progress,
            "steps_complete": steps,
            "llm_provider": run.get("llm_provider"),
            "llm_analyzed_count": run.get("llm_analyzed_count", 0),
            "result_url": f"/api/matching/results/{run_id}" if status == "complete" else None,
        }
    })


# ---------------------------------------------------------------------------
# GET /api/matching/results/{run_id}
# ---------------------------------------------------------------------------

@matching_bp.get("/results/<string:run_id>")
@require_role(["recruiter", "company_admin", "admin", "super_admin"])
def get_results(run_id: str):
    try:
        run_res = supabase.table("ai_matching_runs").select("*").eq("id", run_id).maybe_single().execute()
    except Exception:
        return _err("NOT_FOUND", "Run not found", 404)
    if not run_res.data:
        return _err("RUN_NOT_FOUND", "Run not found", 404)

    run = run_res.data
    job_id = run.get("job_id")

    job_title = None
    try:
        jr = supabase.table("jobs").select("title").eq("id", job_id).maybe_single().execute()
        if jr.data:
            job_title = jr.data.get("title")
    except Exception:
        pass

    page    = max(1, int(request.args.get("page", 1)))
    limit   = min(100, max(1, int(request.args.get("limit", 20))))
    sort    = request.args.get("sort", "score")
    filter_ = request.args.get("filter", "all")

    try:
        rr = (
            supabase.table("ai_match_results")
            .select("student_id, score, explanation")
            .eq("run_id", run_id)
            .order("score", desc=True)
            .execute()
        )
        raw = rr.data or []
    except Exception:
        return _err("SERVER_ERROR", "Failed to fetch results", 500)

    # Shortlisted IDs for this job
    shortlisted_ids: list = []
    try:
        sl = supabase.table("applications").select("student_id").eq("job_id", job_id).eq("status", "shortlisted").execute()
        shortlisted_ids = [r["student_id"] for r in (sl.data or [])]
    except Exception:
        pass

    # Batch-load students
    student_ids = [r["student_id"] for r in raw]
    student_map: dict = {}
    uni_name_map: dict = {}
    if student_ids:
        try:
            for i in range(0, len(student_ids), 50):
                batch = student_ids[i:i + 50]
                sr = supabase.table("students").select(
                    "id, gpa, skills, jp_level, research_title, university_id, department, "
                    "profiles!inner(full_name, avatar_url)"
                ).in_("id", batch).execute()
                for s in (sr.data or []):
                    student_map[s["id"]] = s
            uni_ids = list({s.get("university_id") for s in student_map.values() if s.get("university_id")})
            if uni_ids:
                ur = supabase.table("universities").select("id, name").in_("id", uni_ids).execute()
                uni_name_map = {u["id"]: u["name"] for u in (ur.data or [])}
        except Exception:
            pass

    candidates = []
    for idx, r in enumerate(raw):
        s_id = r["student_id"]
        s = student_map.get(s_id, {})
        exp = r.get("explanation") or {}
        score = round(float(r["score"]))
        flag = exp.get("flag")
        constraint = exp.get("constraint")

        if filter_ == "no_constraints" and flag:
            continue
        if filter_ == "shortlisted" and s_id not in shortlisted_ids:
            continue

        p = s.get("profiles") or {}
        full_name = p.get("full_name") or ""
        initials = "".join(x[0].upper() for x in full_name.split() if x)[:2] or "??"
        uni_id = s.get("university_id")

        candidates.append({
            "rank": idx + 1,
            "student_id": s_id,
            "name": full_name,
            "initials": initials,
            "school": uni_name_map.get(uni_id, "Unknown") if uni_id else "Unknown",
            "department": s.get("department"),
            "score": score,
            "skill_match": round(float(exp.get("skill_match", 0))),
            "research_sim": round(float(exp.get("research_sim", 0))),
            "lang_readiness": round(float(exp.get("lang_readiness", 0))),
            "learning_traj": round(float(exp.get("learning_traj", 0))),
            "skills": (s.get("skills") or [])[:5],
            "research_title": s.get("research_title"),
            "jp_level": s.get("jp_level"),
            "status": _status_label(score),
            "flag": flag,
            "constraint": constraint,
            "explanation": {
                "summary": exp.get("summary", ""),
                "skill_notes": exp.get("skill_notes", ""),
                "research_notes": exp.get("research_notes", ""),
                "language_notes": exp.get("language_notes", ""),
            },
            "llm_analysis": exp.get("llm_analysis"),
        })

    if sort == "skill":
        candidates.sort(key=lambda c: c["skill_match"], reverse=True)
    elif sort == "lang":
        candidates.sort(key=lambda c: c["lang_readiness"], reverse=True)

    for i, c in enumerate(candidates):
        c["rank"] = i + 1

    total = len(candidates)
    page_candidates = candidates[(page - 1) * limit : page * limit]

    return jsonify({
        "data": {
            "run_id": run_id, "job_id": job_id, "job_title": job_title,
            "total_analyzed": run.get("total_analyzed", 0),
            "candidates": page_candidates,
            "shortlisted_ids": shortlisted_ids,
        },
        "meta": {"page": page, "limit": limit, "total": total},
    })


# ---------------------------------------------------------------------------
# POST /api/matching/results/{run_id}/shortlist
# ---------------------------------------------------------------------------

@matching_bp.post("/results/<string:run_id>/shortlist")
@require_role(["recruiter", "company_admin", "admin", "super_admin"])
def update_shortlist(run_id: str):
    data = request.get_json(silent=True) or {}
    student_id = data.get("student_id")
    action = data.get("action", "add")

    if not student_id:
        return _err("VALIDATION_ERROR", "student_id is required", 400)

    try:
        rr = supabase.table("ai_matching_runs").select("job_id").eq("id", run_id).maybe_single().execute()
    except Exception:
        return _err("NOT_FOUND", "Run not found", 404)
    if not rr.data:
        return _err("RUN_NOT_FOUND", "Run not found", 404)

    job_id = rr.data["job_id"]

    if action == "add":
        try:
            supabase.table("applications").upsert(
                {"job_id": job_id, "student_id": student_id, "status": "shortlisted",
                 "shortlisted_at": datetime.now(tz=timezone.utc).isoformat()},
                on_conflict="job_id,student_id"
            ).execute()
        except Exception as exc:
            return _err("SERVER_ERROR", f"Failed to shortlist: {exc}", 500)
    elif action == "remove":
        try:
            supabase.table("applications").update({"status": "pending"}).eq(
                "job_id", job_id).eq("student_id", student_id).execute()
        except Exception as exc:
            return _err("SERVER_ERROR", f"Failed to remove shortlist: {exc}", 500)
    else:
        return _err("VALIDATION_ERROR", "action must be 'add' or 'remove'", 400)

    try:
        sl = supabase.table("applications").select("student_id").eq("job_id", job_id).eq("status", "shortlisted").execute()
        shortlisted_ids = [r["student_id"] for r in (sl.data or [])]
    except Exception:
        shortlisted_ids = []

    return jsonify({"data": {"shortlisted_ids": shortlisted_ids}})


# ---------------------------------------------------------------------------
# GET /api/matching/results/{run_id}/candidates/{student_id}/explain
# ---------------------------------------------------------------------------

@matching_bp.get("/results/<string:run_id>/candidates/<string:student_id>/explain")
@require_role(["recruiter", "company_admin", "admin", "super_admin"])
def explain_candidate(run_id: str, student_id: str):
    try:
        res = (
            supabase.table("ai_match_results")
            .select("score, explanation, job_id")
            .eq("run_id", run_id)
            .eq("student_id", student_id)
            .maybe_single()
            .execute()
        )
    except Exception:
        return _err("NOT_FOUND", "Match result not found", 404)
    if not res.data:
        return _err("NOT_FOUND", "Match result not found", 404)

    r = res.data
    exp = r.get("explanation") or {}
    score = round(float(r["score"]))
    job_id = r.get("job_id")

    research_title = None
    jp_level = None
    matched_skills: list = []
    try:
        sr = supabase.table("students").select("skills, jp_level, research_title").eq("id", student_id).maybe_single().execute()
        if sr.data:
            research_title = sr.data.get("research_title")
            jp_level = sr.data.get("jp_level")
            matched_skills = sr.data.get("skills") or []
    except Exception:
        pass

    job_skills: list = []
    required_lang = None
    try:
        jr = supabase.table("jobs").select("skills, required_language").eq("id", job_id).maybe_single().execute()
        if jr.data:
            job_skills = jr.data.get("skills") or []
            required_lang = jr.data.get("required_language")
    except Exception:
        pass

    student_set = {s.lower() for s in matched_skills}
    job_set = {s.lower() for s in job_skills}
    found = [s for s in matched_skills if s.lower() in job_set]
    missing = [s for s in job_skills if s.lower() not in student_set]
    months = max(0, (_JP_ORDER.get(required_lang, 0) - _JP_ORDER.get(jp_level, 0)) * 6)

    flag = exp.get("flag")
    recommendation = "Top Match — no blockers" if not flag else f"Review required: {flag}"

    return jsonify({
        "data": {
            "student_id": student_id, "job_id": job_id, "overall_score": score,
            "dimensions": {
                "skill_alignment": {"score": round(float(exp.get("skill_match", 0))), "matched_skills": found, "missing_skills": missing},
                "research_similarity": {"score": round(float(exp.get("research_sim", 0))), "research_title": research_title, "relevance_tags": (research_title or "").split()[:3] if research_title else []},
                "language_readiness": {"score": round(float(exp.get("lang_readiness", 0))), "current_level": jp_level, "target_level": required_lang, "months_to_target": months},
                "learning_trajectory": {"score": round(float(exp.get("learning_traj", 0))), "trend": "accelerating" if score >= 85 else "steady" if score >= 70 else "developing", "recent_certifications": 0},
            },
            "constraint": exp.get("constraint"),
            "recommendation": recommendation,
            "llm_analysis": exp.get("llm_analysis"),
        }
    })
