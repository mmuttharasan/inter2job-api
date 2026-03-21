# Module 1 — Company Recruiter
> Role token: `recruiter`
> Persona: **Sarah Richards** — 3-panel RecruiterWorkspace

---

## Overview

The Company Recruiter operates the platform's core hiring workflow:
they browse verified students, configure and run AI matching against open JDs,
evaluate shortlisted candidates in structured interviews, and communicate via messages.

### Pages served
| Frontend Route | Page Component |
|---|---|
| `/app/dashboard` | `RecruiterWorkspace` (3-panel layout) |
| `/app/students` | `StudentsDirectory` |
| `/app/students/:id` | `StudentProfile` |
| `/app/ai-matching` | `AIMatching` (setup → processing → results) |
| `/app/evaluation` | `Evaluation` |
| `/app/messages` | `Messages` |
| `/app/analytics` | `AnalyticsDashboard` |

---

## 1. Students Directory

### `GET /api/students`
Returns paginated list of **verified** students visible to recruiters.

**Query params**
| Param | Type | Default | Notes |
|---|---|---|---|
| `page` | int | 1 | |
| `limit` | int | 20 | max 100 |
| `search` | string | — | matches name, school, skill |
| `jp_level` | string | — | `N1`, `N2`, `N3`, `N4`, `N5` |
| `university_id` | uuid | — | filter by university |
| `sort` | string | `score` | `score`, `gpa`, `name` |
| `order` | string | `desc` | `asc`, `desc` |
| `status` | string | `active` | `active`, `available`, `all` |

**Auth rule:** `role IN ('recruiter', 'admin')` AND student `verification_status = 'verified'`

