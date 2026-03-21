# Module 5 — Student
> Role token: `student`
> Persona: **Aiko Yamada** — Osaka University, CS M2

---

## Overview

The Student is the core supply-side user of the platform. They own their profile,
submit credentials for university verification, browse and apply to job postings,
track their application journey (StudentJourney), communicate with recruiters,
and manage account settings. The student's profile visibility and AI match score
are the central value propositions.

### Pages served
| Frontend Route | Page Component |
|---|---|
| `/app/students/me` | `StudentProfile` (own) |
| `/app/students/me/edit` | `StudentProfileEditor` |
| `/app/students/journey` | `StudentJourney` |
| `/app/messages` | `Messages` |
| `/app/settings` | `Settings` |

> Students are redirected from `/app/dashboard` → `/app/students/me`

---

## 1. Student Profile (own)

### `GET /api/students/me`
Returns the full profile of the authenticated student.

**Auth rule:** `role = 'student'`

**Supabase query**
```python
student = supabase.table("students")
    .select("*, profiles(full_name, avatar_url, email), universities(name)")
    .eq("id", user_id)
    .single()
```

**Response**
```json
{
  "data": {
    "id": "uuid",
    "name": "Aiko Yamada",
    "email": "aiko@osaka-u.ac.jp",
    "avatar_url": null,
    "university": "Osaka University",
    "university_id": "uuid",
    "department": "CS M2",
    "graduation_year": 2026,
    "gpa": "3.9",
    "bio": "Passionate about building intelligent systems...",
    "jp_level": "N3",
    "verification_status": "verified",
    "resume_url": "https://...",
    "linkedin": "https://linkedin.com/in/aiko-yamada",
    "github": "https://github.com/aiko",
    "portfolio": null,
    "skills": [
      { "id": "uuid", "name": "React", "level": 90, "verified": true, "category": "hard" },
      { "id": "uuid", "name": "Python", "level": 85, "verified": true, "category": "hard" },
      { "id": "uuid", "name": "Machine Learning", "level": 78, "verified": false, "category": "hard" },
      { "id": "uuid", "name": "Communication", "level": 88, "verified": false, "category": "soft" }
    ],
    "experiences": [
      {
        "id": "uuid",
        "title": "Software Engineering Intern",
        "company": "SoftBank Corp",
        "duration": "3 months",
        "description": "Built React components for internal dashboard",
        "start_date": "2025-06-01",
        "end_date": "2025-08-31",
        "type": "internship"
      }
    ],
    "research": {
      "title": "Deep Learning for NLP in Japanese Text Processing",
      "abstract": "...",
      "publication_url": null,
      "year": 2025
    },
    "awards": ["Best Research Paper Award 2025", "Hackathon Runner-up 2024"],
    "strengths": ["Problem solving", "Fast learner", "Team player"],
    "badges": [
      { "name": "Top Performer", "icon": "trophy", "earned_at": "2025-12-01" }
    ],
    "ai_score": 94,
    "profile_completeness": 0.87,
    "privacy": {
      "show_email": false,
      "show_gpa": true,
      "show_resume": true,
      "show_linkedin": true
    }
  }
}
```

---

### `GET /api/students/{student_id}`
Returns public-facing student profile (used by recruiters).

**Auth rule:** Requester must be `recruiter`, `company_admin`, `university`, `university_admin`, or `admin`.

**Business logic:** Only return fields allowed by student's `privacy` settings.

**Response:** Same structure as above, but filtered by privacy config.

---

### `PUT /api/students/me`
Update basic student profile fields.

**Auth rule:** `role = 'student'`

**Request body**
```json
{
  "full_name": "Aiko Yamada",
  "phone": "+81-90-1234-5678",
  "location": "Osaka, Japan",
  "linkedin": "https://linkedin.com/in/aiko-yamada",
  "github": "https://github.com/aiko",
  "portfolio": "https://aiko.dev",
  "bio": "Passionate about building intelligent systems...",
  "department": "CS M2",
  "graduation_year": 2026,
  "gpa": "3.9",
  "jp_level": "N3",
  "strengths": ["Problem solving", "Fast learner"],
  "awards": ["Best Research Paper 2025"],
  "privacy": {
    "show_email": false,
    "show_gpa": true,
    "show_resume": true,
    "show_linkedin": true
  }
}
```

