"""
Certificate routes — public verification + download, and company issuance.
Mounted at /api/certificates
"""

from flask import Blueprint, jsonify, request, g
from app.middleware.auth import require_role
from app.services.internship_service import (
    get_student_certificates,
    verify_certificate,
    issue_certificate,
    get_certificate_for_download,
)

certificates_bp = Blueprint("certificates", __name__)


@certificates_bp.get("/me")
@require_role(["student"])
def list_my_certificates():
    """Get all certificates for the authenticated student."""
    certs = get_student_certificates(g.user_id)
    return jsonify({"data": certs})


@certificates_bp.get("/<string:verification_code>/verify")
def verify(verification_code):
    """Public endpoint — verify a certificate by its code."""
    result = verify_certificate(verification_code)
    if not result:
        return jsonify({"error": {"code": "INVALID_CERTIFICATE", "message": "Certificate not found or invalid."}}), 404
    return jsonify({"data": result})


@certificates_bp.get("/<string:verification_code>/download")
def download(verification_code):
    """Download certificate as JSON (PDF generation handled by frontend)."""
    cert = get_certificate_for_download(verification_code)
    if not cert:
        return jsonify({"error": {"code": "CERTIFICATE_NOT_FOUND", "message": "Certificate not found."}}), 404
    # Return full certificate data for client-side PDF rendering
    cert["verification_url"] = f"/verify/{verification_code}"
    return jsonify({"data": cert})


@certificates_bp.post("/issue/<string:internship_id>")
@require_role(["recruiter", "admin"])
def issue(internship_id):
    """Issue a certificate for a completed internship."""
    data = request.get_json() or {}
    result = issue_certificate(internship_id, g.user_id, data)

    if "error" in result:
        code = result["error"]
        status_map = {
            "INTERNSHIP_NOT_FOUND": 404,
            "INTERNSHIP_NOT_COMPLETED": 422,
            "CERTIFICATE_EXISTS": 422,
        }
        messages = {
            "INTERNSHIP_NOT_FOUND": "Internship not found",
            "INTERNSHIP_NOT_COMPLETED": "Internship must be completed before issuing a certificate",
            "CERTIFICATE_EXISTS": "A certificate has already been issued for this internship",
        }
        return jsonify({"error": {"code": code, "message": messages.get(code, code)}}), status_map.get(code, 400)

    return jsonify({"data": result}), 201
