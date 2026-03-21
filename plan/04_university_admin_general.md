# Module 4 — University Admin (General / Osaka University)
> Role token: `university`
> Persona: **Dr. Miyamoto K.** — Osaka University

---

## Overview

The General University Admin (role: `university`) represents a Japanese university
partner operating with a more strategic/partnership focus. Unlike the TN admin
(role: `university_admin`), this persona manages **company partnerships**,
views cross-platform analytics, browses the student directory visible to recruiters,
and explores the Companies and Universities portals. They do not own the verification
workflow — that is delegated to the `university_admin` role within their institution.

### Difference: `university` vs `university_admin`

| Capability | `university` (Osaka) | `university_admin` (TN / Anna Uni) |
|---|---|---|
| View students in own university | ✅ | ✅ |
| Verify student credentials | ❌ | ✅ |
| Manage departments | Read-only | Full CRUD |
| View company partnerships | ✅ | Read-only |
| Browse other universities | ✅ | ❌ |
| Send university announcements | ✅ | ✅ |
| Access Platform Admin | ❌ | ❌ |

### Pages served
| Frontend Route | Page Component |
|---|---|
| `/app/dashboard` | `Dashboard` → `UniversityDashboard` |
| `/app/students` | `StudentsDirectory` (own university only) |
| `/app/universities` | `UniversityPortal` |
| `/app/companies` | `CompanyPortal` (read-only) |
| `/app/analytics` | `AnalyticsDashboard` |
| `/app/messages` | `Messages` |

---

## 1. University Home Dashboard

### `GET /api/universities/me`
Same endpoint as Module 3 — returns Osaka University profile for the authenticated user.

**Response** (Osaka University context)
```json
{
  "data": {
    "id": "uuid",
    "name": "Osaka University",
    "name_jp": "大阪大学",
    "location": "Suita, Osaka, Japan",
    "established": "1931",
    "accreditation": "MEXT Approved",
    "logo_url": "...",
    "domain": "osaka-u.ac.jp",
    "world_ranking": 61,
    "total_students": 2840,
    "departments_count": 22,
    "partner_companies_count": 156,
    "international_partnerships": 12
  }
}
```

---

### `GET /api/analytics/university`
Returns university-level analytics. Same endpoint as Module 3, shared implementation.

**Osaka-specific additions in response:**
```json
{
  "data": {
    "placement_rate": 0.91,
    "total_students": 2840,
    "partner_companies": 156,
    "international_hires": 34,
    "average_ai_match_score": 86.4,
    "top_recruiting_companies": [
      { "company_name": "Sony", "hires": 28 },
      { "company_name": "Toyota", "hires": 22 },
      { "company_name": "SoftBank", "hires": 19 }
    ],
    "placement_trend": [
      { "month": "Sep", "placed": 189, "total": 210 }
    ],
    "pending_verifications": 7
  }
}
```

---

## 2. University Portal (Browse All Universities)

### `GET /api/universities`
Returns list of all universities on the platform.

**Auth rule:** `role IN ('university', 'recruiter', 'admin')`

**Query params**
| Param | Type | Notes |
|---|---|---|
| `page` | int | |
| `limit` | int | default 20 |
| `search` | string | name, location, domain |
| `country` | string | `Japan`, `India`, `all` |
| `sort` | string | `students`, `placement_rate`, `name` |

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "name": "Osaka University",
      "name_jp": "大阪大学",
      "location": "Suita, Osaka, Japan",
      "logo_url": "...",
      "total_students": 2840,
      "placement_rate": 0.91,
      "partner_companies_count": 156,
      "verification_badge": true
    }
  ],
  "meta": { "page": 1, "total": 240 }
}
```

---

### `GET /api/universities/{university_id}`
Returns public profile of a single university.

**Response**
```json
{
  "data": {
    "id": "uuid",
    "name": "Osaka University",
    "name_jp": "大阪大学",
    "location": "Suita, Osaka, Japan",
    "website": "https://osaka-u.ac.jp",
    "established": "1931",
    "accreditation": "MEXT Approved",
    "logo_url": "...",
    "total_students": 2840,
    "departments": [
      { "code": "CS", "name": "Computer Science", "students": 480 }
    ],
    "placement_rate": 0.91,
    "top_recruiters": [
      { "company_name": "Sony", "hires": 28 }
    ],
    "partner_companies_count": 156
  }
}
```

---

### `GET /api/universities/{university_id}/students`
Returns the student directory for a specific university.

**Auth rule:**
- `university` or `university_admin` — can view students in **any** partner university (read-only, limited fields)
- `recruiter` — verified students only

**Query params:** `page`, `limit`, `search`, `department`, `jp_level`, `verification_status`

**Response** (public-facing, limited fields)
```json
{
  "data": [
    {
      "id": "uuid",
      "name": "Aiko Yamada",
      "department": "CS M2",
      "skills": ["React", "ML", "Python"],
      "jp_level": "N3",
      "verified": true,
      "ai_score": 94,
      "graduation_year": 2026
    }
  ],
  "meta": { "page": 1, "total": 480 }
}
```

---

## 3. Company Portal (Read-only for University admins)

### `GET /api/companies`
Returns list of companies on the platform. University admins browse for partnership potential.

**Auth rule:** `role IN ('university', 'university_admin', 'recruiter', 'admin')`

**Query params**
| Param | Type | Notes |
|---|---|---|
| `page` | int | |
| `limit` | int | default 20 |
| `search` | string | company name, industry |
| `industry` | string | |
| `size` | string | `1-50`, `51-200`, `201-1000`, `1000+` |
| `sort` | string | `name`, `size`, `hires` |

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "name": "Toyota Motor Corporation",
      "name_jp": "トヨタ自動車株式会社",
      "logo_url": "...",
      "industry": "Automotive & Technology",
      "size": "10000+",
      "location": "Aichi, Japan",
      "active_jobs_count": 8,
      "total_hires_from_platform": 124,
      "partner_universities_count": 45
    }
  ],
  "meta": { "page": 1, "total": 890 }
}
```