**Supabase query (pseudocode)**
```python
query = supabase.table("students")
    .select("id, profiles(full_name, avatar_url), university_id, department, gpa, skills, verification_status, graduation_year")
    .eq("verification_status", "verified")
    .ilike("profiles.full_name", f"%{search}%")   # if search
    .eq("jp_level", jp_level)                       # if jp_level
    .order(sort, ascending=(order == "asc"))
    .range((page-1)*limit, page*limit - 1)
```

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "name": "Aiko Yamada",
      "initials": "AY",
      "school": "Osaka University",
      "department": "CS M2",
      "gpa": "3.9",
      "skills": ["React", "ML", "Python"],
      "jp_level": "N3",
      "verified": true,
      "ai_score": 94,
      "status": "Active",
      "graduation_year": 2026
    }
  ],
  "meta": { "page": 1, "limit": 20, "total": 847 }
}
```

---

### `GET /api/students/{student_id}`
Returns full public profile of a single verified student.

**Auth rule:** student must have `verification_status = 'verified'` OR requester is `admin`.

**Response**
```json
{
  "data": {
    "id": "uuid",
    "name": "Aiko Yamada",
    "avatar_url": null,
    "school": "Osaka University",
    "department": "CS M2",
    "gpa": "3.9",
    "graduation_year": 2026,
    "bio": "...",
    "skills": [
      { "name": "React", "level": 90, "verified": true }
    ],
    "experiences": [
      { "title": "Software Intern", "company": "SoftBank", "duration": "3 months" }
    ],
    "research_title": "Deep Learning for NLP in Japanese Text Processing",
    "jp_level": "N3",
    "badges": ["Top Performer", "Research Star"],
    "resume_url": "https://supabase.storage/..."
  }
}
```

---

## 2. AI Matching Engine

### `GET /api/jobs?status=published&owned_by_company=true`
Returns the list of active JDs the recruiter can run matching against.
(Reuses the Jobs route from Module 2 — filtered to recruiter's company.)

---

### `POST /api/matching/run`
Triggers an AI matching job. Async — returns a `job_id` immediately.

**Auth rule:** `role IN ('recruiter', 'company_admin', 'admin')`

**Request body**
```json
{
  "job_id": "uuid",
  "config": {
    "university_filter": "all",
    "graduation_years": [2025, 2026],
    "min_score": 70,
    "min_jp_level": "N2",
    "weights": {
      "skill_alignment": 40,
      "research_similarity": 25,
      "language_readiness": 20,
      "learning_trajectory": 15
    }
  }
}
```

**Business logic**
1. Validate `weights` sum to 100
2. Fetch all verified students matching `graduation_years` + `min_jp_level`
3. For each student, compute composite score:
   ```
   score = (skill_alignment * w1 + research_similarity * w2 +
            language_readiness * w3 + learning_trajectory * w4)
   ```
4. Store results in `ai_match_results` table
5. Return async `run_id`

**Response (202 Accepted)**
```json
{
  "data": {
    "run_id": "uuid",
    "status": "processing",
    "estimated_seconds": 8,
    "poll_url": "/api/matching/runs/uuid/status"
  }
}
```

---

### `GET /api/matching/runs/{run_id}/status`
Poll for matching job status.

**Response**
```json
{
  "data": {
    "run_id": "uuid",
    "status": "complete",
    "progress": 100,
    "steps_complete": ["skill_alignment", "research_similarity", "language_readiness", "learning_trajectory", "ranking"],
    "result_url": "/api/matching/results/uuid"
  }
}
```

---

### `GET /api/matching/results/{run_id}`
Returns ranked candidates with explainability data.

**Query params:** `filter=all|no_constraints|shortlisted`, `sort=score|skill|lang`, `page`, `limit`

**Response**
```json
{
  "data": {
    "run_id": "uuid",
    "job_id": "uuid",
    "job_title": "Senior Frontend Engineer",
    "total_analyzed": 2847,
    "candidates": [
      {
        "rank": 1,
        "student_id": "uuid",
        "name": "Aiko Yamada",
        "school": "Osaka University",
        "department": "CS M2",
        "score": 94,
        "skill_match": 96,
        "research_sim": 91,
        "lang_readiness": 82,
        "learning_traj": 98,
        "skills": ["React", "TypeScript", "Machine Learning"],
        "research_title": "Deep Learning for NLP...",
        "jp_level": "N3 → N2 (4mo)",
        "status": "Top Match",
        "flag": null,
        "constraint": null,
        "explanation": {
          "summary": "Strong skill alignment...",
          "skill_notes": "...",
          "research_notes": "...",
          "language_notes": "..."
        }
      }
    ],
    "shortlisted_ids": []
  },
  "meta": { "page": 1, "total": 5 }
}
```

---

### `POST /api/matching/results/{run_id}/shortlist`
Add or remove a candidate from the shortlist for this run.

**Request body**
```json
{ "student_id": "uuid", "action": "add" }
```

**Business logic:** Upserts into `applications` table with `status = 'shortlisted'`.

**Response (200)**
```json
{ "data": { "shortlisted_ids": ["uuid1", "uuid2"] } }
```

---

### `GET /api/matching/results/{run_id}/candidates/{student_id}/explain`
Returns detailed AI explainability report for one candidate.

**Response**
```json
{
  "data": {
    "student_id": "uuid",
    "job_id": "uuid",
    "overall_score": 94,
    "dimensions": {
      "skill_alignment": { "score": 96, "matched_skills": ["React", "TypeScript"], "missing_skills": [] },
      "research_similarity": { "score": 91, "research_title": "...", "relevance_tags": ["NLP", "ML"] },
      "language_readiness": { "score": 82, "current_level": "N3", "target_level": "N2", "months_to_target": 4 },
      "learning_trajectory": { "score": 98, "trend": "accelerating", "recent_certifications": 2 }
    },
    "constraint": null,
    "recommendation": "Top Match — no blockers"
  }
}
```

---

## 3. Evaluation

### `GET /api/evaluation/jobs`
Returns list of JDs available for evaluation sessions.

**Response:** Same shape as `GET /api/jobs` but filtered to `status=published`.

---

### `POST /api/evaluation/sessions`
Create a new evaluation session (links an evaluator, a JD, and a candidate).

**Auth rule:** `role IN ('recruiter', 'company_admin', 'admin')`

**Request body**
```json
{
  "job_id": "uuid",
  "student_id": "uuid",
  "interview_type": "technical",
  "scheduled_at": "2026-03-15T10:00:00Z"
}
```

**Response (201)**
```json
{
  "data": {
    "session_id": "uuid",
    "job_id": "uuid",
    "student_id": "uuid",
    "interview_type": "technical",
    "status": "scheduled",
    "questions": []
  }
}
```

---

### `GET /api/evaluation/sessions/{session_id}/questions`
Returns AI-generated interview questions for the session's JD.

**Business logic:**
- Fetch JD required skills
- Group questions by skill and difficulty (`easy`, `medium`, `hard`)
- Return curated list (Claude API call for AI generation)

**Response**
```json
{
  "data": {
    "session_id": "uuid",
    "questions": [
      {
        "id": "q-uuid",
        "question": "Explain the difference between controlled and uncontrolled components in React.",
        "skill": "React",
        "difficulty": "medium",
        "time_estimate": "5 min",
        "context": "Assess core React knowledge"
      }
    ]
  }
}
```

---

### `POST /api/evaluation/sessions/{session_id}/scores`
Save evaluation scores for a session.

**Request body**
```json
{
  "scores": [
    {
      "question_id": "q-uuid",
      "score": 4,
      "max_score": 5,
      "notes": "Demonstrated good understanding...",
      "dimension": "technical"
    }
  ],
  "overall_notes": "Strong candidate overall.",
  "recommendation": "advance"
}
```

**Business logic:**
1. Validate all question_ids belong to this session
2. Calculate total score
3. Update `applications.status` if `recommendation = 'advance'`
4. Save to `evaluations` table

**Response (201)**
```json
{
  "data": {
    "session_id": "uuid",
    "total_score": 82,
    "max_score": 100,
    "recommendation": "advance",
    "saved_at": "2026-03-08T12:00:00Z"
  }
}
```

---

### `GET /api/evaluation/sessions/{session_id}/summary`
Returns full evaluation summary with JD-fit analysis.

**Response**
```json
{
  "data": {
    "session_id": "uuid",
    "student": { "name": "Aiko Yamada", "school": "..." },
    "job": { "title": "Frontend Engineer", "department": "..." },
    "technical_score": 82,
    "behavioral_score": 76,
    "jd_fit_score": 88,
    "overall": 82,
    "recommendation": "advance",
    "strengths": ["React expertise", "Clear communicator"],
    "gaps": ["Limited backend experience"],
    "notes": "..."
  }
}
```

---

## 4. Messages

### `GET /api/messages/conversations`
Returns all conversations for the authenticated user.

**Auth rule:** Any authenticated role.

**Response**
```json
{
  "data": [
    {
      "conversation_id": "uuid",
      "with": { "id": "uuid", "name": "Aiko Yamada", "role": "student" },
      "last_message": "Looking forward to the interview...",
      "last_message_at": "2026-03-08T10:00:00Z",
      "unread_count": 2
    }
  ]
}
```

---

### `GET /api/messages/conversations/{conversation_id}`
Returns message thread for a conversation.

**Query params:** `page=1&limit=50`

**Response**
```json
{
  "data": {
    "conversation_id": "uuid",
    "messages": [
      {
        "id": "uuid",
        "sender_id": "uuid",
        "body": "Hello, I wanted to follow up...",
        "created_at": "2026-03-08T09:00:00Z",
        "read_at": null
      }
    ]
  },
  "meta": { "page": 1, "total": 24 }
}
```

---

### `POST /api/messages`
Send a message.

**Request body**
```json
{
  "receiver_id": "uuid",
  "body": "Hello, I wanted to reach out about your application."
}
```

**Business logic:**
1. Validate `receiver_id` exists and is reachable (not blocked)
2. Insert into `messages` table
3. Trigger Supabase Realtime broadcast

**Response (201)**
```json
{
  "data": {
    "id": "uuid",
    "sender_id": "uuid",
    "receiver_id": "uuid",
    "body": "...",
    "created_at": "2026-03-08T12:00:00Z"
  }
}
```

---

### `PATCH /api/messages/conversations/{conversation_id}/read`
Mark all messages in a conversation as read.

**Response (200)**
```json
{ "data": { "marked_read": 2 } }
```

---

## 5. Analytics (Recruiter view)

### `GET /api/analytics/recruiter`
Returns recruiter-specific metrics.

**Response**
```json
{
  "data": {
    "active_jds": 4,
    "total_matches_this_week": 47,
    "shortlisted_total": 23,
    "interviews_scheduled": 8,
    "placement_rate": 0.72,
    "top_skill_matches": [
      { "skill": "React", "match_count": 120 },
      { "skill": "Python", "match_count": 98 }
    ],
    "monthly_pipeline": [
      { "month": "Sep", "applications": 142, "shortlisted": 28, "hired": 12 }
    ]
  }
}
```

---

## Flask Blueprint: `app/routes/matching.py`

```python
from flask import Blueprint, jsonify, request
from app.middleware.auth import require_role
from app.services.matching_service import run_matching, get_results, shortlist_candidate

