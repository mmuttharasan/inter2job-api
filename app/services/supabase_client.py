import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

# Main client — used for DB queries (tables, storage, etc.).
# WARNING: Do NOT call auth.sign_in_with_password / auth.sign_up on this
# client; those calls mutate the internal session and subsequent
# auth.admin.* operations would send the user JWT instead of the
# service-role key.
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Dedicated admin client — used exclusively for auth.admin.* operations
# (create_user, get_user_by_id, etc.).  Stays clean because no user
# sign-in ever touches it.
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def _make_auth_client() -> Client:
    """Create a fresh Supabase client for user-facing auth (login/signup).

    Each call returns a new client so that sign_in_with_password / sign_up
    don't pollute any shared client's session state.
    """
    return create_client(SUPABASE_URL, SUPABASE_KEY)
