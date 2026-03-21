"""
Notifications API — /api/notifications/*

Endpoints:
  GET    /api/notifications                — list user's notifications
  GET    /api/notifications/unread-count   — count of unread notifications
  POST   /api/notifications/<id>/read      — mark one notification as read
  POST   /api/notifications/read-all       — mark all as read
"""

from flask import Blueprint, jsonify, request, g
from ..services.supabase_client import supabase
from ..middleware.auth import require_auth

notifications_bp = Blueprint("notifications", __name__)


def _err(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


# ---------------------------------------------------------------------------
# GET /api/notifications
# ---------------------------------------------------------------------------

@notifications_bp.get("/")
@require_auth
def list_notifications():
    """List notifications for the authenticated user."""
    unread_only = request.args.get("unread_only", "").lower() == "true"
    limit = min(100, max(1, int(request.args.get("limit", 20))))
    offset = max(0, int(request.args.get("offset", 0)))

    try:
        query = (
            supabase.table("notifications")
            .select("*")
            .eq("user_id", g.user_id)
        )
        if unread_only:
            query = query.is_("read_at", "null")

        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)
        res = query.execute()
    except Exception as exc:
        return _err("SERVER_ERROR", f"Failed to fetch notifications: {exc}", 500)

    notifications = res.data or []
    return jsonify({
        "data": notifications,
        "meta": {"limit": limit, "offset": offset, "count": len(notifications)},
    })


# ---------------------------------------------------------------------------
# GET /api/notifications/unread-count
# ---------------------------------------------------------------------------

@notifications_bp.get("/unread-count")
@require_auth
def unread_count():
    """Return count of unread notifications for bell badge."""
    try:
        res = (
            supabase.table("notifications")
            .select("id", count="exact")
            .eq("user_id", g.user_id)
            .is_("read_at", "null")
            .execute()
        )
        count = res.count if hasattr(res, "count") and res.count is not None else len(res.data or [])
    except Exception:
        count = 0

    return jsonify({"count": count})


# ---------------------------------------------------------------------------
# POST /api/notifications/<id>/read
# ---------------------------------------------------------------------------

@notifications_bp.post("/<string:notification_id>/read")
@require_auth
def mark_read(notification_id: str):
    """Mark a single notification as read."""
    from datetime import datetime
    try:
        res = (
            supabase.table("notifications")
            .update({"read_at": datetime.utcnow().isoformat()})
            .eq("id", notification_id)
            .eq("user_id", g.user_id)
            .execute()
        )
    except Exception:
        return _err("SERVER_ERROR", "Failed to mark notification as read", 500)

    if not res.data:
        return _err("NOT_FOUND", "Notification not found", 404)

    return jsonify({"data": res.data[0]})


# ---------------------------------------------------------------------------
# POST /api/notifications/read-all
# ---------------------------------------------------------------------------

@notifications_bp.post("/read-all")
@require_auth
def mark_all_read():
    """Mark all unread notifications as read for the current user."""
    from datetime import datetime
    try:
        supabase.table("notifications").update(
            {"read_at": datetime.utcnow().isoformat()}
        ).eq("user_id", g.user_id).is_("read_at", "null").execute()
    except Exception:
        return _err("SERVER_ERROR", "Failed to mark notifications as read", 500)

    return jsonify({"message": "All notifications marked as read"})
