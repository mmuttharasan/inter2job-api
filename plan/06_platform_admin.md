# Module 6 — Platform Admin
> Role token: `admin`
> Persona: **Platform Admin** — System administration (super-admin)

---

## Overview

The Platform Admin has unrestricted access to all data and operations.
Their primary responsibilities are:
- **User management**: onboard/suspend/delete users across all roles
- **Platform health**: monitor KPIs, system status, API usage
- **Content moderation**: review flagged content, manage company/university approval
- **AI configuration**: set global matching weights and model parameters
- **Data export**: generate reports for compliance and business analysis

The Platform Admin accesses all Module 1–5 routes plus the dedicated `/api/admin/*` namespace.

### Pages served
| Frontend Route | Page Component |
|---|---|
| `/app/dashboard` | `Dashboard` → Admin overview |
| `/app/students` | `StudentsDirectory` (all, including unverified) |
| `/app/companies` | `CompanyPortal` |
| `/app/universities` | `UniversityPortal` |
| `/app/ai-matching` | `AIMatching` (cross-company) |
| `/app/analytics` | `AnalyticsDashboard` (platform-wide) |
| `/app/evaluation` | `Evaluation` |
| `/app/messages` | `Messages` |

---

## 1. Platform Statistics (public + admin)

### `GET /api/platform/stats`
**Public endpoint — no auth required.**
Used on the Landing page for marketing stats.

**Response**
```json
{
  "data": {
    "verified_students": 12400,
    "partner_companies": 890,
    "partner_universities": 240,
    "successful_placements": 4800,
    "last_updated": "2026-03-08T00:00:00Z"
  }
}
```

**Business logic:** Cache this response for 1 hour. Query counts from Supabase.

---

### `GET /api/admin/dashboard`
Returns comprehensive platform admin dashboard data.

**Auth rule:** `role = 'admin'`

**Response**
```json
{
  "data": {
    "users": {
      "total": 15840,
      "students": 12400,
      "recruiters": 1240,
      "company_admins": 890,
      "university_admins": 480,
      "universities": 240,
      "admins": 12,
      "new_this_week": 284,
      "new_this_month": 1102
    },
    "content": {
      "active_jobs": 342,
      "draft_jobs": 89,
      "applications_this_week": 2840,
      "ai_matches_this_week": 18400,
      "pending_verifications": 142,
      "flagged_content": 8
    },
    "system": {
      "api_requests_today": 284000,
      "error_rate": 0.002,
      "avg_response_ms": 142,
      "supabase_storage_gb": 48.2,
      "active_sessions": 1240
    },
    "growth": {
      "weekly_signups": [
        { "week": "W1", "students": 84, "companies": 12, "universities": 3 }
      ]
    }
  }
}
```

---

## 2. User Management

### `GET /api/admin/users`
Returns all users across all roles.

**Auth rule:** `role = 'admin'`

**Query params**
| Param | Type | Notes |
|---|---|---|
| `page` | int | |
| `limit` | int | default 50 |
| `search` | string | name, email |
| `role` | string | filter by role |
| `status` | string | `active`, `suspended`, `pending` |
| `university_id` | uuid | filter by university |
| `company_id` | uuid | filter by company |
| `sort` | string | `created_at`, `name`, `role` |

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "email": "aiko@osaka-u.ac.jp",
      "full_name": "Aiko Yamada",
      "role": "student",
      "status": "active",
      "university": "Osaka University",
      "company": null,
      "verification_status": "verified",
      "created_at": "2025-09-01T00:00:00Z",
      "last_sign_in_at": "2026-03-08T08:00:00Z"
    }
  ],
  "meta": { "page": 1, "total": 15840 }
}
```

---

### `GET /api/admin/users/{user_id}`
Returns full profile of any user.

**Response:** Full user data including auth metadata, profile, role-specific tables, activity log.

---

### `PATCH /api/admin/users/{user_id}/status`
Suspend or reactivate a user account.

**Auth rule:** `role = 'admin'` — cannot suspend another admin.

**Request body**
```json
{
  "status": "suspended",
  "reason": "Violation of terms of service — section 4.2",
  "notify_user": true
}
```

**Business logic:**
1. Validate target user is not `admin` role
2. Update Supabase Auth user `banned_until` (permanent = far future date)
3. Terminate all active sessions for the user
4. Insert into `admin_audit_log` table
5. If `notify_user = true`, send email notification

**Response (200)**
```json
{ "data": { "user_id": "uuid", "status": "suspended", "reason": "...", "suspended_at": "..." } }
```

---

### `PATCH /api/admin/users/{user_id}/role`
Change a user's role.

**Auth rule:** `role = 'admin'`

**Request body**
```json
{ "role": "university_admin", "reason": "Promoted to university admin" }
```

**Allowed role changes:**
- `student` ↔ any (with care — student → recruiter requires company assignment)
- `recruiter` ↔ `company_admin`
- `university` ↔ `university_admin`

**Business logic:**
1. Validate new role is valid
2. Update `profiles.role`
3. Create/update role-specific table record if needed
4. Invalidate existing JWT sessions (force re-login)
5. Log to `admin_audit_log`

**Response (200)**
```json
{ "data": { "user_id": "uuid", "old_role": "student", "new_role": "university_admin" } }
```

---

### `DELETE /api/admin/users/{user_id}`
Permanently delete a user account.

**Auth rule:** `role = 'admin'` — cannot delete another admin.

**Business logic:**
1. Check user is not the last admin
2. Soft-delete or hard-delete based on `permanent=true` query param
3. Cascade: delete profile, student/recruiter records, applications, messages
4. Remove from Supabase Auth
5. Log to `admin_audit_log`

**Response (204)**

---

## 3. Company & University Approval

### `GET /api/admin/companies/pending`
Returns companies awaiting platform approval.

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "name": "NewTech Corp",
      "industry": "Technology",
      "size": "51-200",
      "contact_name": "Tanaka Hiroshi",
      "contact_email": "tanaka@newtech.co.jp",
      "submitted_at": "2026-03-07T09:00:00Z",
      "documents": ["Business_License.pdf"]
    }
  ]
}
```

