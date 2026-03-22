from flask import Blueprint, request, jsonify
from ..services.supabase_client import supabase, _make_auth_client

auth_bp = Blueprint("auth", __name__)


def _fetch_profile(user_id: str) -> dict:
    """Fetch profile row; returns empty dict if table missing or row not found."""
    try:
        res = (
            supabase.table("profiles")
            .select("full_name, role, avatar_url")
            .eq("id", user_id)
            .single()
            .execute()
        )
        return res.data or {}
    except Exception:
        return {}


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email", "").strip()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    try:
        auth_client = _make_auth_client()
        response = auth_client.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
        user = response.user
        session = response.session
    except Exception:
        return jsonify({"error": "Invalid email or password"}), 401

    profile = _fetch_profile(user.id)

    return jsonify(
        {
            "access_token": session.access_token,
            "refresh_token": session.refresh_token,
            "user": {
                "id": user.id,
                "email": user.email,
                "name": profile.get("full_name") or user.user_metadata.get("full_name", ""),
                "role": profile.get("role") or user.user_metadata.get("role", "student"),
                "avatar_url": profile.get("avatar_url", ""),
            },
        }
    )


@auth_bp.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()
    email = data.get("email", "").strip()
    password = data.get("password", "")
    name = data.get("name", "").strip()
    role = data.get("role", "student")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    allowed_roles = {"student", "recruiter", "company_admin", "university_admin", "university"}
    if role not in allowed_roles:
        role = "student"

    try:
        auth_client = _make_auth_client()
        response = auth_client.auth.sign_up(
            {
                "email": email,
                "password": password,
                "options": {"data": {"full_name": name, "role": role}},
            }
        )
        user = response.user
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if user:
        # Ensure the profile has the correct role — the DB trigger should
        # already set it (migration 006), but this is a safety net.
        try:
            supabase.table("profiles").update({"role": role, "full_name": name}).eq(
                "id", user.id
            ).execute()
        except Exception:
            pass

        # For recruiter/company_admin roles: ensure a recruiters row exists
        # so that the company API (profiles → recruiters → companies) works.
        if role in ("recruiter", "company_admin"):
            try:
                company_id = None

                if role == "company_admin":
                    # Create a default company for the new admin.
                    company_name = f"{name}'s Company" if name else "My Company"
                    company_res = (
                        supabase.table("companies")
                        .insert({"name": company_name})
                        .execute()
                    )
                    if company_res.data:
                        company_id = company_res.data[0]["id"]

                supabase.table("recruiters").insert(
                    {"id": user.id, "company_id": company_id}
                ).execute()
            except Exception:
                pass

    return jsonify(
        {"message": "Signup successful. Please check your email to verify your account."}
    )


@auth_bp.route("/logout", methods=["POST"])
def logout():
    try:
        _make_auth_client().auth.sign_out()
    except Exception:
        pass
    return jsonify({"message": "Logged out successfully"})


@auth_bp.route("/me", methods=["GET"])
def me():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Unauthorized"}), 401

    token = auth_header.split(" ", 1)[1]

    try:
        user_response = supabase.auth.get_user(token)
        user = user_response.user
    except Exception:
        return jsonify({"error": "Invalid or expired token"}), 401

    profile = _fetch_profile(user.id)

    return jsonify(
        {
            "id": user.id,
            "email": user.email,
            "name": profile.get("full_name") or user.user_metadata.get("full_name", ""),
            "role": profile.get("role") or user.user_metadata.get("role", "student"),
            "avatar_url": profile.get("avatar_url", ""),
        }
    )
