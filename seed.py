"""
Seed dummy data into Supabase for frontend screen validation.

STEP 1 — Apply pending migrations in Supabase SQL Editor first:
  Run: repo-backend/migrations/005_company_admin_extended.sql
  Run: repo-backend/migrations/006_fix_profile_trigger.sql

STEP 2 — Run this script:
  cd repo-middleware
  python seed.py

Creates:
  - 1 company admin user  (admin@nexatech.co.jp / Password123!)
  - 1 company             (NexaTech)
  - 1 recruiter record
  - 1 university          (University of Tokyo)
  - 5 student users       (haruto, yuna, kenji, aoi, ren)
  - 3 jobs                (2 published, 1 draft)
  - 7 applications        (various statuses)
  - 1 AI matching run + 5 AI match results
  - 1 company landing page
"""

import os
import sys
from datetime import date, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

TODAY = date.today()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def ok(label: str):
    print(f"  ✓ {label}")

def skip(label: str):
    print(f"  ~ {label} (already exists)")

def fail(label: str, err):
    print(f"  ✗ {label}: {err}")


def get_or_create_auth_user(email: str, name: str, role: str, password: str = "Password123!") -> str | None:
    """
    Create auth user via admin API.
    Returns the user UUID, or None on failure.
    """
    try:
        res = supabase.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"full_name": name, "role": role},
        })
        uid = res.user.id
        ok(f"auth.users: {email} → {uid}")
        return uid
    except Exception as e:
        msg = str(e)
        if "already been registered" in msg or "already exists" in msg or "duplicate" in msg.lower():
            # User exists — look up by email via admin list
            try:
                users = supabase.auth.admin.list_users()
                for u in users:
                    if u.email == email:
                        skip(f"auth.users: {email} → {u.id}")
                        return u.id
            except Exception as e2:
                fail(f"auth.users lookup {email}", e2)
                return None
        fail(f"auth.users: {email}", msg)
        return None


def insert_one(table: str, data: dict) -> dict | None:
    """Insert a single row, return the inserted row or None."""
    try:
        res = supabase.table(table).insert(data).execute()
        row = res.data[0] if res.data else data
        ok(f"{table}: {row.get('id', row.get('email', '?'))}")
        return row
    except Exception as e:
        msg = str(e)
        if "duplicate" in msg.lower() or "unique" in msg.lower() or "already exists" in msg.lower():
            skip(f"{table} row")
            return None
        fail(table, msg)
        return None


def upsert_one(table: str, data: dict, match_col: str = "id") -> dict | None:
    """Upsert a row. Returns the upserted row."""
    try:
        res = supabase.table(table).upsert(data, on_conflict=match_col).execute()
        row = res.data[0] if res.data else data
        ok(f"{table}: {row.get('id', '?')}")
        return row
    except Exception as e:
        fail(table, e)
        return None


# ─── Seed steps ──────────────────────────────────────────────────────────────

def seed_company_admin() -> str | None:
    print("\n[1] Company admin user")
    uid = get_or_create_auth_user(
        email="admin@nexatech.co.jp",
        name="Yuki Tanaka",
        role="recruiter",
    )
    if uid:
        # Update profile role (trigger may create it as 'student')
        try:
            supabase.table("profiles").update({"role": "recruiter", "full_name": "Yuki Tanaka"}).eq("id", uid).execute()
            ok(f"profiles: role=recruiter for {uid}")
        except Exception as e:
            fail("profiles update", e)
    return uid