**Validation rules:**
- `gpa` if provided: numeric between 0.0–10.0 (India) or 0.0–4.0 (USA/Japan)
- `graduation_year`: current year to current year + 6
- `jp_level`: enum of `N1`, `N2`, `N3`, `N4`, `N5`, `None`
- `linkedin`, `github`, `portfolio`: valid URLs if provided

**Response (200)**
```json
{ "data": { "id": "uuid", "updated_at": "...", "profile_completeness": 0.92 } }
```

---

### `POST /api/students/me/avatar`
Upload profile avatar.

**Request:** `multipart/form-data`, field `file` (PNG/JPG, max 1MB)

**Business logic:**
1. Validate file type and size
2. Upload to `avatars/{user_id}/avatar.{ext}` in Supabase Storage
3. Update `profiles.avatar_url`

**Response (200)**
```json
{ "data": { "avatar_url": "https://..." } }
```

---

### `POST /api/students/me/resume`
Upload CV/resume to Supabase Storage.

**Request:** `multipart/form-data`, field `file` (PDF, DOC, DOCX — max 5MB)

**Business logic:**
1. Validate file type: `.pdf`, `.doc`, `.docx` only
2. Upload to `resumes/{user_id}/resume.{ext}` (private bucket)
3. Update `students.resume_url`

**Response (200)**
```json
{ "data": { "resume_url": "https://...", "filename": "Aiko_Yamada_CV.pdf" } }
```

---

## 2. Skills Management

### `GET /api/students/me/skills`
Returns all skills with proficiency levels and verification status.

**Response**
```json
{
  "data": [
    { "id": "uuid", "name": "React", "level": 90, "verified": true, "category": "hard", "added_at": "..." },
    { "id": "uuid", "name": "Communication", "level": 88, "verified": false, "category": "soft" }
  ]
}
```

---

### `POST /api/students/me/skills`
Add a new skill.

**Request body**
```json
{
  "name": "TypeScript",
  "level": 75,
  "category": "hard"
}
```

**Validation:**
- `name`: required, 2–100 chars, must not duplicate existing skills
- `level`: integer 0–100
- `category`: `hard` or `soft`

**Response (201)**
```json
{ "data": { "id": "uuid", "name": "TypeScript", "level": 75, "verified": false } }
```

---

### `PUT /api/students/me/skills/{skill_id}`
Update skill proficiency level.

**Request body**
```json
{ "level": 85 }
```

**Auth rule:** Student can only update their own skills.

**Response (200)**
```json
{ "data": { "id": "uuid", "name": "TypeScript", "level": 85 } }
```

---

### `DELETE /api/students/me/skills/{skill_id}`
Remove a skill.

**Response (204)**

---

## 3. Experiences

### `GET /api/students/me/experiences`
Returns all work/internship/research experiences.

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "type": "internship",
      "title": "Software Engineering Intern",
      "company": "SoftBank Corp",
      "description": "Built React components for internal dashboard",
      "start_date": "2025-06-01",
      "end_date": "2025-08-31",
      "is_current": false
    }
  ]
}
```

---

### `POST /api/students/me/experiences`
Add experience.

**Request body**
```json
{
  "type": "internship",
  "title": "Software Engineering Intern",
  "company": "SoftBank Corp",
  "description": "...",
  "start_date": "2025-06-01",
  "end_date": "2025-08-31",
  "is_current": false
}
```

**Validation:**
- `type`: `internship`, `research`, `project`, `part_time`, `full_time`
- `start_date` < `end_date` unless `is_current = true`

**Response (201)**
```json
{ "data": { "id": "uuid", "type": "internship", "title": "..." } }
```

---

### `PUT /api/students/me/experiences/{exp_id}` / `DELETE /api/students/me/experiences/{exp_id}`
Standard update / delete.

---

## 4. Student Journey — Applications

### `GET /api/students/me/applications`
Returns all job applications for the student.

**Query params:** `status=pending|shortlisted|rejected|offered|accepted|withdrawn`, `page`, `limit`

**Auth rule:** `role = 'student'` — own applications only.

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "job_id": "uuid",
      "job_title": "Senior Frontend Engineer",
      "company_name": "SoftBank Corp",
      "company_logo_url": "...",
      "location": "Tokyo",
      "status": "shortlisted",
      "applied_at": "2026-02-10T08:00:00Z",
      "updated_at": "2026-02-15T12:00:00Z",
      "ai_score": 94,
      "cover_letter": "...",
      "timeline": [
        { "status": "pending", "occurred_at": "2026-02-10T08:00:00Z" },
        { "status": "shortlisted", "occurred_at": "2026-02-15T12:00:00Z" }
      ]
    }
  ],
  "meta": { "total": 5, "by_status": { "shortlisted": 2, "pending": 2, "rejected": 1 } }
}
```