---

### `POST /api/admin/companies/{company_id}/approve`
Approve a company registration.

**Request body**
```json
{ "note": "Verified business registration documents." }
```

**Business logic:**
1. Set company `status = 'approved'`
2. Notify company admin via email
3. Log to audit log

**Response (200)**
```json
{ "data": { "company_id": "uuid", "status": "approved" } }
```

---

### `POST /api/admin/companies/{company_id}/reject`
Reject a company registration.

**Request body**
```json
{ "reason": "Incomplete documentation", "note": "Please resubmit with valid business license." }
```

**Response (200)**
```json
{ "data": { "company_id": "uuid", "status": "rejected", "reason": "..." } }
```

---

### `GET /api/admin/universities/pending`
Same pattern — returns universities awaiting platform approval.

### `POST /api/admin/universities/{university_id}/approve`
### `POST /api/admin/universities/{university_id}/reject`
Same pattern as company approval/rejection.

---

## 4. Content Moderation

### `GET /api/admin/flags`
Returns all flagged content (jobs, profiles, messages).

**Query params:** `type=job|profile|message`, `status=open|resolved`, `page`, `limit`

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "type": "job",
      "content_id": "uuid",
      "content_preview": "Senior Engineer — suspicious requirements...",
      "flagged_by": "uuid",
      "reason": "misleading_requirements",
      "status": "open",
      "created_at": "..."
    }
  ]
}
```

---

### `POST /api/admin/flags/{flag_id}/resolve`
Resolve a content flag.

**Request body**
```json
{
  "action": "remove_content",
  "note": "Job posting contained misleading salary information."
}
```

**Actions:** `dismiss`, `remove_content`, `suspend_author`, `escalate`

**Business logic:**
- `remove_content`: sets the content's status to `archived`/`deleted`
- `suspend_author`: calls the user suspend endpoint internally
- Both: update flag `status = 'resolved'`, log to audit

**Response (200)**
```json
{ "data": { "flag_id": "uuid", "action": "remove_content", "resolved_at": "..." } }
```

---

## 5. AI Matching Configuration

### `GET /api/admin/ai-config`
Returns global AI matching configuration.

**Response**
```json
{
  "data": {
    "default_weights": {
      "skill_alignment": 40,
      "research_similarity": 25,
      "language_readiness": 20,
      "learning_trajectory": 15
    },
    "min_score_threshold": 60,
    "max_candidates_per_run": 5000,
    "model_version": "intern2job-match-v2",
    "updated_at": "2026-01-15T00:00:00Z",
    "updated_by": "uuid"
  }
}
```

---

### `PUT /api/admin/ai-config`
Update global AI configuration.

**Auth rule:** `role = 'admin'`

**Request body**
```json
{
  "default_weights": {
    "skill_alignment": 35,
    "research_similarity": 30,
    "language_readiness": 20,
    "learning_trajectory": 15
  },
  "min_score_threshold": 65
}
```

**Validation:** `default_weights` values must sum to 100.

**Business logic:**
1. Validate weights
2. Update `ai_config` table
3. Log change to audit log with before/after values

**Response (200)**
```json
{ "data": { "updated_at": "...", "updated_by": "uuid" } }
```

---

## 6. Platform Analytics

### `GET /api/analytics/platform`
Returns platform-wide analytics for the admin dashboard.

**Query params:** `period=7d|30d|90d|ytd|all`

**Auth rule:** `role = 'admin'`

**Response**
```json
{
  "data": {
    "user_growth": [
      { "date": "2026-03-01", "students": 12200, "companies": 880, "universities": 238 }
    ],
    "matching_activity": [
      { "date": "2026-03-01", "runs": 84, "candidates_analyzed": 240000, "shortlists": 1240 }
    ],
    "verification_throughput": [
      { "date": "2026-03-01", "submitted": 48, "approved": 42, "rejected": 6 }
    ],
    "top_universities_by_placement": [
      { "university": "Osaka University", "placement_rate": 0.91, "placements": 258 }
    ],
    "top_companies_by_hires": [
      { "company": "Sony Group", "hires": 124 }
    ],
    "api_performance": {
      "avg_response_ms": 142,
      "p95_response_ms": 380,
      "error_rate": 0.002,
      "requests_today": 284000
    }
  }
}
```

---

## 7. Data Export

### `POST /api/admin/exports`
Trigger a data export job.

**Auth rule:** `role = 'admin'`

**Request body**
```json
{
  "type": "students",
  "filters": {
    "university_id": null,
    "verification_status": "verified",
    "graduation_year": 2026
  },
  "format": "csv",
  "notify_email": "admin@intern2job.com"
}
```

**Export types:** `students`, `companies`, `jobs`, `applications`, `verifications`, `analytics`

**Business logic:**
1. Validate export type and filters
2. Enqueue background export job
3. On completion, upload CSV/JSON to Supabase Storage (admin bucket)
4. Send download link to `notify_email`

**Response (202)**
```json
{ "data": { "export_id": "uuid", "status": "queued", "estimated_rows": 12400 } }
```

---

### `GET /api/admin/exports/{export_id}`
Check export status and get download link.

**Response**
```json
{
  "data": {
    "export_id": "uuid",
    "status": "complete",
    "rows_exported": 12387,
    "download_url": "https://supabase.storage/.../export.csv",
    "expires_at": "2026-03-09T12:00:00Z"
  }
}
```

---

## 8. Audit Log

### `GET /api/admin/audit-log`
Returns chronological audit log of all admin actions.

**Query params:** `page`, `limit`, `action_type`, `actor_id`, `from_date`, `to_date`

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "actor_id": "uuid",
      "actor_name": "Platform Admin",
      "action": "user.suspend",
      "target_id": "uuid",
      "target_type": "user",
      "metadata": { "reason": "ToS violation", "old_status": "active" },
      "ip_address": "203.0.113.42",
      "created_at": "2026-03-08T14:00:00Z"
    }
  ],
  "meta": { "page": 1, "total": 4820 }
}
```