def seed_company(admin_uid: str) -> str | None:
    print("\n[2] Company")
    res = supabase.table("companies").select("id").eq("name", "NexaTech").execute()
    if res.data:
        company_id = res.data[0]["id"]
        skip(f"companies: NexaTech → {company_id}")
    else:
        row = insert_one("companies", {
            "name":         "NexaTech",
            "name_jp":      "ネクサテック株式会社",
            "tagline":      "Connecting talent with opportunity across Asia",
            "logo_url":     None,
            "website":      "https://nexatech.co.jp",
            "industry":     "Technology",
            "size":         "501-1000",
            "location":     "Tokyo, Japan",
            "description":  "NexaTech is a leading technology company headquartered in Tokyo, building AI-powered recruitment and enterprise software solutions for the Asian market.",
            "mission":      "To empower every student and professional with technology that opens doors to meaningful careers.",
            "culture":      "We foster a culture of curiosity, collaboration, and continuous learning. Our teams work with autonomy and purpose.",
            "values":       ["Innovation", "Integrity", "Inclusivity", "Impact"],
            "benefits":     ["Flexible remote work", "Annual learning budget ¥200,000", "Full health insurance", "Stock options", "Relocation support"],
            "founded_year": 2018,
        })
        company_id = row["id"] if row else None

    print("\n[3] Recruiter link")
    if company_id and admin_uid:
        res2 = supabase.table("recruiters").select("id").eq("id", admin_uid).execute()
        if res2.data:
            skip(f"recruiters: {admin_uid}")
        else:
            insert_one("recruiters", {
                "id":         admin_uid,
                "company_id": company_id,
                "title":      "Head of Talent Acquisition",
            })

    return company_id


def seed_university() -> str | None:
    print("\n[4] University")
    res = supabase.table("universities").select("id").eq("domain", "u-tokyo.ac.jp").execute()
    if res.data:
        uid = res.data[0]["id"]
        skip(f"universities: u-tokyo.ac.jp → {uid}")
        return uid
    row = insert_one("universities", {
        "name":     "University of Tokyo",
        "domain":   "u-tokyo.ac.jp",
        "logo_url": None,
    })
    return row["id"] if row else None


def seed_students(university_id: str) -> list[str]:
    print("\n[5] Students")
    student_data = [
        {"email": "haruto.sato@u-tokyo.ac.jp",   "name": "Haruto Sato",    "dept": "Computer Science",    "grad": 2025, "gpa": 3.85, "skills": ["Python", "Machine Learning", "SQL", "React", "TypeScript"],    "jp_level": "N2", "research_title": "Neural network optimization for recommendation systems"},
        {"email": "yuna.kim@u-tokyo.ac.jp",       "name": "Yuna Kim",       "dept": "Data Science",        "grad": 2025, "gpa": 3.92, "skills": ["Python", "TensorFlow", "R", "Statistics", "Data Visualization"], "jp_level": "N1", "research_title": "Graph neural networks for knowledge graph completion"},
        {"email": "kenji.w@u-tokyo.ac.jp",        "name": "Kenji Watanabe", "dept": "Software Engineering","grad": 2024, "gpa": 3.70, "skills": ["Go", "Kubernetes", "Docker", "PostgreSQL", "AWS"],             "jp_level": "N3", "research_title": "Container orchestration for ML pipeline deployment"},
        {"email": "aoi.nakamura@u-tokyo.ac.jp",   "name": "Aoi Nakamura",   "dept": "Information Systems", "grad": 2025, "gpa": 3.55, "skills": ["JavaScript", "Node.js", "React", "MongoDB", "GraphQL"],        "jp_level": "N4", "research_title": "Real-time web application architecture patterns"},
        {"email": "ren.fujita@u-tokyo.ac.jp",     "name": "Ren Fujita",     "dept": "Computer Science",    "grad": 2026, "gpa": 3.78, "skills": ["Rust", "C++", "Embedded Systems", "Linux", "FPGA"],             "jp_level": "N5", "research_title": "FPGA-based acceleration for deep learning inference"},
    ]

    student_ids = []
    for s in student_data:
        uid = get_or_create_auth_user(s["email"], s["name"], "student")
        if not uid:
            continue

        # Update profile
        try:
            supabase.table("profiles").update({
                "role":          "student",
                "full_name":     s["name"],
                "university_id": university_id,
            }).eq("id", uid).execute()
        except Exception as e:
            fail(f"profiles update for {s['name']}", e)

        # Upsert student row
        res = supabase.table("students").select("id").eq("id", uid).execute()
        if res.data:
            skip(f"students: {s['name']}")
        else:
            insert_one("students", {
                "id":                  uid,
                "university_id":       university_id,
                "department":          s["dept"],
                "graduation_year":     s["grad"],
                "gpa":                 s["gpa"],
                "skills":              s["skills"],
                "jp_level":            s.get("jp_level"),
                "research_title":      s.get("research_title"),
                "verification_status": "verified",
            })
        student_ids.append(uid)

    return student_ids


