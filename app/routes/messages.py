"""
Messages API — /api/messages/*

Endpoints:
  GET   /api/messages/conversations                      — list all conversations
  GET   /api/messages/conversations/{id}                 — messages in a conversation
  POST  /api/messages                                    — send a message
  PATCH /api/messages/conversations/{id}/read            — mark as read
"""

from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, g
from ..middleware.auth import require_auth
from ..services.supabase_client import supabase

messages_bp = Blueprint("messages", __name__)


def _err(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _conv_id(uid1: str, uid2: str) -> str:
    """Deterministic conversation ID from two user IDs (sorted, joined)."""
    parts = sorted([uid1, uid2])
    return f"{parts[0]}:{parts[1]}"


def _display_name(profile) -> str:
    if not profile:
        return "Unknown"
    return profile.get("full_name") or "Unknown"


# ── Role-based contact rules ───────────────────────────────────────────────
# super_admin   → anyone
# recruiter     → super_admin only
# university_admin → super_admin only
# student       → their university_admin(s) + super_admin

def _can_message(sender_role: str, sender_profile: dict,
                 receiver_role: str, receiver_profile: dict) -> bool:
    """Return True if sender is allowed to message receiver."""
    if sender_role == "super_admin":
        return True
    if sender_role in ("recruiter", "company_admin"):
        return receiver_role == "super_admin"
    if sender_role == "university_admin":
        return receiver_role == "super_admin"
    if sender_role == "student":
        if receiver_role == "super_admin":
            return True
        if receiver_role == "university_admin":
            # Same university check
            s_uni = sender_profile.get("university_id")
            r_uni = receiver_profile.get("university_id")
            return bool(s_uni and r_uni and s_uni == r_uni)
        return False
    return False


# ---------------------------------------------------------------------------
# GET /api/messages/contacts  — who can this user message?
# ---------------------------------------------------------------------------

@messages_bp.get("/contacts")
@require_auth
def list_contacts():
    user_id = g.user_id
    role = g.user_role
    profile = g.profile or {}

    try:
        if role == "super_admin" or role == "admin":
            # Can message anyone — return all profiles except self
            res = (
                supabase.table("profiles")
                .select("id, full_name, role, avatar_url, university_id")
                .neq("id", user_id)
                .execute()
            )
        elif role in ("recruiter", "company_admin"):
            # Only super_admins
            res = (
                supabase.table("profiles")
                .select("id, full_name, role, avatar_url, university_id")
                .eq("role", "super_admin")
                .execute()
            )
        elif role == "university_admin":
            # Only super_admins
            res = (
                supabase.table("profiles")
                .select("id, full_name, role, avatar_url, university_id")
                .eq("role", "super_admin")
                .execute()
            )
        elif role == "student":
            uni_id = profile.get("university_id")
            # Super admins
            admins_res = (
                supabase.table("profiles")
                .select("id, full_name, role, avatar_url, university_id")
                .eq("role", "super_admin")
                .execute()
            )
            contacts = admins_res.data or []
            # University admins from the same university
            if uni_id:
                uni_admins_res = (
                    supabase.table("profiles")
                    .select("id, full_name, role, avatar_url, university_id")
                    .eq("role", "university_admin")
                    .eq("university_id", uni_id)
                    .execute()
                )
                contacts += uni_admins_res.data or []
            return jsonify({
                "data": [
                    {
                        "id": p["id"],
                        "name": _display_name(p),
                        "role": p.get("role", "student"),
                        "avatar_url": p.get("avatar_url"),
                    }
                    for p in contacts if p["id"] != user_id
                ]
            })
        else:
            res = type("Obj", (), {"data": []})()

        profiles = res.data or []
        return jsonify({
            "data": [
                {
                    "id": p["id"],
                    "name": _display_name(p),
                    "role": p.get("role", "student"),
                    "avatar_url": p.get("avatar_url"),
                }
                for p in profiles if p["id"] != user_id
            ]
        })
    except Exception as exc:
        return _err("SERVER_ERROR", f"Failed to fetch contacts: {exc}", 500)


# ---------------------------------------------------------------------------
# GET /api/messages/conversations
# ---------------------------------------------------------------------------

@messages_bp.get("/conversations")
@require_auth
def list_conversations():
    user_id = g.user_id

    try:
        # Fetch all messages where user is sender or receiver
        res = (
            supabase.table("messages")
            .select("id, sender_id, receiver_id, body, read_at, created_at")
            .or_(f"sender_id.eq.{user_id},receiver_id.eq.{user_id}")
            .order("created_at", desc=True)
            .execute()
        )
        msgs = res.data or []
    except Exception as exc:
        return _err("SERVER_ERROR", f"Failed to fetch messages: {exc}", 500)

    # Group into conversations by the other participant
    conv_map: dict = {}
    for m in msgs:
        sender = m["sender_id"]
        receiver = m["receiver_id"]
        other_id = receiver if sender == user_id else sender
        cid = _conv_id(user_id, other_id)

        if cid not in conv_map:
            conv_map[cid] = {
                "conversation_id": cid,
                "other_id": other_id,
                "last_message": m["body"],
                "last_message_at": m["created_at"],
                "unread_count": 0,
            }

        # Count unread messages sent TO this user
        if m["receiver_id"] == user_id and not m.get("read_at"):
            conv_map[cid]["unread_count"] += 1

    if not conv_map:
        return jsonify({"data": []})

    # Fetch profiles for the "other" participants
    other_ids = list({v["other_id"] for v in conv_map.values()})
    profile_map: dict = {}
    try:
        pr = supabase.table("profiles").select("id, full_name, role").in_("id", other_ids).execute()
        for p in (pr.data or []):
            profile_map[p["id"]] = p
    except Exception:
        pass

    conversations = []
    for conv in conv_map.values():
        other_id = conv["other_id"]
        other_profile = profile_map.get(other_id, {})
        conversations.append({
            "conversation_id": conv["conversation_id"],
            "with": {
                "id": other_id,
                "name": _display_name(other_profile),
                "role": other_profile.get("role", "student"),
            },
            "last_message": conv["last_message"],
            "last_message_at": conv["last_message_at"],
            "unread_count": conv["unread_count"],
        })

    # Sort by last_message_at desc
    conversations.sort(key=lambda c: c["last_message_at"] or "", reverse=True)
    return jsonify({"data": conversations})


# ---------------------------------------------------------------------------
# GET /api/messages/conversations/{conversation_id}
# ---------------------------------------------------------------------------

@messages_bp.get("/conversations/<path:conversation_id>")
@require_auth
def get_conversation(conversation_id: str):
    user_id = g.user_id

    # Parse the conversation_id to get the other participant
    parts = conversation_id.split(":")
    if len(parts) != 2:
        return _err("INVALID_CONVERSATION", "Invalid conversation ID", 400)

    other_id = parts[1] if parts[0] == user_id else parts[0]

    page  = max(1, int(request.args.get("page", 1)))
    limit = min(100, max(1, int(request.args.get("limit", 50))))

    try:
        # Get all messages between the two users
        res = (
            supabase.table("messages")
            .select("id, sender_id, receiver_id, body, created_at, read_at")
            .or_(
                f"and(sender_id.eq.{user_id},receiver_id.eq.{other_id}),"
                f"and(sender_id.eq.{other_id},receiver_id.eq.{user_id})"
            )
            .order("created_at", desc=False)
            .execute()
        )
        all_msgs = res.data or []
    except Exception as exc:
        return _err("SERVER_ERROR", f"Failed to fetch conversation: {exc}", 500)

    total = len(all_msgs)
    page_msgs = all_msgs[(page - 1) * limit : page * limit]

    return jsonify({
        "data": {
            "conversation_id": conversation_id,
            "messages": [
                {
                    "id": m["id"],
                    "sender_id": m["sender_id"],
                    "body": m["body"],
                    "created_at": m["created_at"],
                    "read_at": m.get("read_at"),
                }
                for m in page_msgs
            ],
        },
        "meta": {"page": page, "limit": limit, "total": total},
    })


# ---------------------------------------------------------------------------
# POST /api/messages
# ---------------------------------------------------------------------------

@messages_bp.post("")
@require_auth
def send_message():
    data = request.get_json(silent=True) or {}
    receiver_id = data.get("receiver_id")
    body = (data.get("body") or "").strip()

    if not receiver_id:
        return _err("VALIDATION_ERROR", "receiver_id is required", 400)
    if not body:
        return _err("VALIDATION_ERROR", "body cannot be empty", 400)

    # Verify receiver exists
    try:
        rx_res = supabase.table("profiles").select("id, role, university_id").eq("id", receiver_id).maybe_single().execute()
    except Exception:
        return _err("NOT_FOUND", "Receiver not found", 404)
    if not rx_res.data:
        return _err("NOT_FOUND", "Receiver not found", 404)

    # Enforce role-based messaging rules
    sender_role = g.user_role or ""
    # Normalize admin alias
    if sender_role == "admin":
        sender_role = "super_admin"
    sender_profile = g.profile or {}
    receiver_profile = rx_res.data
    receiver_role = receiver_profile.get("role", "student")

    if not _can_message(sender_role, sender_profile, receiver_role, receiver_profile):
        return _err("FORBIDDEN", "You are not allowed to message this user", 403)

    now = datetime.now(tz=timezone.utc).isoformat()
    try:
        ins = supabase.table("messages").insert({
            "sender_id": g.user_id,
            "receiver_id": receiver_id,
            "body": body,
            "created_at": now,
        }).execute()
    except Exception as exc:
        return _err("SERVER_ERROR", f"Failed to send message: {exc}", 500)

    msg = (ins.data or [{}])[0]
    return jsonify({
        "data": {
            "id": msg.get("id"),
            "sender_id": g.user_id,
            "receiver_id": receiver_id,
            "body": body,
            "created_at": now,
        }
    }), 201


# ---------------------------------------------------------------------------
# PATCH /api/messages/conversations/{conversation_id}/read
# ---------------------------------------------------------------------------

@messages_bp.patch("/conversations/<path:conversation_id>/read")
@require_auth
def mark_read(conversation_id: str):
    user_id = g.user_id

    parts = conversation_id.split(":")
    if len(parts) != 2:
        return _err("INVALID_CONVERSATION", "Invalid conversation ID", 400)

    other_id = parts[1] if parts[0] == user_id else parts[0]
    now = datetime.now(tz=timezone.utc).isoformat()

    try:
        res = (
            supabase.table("messages")
            .update({"read_at": now})
            .eq("receiver_id", user_id)
            .eq("sender_id", other_id)
            .is_("read_at", "null")
            .execute()
        )
        marked = len(res.data or [])
    except Exception as exc:
        return _err("SERVER_ERROR", f"Failed to mark as read: {exc}", 500)

    return jsonify({"data": {"marked_read": marked}})