---

### `GET /api/companies/{company_id}`
Returns public company profile.

**Response**
```json
{
  "data": {
    "id": "uuid",
    "name": "Toyota Motor Corporation",
    "name_jp": "トヨタ自動車株式会社",
    "logo_url": "...",
    "website": "https://toyota.com",
    "industry": "Automotive & Technology",
    "size": "10000+",
    "location": "Aichi, Japan",
    "description": "...",
    "active_jobs": [
      {
        "id": "uuid",
        "title": "ML Research Engineer",
        "location": "Aichi",
        "deadline": "2026-04-01"
      }
    ],
    "university_partnerships": [
      { "university_name": "Nagoya University", "hires": 24 }
    ]
  }
}
```

---

## 4. Partnership Management

### `GET /api/universities/me/partnerships`
Returns all company partnerships for this university.

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "company_id": "uuid",
      "company_name": "Sony Group Corporation",
      "company_logo": "...",
      "status": "active",
      "hires_this_year": 28,
      "established_at": "2020-04-01T00:00:00Z",
      "contact_person": "Sato Kenji",
      "contact_email": "sato@sony.com",
      "notes": "Preferred partner for AI/ML roles"
    }
  ],
  "meta": { "total": 156 }
}
```

---

### `POST /api/universities/me/partnerships`
Initiate a partnership request with a company.

**Auth rule:** `role IN ('university', 'university_admin')`

**Request body**
```json
{
  "company_id": "uuid",
  "message": "We would like to explore a campus recruitment partnership...",
  "proposed_roles": ["Software Engineer", "Data Analyst"]
}
```

**Business logic:**
1. Check if partnership already exists → return `422 ALREADY_PARTNERS`
2. Insert into `university_company_partnerships` table with `status = 'pending'`
3. Notify company admin via `notifications` table

**Response (201)**
```json
{
  "data": {
    "id": "uuid",
    "company_id": "uuid",
    "status": "pending",
    "requested_at": "..."
  }
}
```

---

### `PATCH /api/universities/me/partnerships/{partnership_id}`
Update partnership details or notes.

**Request body**
```json
{ "notes": "Updated partnership terms", "status": "active" }
```

**Valid status transitions:** `pending → active`, `active → paused`, `paused → active`, `active → terminated`

**Response (200)**
```json
{ "data": { "id": "uuid", "status": "active", "updated_at": "..." } }
```

---

## 5. Student Management (Read-only for `university` role)

### `GET /api/universities/me/students`
Same endpoint as Module 3 but `university` role gets read-only access — cannot call
verify/approve endpoints.

**Additional field in response for university role:**
```json
{ "can_verify": false }
```

---

## 6. Messages

### Uses the same `/api/messages/*` endpoints defined in Module 1.

University admins can message:
- Recruiters / company contacts they are partnered with
- Students in their own university
- Platform admins

---

## 7. Analytics — University View

### `GET /api/analytics/university/placement-by-company`
Returns a breakdown of placements by company, useful for partnership planning.

**Response**
```json
{
  "data": [
    { "company_name": "Sony", "hires": 28, "departments": ["CS", "EE"], "avg_package": null },
    { "company_name": "Toyota", "hires": 22, "departments": ["ME", "CS"], "avg_package": null }
  ]
}
```

---

### `GET /api/analytics/university/student-skills`
Returns aggregated skill distribution across the university's student body.

**Response**
```json
{
  "data": [
    { "skill": "Python", "count": 840, "verified_count": 620 },
    { "skill": "React", "count": 480, "verified_count": 310 },
    { "skill": "Machine Learning", "count": 360, "verified_count": 280 }
  ]
}
```

---

## Flask Blueprint: `app/routes/universities.py`

```python
from flask import Blueprint, jsonify, request, g
from app.middleware.auth import require_role
from app.services.university_service import (
    get_university_for_user, list_universities, get_university_students,
    get_partnerships, create_partnership
)

universities_bp = Blueprint("universities", __name__)

@universities_bp.get("/")
@require_role(["university", "university_admin", "recruiter", "admin"])
def list_all():
    params = {
        "search": request.args.get("search"),
        "country": request.args.get("country"),
        "page": int(request.args.get("page", 1)),
        "limit": int(request.args.get("limit", 20)),
    }
    return jsonify(list_universities(params))

@universities_bp.get("/me")
@require_role(["university", "university_admin"])
def get_my_university():
    uni = get_university_for_user(g.user_id)
    return jsonify({"data": uni})

@universities_bp.get("/me/partnerships")
@require_role(["university", "university_admin"])
def get_my_partnerships():
    return jsonify(get_partnerships(g.university_id))

@universities_bp.post("/me/partnerships")
@require_role(["university", "university_admin"])
def create_new_partnership():
    data = request.get_json()
    result = create_partnership(g.university_id, g.user_id, data)
    return jsonify({"data": result}), 201
```

---

## Error Cases to Handle

| Scenario | HTTP | Error Code |
|---|---|---|
| Partnership request already exists | 422 | `ALREADY_PARTNERS` |
| University not found | 404 | `UNIVERSITY_NOT_FOUND` |
| Attempting to verify students (wrong role) | 403 | `VERIFICATION_NOT_ALLOWED` |
| Invalid partnership status transition | 422 | `INVALID_STATUS_TRANSITION` |
| Message to non-partner company | 422 | `NOT_PARTNERS` |
