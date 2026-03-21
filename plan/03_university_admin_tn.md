# Module 3 — University Admin (Tamil Nadu)
> Role token: `university_admin`
> Persona: **Dr. Rajendran Kumar** — Anna University, Chennai, Tamil Nadu

---

## Overview

The Tamil Nadu University Admin manages their institution's student population:
verifying academic credentials, managing department hierarchies, tracking placement
statistics, and coordinating with company partners. The key differentiator from the
general university view is the **credential verification workflow** — a structured
approve/reject queue for student document submissions.

### Pages served
| Frontend Route | Page Component |
|---|---|
| `/app/university/dashboard` | `UniversityDashboard` |
| `/app/university/departments` | `DepartmentHierarchy` |
| `/app/university/students` | `StudentManagement` |
| `/app/university/verification` | `VerificationWorkflow` |
| `/app/analytics` | `AnalyticsDashboard` |
| `/app/messages` | `Messages` |

---

## 1. University Dashboard

### `GET /api/universities/me`
Returns the authenticated admin's university profile.

**Auth rule:** `role IN ('university_admin', 'university')` — scoped to their university.

**Supabase query**
```python
profile = supabase.table("profiles").select("university_id").eq("id", user_id).single()
uni = supabase.table("universities").select("*").eq("id", profile["university_id"]).single()
```

**Response**
```json
{
  "data": {
    "id": "uuid",
    "name": "Anna University",
    "name_regional": "அண்ணா பல்கலைக்கழகம்",
    "location": "Chennai, Tamil Nadu",
    "established": "1978",
    "accreditation": "NAAC A++",
    "logo_url": "...",
    "domain": "annauniv.edu",
    "total_students": 1460,
    "departments_count": 18,
    "partner_companies_count": 89,
    "created_at": "..."
  }
}
```

---

### `GET /api/analytics/university`
Returns placement metrics and dashboard statistics for the university.

**Query params:** `period=6m|3m|1m|ytd|academic_year`

**Auth rule:** `role IN ('university_admin', 'university')` — scoped to own university.

**Response**
```json
{
  "data": {
    "total_students": 1460,
    "placement_rate": 0.86,
    "partner_companies": 89,
    "departments_count": 18,
    "placement_trend": [
      { "month": "Sep", "placed": 142, "total": 180 },
      { "month": "Oct", "placed": 198, "total": 240 },
      { "month": "Nov", "placed": 234, "total": 290 },
      { "month": "Dec", "placed": 289, "total": 340 },
      { "month": "Jan", "placed": 356, "total": 410 },
      { "month": "Feb", "placed": 412, "total": 480 }
    ],
    "top_recruiters": [
      { "company_name": "TCS", "hires": 45 },
      { "company_name": "Infosys", "hires": 38 }
    ],
    "pending_verifications": 14
  }
}
```

---

## 2. Department Hierarchy

### `GET /api/universities/me/departments`
Returns all departments in the university.

**Query params:** `include_stats=true`

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "name": "Computer Science and Engineering",
      "code": "CSE",
      "head_of_department": "Dr. Senthil Kumar",
      "total_students": 480,
      "placed_students": 432,
      "placement_rate": 0.90,
      "active_batches": ["2021-25", "2022-26"],
      "sub_departments": []
    },
    {
      "id": "uuid",
      "name": "Electronics and Communication Engineering",
      "code": "ECE",
      "head_of_department": "Dr. Priya Nair",
      "total_students": 380,
      "placed_students": 323,
      "placement_rate": 0.85,
      "active_batches": ["2021-25", "2022-26"],
      "sub_departments": []
    }
  ]
}
```

---

### `POST /api/universities/me/departments`
Create a new department.

**Auth rule:** `role = 'university_admin'`

**Request body**
```json
{
  "name": "Artificial Intelligence and Data Science",
  "code": "AIDS",
  "head_of_department": "Dr. Kavitha Raman",
  "established_year": 2020
}
```

**Response (201)**
```json
{ "data": { "id": "uuid", "name": "...", "code": "AIDS" } }
```

---

### `PUT /api/universities/me/departments/{dept_id}`
Update department details.

**Request body:** Partial update allowed — any fields from the `POST` body.

**Response (200)**
```json
{ "data": { "id": "uuid", "name": "...", "updated_at": "..." } }
```

---

### `GET /api/universities/me/departments/{dept_id}/stats`
Returns detailed statistics for a single department.

**Query params:** `academic_year=2025-26`

**Response**
```json
{
  "data": {
    "department_id": "uuid",
    "code": "CSE",
    "total_students": 480,
    "placed_students": 432,
    "placement_rate": 0.90,
    "avg_package_lpa": 8.5,
    "highest_package_lpa": 24.0,
    "active_backlogs_count": 12,
    "companies_visited": 34,
    "students_by_batch": [
      { "batch": "2021-25", "count": 240, "placed": 218 },
      { "batch": "2022-26", "count": 240, "placed": 214 }
    ],
    "top_skills": ["Python", "Java", "SQL", "React", "Machine Learning"]
  }
}
```

---

## 3. Student Management

### `GET /api/universities/me/students`
Returns all students enrolled in this university.

**Query params**
| Param | Type | Notes |
|---|---|---|
| `page` | int | |
| `limit` | int | default 30 |
| `search` | string | name, roll number |
| `department_id` | uuid | filter by department |
| `batch` | string | e.g. `2022-26` |
| `verification_status` | string | `unverified`, `pending`, `verified`, `rejected` |
| `placement_status` | string | `placed`, `unplaced`, `all` |

**Auth rule:** `role IN ('university_admin', 'university')` — scoped to own university.

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "name": "Arjun Ramesh",
      "roll_number": "CS21B001",
      "email": "arjun@annauniv.edu",
      "department": "CSE",
      "batch": "2021-25",
      "gpa": "8.5",
      "verification_status": "verified",
      "placement_status": "placed",
      "placed_company": "TCS",
      "skills": ["Python", "Java"],
      "jp_level": null
    }
  ],
  "meta": { "page": 1, "total": 1460, "verified": 1241, "placed": 1256 }
}
```