---

### `POST /api/students/me/applications`
Apply to a job.

**Auth rule:** `role = 'student'` — must have `verification_status = 'verified'`

**Request body**
```json
{
  "job_id": "uuid",
  "cover_letter": "Dear Hiring Manager, I am excited to apply for..."
}
```

**Business logic:**
1. Check student's `verification_status = 'verified'` — else return `403 NOT_VERIFIED`
2. Check job `status = 'published'` — else return `422 JOB_CLOSED`
3. Check no duplicate application (unique constraint) — else return `422 ALREADY_APPLIED`
4. Insert into `applications` table

**Response (201)**
```json
{ "data": { "id": "uuid", "job_id": "uuid", "status": "pending", "applied_at": "..." } }
```

---

### `DELETE /api/students/me/applications/{application_id}`
Withdraw an application.

**Business logic:**
1. Can only withdraw `pending` applications (not shortlisted+)
2. Update `status = 'withdrawn'`

**Response (200)**
```json
{ "data": { "id": "uuid", "status": "withdrawn" } }
```

---

## 5. Interviews

### `GET /api/students/me/interviews`
Returns upcoming and past interviews.

**Query params:** `status=scheduled|completed|cancelled`, `page`, `limit`

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "job_id": "uuid",
      "job_title": "Senior Frontend Engineer",
      "company_name": "SoftBank Corp",
      "interview_type": "technical",
      "scheduled_at": "2026-03-20T10:00:00Z",
      "duration_minutes": 60,
      "format": "video",
      "meeting_link": "https://zoom.us/...",
      "status": "scheduled",
      "interviewer_name": "Sarah Richards"
    }
  ]
}
```

---

## 6. Credential Submissions (Verification)

### `POST /api/students/me/verifications`
Submit a credential document for university verification.

**Request:** `multipart/form-data`
```
type: "academic_transcript"
file: <binary PDF>
```

**Valid types:** `academic_transcript`, `research_publication`, `internship_certificate`, `project_report`

**Business logic:**
1. Upload file to `resumes/{user_id}/verifications/{type}/{filename}` bucket (private)
2. Insert into `verifications` table with `status = 'pending'`
3. Update `students.verification_status = 'pending'` if currently `unverified`
4. Notify university admin

**Response (201)**
```json
{
  "data": {
    "id": "uuid",
    "type": "academic_transcript",
    "status": "pending",
    "submitted_at": "...",
    "document_url": "..."
  }
}
```

---

### `GET /api/students/me/verifications`
Returns all verification submissions and their current status.

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "type": "academic_transcript",
      "status": "approved",
      "submitted_at": "2026-02-28T09:00:00Z",
      "reviewed_at": "2026-03-01T11:00:00Z",
      "review_note": "Verified successfully."
    }
  ]
}
```

---

## 7. Settings

### `GET /api/students/me/settings`
Returns user settings.

**Response**
```json
{
  "data": {
    "notifications": {
      "new_match": true,
      "application_update": true,
      "message_received": true,
      "job_recommendation": false,
      "weekly_digest": true
    },
    "privacy": {
      "show_email": false,
      "show_gpa": true,
      "show_resume": true,
      "show_linkedin": true,
      "profile_visibility": "verified_recruiters"
    },
    "ai_preferences": {
      "preferred_industries": ["Technology", "Automotive"],
      "preferred_locations": ["Tokyo", "Osaka"],
      "open_to_remote": true,
      "min_salary_jpy": 4500000
    }
  }
}
```

