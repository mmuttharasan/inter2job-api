# Middleware Implementation Plan — Index
> Flask REST API · InterntoJob Platform
> Planned: 2026-03-08

This folder contains one implementation plan per user-persona module.
Each plan describes every API endpoint, request/response schema, Supabase query,
auth rule, and business logic the Flask middleware must provide for that persona.

---

## Module Plans

| # | File | Persona | Role Token | Primary Routes |
|---|------|---------|------------|----------------|
| 1 | [01_company_recruiter.md](01_company_recruiter.md) | Company Recruiter | `recruiter` | `/api/matching`, `/api/students`, `/api/evaluation`, `/api/messages` |
| 2 | [02_company_admin.md](02_company_admin.md) | Company Admin | `company_admin` | `/api/companies`, `/api/jobs`, `/api/shortlist`, `/api/analytics` |
| 3 | [03_university_admin_tn.md](03_university_admin_tn.md) | University Admin (TN) | `university_admin` | `/api/universities/{id}/students`, `/api/verifications`, `/api/departments` |
| 4 | [04_university_admin_general.md](04_university_admin_general.md) | University Admin (Osaka) | `university` | `/api/universities`, `/api/partnerships`, `/api/analytics` |
| 5 | [05_student.md](05_student.md) | Student | `student` | `/api/students/me`, `/api/applications`, `/api/skills`, `/api/messages` |
| 6 | [06_platform_admin.md](06_platform_admin.md) | Platform Admin | `admin` | `/api/admin/*`, `/api/platform/stats`, `/api/users` |

---

## Shared Conventions (apply to all modules)

### Auth
All `/api/*` routes require a JWT Bearer token issued by Supabase Auth.

```
Authorization: Bearer <supabase_access_token>
```

The Flask middleware validates the token via `supabase.auth.get_user(token)`,
extracts `user_id` and `role` from the profile table, and enforces per-module
access. Supabase RLS provides a second layer of defence at the DB level.

### Response envelope

```json
// Success
{ "data": { ... }, "meta": { "page": 1, "total": 42 } }

// Error
{ "error": { "code": "NOT_FOUND", "message": "Student not found" } }
```

### Pagination query params
```
?page=1&limit=20&sort=created_at&order=desc
```

### HTTP status codes
| Status | Meaning |
|---|---|
| 200 | OK |
| 201 | Created |
| 204 | Deleted / no content |
| 400 | Validation error |
| 401 | Missing / invalid token |
| 403 | Authenticated but unauthorized (wrong role) |
| 404 | Resource not found |
| 422 | Business logic error |
| 500 | Unhandled server error |

### Flask Blueprint structure
```
app/
  routes/
    auth.py          # POST /api/auth/login, signup, refresh, logout
    students.py      # Module 5
    companies.py     # Module 2
    jobs.py          # Module 2
    matching.py      # Module 1
    evaluation.py    # Module 1
    universities.py  # Modules 3 & 4
    verifications.py # Module 3
    messages.py      # Modules 1, 5
    analytics.py     # Modules 2, 4, 6
    admin.py         # Module 6
    platform.py      # Module 6 (public stats)
```