def seed_jobs(company_id: str, recruiter_id: str) -> list[str]:
    print("\n[6] Jobs")
    jobs_def = [
        {
            "company_id":          company_id,
            "recruiter_id":        recruiter_id,
            "title":               "AI Software Engineer",
            "description":         "Build and scale machine learning pipelines for our recruitment matching engine.",
            "location":            "Tokyo, Japan",
            "department":          "Engineering",
            "skills":              ["Python", "Machine Learning", "TensorFlow", "SQL", "Docker"],
            "required_language":   "N2",
            "job_benefits":        ["Remote-friendly", "Stock options", "Learning budget"],
            "employment_type":     "full-time",
            "experience_level":    "mid",
            "openings":            3,
            "salary_min":          8000000,
            "salary_max":          12000000,
            "status":              "published",
            "deadline":            str(TODAY + timedelta(days=45)),
            "ai_matching_enabled": True,
            "priority":            "high",
        },
        {
            "company_id":          company_id,
            "recruiter_id":        recruiter_id,
            "title":               "Senior Frontend Engineer",
            "description":         "Lead our frontend platform team building the next-generation recruiter dashboard.",
            "location":            "Tokyo, Japan (Hybrid)",
            "department":          "Engineering",
            "skills":              ["React", "TypeScript", "Next.js", "GraphQL", "CSS"],
            "required_language":   "N3",
            "job_benefits":        ["Hybrid work", "Annual bonus", "Health insurance"],
            "employment_type":     "full-time",
            "experience_level":    "senior",
            "openings":            2,
            "salary_min":          10000000,
            "salary_max":          15000000,
            "status":              "published",
            "deadline":            str(TODAY + timedelta(days=30)),
            "ai_matching_enabled": True,
            "priority":            "high",
        },
        {
            "company_id":          company_id,
            "recruiter_id":        recruiter_id,
            "title":               "Product Manager — Internship Platform",
            "description":         "Define and drive the roadmap for our student internship discovery product.",
            "location":            "Remote",
            "department":          "Product",
            "skills":              ["Product Strategy", "Agile", "SQL", "Figma", "User Research"],
            "job_benefits":        ["Full remote", "Company retreats", "ESOP"],
            "employment_type":     "full-time",
            "experience_level":    "mid",
            "openings":            1,
            "salary_min":          9000000,
            "salary_max":          13000000,
            "status":              "draft",
            "deadline":            str(TODAY + timedelta(days=60)),
            "ai_matching_enabled": False,
            "priority":            "medium",
        },
    ]

    job_ids = []
    for j in jobs_def:
        row = insert_one("jobs", j)
        if row:
            job_ids.append(row["id"])
    return job_ids