---

### `GET /api/universities/me/students/{student_id}`
Returns full profile of a student in this university.

**Response:** Extended student profile including academic records, placements, verifications.

---

### `POST /api/universities/me/students/{student_id}/verify`
Manually mark a student as verified by the university (admin override).

**Auth rule:** `role = 'university_admin'`

**Request body**
```json
{ "note": "Verified against university records — batch 2021-25" }
```

**Business logic:**
1. Update `students.verification_status = 'verified'`
2. Create an entry in `verification_events` table with admin ID and note
3. Send notification to student

**Response (200)**
```json
{ "data": { "student_id": "uuid", "verification_status": "verified", "verified_at": "..." } }
```

---

## 4. Verification Workflow

### `GET /api/verifications`
Returns the pending verification queue for this university.

**Query params**
| Param | Type | Notes |
|---|---|---|
| `status` | string | `pending` (default), `approved`, `rejected`, `all` |
| `urgency` | string | `high`, `medium`, `low`, `all` |
| `department_id` | uuid | filter by department |
| `type` | string | `academic_transcript`, `research_publication`, `internship_certificate`, `project_report` |
| `page` | int | |
| `limit` | int | default 20 |

**Auth rule:** `role IN ('university_admin', 'university')` — scoped to own university.

**Response**
```json
{
  "data": [
    {
      "id": "uuid",
      "student_id": "uuid",
      "student_name": "Arjun Ramesh",
      "roll_number": "CS21B001",
      "department": "CSE",
      "type": "academic_transcript",
      "type_label": "Academic Transcript",
      "submitted_at": "2026-02-28T09:00:00Z",
      "urgency": "high",
      "documents": [
        {
          "id": "uuid",
          "filename": "Final_Transcript.pdf",
          "storage_url": "https://supabase.storage/.../Final_Transcript.pdf",
          "file_size_kb": 240,
          "uploaded_at": "2026-02-28T09:00:00Z"
        }
      ],
      "status": "pending",
      "reviewer_id": null,
      "review_note": null
    }
  ],
  "meta": {
    "total": 14,
    "by_urgency": { "high": 4, "medium": 6, "low": 4 },
    "by_type": { "academic_transcript": 5, "research_publication": 3, "internship_certificate": 4, "project_report": 2 },
    "avg_review_time_hours": 2.5,
    "approved_today": 8
  }
}
```

---

### `GET /api/verifications/{verification_id}`
Returns single verification item with full document list and review history.

**Response**
```json
{
  "data": {
    "id": "uuid",
    "student_id": "uuid",
    "student_name": "Arjun Ramesh",
    "roll_number": "CS21B001",
    "department": "CSE",
    "batch": "2021-25",
    "type": "academic_transcript",
    "submitted_at": "2026-02-28T09:00:00Z",
    "urgency": "high",
    "documents": [
      {
        "id": "uuid",
        "filename": "Final_Transcript.pdf",
        "storage_url": "...",
        "signed_url": "https://supabase.storage/.../Final_Transcript.pdf?token=...",
        "file_size_kb": 240
      }
    ],
    "status": "pending",
    "review_history": []
  }
}
```

---

### `POST /api/verifications/{verification_id}/approve`
Approve a verification request.

**Auth rule:** `role IN ('university_admin', 'university')`

**Request body**
```json
{ "note": "Documents verified against university records." }
```

**Business logic:**
1. Update `verifications` record: `status = 'approved'`, `reviewer_id = user_id`, `reviewed_at = now()`
2. Update `students.verification_status = 'verified'` (if all required docs approved)
3. Insert into `verification_events` table (audit log)
4. Send notification to student: "Your [type] has been verified."

