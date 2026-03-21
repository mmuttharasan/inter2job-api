"""
Demo seed: Arjun (arjun1@anna.edu) — completed internship + certificate
at NexaTech (re-uses existing company if present).

Run:
  cd repo-middleware
  python seed_arjun_certificate.py
"""

import os
import sys
import secrets
import string
from datetime import date, timedelta, datetime, timezone
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def ok(msg):  print(f"  ✓ {msg}")
def skip(msg): print(f"  ~ {msg} (already exists)")
def fail(msg, err): print(f"  ✗ {msg}: {err}")


# ─── Auth user ───────────────────────────────────────────────────────────────

def get_or_create_user(email, name, role, password="Password123!"):
    try:
        res = supabase.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"full_name": name, "role": role},
        })
        uid = res.user.id
        ok(f"auth: {email} → {uid}")
        return uid
    except Exception as e:
        if "already" in str(e).lower() or "duplicate" in str(e).lower():
            users = supabase.auth.admin.list_users()
            for u in users:
                if u.email == email:
                    skip(f"auth: {email} → {u.id}")
                    return u.id
        fail(f"auth: {email}", e)
        return None


def ensure_profile(uid, name, role, university_id=None):
    try:
        data = {"role": role, "full_name": name}
        if university_id:
            data["university_id"] = university_id
        supabase.table("profiles").upsert({"id": uid, **data}, on_conflict="id").execute()
        ok(f"profiles: {name}")
    except Exception as e:
        fail("profiles", e)


def insert(table, data):
    try:
        res = supabase.table(table).insert(data).execute()
        row = res.data[0] if res.data else data
        ok(f"{table}: {row.get('id', '?')}")
        return row
    except Exception as e:
        msg = str(e)
        if "duplicate" in msg.lower() or "unique" in msg.lower():
            skip(table)
            return None
        fail(table, e)
        return None


def upsert(table, data, conflict):
    try:
        res = supabase.table(table).upsert(data, on_conflict=conflict).execute()
        row = res.data[0] if res.data else data
        ok(f"{table}: {row.get('id', '?')}")
        return row
    except Exception as e:
        fail(table, e)
        return None


# ─── Step 1: University ───────────────────────────────────────────────────────

def get_or_create_university():
    print("\n[1] Anna University")
    res = supabase.table("universities").select("id").eq("domain", "anna.edu").execute()
    if res.data:
        uid = res.data[0]["id"]
        skip(f"universities: anna.edu → {uid}")
        return uid
    row = insert("universities", {
        "name":     "Anna University",
        "domain":   "anna.edu",
        "logo_url": None,
        "status":   "approved",
        "country":  "India",
    })
    return row["id"] if row else None


# ─── Step 2: Company (NexaTech or fallback) ───────────────────────────────────

def get_or_create_company():
    print("\n[2] Company (NexaTech)")
    res = supabase.table("companies").select("id").eq("name", "NexaTech").execute()
    if res.data:
        cid = res.data[0]["id"]
        skip(f"companies: NexaTech → {cid}")
        return cid
    row = insert("companies", {
        "name":         "NexaTech",
        "name_jp":      "ネクサテック株式会社",
        "tagline":      "Connecting talent with opportunity across Asia",
        "website":      "https://nexatech.co.jp",
        "industry":     "Technology",
        "size":         "501-1000",
        "location":     "Tokyo, Japan",
        "description":  "NexaTech builds AI-powered recruitment and enterprise software for the Asian market.",
        "mission":      "Empowering every student with technology that opens doors to meaningful careers.",
        "values":       ["Innovation", "Integrity", "Inclusivity", "Impact"],
        "benefits":     ["Flexible remote work", "Annual learning budget", "Full health insurance"],
        "founded_year": 2018,
        "status":       "active",
    })
    return row["id"] if row else None


# ─── Step 3: Student user ─────────────────────────────────────────────────────

def get_or_create_student(university_id):
    print("\n[3] Student: Arjun (arjun1@anna.edu)")
    uid = get_or_create_user("arjun1@anna.edu", "Arjun Kumar", "student")
    if not uid:
        return None

    ensure_profile(uid, "Arjun Kumar", "student", university_id)

    # Student row
    res = supabase.table("students").select("id").eq("id", uid).execute()
    if res.data:
        skip(f"students: Arjun Kumar")
    else:
        insert("students", {
            "id":                  uid,
            "university_id":       university_id,
            "department":          "Computer Science & Engineering",
            "graduation_year":     2025,
            "gpa":                 3.80,
            "skills":              ["Python", "Machine Learning", "React", "SQL", "Data Analysis", "FastAPI"],
            "verification_status": "verified",
            "bio":                 "Passionate about AI and building scalable systems. Experienced in full-stack development with a strong focus on ML applications.",
        })
    return uid


