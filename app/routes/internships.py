"""
Internship tracking routes for students.
Mounted at /api/students/me/internships (via students blueprint)
"""

from flask import Blueprint, jsonify, request, g
from app.middleware.auth import require_role
from app.services.internship_service import (
    get_student_internships,
    get_internship_detail,
    complete_milestone,
)

internships_bp = Blueprint("internships", __name__)


@internships_bp.get("/me/internships")
@require_role(["student"])
def list_my_internships():
    """Get all internships for the authenticated student."""
    internships = get_student_internships(g.user_id)
    return jsonify({"data": internships})


@internships_bp.get("/me/internships/<string:internship_id>")
@require_role(["student"])
def get_my_internship(internship_id):
    """Get detailed internship with milestones."""
    intern = get_internship_detail(g.user_id, internship_id)
    if not intern:
        return jsonify({"error": {"code": "INTERNSHIP_NOT_FOUND", "message": "Internship not found"}}), 404
    return jsonify({"data": intern})


@internships_bp.patch("/me/internships/<string:internship_id>/milestones/<string:milestone_id>")
@require_role(["student"])
def update_milestone(internship_id, milestone_id):
    """Mark a student-actionable milestone as completed."""
    result = complete_milestone(g.user_id, internship_id, milestone_id)
    if result is None:
        return jsonify({"error": {"code": "NOT_FOUND", "message": "Internship or milestone not found"}}), 404
    if "error" in result:
        code = result["error"]
        messages = {
            "NOT_ACTIONABLE": "This milestone cannot be updated by students",
            "ALREADY_COMPLETED": "This milestone is already completed",
        }
        return jsonify({"error": {"code": code, "message": messages.get(code, code)}}), 422
    return jsonify({"data": result})
