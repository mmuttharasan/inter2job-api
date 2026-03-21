"""
Evaluation API — /api/evaluation/*

Endpoints:
  GET  /api/evaluation/jobs                              — list published jobs
  POST /api/evaluation/sessions                          — create evaluation session
  GET  /api/evaluation/sessions/{id}/questions           — AI-generated questions
  POST /api/evaluation/sessions/{id}/scores              — save scores
  GET  /api/evaluation/sessions/{id}/summary             — evaluation summary
"""

import uuid
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, g
from ..middleware.auth import require_role
from ..services.supabase_client import supabase

evaluation_bp = Blueprint("evaluation", __name__)


def _err(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


# ---------------------------------------------------------------------------
# Question bank — skills → questions mapping
# ---------------------------------------------------------------------------

_QUESTION_BANK: dict[str, list[dict]] = {
    "React": [
        {"question": "Explain the difference between controlled and uncontrolled components in React.", "difficulty": "medium", "time_estimate": "5 min", "context": "Core React knowledge"},
        {"question": "How does React's reconciliation algorithm work?", "difficulty": "hard", "time_estimate": "8 min", "context": "Performance optimization"},
        {"question": "What are React hooks and why were they introduced?", "difficulty": "easy", "time_estimate": "3 min", "context": "Modern React patterns"},
    ],
    "TypeScript": [
        {"question": "What is the difference between 'interface' and 'type' in TypeScript?", "difficulty": "medium", "time_estimate": "5 min", "context": "Type system"},
        {"question": "Explain generic constraints in TypeScript with an example.", "difficulty": "hard", "time_estimate": "8 min", "context": "Advanced types"},
    ],
    "Python": [
        {"question": "Explain Python's GIL and its implications for concurrency.", "difficulty": "hard", "time_estimate": "8 min", "context": "Concurrency"},
        {"question": "What are Python decorators and how do you create them?", "difficulty": "medium", "time_estimate": "5 min", "context": "Language features"},
        {"question": "What is the difference between a list and a generator in Python?", "difficulty": "easy", "time_estimate": "3 min", "context": "Data structures"},
    ],
    "Machine Learning": [
        {"question": "Explain overfitting and techniques to prevent it.", "difficulty": "medium", "time_estimate": "6 min", "context": "Model training"},
        {"question": "What is the difference between supervised and unsupervised learning?", "difficulty": "easy", "time_estimate": "3 min", "context": "Fundamentals"},
        {"question": "Describe the backpropagation algorithm.", "difficulty": "hard", "time_estimate": "10 min", "context": "Deep learning"},
    ],
    "SQL": [
        {"question": "Explain the difference between INNER JOIN, LEFT JOIN, and FULL OUTER JOIN.", "difficulty": "easy", "time_estimate": "4 min", "context": "Joins"},
        {"question": "How would you optimize a slow SQL query?", "difficulty": "hard", "time_estimate": "8 min", "context": "Performance"},
    ],
    "default": [
        {"question": "Describe a challenging technical problem you've solved.", "difficulty": "medium", "time_estimate": "8 min", "context": "General problem solving"},
        {"question": "How do you stay up to date with new technologies?", "difficulty": "easy", "time_estimate": "3 min", "context": "Learning habits"},
        {"question": "Tell me about a project you're proud of.", "difficulty": "easy", "time_estimate": "5 min", "context": "Technical experience"},
        {"question": "How do you handle disagreements in a team?", "difficulty": "medium", "time_estimate": "5 min", "context": "Behavioral"},
    ],
}


def _generate_questions(job_skills: list) -> list[dict]:
    """Generate interview questions based on job skills."""
    questions = []
    order = 0
    seen_skills = set()

    for skill in (job_skills or []):
        if skill in seen_skills or skill not in _QUESTION_BANK:
            continue
        seen_skills.add(skill)
        for q in _QUESTION_BANK[skill][:2]:  # max 2 per skill
            questions.append({
                "id": str(uuid.uuid4()),
                "question": q["question"],
                "skill": skill,
                "difficulty": q["difficulty"],
                "time_estimate": q["time_estimate"],
                "context": q["context"],
                "sort_order": order,
            })
            order += 1

    # Fill with defaults if fewer than 5 questions
    if len(questions) < 5:
        for q in _QUESTION_BANK["default"]:
            questions.append({
                "id": str(uuid.uuid4()),
                "question": q["question"],
                "skill": "General",
                "difficulty": q["difficulty"],
                "time_estimate": q["time_estimate"],
                "context": q["context"],
                "sort_order": order,
            })
            order += 1

    return questions[:10]  # cap at 10 questions


# ---------------------------------------------------------------------------
# GET /api/evaluation/jobs
# ---------------------------------------------------------------------------

@evaluation_bp.get("/jobs")
@require_role(["recruiter", "company_admin", "admin", "super_admin"])
def list_eval_jobs():
    """Return published jobs belonging to the recruiter's company."""
    try:
        rr = supabase.table("recruiters").select("company_id").eq("id", g.user_id).maybe_single().execute()
        company_id = rr.data["company_id"] if rr.data else None
    except Exception:
        company_id = None

    try:
        query = supabase.table("jobs").select("id, title, department, status, skills, created_at").eq("status", "published")
        if company_id:
            query = query.eq("company_id", company_id)
        res = query.order("created_at", desc=True).execute()
    except Exception as exc:
        return _err("SERVER_ERROR", f"Failed to fetch jobs: {exc}", 500)

    return jsonify({"data": res.data or []})


# ---------------------------------------------------------------------------
# POST /api/evaluation/sessions
# ---------------------------------------------------------------------------

@evaluation_bp.post("/sessions")
@require_role(["recruiter", "company_admin", "admin", "super_admin"])
def create_session():
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    student_id = data.get("student_id")
    interview_type = data.get("interview_type", "technical")
    scheduled_at = data.get("scheduled_at")

    if not job_id or not student_id:
        return _err("VALIDATION_ERROR", "job_id and student_id are required", 400)

    session_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()

    try:
        supabase.table("evaluation_sessions").insert({
            "id": session_id,
            "job_id": job_id,
            "student_id": student_id,
            "recruiter_id": g.user_id,
            "interview_type": interview_type,
            "scheduled_at": scheduled_at,
            "status": "scheduled",
            "created_at": now,
            "updated_at": now,
        }).execute()
    except Exception as exc:
        return _err("SERVER_ERROR", f"Failed to create session: {exc}", 500)

    return jsonify({
        "data": {
            "session_id": session_id,
            "job_id": job_id,
            "student_id": student_id,
            "interview_type": interview_type,
            "status": "scheduled",
            "questions": [],
        }
    }), 201


# ---------------------------------------------------------------------------
# GET /api/evaluation/sessions/{session_id}/questions
# ---------------------------------------------------------------------------

@evaluation_bp.get("/sessions/<string:session_id>/questions")
@require_role(["recruiter", "company_admin", "admin", "super_admin"])
def get_questions(session_id: str):
    try:
        sr = supabase.table("evaluation_sessions").select("job_id, status").eq("id", session_id).maybe_single().execute()
    except Exception:
        return _err("NOT_FOUND", "Session not found", 404)
    if not sr.data:
        return _err("NOT_FOUND", "Session not found", 404)

    job_id = sr.data["job_id"]

    # Check if questions are already persisted
    try:
        existing = supabase.table("evaluation_questions").select("*").eq("session_id", session_id).order("sort_order").execute()
        if existing.data:
            return jsonify({
                "data": {
                    "session_id": session_id,
                    "questions": [
                        {
                            "id": q["id"],
                            "question": q["question_text"],
                            "skill": q["skill"],
                            "difficulty": q["difficulty"],
                            "time_estimate": q.get("time_estimate", "5 min"),
                            "context": q.get("context"),
                        }
                        for q in existing.data
                    ],
                }
            })
    except Exception:
        pass

    # Fetch job skills and generate questions
    job_skills = []
    try:
        jr = supabase.table("jobs").select("skills").eq("id", job_id).maybe_single().execute()
        if jr.data:
            job_skills = jr.data.get("skills") or []
    except Exception:
        pass

    questions = _generate_questions(job_skills)

    # Persist generated questions
    now = datetime.now(tz=timezone.utc).isoformat()
    try:
        supabase.table("evaluation_questions").insert([
            {
                "id": q["id"],
                "session_id": session_id,
                "question_text": q["question"],
                "skill": q["skill"],
                "difficulty": q["difficulty"],
                "time_estimate": q["time_estimate"],
                "context": q["context"],
                "sort_order": q["sort_order"],
                "created_at": now,
            }
            for q in questions
        ]).execute()
    except Exception:
        pass

    return jsonify({
        "data": {
            "session_id": session_id,
            "questions": [
                {
                    "id": q["id"],
                    "question": q["question"],
                    "skill": q["skill"],
                    "difficulty": q["difficulty"],
                    "time_estimate": q["time_estimate"],
                    "context": q["context"],
                }
                for q in questions
            ],
        }
    })


# ---------------------------------------------------------------------------
# POST /api/evaluation/sessions/{session_id}/scores
# ---------------------------------------------------------------------------

@evaluation_bp.post("/sessions/<string:session_id>/scores")
@require_role(["recruiter", "company_admin", "admin", "super_admin"])
def save_scores(session_id: str):
    try:
        sr = supabase.table("evaluation_sessions").select("job_id, student_id, status").eq("id", session_id).maybe_single().execute()
    except Exception:
        return _err("NOT_FOUND", "Session not found", 404)
    if not sr.data:
        return _err("NOT_FOUND", "Session not found", 404)

    data = request.get_json(silent=True) or {}
    scores = data.get("scores", [])
    overall_notes = data.get("overall_notes", "")
    recommendation = data.get("recommendation", "hold")

    if recommendation not in {"advance", "hold", "reject"}:
        return _err("VALIDATION_ERROR", "recommendation must be 'advance', 'hold', or 'reject'", 400)

    # Compute total score
    total = sum(s.get("score", 0) for s in scores)
    max_total = sum(s.get("max_score", 5) for s in scores)
    now = datetime.now(tz=timezone.utc).isoformat()

    # Upsert scores
    if scores:
        try:
            to_insert = [
                {
                    "session_id": session_id,
                    "question_id": s["question_id"],
                    "score": s.get("score", 0),
                    "max_score": s.get("max_score", 5),
                    "notes": s.get("notes", ""),
                    "dimension": s.get("dimension", "technical"),
                    "created_at": now,
                }
                for s in scores if s.get("question_id")
            ]
            if to_insert:
                supabase.table("evaluation_scores").upsert(
                    to_insert, on_conflict="session_id,question_id"
                ).execute()
        except Exception as exc:
            return _err("SERVER_ERROR", f"Failed to save scores: {exc}", 500)

    # Update session status
    try:
        supabase.table("evaluation_sessions").update({
            "status": "completed",
            "overall_notes": overall_notes,
            "recommendation": recommendation,
            "total_score": total,
            "max_score": max_total,
            "updated_at": now,
        }).eq("id", session_id).execute()
    except Exception as exc:
        return _err("SERVER_ERROR", f"Failed to update session: {exc}", 500)

    # If recommendation is 'advance', update application status
    if recommendation == "advance":
        try:
            supabase.table("applications").update({"status": "shortlisted"}).eq(
                "job_id", sr.data["job_id"]
            ).eq("student_id", sr.data["student_id"]).execute()
        except Exception:
            pass

    return jsonify({
        "data": {
            "session_id": session_id,
            "total_score": total,
            "max_score": max_total,
            "recommendation": recommendation,
            "saved_at": now,
        }
    }), 201


# ---------------------------------------------------------------------------
# GET /api/evaluation/sessions/{session_id}/summary
# ---------------------------------------------------------------------------

@evaluation_bp.get("/sessions/<string:session_id>/summary")
@require_role(["recruiter", "company_admin", "admin", "super_admin"])
def get_summary(session_id: str):
    try:
        sr = supabase.table("evaluation_sessions").select("*").eq("id", session_id).maybe_single().execute()
    except Exception:
        return _err("NOT_FOUND", "Session not found", 404)
    if not sr.data:
        return _err("NOT_FOUND", "Session not found", 404)

    session = sr.data

    # Fetch student name
    student_info = {"name": "Unknown", "school": "Unknown"}
    try:
        sp = supabase.table("profiles").select("full_name").eq("id", session["student_id"]).maybe_single().execute()
        if sp.data:
            student_info["name"] = sp.data.get("full_name", "Unknown")
    except Exception:
        pass

    # Fetch job title
    job_info = {"title": "Unknown", "department": "Unknown"}
    try:
        jp = supabase.table("jobs").select("title, department").eq("id", session["job_id"]).maybe_single().execute()
        if jp.data:
            job_info["title"] = jp.data.get("title", "Unknown")
            job_info["department"] = jp.data.get("department", "Unknown")
    except Exception:
        pass

    # Fetch scores by dimension
    technical_scores = []
    behavioral_scores = []
    try:
        sc_res = supabase.table("evaluation_scores").select("*").eq("session_id", session_id).execute()
        for sc in (sc_res.data or []):
            pct = (sc["score"] / sc["max_score"] * 100) if sc.get("max_score") else 0
            dim = sc.get("dimension", "technical")
            if dim == "behavioral":
                behavioral_scores.append(pct)
            else:
                technical_scores.append(pct)
    except Exception:
        pass

    technical_score = round(sum(technical_scores) / len(technical_scores)) if technical_scores else 0
    behavioral_score = round(sum(behavioral_scores) / len(behavioral_scores)) if behavioral_scores else 0
    total = session.get("total_score") or 0
    max_total = session.get("max_score") or 1
    overall = round((total / max_total) * 100) if max_total else 0
    jd_fit_score = round((technical_score + overall) / 2)

    recommendation = session.get("recommendation", "hold")
    strengths = []
    gaps = []
    if technical_score >= 80:
        strengths.append("Strong technical skills")
    if behavioral_score >= 80:
        strengths.append("Good communication and teamwork")
    if overall < 60:
        gaps.append("Needs improvement in core technical areas")
    if technical_score < 70:
        gaps.append("Limited technical depth in key skills")

    return jsonify({
        "data": {
            "session_id": session_id,
            "student": student_info,
            "job": job_info,
            "technical_score": technical_score,
            "behavioral_score": behavioral_score,
            "jd_fit_score": jd_fit_score,
            "overall": overall,
            "recommendation": recommendation,
            "strengths": strengths,
            "gaps": gaps,
            "notes": session.get("overall_notes", ""),
        }
    })
