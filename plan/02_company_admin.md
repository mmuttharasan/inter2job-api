# Module 2 — Company Admin
> Role token: `company_admin`
> Persona: **Sato Kenji** — Full company portal (Japan-based: Sony Group)

> **Last synced with frontend:** 2026-03-11
> **Port note:** Middleware runs on `8000` (`run.py`). Frontend `VITE_API_URL` must be `http://localhost:8000`.
> **DB note:** Migration `005_company_admin_extended.sql` adds columns required by this module. Apply it before using these endpoints.

---

## Overview

The Company Admin manages the full hiring lifecycle for their organisation:
company profile, job posting creation and management (JD Lifecycle), AI matching
results per JD, candidate shortlisting, side-by-side comparison, and a shortlist
workspace. They also have access to hiring analytics and a company landing page builder.

### Pages served
| Frontend Route | Page Component |
|---|---|
| `/app/company/dashboard` | `CompanyDashboard` |
| `/app/company/profile` | `CompanyProfileEditor` |
| `/app/company/landing-page` | `LandingPageBuilder` |
| `/app/company/job-creation` | `JobCreationWizard` |
| `/app/company/jd-lifecycle` | `JDLifecycleView` |
| `/app/company/jd-lifecycle/:id` | `JDLifecycleView` (single JD) |
| `/app/company/ai-matching/:id` | `AIMatchingResults` |
| `/app/company/compare` | `CandidateCompareView` |
| `/app/company/shortlist` | `ShortlistWorkspace` |
| `/app/evaluation` | `Evaluation` |
| `/app/analytics` | `AnalyticsDashboard` |
| `/app/messages` | `Messages` |

---

## 1. Company Profile

### `GET /api/companies/me`
Returns the company profile belonging to the authenticated `company_admin`.

**Auth rule:** `role = 'company_admin'` — returns only their own company.

**Supabase query**
```python
recruiter = supabase.table("recruiters").select("company_id").eq("id", user_id).single()
company = supabase.table("companies").select("*").eq("id", recruiter["company_id"]).single()
```

**Frontend fields used by `CompanyProfileEditor.tsx`:**
- `nameEn` → mapped from `name`
- `nameJp` → mapped from `name_jp` *(extended schema)*
- `tagline` *(extended schema)*
- `industry` (dropdown: Technology & Electronics, Automotive, etc.)
- `companySize` → mapped from `size` (dropdown: "1-50 employees" … "10,000+ employees")
- `founded` → mapped from `founded_year` *(extended schema)*
- `headquarters` → mapped from `location` *(extended schema)*
- `website`
- `description`, `mission`, `culture` *(extended schema)*
- `values[]`, `benefits[]` *(extended schema)*

**Response**
```json
{
  "data": {
    "id": "uuid",
    "name": "Sony Group Corporation",
    "name_jp": "ソニーグループ株式会社",
    "tagline": "Inspiring the world with creativity and technology",
    "logo_url": "https://...",
    "website": "https://sony.com",
    "industry": "Technology & Electronics",
    "size": "10,000+ employees",
    "location": "Tokyo, Japan",
    "description": "...",
    "mission": "...",
    "culture": "...",
    "values": ["Innovation", "Creativity"],
    "benefits": ["Competitive salary", "Health insurance"],
    "founded_year": 1946,
    "created_at": "2025-01-01T00:00:00Z",
    "updated_at": "2025-01-01T00:00:00Z"
  }
}
```

---

### `PUT /api/companies/me`
Update company profile.

**Auth rule:** `role = 'company_admin'` — can only update their own company.

**Request body** (all fields optional on update)
```json
{
  "name": "Sony Group Corporation",
  "name_jp": "ソニーグループ株式会社",
  "tagline": "Inspiring the world with creativity and technology",
  "website": "https://sony.com",
  "industry": "Technology & Electronics",
  "size": "10,000+ employees",
  "location": "Tokyo, Japan",
  "description": "Updated description...",
  "mission": "To fill the world with emotion...",
  "culture": "A culture of innovation...",
  "values": ["Innovation", "Creativity", "Quality"],
  "benefits": ["Competitive salary", "Health insurance"],
  "founded_year": 1946
}
```