**Response (200)**
```json
{
  "data": {
    "id": "uuid",
    "status": "approved",
    "reviewed_by": "uuid",
    "reviewed_at": "2026-03-08T14:00:00Z",
    "note": "Documents verified against university records."
  }
}
```

---

### `POST /api/verifications/{verification_id}/reject`
Reject a verification request with a reason.

**Auth rule:** `role IN ('university_admin', 'university')`

**Request body**
```json
{
  "reason": "document_mismatch",
  "note": "The GPA on the transcript does not match internal records. Please resubmit.",
  "request_resubmission": true
}
```

**Valid `reason` values:**
- `document_mismatch`
- `document_unreadable`
- `document_expired`
- `incomplete_submission`
- `fraudulent_document`
- `other`

**Business logic:**
1. Update `verifications` record: `status = 'rejected'`
2. If `request_resubmission = true`, reset `students.verification_status = 'unverified'`
3. Send notification to student with rejection reason and note

**Response (200)**
```json
{
  "data": {
    "id": "uuid",
    "status": "rejected",
    "reason": "document_mismatch",
    "note": "...",
    "resubmission_requested": true
  }
}
```

---

### `GET /api/verifications/{verification_id}/documents/{document_id}/signed-url`
Generate a short-lived signed URL to view a document securely.

**Business logic:**
1. Verify admin belongs to same university as the student
2. Generate Supabase Storage signed URL (expires in 15 min)

**Response (200)**
```json
{ "data": { "signed_url": "https://...", "expires_in_seconds": 900 } }
```

---

### `POST /api/universities/me/announcements`
Send a broadcast announcement to all students in the university.

**Auth rule:** `role IN ('university_admin', 'university')`

**Request body**
```json
{
  "title": "Campus Placement Drive — TCS",
  "body": "TCS will be visiting our campus on March 20th...",
  "target": "all",
  "departments": ["CSE", "ECE"],
  "priority": "high"
}
```

**Business logic:**
1. Validate target students (filter by `departments` if provided)
2. Insert into `notifications` table for each target student
3. Optionally send email via Supabase Edge Function

**Response (202)**
```json
{ "data": { "announcement_id": "uuid", "recipients": 842, "status": "queued" } }
```

---

## 5. University Analytics

### `GET /api/analytics/university/departments`
Returns placement breakdown per department.

**Response**
```json
{
  "data": [
    {
      "department": "CSE",
      "total_students": 480,
      "placed": 432,
      "placement_rate": 0.90,
      "avg_package_lpa": 8.5
    }
  ]
}
```

---

### `GET /api/analytics/university/companies`
Returns top recruiting companies and hire counts.

**Response**
```json
{
  "data": [
    { "company_name": "TCS", "hires": 45, "avg_package_lpa": 7.5 },
    { "company_name": "Infosys", "hires": 38, "avg_package_lpa": 7.2 }
  ]
}
```

---

## Flask Blueprint: `app/routes/verifications.py`

```python
from flask import Blueprint, jsonify, request, g
from app.middleware.auth import require_role
from app.services.verification_service import (
    get_verification_queue, approve_verification, reject_verification, get_signed_url
)

verifications_bp = Blueprint("verifications", __name__)

@verifications_bp.get("/")
@require_role(["university_admin", "university"])
def list_verifications():
    params = {
        "status": request.args.get("status", "pending"),
        "urgency": request.args.get("urgency"),
        "page": int(request.args.get("page", 1)),
        "limit": int(request.args.get("limit", 20)),
    }
    result = get_verification_queue(g.university_id, params)
    return jsonify(result)

@verifications_bp.post("/<verification_id>/approve")
@require_role(["university_admin", "university"])
def approve(verification_id):
    data = request.get_json()
    result = approve_verification(verification_id, g.user_id, data.get("note"))
    return jsonify({"data": result})

@verifications_bp.post("/<verification_id>/reject")
@require_role(["university_admin", "university"])
def reject(verification_id):
    data = request.get_json()
    if not data.get("reason"):
        return jsonify({"error": {"code": "REASON_REQUIRED", "message": "Rejection reason is required"}}), 400
    result = reject_verification(verification_id, g.user_id, data)
    return jsonify({"data": result})
```

---

## Error Cases to Handle

| Scenario | HTTP | Error Code |
|---|---|---|
| Verification already approved/rejected | 422 | `ALREADY_REVIEWED` |
| Reject without providing reason | 400 | `REASON_REQUIRED` |
| Document signed URL expired | 410 | `URL_EXPIRED` |
| Student not in this university | 403 | `WRONG_UNIVERSITY` |
| Department code already exists | 422 | `DUPLICATE_DEPT_CODE` |
| Announcement sent to 0 recipients | 422 | `NO_RECIPIENTS` |
| Fraudulent document flag | 200 | triggers admin alert |