def seed_applications(job_ids: list[str], student_ids: list[str]) -> list[str]:
    print("\n[7] Applications")
    if len(job_ids) < 2 or len(student_ids) < 5:
        fail("applications", f"need 2+ jobs and 5 students, got {len(job_ids)} jobs and {len(student_ids)} students")
        return []

    job1, job2 = job_ids[0], job_ids[1]
    s1, s2, s3, s4, s5 = student_ids[0], student_ids[1], student_ids[2], student_ids[3], student_ids[4]

    apps = [
        # Job 1 — AI Software Engineer
        {"job_id": job1, "student_id": s1, "status": "shortlisted", "ai_score": 88.50, "cover_letter": "Passionate about AI for hiring challenges.", "shortlisted_at": "2026-03-09T00:00:00Z"},
        {"job_id": job1, "student_id": s2, "status": "shortlisted", "ai_score": 92.30, "cover_letter": "Research on graph neural networks for recommendation systems.", "shortlisted_at": "2026-03-10T00:00:00Z"},
        {"job_id": job1, "student_id": s3, "status": "pending",     "ai_score": 74.20, "cover_letter": "Building ML pipelines on Kubernetes."},
        {"job_id": job1, "student_id": s4, "status": "pending",     "ai_score": 65.10, "cover_letter": "Full-stack applications with ML components."},
        {"job_id": job1, "student_id": s5, "status": "offered",     "ai_score": 81.00, "cover_letter": "Systems programming perspective on ML inference.", "shortlisted_at": "2026-03-07T00:00:00Z"},
        # Job 2 — Frontend
        {"job_id": job2, "student_id": s4, "status": "pending",     "ai_score": 78.90, "cover_letter": "3 years of production React experience."},
        {"job_id": job2, "student_id": s1, "status": "shortlisted", "ai_score": 82.40, "cover_letter": "React/TypeScript from university course management platform.", "shortlisted_at": "2026-03-11T00:00:00Z"},
    ]

    app_ids = []
    for app in apps:
        row = insert_one("applications", app)
        if row:
            app_ids.append(row["id"])
    return app_ids


def seed_ai_matching(job1_id: str, recruiter_id: str, student_ids: list[str]) -> None:
    print("\n[8] AI matching run + results")
    if not job1_id or len(student_ids) < 5:
        fail("ai_matching", "missing job or students")
        return

    run_row = insert_one("ai_matching_runs", {
        "job_id":         job1_id,
        "triggered_by":   recruiter_id,
        "status":         "complete",
        "total_analyzed": 5,
        "top_score":      92.30,
    })
    if not run_row:
        return

    run_id = run_row["id"]
    s1, s2, s3, s4, s5 = student_ids[0], student_ids[1], student_ids[2], student_ids[3], student_ids[4]

    results = [
        {
            "job_id": job1_id, "student_id": s2, "run_id": run_id, "score": 92.30,
            "explanation": {"skill_match": 95, "research_sim": 90, "lang_readiness": 88, "learning_traj": 93,
                            "summary": "Exceptional match. Research on graph neural networks directly applies to the matching engine.",
                            "strengths": ["Deep ML research", "Published papers", "High GPA"], "concerns": []},
        },
        {
            "job_id": job1_id, "student_id": s1, "run_id": run_id, "score": 88.50,
            "explanation": {"skill_match": 88, "research_sim": 82, "lang_readiness": 92, "learning_traj": 87,
                            "summary": "Strong candidate with hands-on ML internship experience.",
                            "strengths": ["Practical ML pipelines", "Strong Python"], "concerns": ["Less research publications"]},
        },
        {
            "job_id": job1_id, "student_id": s5, "run_id": run_id, "score": 81.00,
            "explanation": {"skill_match": 78, "research_sim": 80, "lang_readiness": 85, "learning_traj": 84,
                            "summary": "Unique systems perspective for ML inference optimization.",
                            "strengths": ["Systems programming", "Performance optimization"], "concerns": ["Limited Python ML", "No TensorFlow"]},
        },
        {
            "job_id": job1_id, "student_id": s3, "run_id": run_id, "score": 74.20,
            "explanation": {"skill_match": 70, "research_sim": 72, "lang_readiness": 80, "learning_traj": 75,
                            "summary": "Infrastructure-focused candidate pivoting to ML.",
                            "strengths": ["MLOps", "Kubernetes"], "concerns": ["Core ML gap"]},
        },
        {
            "job_id": job1_id, "student_id": s4, "run_id": run_id, "score": 65.10,
            "explanation": {"skill_match": 60, "research_sim": 65, "lang_readiness": 70, "learning_traj": 68,
                            "summary": "Fullstack background with some ML exposure.",
                            "strengths": ["Full-stack versatility"], "concerns": ["No dedicated ML experience"]},
        },
    ]
    for r in results:
        insert_one("ai_match_results", r)