**Business logic:**
1. Look up `company_id` from `recruiters` for this user
2. Validate fields (name required, website valid URL)
3. Update `companies` table

**Response (200)**
```json
{ "data": { "id": "uuid", "name": "Sony Group Corporation", "updated_at": "..." } }
```

---

### `POST /api/companies/me/logo`
Upload company logo to Supabase Storage.

**Request:** `multipart/form-data` with field `file` (PNG/JPG, max 2MB)

**Business logic:**
1. Validate file type and size
2. Upload to `logos` bucket: `logos/{company_id}/logo.{ext}`
3. Update `companies.logo_url`

**Response (200)**
```json
{ "data": { "logo_url": "https://supabase.storage/.../logo.png" } }
```

---

## 2. Job Postings (JD Lifecycle)

### `GET /api/jobs`
Returns all jobs for the authenticated company.

**Query params**
| Param | Type | Default |
|---|---|---|
| `status` | string | `all` — `draft`, `published`, `closed`, `archived` |
| `page` | int | 1 |
| `limit` | int | 20 |
| `sort` | string | `created_at` |
| `order` | string | `desc` |

**Auth rule:** `role IN ('company_admin', 'recruiter')` — scoped to their `company_id`.

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "title": "Senior AI Research Engineer",
      "department": "R&D Division - AI Lab",
      "location": "Tokyo",
      "status": "published",
      "priority": "high",
      "deadline": "2026-03-15",
      "applications_count": 89,
      "ai_matches_count": 23,
      "posted_days_ago": 5,
      "created_at": "..."
    }
  ],
  "meta": { "page": 1, "total": 12 }
}
```

---

### `GET /api/jobs/{job_id}`
Returns full detail of a single job.

**Response**
```json
{
  "data": {
    "id": "uuid",
    "company_id": "uuid",
    "recruiter_id": "uuid",
    "title": "Senior AI Research Engineer",
    "department": "R&D Division - AI Lab",
    "description": "...",
    "responsibilities": ["Lead AI research projects", "..."],
    "qualifications": ["PhD or M.S. in CS or related", "..."],
    "skills": ["Python", "PyTorch", "Research"],
    "benefits": ["Stock options", "Remote-friendly"],
    "location": "Tokyo",
    "is_remote": false,
    "employment_type": "Full-time",
    "experience_level": "Senior",
    "salary_min": 8000000,
    "salary_max": 12000000,
    "openings": 2,
    "deadline": "2026-03-15",
    "required_language": "Japanese (Business Level)",
    "ai_matching_enabled": true,
    "target_universities": ["uuid1", "uuid2"],
    "status": "published",
    "applications_count": 89,
    "ai_matches_count": 23,
    "created_at": "..."
  }
}
```

---

### `POST /api/jobs`
Create a new job posting.

**Auth rule:** `role IN ('company_admin', 'recruiter')`

**Request body**
```json
{
  "title": "Senior AI Research Engineer",
  "department": "R&D Division - AI Lab",
  "description": "...",
  "responsibilities": ["Lead AI research projects"],
  "qualifications": ["PhD or M.S."],
  "skills": ["Python", "PyTorch"],
  "benefits": ["Stock options"],
  "location": "Tokyo, Japan",
  "is_remote": false,
  "employment_type": "Full-time",
  "experience_level": "Senior",
  "salary_min": 8000000,
  "salary_max": 12000000,
  "openings": 2,
  "deadline": "2026-03-15",
  "required_language": "Japanese (Business Level)",
  "ai_matching_enabled": true,
  "target_universities": [],
  "status": "draft"
}
```

**Validation rules**
- `title` required, max 200 chars
- `skills` array required, min 1 item
- `salary_min` < `salary_max`
- `deadline` must be in the future
- `status` must be `draft` or `published` on creation

**Business logic:**
1. Validate request
2. Attach `company_id` and `recruiter_id` from auth context
3. Insert into `jobs` table
4. If `ai_matching_enabled = true` and `status = 'published'`, enqueue background AI matching run

**Response (201)**
```json
{ "data": { "id": "uuid", "title": "Senior AI Research Engineer", "status": "draft" } }
```

---

### `PUT /api/jobs/{job_id}`
Update job posting.

**Auth rule:** Only owner recruiter or company_admin of same company.

**Business logic:**
1. Verify ownership
2. Cannot publish a `closed` or `archived` job
3. If changing `status` to `published`, validate all required fields are filled

**Response (200)**
```json
{ "data": { "id": "uuid", "status": "published", "updated_at": "..." } }
```

---

### `PATCH /api/jobs/{job_id}/status`
Change job status only. Lighter endpoint for lifecycle status updates.

**Request body**
```json
{ "status": "closed" }
```

**Valid transitions:**
```
draft → published
published → closed
closed → archived
draft → archived
```

**Response (200)**
```json
{ "data": { "id": "uuid", "status": "closed", "closed_at": "..." } }
```

---

### `DELETE /api/jobs/{job_id}`
Soft-delete (archive) a job.

**Auth rule:** Company admin of same company only.

**Response (204)**

---

## 3. Applications per Job

### `GET /api/jobs/{job_id}/applications`
Returns all applications for a job.

**Query params:** `status=pending|shortlisted|rejected|offered|accepted`, `page`, `limit`

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "student_id": "uuid",
      "student_name": "Aiko Yamada",
      "student_school": "Osaka University",
      "status": "shortlisted",
      "ai_score": 94,
      "applied_at": "2026-02-10T08:00:00Z",
      "updated_at": "..."
    }
  ],
  "meta": { "total": 89, "by_status": { "pending": 52, "shortlisted": 23, "rejected": 14 } }
}
```