---

## Flask Blueprint: `app/routes/admin.py`

```python
from flask import Blueprint, jsonify, request, g
from app.middleware.auth import require_role
from app.services.admin_service import (
    get_admin_dashboard, list_users, update_user_status,
    approve_company, reject_company, get_audit_log
)

admin_bp = Blueprint("admin", __name__)

@admin_bp.get("/dashboard")
@require_role(["admin"])
def dashboard():
    return jsonify({"data": get_admin_dashboard()})

@admin_bp.get("/users")
@require_role(["admin"])
def list_all_users():
    params = {
        "page": int(request.args.get("page", 1)),
        "limit": int(request.args.get("limit", 50)),
        "search": request.args.get("search"),
        "role": request.args.get("role"),
        "status": request.args.get("status"),
    }
    return jsonify(list_users(params))

@admin_bp.patch("/users/<user_id>/status")
@require_role(["admin"])
def suspend_user(user_id):
    data = request.get_json()
    if not data.get("status") or not data.get("reason"):
        return jsonify({"error": {"code": "MISSING_FIELDS"}}), 400
    result = update_user_status(user_id, g.user_id, data)
    return jsonify({"data": result})

@admin_bp.get("/audit-log")
@require_role(["admin"])
def audit_log():
    params = { "page": int(request.args.get("page", 1)), "limit": int(request.args.get("limit", 50)) }
    return jsonify(get_audit_log(params))
```

---

## Auth Middleware (`app/middleware/auth.py`)

```python
from functools import wraps
from flask import request, jsonify, g
from app.services.supabase_client import supabase

def require_role(allowed_roles: list[str]):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return jsonify({"error": {"code": "UNAUTHORIZED", "message": "Token required"}}), 401

            token = auth_header.split(" ")[1]
            try:
                user = supabase.auth.get_user(token)
                if not user or not user.user:
                    raise Exception("Invalid token")
            except Exception:
                return jsonify({"error": {"code": "INVALID_TOKEN"}}), 401

            # Fetch role from profiles table
            profile = supabase.table("profiles").select("role, university_id").eq("id", user.user.id).single()

            g.user_id = user.user.id
            g.role = profile.data["role"]
            g.university_id = profile.data.get("university_id")

            if g.role not in allowed_roles:
                return jsonify({"error": {"code": "FORBIDDEN", "message": f"Role '{g.role}' is not authorized"}}), 403

            return f(*args, **kwargs)
        return decorated
    return decorator
```

---

## Error Cases to Handle

| Scenario | HTTP | Error Code |
|---|---|---|
| Admin tries to suspend another admin | 403 | `CANNOT_SUSPEND_ADMIN` |
| Admin tries to delete last admin | 422 | `LAST_ADMIN` |
| AI weights don't sum to 100 | 400 | `INVALID_WEIGHTS` |
| Export type not supported | 400 | `INVALID_EXPORT_TYPE` |
| User already suspended | 422 | `ALREADY_SUSPENDED` |
| Role change to invalid role | 400 | `INVALID_ROLE` |
| Flag already resolved | 422 | `ALREADY_RESOLVED` |
| Company already approved | 422 | `ALREADY_APPROVED` |