def seed_platform_admin() -> str | None:
    print("\n[10] Platform admin (super_admin)")
    uid = get_or_create_auth_user(
        email="superadmin@intern2job.com",
        name="Platform Admin",
        role="super_admin",
    )
    if uid:
        try:
            supabase.table("profiles").update({"role": "super_admin", "full_name": "Platform Admin"}).eq("id", uid).execute()
            ok(f"profiles: role=super_admin for {uid}")
        except Exception as e:
            fail("profiles update", e)

    return uid


def seed_pending_companies(admin_uid: str) -> None:
    print("\n[11] Pending companies (for CompanyApproval screen)")
    companies = [
        {
            "name":        "TechVision Japan",
            "name_jp":     "テックビジョン株式会社",
            "tagline":     "Enterprise software for the next decade",
            "website":     "https://techvision.jp",
            "industry":    "Technology",
            "size":        "51-200",
            "location":    "Osaka, Japan",
            "description": "TechVision builds enterprise SaaS tools for the Japanese market.",
            "status":      "pending",
        },
        {
            "name":        "Green Robotics",
            "name_jp":     "グリーンロボティクス",
            "tagline":     "Automating the sustainable future",
            "website":     "https://greenrobotics.jp",
            "industry":    "Robotics",
            "size":        "11-50",
            "location":    "Kyoto, Japan",
            "description": "Developing eco-friendly robotic systems for agriculture and logistics.",
            "status":      "pending",
        },
    ]
    for c in companies:
        res = supabase.table("companies").select("id").eq("name", c["name"]).execute()
        if res.data:
            skip(f"companies: {c['name']}")
        else:
            insert_one("companies", c)


def seed_pending_universities() -> None:
    print("\n[12] Pending universities (for UniversityApproval screen)")
    unis = [
        {"name": "Kyoto Institute of Technology", "domain": "kit.ac.jp",    "status": "pending", "country": "Japan",        "contact_email": "international@kit.ac.jp"},
        {"name": "Osaka University",              "domain": "osaka-u.ac.jp","status": "pending", "country": "Japan",        "contact_email": "global@osaka-u.ac.jp"},
        {"name": "Seoul National University",     "domain": "snu.ac.kr",    "status": "pending", "country": "South Korea",  "contact_email": "intl@snu.ac.kr"},
    ]
    for u in unis:
        res = supabase.table("universities").select("id").eq("domain", u["domain"]).execute()
        if res.data:
            skip(f"universities: {u['domain']}")
        else:
            insert_one("universities", u)


def seed_content_flags(job_ids: list[str], student_ids: list[str], admin_uid: str) -> None:
    print("\n[13] Content flags (for ContentModeration screen)")
    if not job_ids or not student_ids:
        fail("content_flags", "need jobs and students")
        return

    flags = [
        {
            "target_id":   job_ids[0],
            "target_type": "job",
            "reason":      "misleading_salary",
            "details":     "Salary range appears inconsistent with similar roles in the market.",
            "status":      "open",
        },
        {
            "target_id":   student_ids[0],
            "target_type": "profile",
            "reason":      "fake_credentials",
            "details":     "GPA listed (4.5/4.0) exceeds maximum possible value.",
            "status":      "open",
        },
        {
            "target_id":   job_ids[1] if len(job_ids) > 1 else job_ids[0],
            "target_type": "job",
            "reason":      "inappropriate_content",
            "details":     "Job description contains discriminatory language regarding age requirements.",
            "status":      "resolved",
            "resolved_by": admin_uid,
            "resolved_at": "2026-03-10T09:00:00Z",
        },
    ]
    for f in flags:
        insert_one("content_flags", f)