# ─── Step 4: Job (or re-use existing) ────────────────────────────────────────

def get_or_create_job(company_id):
    print("\n[4] Job: AI Software Engineer Intern")
    # Try to find an existing published job at NexaTech
    res = (
        supabase.table("jobs")
        .select("id, recruiter_id")
        .eq("company_id", company_id)
        .eq("title", "AI Software Engineer Intern")
        .execute()
    )
    if res.data:
        j = res.data[0]
        skip(f"jobs: AI Software Engineer Intern → {j['id']}")
        return j["id"], j["recruiter_id"]

    # Get any recruiter for this company
    rec = supabase.table("recruiters").select("id").eq("company_id", company_id).limit(1).execute()
    recruiter_id = rec.data[0]["id"] if rec.data else None

    if not recruiter_id:
        # Create a dummy recruiter identity (reuse company admin or skip)
        fail("jobs", "no recruiter found for company — create company admin first via seed.py")
        return None, None

    today = date.today()
    row = insert("jobs", {
        "company_id":          company_id,
        "recruiter_id":        recruiter_id,
        "title":               "AI Software Engineer Intern",
        "description":         "Build ML-powered features for our internship matching platform.",
        "location":            "Chennai, India (Remote)",
        "department":          "Engineering",
        "skills":              ["Python", "Machine Learning", "SQL", "FastAPI", "React"],
        "employment_type":     "internship",
        "experience_level":    "entry",
        "openings":            2,
        "status":              "published",
        "deadline":            str(today + timedelta(days=30)),
        "ai_matching_enabled": True,
        "priority":            "high",
    })
    if row:
        return row["id"], recruiter_id
    return None, None


# ─── Step 5: Application ──────────────────────────────────────────────────────

def get_or_create_application(job_id, student_id):
    print("\n[5] Application")
    res = (
        supabase.table("applications")
        .select("id")
        .eq("job_id", job_id)
        .eq("student_id", student_id)
        .execute()
    )
    if res.data:
        aid = res.data[0]["id"]
        skip(f"applications → {aid}")
        return aid

    row = insert("applications", {
        "job_id":      job_id,
        "student_id":  student_id,
        "status":      "offered",
        "ai_score":    91.5,
        "cover_letter": "I am deeply interested in applying my ML and full-stack skills at NexaTech. "
                        "My experience building AI-powered features for student platforms aligns well with your mission.",
        "shortlisted_at": "2025-07-10T00:00:00Z",
    })
    return row["id"] if row else None


# ─── Step 6: Internship (completed) ──────────────────────────────────────────

def get_or_create_internship(application_id, student_id, job_id, company_id):
    print("\n[6] Internship (completed)")
    res = (
        supabase.table("internships")
        .select("id")
        .eq("application_id", application_id)
        .execute()
    )
    if res.data:
        iid = res.data[0]["id"]
        skip(f"internships → {iid}")
        return iid

    row = insert("internships", {
        "application_id": application_id,
        "student_id":     student_id,
        "job_id":         job_id,
        "company_id":     company_id,
        "status":         "completed",
        "start_date":     "2024-07-15",
        "end_date":       "2024-10-15",
        "mentor_name":    "Yuki Tanaka",
        "team":           "AI Platform Team",
    })
    return row["id"] if row else None


# ─── Step 7: Milestones (all completed) ──────────────────────────────────────