---

### `PUT /api/students/me/settings`
Update settings.

**Request body:** Partial update allowed — any subset of the response above.

**Response (200)**
```json
{ "data": { "updated_at": "..." } }
```

---

### `POST /api/auth/change-password`
Change account password.

**Auth rule:** Any authenticated role.

**Request body**
```json
{
  "current_password": "...",
  "new_password": "...",
  "confirm_password": "..."
}
```

**Validation:**
- `new_password` min 8 chars, at least 1 uppercase, 1 number
- `confirm_password` must match `new_password`

**Business logic:**
1. Re-authenticate with Supabase Auth using `current_password`
2. Call `supabase.auth.update_user(password=new_password)`

**Response (200)**
```json
{ "data": { "message": "Password changed successfully." } }
```

---

## 8. Notifications

### `GET /api/students/me/notifications`
Returns notification feed for the student.

**Query params:** `read=true|false|all`, `page`, `limit`

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "type": "application_update",
      "title": "Application shortlisted!",
      "body": "SoftBank Corp has shortlisted your application for Senior Frontend Engineer.",
      "read": false,
      "created_at": "2026-03-08T10:00:00Z",
      "action_url": "/app/students/journey"
    }
  ],
  "meta": { "total": 12, "unread": 3 }
}
```

---

### `PATCH /api/students/me/notifications/{notification_id}/read`
Mark a notification as read.

**Response (200)**
```json
{ "data": { "id": "uuid", "read": true } }
```

---

### `PATCH /api/students/me/notifications/read-all`
Mark all notifications as read.

**Response (200)**
```json
{ "data": { "marked_read": 3 } }
```

---

## Flask Blueprint: `app/routes/students.py`

```python
from flask import Blueprint, jsonify, request, g
from app.middleware.auth import require_role
from app.services.student_service import (
    get_student_profile, update_student_profile, upload_resume,
    get_applications, create_application, withdraw_application
)

students_bp = Blueprint("students", __name__)

@students_bp.get("/me")
@require_role(["student"])
def get_my_profile():
    profile = get_student_profile(g.user_id)
    return jsonify({"data": profile})

@students_bp.put("/me")
@require_role(["student"])
def update_my_profile():
    data = request.get_json()
    updated = update_student_profile(g.user_id, data)
    return jsonify({"data": updated})

@students_bp.post("/me/resume")
@require_role(["student"])
def upload_my_resume():
    if "file" not in request.files:
        return jsonify({"error": {"code": "NO_FILE", "message": "No file provided"}}), 400
    file = request.files["file"]
    result = upload_resume(g.user_id, file)
    return jsonify({"data": result})

@students_bp.get("/me/applications")
@require_role(["student"])
def get_my_applications():
    params = { "status": request.args.get("status", "all"), "page": int(request.args.get("page", 1)) }
    return jsonify(get_applications(g.user_id, params))

@students_bp.post("/me/applications")
@require_role(["student"])
def apply_to_job():
    data = request.get_json()
    result = create_application(g.user_id, data)
    return jsonify({"data": result}), 201