def seed_audit_log(admin_uid: str) -> None:
    print("\n[14] Audit log entries (for AuditLogPage screen)")
    entries = [
        {"actor_id": admin_uid, "action": "company.approved",  "target_type": "company",    "metadata": {"company_name": "NexaTech", "reason": "all documents verified"}},
        {"actor_id": admin_uid, "action": "user.suspended",    "target_type": "user",       "metadata": {"reason": "Terms of service violation", "old_status": "active"}},
        {"actor_id": admin_uid, "action": "ai_config.updated", "target_type": "ai_config",  "metadata": {"skill_weight": {"from": 0.35, "to": 0.40}}},
        {"actor_id": admin_uid, "action": "flag.resolved",     "target_type": "flag",       "metadata": {"reason": "inappropriate_content", "resolution": "content removed"}},
        {"actor_id": admin_uid, "action": "university.approved","target_type": "university", "metadata": {"university_name": "University of Tokyo"}},
    ]
    for e in entries:
        insert_one("admin_audit_log", e)


def seed_landing_page(company_id: str) -> None:
    print("\n[9] Company landing page")
    res = supabase.table("company_landing_pages").select("id").eq("company_id", company_id).execute()
    if res.data:
        skip(f"company_landing_pages: {company_id}")
        return
    insert_one("company_landing_pages", {
        "company_id":     company_id,
        "headline":       "Build the Future of Work with NexaTech",
        "subheadline":    "Join a team that's redefining how companies discover top talent across Asia.",
        "hero_image_url": None,
        "sections": [
            {"id": "hero",    "type": "hero",    "title": "Our Mission",    "content": "We believe every talented student deserves a fair shot. NexaTech's AI platform removes bias and surfaces talent based on skills.",               "visible": True},
            {"id": "about",   "type": "about",   "title": "Who We Are",     "content": "Founded in 2018, NexaTech has grown to 700+ employees across Tokyo, Seoul, and Singapore. We partner with 150+ universities.",                    "visible": True},
            {"id": "culture", "type": "culture", "title": "Life at NexaTech","content": "Engineers ship to production on day one. PMs own their product area end-to-end. Annual learning budget and bi-annual retreats.", "visible": True},
        ],
        "cta_text":  "See Open Roles",
        "published": True,
    })


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("NexaTech seed data")
    print("=" * 60)
    print("NOTE: Make sure migrations 005 and 006 have been applied")
    print("      in the Supabase SQL Editor before running this.")
    print("=" * 60)

    admin_uid = seed_company_admin()
    if not admin_uid:
        print("\n⚠  Could not create company admin — aborting.")
        sys.exit(1)

    company_id = seed_company(admin_uid)
    if not company_id:
        print("\n⚠  Could not create company — aborting.")
        sys.exit(1)

    university_id = seed_university()
    if not university_id:
        print("\n⚠  Could not create university — aborting.")
        sys.exit(1)

    student_ids = seed_students(university_id)

    job_ids = seed_jobs(company_id, admin_uid)

    if student_ids and job_ids:
        seed_applications(job_ids, student_ids)

    if job_ids and student_ids:
        seed_ai_matching(job_ids[0], admin_uid, student_ids)

    if company_id:
        seed_landing_page(company_id)

    platform_admin_uid = seed_platform_admin()
    seed_pending_companies(platform_admin_uid)
    seed_pending_universities()
    if job_ids and student_ids and platform_admin_uid:
        seed_content_flags(job_ids, student_ids, platform_admin_uid)
        seed_audit_log(platform_admin_uid)

    print("\n" + "=" * 60)
    print("Seed complete!")
    print()
    print("── Company Admin ─────────────────────────────")
    print("  Email:    admin@nexatech.co.jp")
    print("  Password: Password123!")
    print()
    print("── Platform Admin (super_admin) ──────────────")
    print("  Email:    superadmin@intern2job.com")
    print("  Password: Password123!")
    print()
    print("Supabase project:")
    print(f"  {SUPABASE_URL}")
    print("=" * 60)


if __name__ == "__main__":
    main()