def seed_milestones(internship_id):
    print("\n[7] Milestones")
    res = supabase.table("internship_milestones").select("id").eq("internship_id", internship_id).execute()
    if res.data:
        skip(f"internship_milestones for {internship_id}")
        return

    milestones = [
        {"title": "Onboarding & codebase walkthrough",                 "status": "completed", "due_date": "2024-07-22", "completed_at": "2024-07-20T10:00:00Z", "sort_order": 0, "student_actionable": False},
        {"title": "Set up local ML pipeline environment",              "status": "completed", "due_date": "2024-07-29", "completed_at": "2024-07-27T14:00:00Z", "sort_order": 1, "student_actionable": True},
        {"title": "Complete first feature: skills-gap analysis API",   "status": "completed", "due_date": "2024-08-15", "completed_at": "2024-08-12T16:00:00Z", "sort_order": 2, "student_actionable": True},
        {"title": "Mid-internship review & feedback session",          "status": "completed", "due_date": "2024-08-20", "completed_at": "2024-08-19T11:00:00Z", "sort_order": 3, "student_actionable": False},
        {"title": "Deliver recommendation model (v1) to production",   "status": "completed", "due_date": "2024-09-15", "completed_at": "2024-09-10T17:00:00Z", "sort_order": 4, "student_actionable": True},
        {"title": "Write technical handover documentation",            "status": "completed", "due_date": "2024-10-10", "completed_at": "2024-10-08T13:00:00Z", "sort_order": 5, "student_actionable": True},
        {"title": "Final presentation to the AI Platform Team",        "status": "completed", "due_date": "2024-10-14", "completed_at": "2024-10-14T15:00:00Z", "sort_order": 6, "student_actionable": True},
    ]
    for m in milestones:
        insert("internship_milestones", {"internship_id": internship_id, **m})


# ─── Step 8: Certificate ──────────────────────────────────────────────────────

def _gen_code():
    year = datetime.now(tz=timezone.utc).year
    chars = string.ascii_uppercase + string.digits
    rand = "".join(secrets.choice(chars) for _ in range(6))
    return f"CERT-{year}-NEX-{rand}"


def seed_certificate(internship_id, student_id, company_id):
    print("\n[8] Certificate")
    res = supabase.table("certificates").select("id, verification_code").eq("internship_id", internship_id).execute()
    if res.data:
        code = res.data[0]["verification_code"]
        skip(f"certificates: {code}")
        return res.data[0]

    code = _gen_code()
    row = insert("certificates", {
        "internship_id":       internship_id,
        "student_id":          student_id,
        "company_id":          company_id,
        "verification_code":   code,
        "student_name":        "Arjun Kumar",
        "company_name":        "NexaTech",
        "job_title":           "AI Software Engineer Intern",
        "start_date":          "2024-07-15",
        "end_date":            "2024-10-15",
        "skills_demonstrated": [
            "Python", "Machine Learning", "FastAPI",
            "React", "SQL", "Data Analysis", "Model Deployment"
        ],
        "performance_summary": (
            "Arjun demonstrated exceptional initiative and technical depth throughout his 3-month internship. "
            "He independently designed and shipped the skills-gap analysis API, and contributed a recommendation "
            "model that improved match accuracy by 12%. His communication, ownership mindset, and ability to "
            "deliver production-ready code set a high bar for the team."
        ),
        "mentor_name": "Yuki Tanaka",
        "issued_at":   "2024-10-16T10:00:00Z",
    })
    return row


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Demo seed: Arjun Kumar certificate")
    print("=" * 60)

    university_id = get_or_create_university()
    if not university_id:
        print("✗ Could not resolve university"); sys.exit(1)

    company_id = get_or_create_company()
    if not company_id:
        print("✗ Could not resolve company"); sys.exit(1)

    student_id = get_or_create_student(university_id)
    if not student_id:
        print("✗ Could not create student"); sys.exit(1)

    job_id, _ = get_or_create_job(company_id)
    if not job_id:
        print("✗ Could not resolve job\n  → Run seed.py first to create the NexaTech recruiter."); sys.exit(1)

    application_id = get_or_create_application(job_id, student_id)
    if not application_id:
        print("✗ Could not create application"); sys.exit(1)

    internship_id = get_or_create_internship(application_id, student_id, job_id, company_id)
    if not internship_id:
        print("✗ Could not create internship"); sys.exit(1)

    seed_milestones(internship_id)

    cert = seed_certificate(internship_id, student_id, company_id)

    print("\n" + "=" * 60)
    print("Done! Login to see the certificate:")
    print()
    print("  Email:    arjun1@anna.edu")
    print("  Password: Password123!")
    print()
    if cert:
        code = cert.get("verification_code", "?")
        print(f"  Certificate code: {code}")
        print(f"  Public verify:    /verify/{code}")
    print("=" * 60)


if __name__ == "__main__":
    main()