---

### `PATCH /api/jobs/{job_id}/applications/{application_id}/status`
Update a single application's status.

**Request body**
```json
{ "status": "shortlisted", "note": "Strong technical background" }
```

**Valid transitions:** `pending → shortlisted|rejected`, `shortlisted → offered|rejected`, `offered → accepted|withdrawn`

**Response (200)**
```json
{ "data": { "id": "uuid", "status": "shortlisted", "updated_at": "..." } }
```

---

## 4. AI Matching Results (per JD)

### `GET /api/jobs/{job_id}/matching-results`
Returns the latest AI matching results for a specific JD.

**Response:** Same shape as `GET /api/matching/results/{run_id}` from Module 1,
but scoped to a job and automatically fetching the latest run.

---

### `GET /api/jobs/{job_id}/matching-runs`
Returns history of all matching runs for a JD.

**Response**
```json
{
  "data": [
    {
      "run_id": "uuid",
      "triggered_by": "uuid",
      "triggered_at": "2026-03-08T10:00:00Z",
      "status": "complete",
      "total_analyzed": 2847,
      "top_score": 94
    }
  ]
}
```

---

## 5. Shortlist Workspace

### `GET /api/jobs/{job_id}/shortlist`
Returns shortlisted candidates for a job with full comparison data.

**Response**
```json
{
  "data": [
    {
      "application_id": "uuid",
      "student_id": "uuid",
      "name": "Aiko Yamada",
      "school": "Osaka University",
      "department": "CS M2",
      "ai_score": 94,
      "skill_match": 96,
      "research_sim": 91,
      "lang_readiness": 82,
      "learning_traj": 98,
      "skills": ["React", "TypeScript"],
      "jp_level": "N3",
      "status": "shortlisted",
      "shortlisted_at": "..."
    }
  ]
}
```

---

### `POST /api/jobs/{job_id}/shortlist/compare`
Returns side-by-side comparison data for up to 3 candidates.

