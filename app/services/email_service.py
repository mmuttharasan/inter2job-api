"""
Email Service — sends transactional emails via Resend.

Configure in .env:
  RESEND_API_KEY   — Resend API key (starts with re_...)
  RESEND_FROM_EMAIL — verified sender address (e.g. noreply@yourdomain.com)
  FRONTEND_URL      — full URL of the frontend app (e.g. https://app.interntojob.com)
"""

import os
import requests as http

RESEND_API_KEY    = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM       = os.environ.get("RESEND_FROM_EMAIL", "InternToJob <noreply@interntojob.com>")
FRONTEND_URL      = os.environ.get("FRONTEND_URL", "http://localhost:5173")

_RESEND_ENDPOINT  = "https://api.resend.com/emails"


def _send(to: str, subject: str, html: str) -> bool:
    """Low-level send via Resend REST API. Returns True on success."""
    if not RESEND_API_KEY:
        # Not configured — log and skip silently in dev
        print(f"[email_service] RESEND_API_KEY not set. Skipping email to {to}")
        return False
    try:
        resp = http.post(
            _RESEND_ENDPOINT,
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"from": RESEND_FROM, "to": [to], "subject": subject, "html": html},
            timeout=10,
        )
        if resp.status_code >= 300:
            print(f"[email_service] Resend error {resp.status_code}: {resp.text[:200]}")
        return resp.status_code < 300
    except Exception as exc:
        print(f"[email_service] Request failed: {exc}")
        return False


# ─── Email templates ─────────────────────────────────────────────────────────

def send_company_admin_welcome(
    to_email: str,
    admin_name: str,
    company_name: str,
    temp_password: str,
) -> bool:
    """
    Send welcome email to a newly-created company admin with their login credentials.
    """
    login_url = f"{FRONTEND_URL}/login"
    greeting = f"Hi {admin_name}," if admin_name else "Hi there,"

    html = f"""
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,sans-serif;">
  <div style="max-width:580px;margin:40px auto;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #e2e8f0;">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#4f46e5,#7c3aed);padding:36px 32px;text-align:center;">
      <div style="display:inline-flex;align-items:center;justify-content:center;width:48px;height:48px;background:rgba(255,255,255,0.2);border-radius:12px;margin-bottom:16px;">
        <span style="font-size:24px;">⚡</span>
      </div>
      <h1 style="color:#ffffff;margin:0;font-size:22px;font-weight:700;">Welcome to InternToJob</h1>
      <p style="color:#c7d2fe;margin:8px 0 0;font-size:14px;">Your company account is ready</p>
    </div>

    <!-- Body -->
    <div style="padding:36px 32px;">
      <p style="color:#1e293b;font-size:16px;margin:0 0 8px;">{greeting}</p>
      <p style="color:#475569;font-size:14px;line-height:1.7;margin:0 0 24px;">
        Your company <strong style="color:#1e293b;">{company_name}</strong> has been successfully
        registered on InternToJob. Log in with the credentials below to complete your company
        profile and start posting internship opportunities.
      </p>

      <!-- Credentials box -->
      <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:24px;margin-bottom:28px;">
        <p style="color:#64748b;font-size:12px;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;margin:0 0 12px;">
          Your Login Credentials
        </p>
        <table style="width:100%;border-collapse:collapse;font-size:14px;">
          <tr>
            <td style="color:#64748b;padding:6px 0;width:40%;">Email address</td>
            <td style="color:#1e293b;font-weight:600;padding:6px 0;">{to_email}</td>
          </tr>
          <tr>
            <td style="color:#64748b;padding:6px 0;">Temporary password</td>
            <td style="padding:6px 0;">
              <code style="background:#e0e7ff;color:#3730a3;padding:4px 10px;border-radius:6px;font-size:14px;font-weight:700;letter-spacing:0.05em;">
                {temp_password}
              </code>
            </td>
          </tr>
        </table>
      </div>

      <!-- CTA -->
      <div style="text-align:center;margin-bottom:28px;">
        <a href="{login_url}"
           style="display:inline-block;background:#4f46e5;color:#ffffff;padding:14px 32px;border-radius:10px;text-decoration:none;font-size:14px;font-weight:700;">
          Log In to Your Account →
        </a>
      </div>

      <!-- Steps -->
      <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:18px 20px;">
        <p style="color:#166534;font-size:13px;font-weight:700;margin:0 0 10px;">Next Steps</p>
        <ol style="color:#15803d;font-size:13px;line-height:1.8;margin:0;padding-left:18px;">
          <li>Log in and change your password</li>
          <li>Complete your company profile (logo, description, values)</li>
          <li>Post your first internship opportunity</li>
          <li>Review AI-matched student candidates</li>
        </ol>
      </div>
    </div>

    <!-- Footer -->
    <div style="border-top:1px solid #e2e8f0;padding:20px 32px;text-align:center;">
      <p style="color:#94a3b8;font-size:12px;margin:0;">
        Please change your temporary password after your first login.
        If you did not expect this email, please contact
        <a href="mailto:support@interntojob.com" style="color:#6366f1;">support@interntojob.com</a>.
      </p>
    </div>

  </div>
</body>
</html>
"""

    subject = f"Your {company_name} account on InternToJob is ready"
    return _send(to_email, subject, html)