matching_bp = Blueprint("matching", __name__)

@matching_bp.post("/run")
@require_role(["recruiter", "company_admin", "admin"])
def trigger_match():
    data = request.get_json()
    # validate weights sum to 100
    weights = data.get("config", {}).get("weights", {})
    if sum(weights.values()) != 100:
        return jsonify({"error": {"code": "INVALID_WEIGHTS", "message": "Weights must sum to 100"}}), 400
    result = run_matching(data["job_id"], data["config"])
    return jsonify({"data": result}), 202

@matching_bp.get("/runs/<run_id>/status")
@require_role(["recruiter", "company_admin", "admin"])
def run_status(run_id):
    ...

@matching_bp.get("/results/<run_id>")
@require_role(["recruiter", "company_admin", "admin"])
def get_match_results(run_id):
    ...

@matching_bp.post("/results/<run_id>/shortlist")
@require_role(["recruiter", "company_admin", "admin"])
def update_shortlist(run_id):
    ...
```

---

## Error Cases to Handle

| Scenario | HTTP | Error Code |
|---|---|---|
| Recruiter accesses unverified student | 403 | `STUDENT_NOT_VERIFIED` |
| Weights don't sum to 100 | 400 | `INVALID_WEIGHTS` |
| Run ID not found | 404 | `RUN_NOT_FOUND` |
| Matching run still in progress | 202 | `PROCESSING` |
| Student profile is private | 403 | `PROFILE_PRIVATE` |
| Message to blocked user | 422 | `USER_BLOCKED` |