```

---

## Error Cases to Handle

| Scenario | HTTP | Error Code |
|---|---|---|
| Student not verified trying to apply | 403 | `NOT_VERIFIED` |
| Applying to a closed/draft job | 422 | `JOB_CLOSED` |
| Duplicate application | 422 | `ALREADY_APPLIED` |
| Withdrawing a shortlisted application | 422 | `CANNOT_WITHDRAW` |
| Password confirmation mismatch | 400 | `PASSWORD_MISMATCH` |
| Weak new password | 400 | `WEAK_PASSWORD` |
| Resume file type not allowed | 400 | `INVALID_FILE_TYPE` |
| File too large | 400 | `FILE_TOO_LARGE` |
| Duplicate skill name | 422 | `SKILL_EXISTS` |
| Invalid skill level (not 0–100) | 400 | `INVALID_SKILL_LEVEL` |
| Verification submission for already-verified type | 422 | `ALREADY_VERIFIED` |
| Internship not found | 404 | `INTERNSHIP_NOT_FOUND` |
| Certificate not found | 404 | `CERTIFICATE_NOT_FOUND` |
| Internship not completed (certificate request) | 422 | `INTERNSHIP_NOT_COMPLETED` |
| Certificate already issued for internship | 422 | `CERTIFICATE_EXISTS` |

---

## 9. Internship Status Tracking

Once an application reaches `accepted` status and the student is onboarded, an `internship` record is created. The student can track their internship lifecycle.

### Internship Statuses (lifecycle)
`pre_boarding` → `in_progress` → `completed` | `terminated`

### `GET /api/students/me/internships`
Returns all internships for the student (current + past).

**Auth rule:** `role = 'student'`

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "application_id": "uuid",
      "job_id": "uuid",
      "job_title": "Frontend Engineer Intern",
      "company_id": "uuid",
      "company_name": "Rakuten",
      "company_logo_url": "...",
      "status": "in_progress",
      "start_date": "2026-06-01",
      "end_date": "2026-08-31",
      "mentor_name": "Takeshi Yamamoto",
      "team": "Frontend Platform Team",
      "created_at": "2026-02-28T...",
      "milestones": [
        { "id": "uuid", "title": "Accept Offer", "status": "completed", "due_date": "2026-02-28", "completed_at": "2026-02-28T..." },
        { "id": "uuid", "title": "Pre-boarding Documents", "status": "completed", "due_date": "2026-04-15", "completed_at": "2026-04-10T..." },
        { "id": "uuid", "title": "Visa Application", "status": "completed", "due_date": "2026-05-01", "completed_at": "2026-04-28T..." },
        { "id": "uuid", "title": "Orientation", "status": "in_progress", "due_date": "2026-05-28", "completed_at": null },
        { "id": "uuid", "title": "Mid-term Review", "status": "pending", "due_date": "2026-07-15", "completed_at": null },
        { "id": "uuid", "title": "Final Presentation", "status": "pending", "due_date": "2026-08-25", "completed_at": null }
      ],
      "certificate": null
    }
  ]
}
```

---

### `GET /api/students/me/internships/{internship_id}`
Returns detailed internship status with milestones.

**Auth rule:** `role = 'student'`, must own the internship.

**Response:** Same structure as single item above.

---

### `PATCH /api/students/me/internships/{internship_id}/milestones/{milestone_id}`
Student marks a milestone as completed (where allowed — some milestones are company-managed).

**Auth rule:** `role = 'student'`, milestone `student_actionable = true`

**Request body**
```json
{ "status": "completed" }
```

**Response (200)**
```json
{ "data": { "id": "uuid", "title": "Pre-boarding Documents", "status": "completed", "completed_at": "..." } }
```

---

## 10. Certificate Issuance & Verification

After an internship is marked `completed`, the company (or platform admin) can issue a certificate. The student can download it and share a public verification link.

### `GET /api/students/me/certificates`
Returns all certificates earned by the student.

