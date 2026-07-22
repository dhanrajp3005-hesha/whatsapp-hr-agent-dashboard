from functools import lru_cache

from supabase import create_client, Client

from app.config import (
    SUPABASE_URL,
    SUPABASE_ANON_KEY,
    SUPABASE_SERVICE_ROLE_KEY,
    require_supabase_config,
)


@lru_cache
def get_service_client() -> Client:
    """
    Server-side client authenticated with the service role key.
    Bypasses Row Level Security by design - every call site is
    responsible for scoping its own queries to the intended user_id
    (see app/repository.py, which is the only module that should call
    this directly).
    """

    require_supabase_config()
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


@lru_cache
def get_anon_client() -> Client:
    """
    Client authenticated with the public anon key. Used only for
    validating a user's access token via Supabase Auth
    (client.auth.get_user) and for refreshing sessions - never for
    reading/writing tenant data, which always goes through the service
    client + explicit user_id filters in app/repository.py.
    """

    require_supabase_config()
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