**Request body**
```json
{ "student_ids": ["uuid1", "uuid2", "uuid3"] }
```

**Response**
```json
{
  "data": {
    "candidates": [
      {
        "student_id": "uuid",
        "name": "Aiko Yamada",
        "dimensions": {
          "skill_match": 96,
          "research_sim": 91,
          "lang_readiness": 82,
          "learning_traj": 98
        },
        "skills": ["React", "TypeScript"],
        "radar_data": [
          { "dimension": "Skills", "value": 96 },
          { "dimension": "Research", "value": 91 },
          { "dimension": "Language", "value": 82 },
          { "dimension": "Growth", "value": 98 },
          { "dimension": "Domain", "value": 93 }
        ]
      }
    ]
  }
}
```

---

## 6. Company Landing Page Builder

### `GET /api/companies/me/landing-page`
Returns the current landing page content for the company.

**Response**
```json
{
  "data": {
    "company_id": "uuid",
    "headline": "Build the future with Sony",
    "subheadline": "Join our engineering excellence programs",
    "hero_image_url": "...",
    "sections": [
      { "type": "benefits", "title": "Why Sony?", "items": ["..."] },
      { "type": "testimonials", "items": [{ "name": "...", "quote": "..." }] }
    ],
    "cta_text": "Explore Opportunities",
    "published": true
  }
}
```

---

### `PUT /api/companies/me/landing-page`
Save landing page content.

**Request body:** Same structure as above.

**Response (200)**
```json
{ "data": { "published": true, "updated_at": "..." } }
```

---

## 7. Company Analytics Dashboard

### `GET /api/analytics/company`
Returns all metrics for the company dashboard.

**Query params:** `period=6m|3m|1m|ytd`

**Response**
```json
{
  "data": {
    "active_jobs": 12,
    "total_applicants": 342,
    "ai_matches_today": 47,
    "offers_extended": 8,
    "offers_accepted": 5,
    "hiring_funnel": [
      { "month": "Sep", "applications": 142, "shortlisted": 28, "hired": 12 }
    ],
    "pipeline": {
      "screening": 128,
      "interview": 47,
      "assessment": 24,
      "offer_stage": 12
    },
    "recent_activity": [
      {
        "type": "match",
        "message": "23 new AI matches for Senior AI Research Engineer",
        "created_at": "2026-03-08T10:00:00Z",
        "urgent": true
      }
    ]
  }
}
```

---

## Flask Blueprints

### `app/routes/companies.py`
Handles `/api/companies/*`. Auth via `app/middleware/auth.py`.

### `app/routes/jobs.py`
Handles `/api/jobs/*`. Includes applications, matching-results, shortlist sub-resources.

### `app/routes/analytics.py`
Handles `/api/analytics/company`. Registered at `/api/analytics`.

### `app/middleware/auth.py`
Exports `require_auth` and `require_role(roles)` decorators.
Sets `flask.g.user_id`, `g.user_role`, `g.profile` for downstream handlers.

### DB Lookup Pattern
Company admin's company is resolved via the `recruiters` table:
```python
recruiter = supabase.table("recruiters").select("company_id").eq("id", g.user_id).single().execute()
company_id = recruiter.data["company_id"]
```

---

## Error Cases to Handle

| Scenario | HTTP | Error Code |
|---|---|---|
| Duplicate job title in same company | 422 | `DUPLICATE_JOB` |
| Salary min > salary max | 400 | `INVALID_SALARY_RANGE` |
| Deadline in the past | 400 | `INVALID_DEADLINE` |
| Publishing a job with missing required fields | 422 | `JOB_INCOMPLETE` |
| Invalid status transition | 422 | `INVALID_STATUS_TRANSITION` |
| Compare more than 3 candidates | 400 | `TOO_MANY_COMPARE` |
| Logo file too large | 400 | `FILE_TOO_LARGE` |
| Accessing another company's job | 403 | `FORBIDDEN_COMPANY` |