**Auth rule:** `role = 'student'`

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "internship_id": "uuid",
      "company_name": "Rakuten",
      "job_title": "Frontend Engineer Intern",
      "student_name": "Aiko Yamada",
      "start_date": "2026-06-01",
      "end_date": "2026-08-31",
      "issued_at": "2026-09-05T...",
      "verification_code": "CERT-2026-RKT-A1B2C3",
      "verification_url": "https://interntojob.com/verify/CERT-2026-RKT-A1B2C3",
      "download_url": "/api/certificates/CERT-2026-RKT-A1B2C3/download",
      "skills_demonstrated": ["React", "TypeScript", "Team Collaboration"],
      "performance_summary": "Aiko demonstrated exceptional frontend engineering skills...",
      "mentor_name": "Takeshi Yamamoto"
    }
  ]
}
```

---

### `GET /api/certificates/{verification_code}/verify`
**Public endpoint (no auth required)** — Verify a certificate's authenticity.

**Response (200)**
```json
{
  "data": {
    "valid": true,
    "student_name": "Aiko Yamada",
    "company_name": "Rakuten",
    "job_title": "Frontend Engineer Intern",
    "duration": "2026-06-01 to 2026-08-31",
    "issued_at": "2026-09-05T...",
    "verification_code": "CERT-2026-RKT-A1B2C3"
  }
}
```

**Response (404)** — Invalid code
```json
{ "error": { "code": "INVALID_CERTIFICATE", "message": "Certificate not found or invalid." } }
```

---

### `GET /api/certificates/{verification_code}/download`
**Auth rule:** `role = 'student'` (owner) or public with verification code.

Downloads the certificate as a PDF file.

**Response:** `application/pdf` binary stream with `Content-Disposition: attachment; filename="certificate_CERT-2026-RKT-A1B2C3.pdf"`

**Business logic:**
1. Look up certificate by `verification_code`
2. Generate PDF with: student name, company name, role, duration, skills, verification QR code, issuer signature
3. Return PDF binary

---

### `POST /api/internships/{internship_id}/certificate` *(Company/Admin only)*
Issue a certificate for a completed internship.

**Auth rule:** `role = 'recruiter'` (same company) or `role = 'super_admin'`

**Request body**
```json
{
  "skills_demonstrated": ["React", "TypeScript", "Team Collaboration"],
  "performance_summary": "Aiko demonstrated exceptional frontend engineering skills...",
  "mentor_name": "Takeshi Yamamoto"
}
```

**Business logic:**
1. Verify internship `status = 'completed'` — else `422 INTERNSHIP_NOT_COMPLETED`
2. Check no certificate already exists — else `422 CERTIFICATE_EXISTS`
3. Generate unique `verification_code`: `CERT-{year}-{company_prefix}-{random_6}`
4. Insert into `certificates` table
5. Notify student

**Response (201)**
```json
{
  "data": {
    "id": "uuid",
    "verification_code": "CERT-2026-RKT-A1B2C3",
    "verification_url": "https://interntojob.com/verify/CERT-2026-RKT-A1B2C3",
    "issued_at": "..."
  }
}
```

---

## Frontend Pages (New)

| Frontend Route | Page Component | Description |
|---|---|---|
| `/app/students/internships` | `InternshipTracker` | List & track all internships |
| `/app/students/internships/:id` | `InternshipDetail` | Detailed internship view with milestones |
| `/app/students/certificates` | `MyCertificates` | View & download certificates |
| `/verify/:code` | `CertificateVerify` | Public certificate verification page |

---

## DB Tables (New)

### `internships`
```sql
create type internship_status as enum ('pre_boarding', 'in_progress', 'completed', 'terminated');

create table internships (
  id              uuid primary key default uuid_generate_v4(),
  application_id  uuid references applications(id) on delete cascade unique,
  student_id      uuid references students(id) on delete cascade,
  job_id          uuid references jobs(id),
  company_id      uuid references companies(id),
  status          internship_status default 'pre_boarding',
  start_date      date not null,
  end_date        date not null,
  mentor_name     text,
  team            text,
  created_at      timestamptz default now(),
  updated_at      timestamptz default now()
);
```

### `internship_milestones`
```sql
create type milestone_status as enum ('pending', 'in_progress', 'completed');

create table internship_milestones (
  id                  uuid primary key default uuid_generate_v4(),
  internship_id       uuid references internships(id) on delete cascade,
  title               text not null,
  status              milestone_status default 'pending',
  due_date            date,
  completed_at        timestamptz,
  student_actionable  boolean default true,
  sort_order          int default 0,
  created_at          timestamptz default now()
);
```

### `certificates`
```sql
create table certificates (
  id                    uuid primary key default uuid_generate_v4(),
  internship_id         uuid references internships(id) on delete cascade unique,
  student_id            uuid references students(id) on delete cascade,
  company_id            uuid references companies(id),
  verification_code     text unique not null,
  student_name          text not null,
  company_name          text not null,
  job_title             text not null,
  start_date            date not null,
  end_date              date not null,
  skills_demonstrated   text[],
  performance_summary   text,
  mentor_name           text,
  issued_at             timestamptz default now(),
  created_at            timestamptz default now()
);
```
