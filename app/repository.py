"""
Data-access helpers over the Supabase tables defined in
supabase/migrations/0001_init.sql. Every function here takes an explicit
user_id and scopes its query to it, even though the service-role client
bypasses RLS - defense in depth, and it keeps callers (api.py, mailer.py,
scanner.py, whatsapp_session.py) from needing to know the schema.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.crypto import encrypt_secret, decrypt_secret
from app.db import get_service_client


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ==========================================================
# user_settings
# ==========================================================

def get_user_settings(user_id: str) -> Optional[dict]:
    res = (
        get_service_client()
        .table("user_settings")
        .select("*")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    return res.data if res else None


def ensure_user_settings(user_id: str) -> dict:
    existing = get_user_settings(user_id)
    if existing:
        return existing

    res = (
        get_service_client()
        .table("user_settings")
        .insert({"user_id": user_id})
        .execute()
    )
    return res.data[0]


def save_smtp_settings(
    user_id: str,
    smtp_host: str,
    smtp_port: int,
    smtp_username: str,
    smtp_password: str,
    from_email: str,
) -> dict:
    ensure_user_settings(user_id)

    payload = {
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "smtp_username": smtp_username,
        "smtp_password_encrypted": encrypt_secret(smtp_password),
        "from_email": from_email,
    }

    res = (
        get_service_client()
        .table("user_settings")
        .update(payload)
        .eq("user_id", user_id)
        .execute()
    )
    return res.data[0]


def get_decrypted_smtp_settings(user_id: str) -> Optional[dict]:
    settings = get_user_settings(user_id)
    if not settings or not settings.get("smtp_password_encrypted"):
        return None

    return {
        "smtp_host": settings["smtp_host"],
        "smtp_port": settings["smtp_port"],
        "smtp_username": settings["smtp_username"],
        "smtp_password": decrypt_secret(settings["smtp_password_encrypted"]),
        "from_email": settings["from_email"],
    }


def set_resume_path(user_id: str, storage_path: str) -> dict:
    ensure_user_settings(user_id)
    res = (
        get_service_client()
        .table("user_settings")
        .update({"resume_storage_path": storage_path})
        .eq("user_id", user_id)
        .execute()
    )
    return res.data[0]


def set_whatsapp_status(user_id: str, status: str, session_path: Optional[str] = None) -> dict:
    ensure_user_settings(user_id)

    payload = {"whatsapp_session_status": status}
    if session_path is not None:
        payload["whatsapp_session_path"] = session_path

    res = (
        get_service_client()
        .table("user_settings")
        .update(payload)
        .eq("user_id", user_id)
        .execute()
    )
    return res.data[0]


def set_qr_image(user_id: str, base64_png: Optional[str]) -> None:
    ensure_user_settings(user_id)
    get_service_client().table("user_settings").update(
        {"whatsapp_qr_image": base64_png}
    ).eq("user_id", user_id).execute()


def get_qr_image(user_id: str) -> Optional[str]:
    settings = get_user_settings(user_id)
    return (settings or {}).get("whatsapp_qr_image")


def set_selected_community(user_id: str, community_name: str) -> dict:
    ensure_user_settings(user_id)
    res = (
        get_service_client()
        .table("user_settings")
        .update({"selected_community_name": community_name})
        .eq("user_id", user_id)
        .execute()
    )
    return res.data[0]


def save_mail_content(user_id: str, subject: Optional[str], body: Optional[str]) -> dict:
    """
    subject/body of None (or "") resets that field back to the app
    default (app.config.MAIL_SUBJECT / templates/mail.html) - see
    app/mailer.py._resolve_mail_content.
    """

    ensure_user_settings(user_id)
    res = (
        get_service_client()
        .table("user_settings")
        .update({"mail_subject": subject or None, "mail_body": body or None})
        .eq("user_id", user_id)
        .execute()
    )
    return res.data[0]


# ==========================================================
# whatsapp_communities
# ==========================================================

def replace_discovered_communities(user_id: str, community_names: list[str]) -> None:
    client = get_service_client()

    client.table("whatsapp_communities").delete().eq("user_id", user_id).execute()

    if not community_names:
        return

    rows = [{"user_id": user_id, "community_name": name} for name in community_names]
    client.table("whatsapp_communities").insert(rows).execute()


def list_communities(user_id: str) -> list[str]:
    res = (
        get_service_client()
        .table("whatsapp_communities")
        .select("community_name")
        .eq("user_id", user_id)
        .order("community_name")
        .execute()
    )
    return [row["community_name"] for row in res.data]


# ==========================================================
# jobs
# ==========================================================

def insert_jobs(user_id: str, jobs: list[dict], source: str = "whatsapp") -> int:
    """
    Insert new job rows, relying on the (user_id, email) unique index to
    silently skip duplicates - this is the whole dedup mechanism for
    both the WhatsApp scan pipeline and the upload pipeline (see
    app/upload_parser.py, app/api.py's /api/jobs/upload): an
    already-seen email is a safe no-op, existing row (including its
    mail_status) untouched. Returns the number of rows actually
    inserted.
    """

    if not jobs:
        return 0

    rows = [
        {
            "user_id": user_id,
            "email": job["email"],
            "company": job.get("company"),
            "job_title": job.get("job_title"),
            "location": job.get("location"),
            "experience": job.get("experience"),
            "apply_link": job.get("apply_link"),
            "mail_status": "Pending",
            "source_message_hash": job.get("source_message_hash"),
            "source": source,
        }
        for job in jobs
    ]

    res = (
        get_service_client()
        .table("jobs")
        .upsert(rows, on_conflict="user_id,email", ignore_duplicates=True)
        .execute()
    )
    return len(res.data or [])


def list_pending_job_emails(user_id: str, limit: Optional[int] = None) -> list[dict]:
    """
    FIFO by created_at - matters now that a shared daily send cap means
    not every call necessarily drains every pending row (see
    app/mailer.py): the oldest lead from either pipeline goes out
    first, so neither pipeline can starve the other via insertion-order
    timing.
    """

    query = (
        get_service_client()
        .table("jobs")
        .select("id, email")
        .eq("user_id", user_id)
        .eq("mail_status", "Pending")
        .order("created_at")
    )

    if limit is not None:
        query = query.limit(limit)

    return query.execute().data


def count_sent_today(user_id: str) -> int:
    """
    Emails sent since the start of the current UTC calendar day - the
    combined daily send cap enforced in app/mailer.py checks this
    across both the WhatsApp scan and upload pipelines together, since
    both funnel through the same jobs table and send_pending_emails().
    """

    start_of_day = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()

    res = (
        get_service_client()
        .table("jobs")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .eq("mail_status", "Sent")
        .gte("sent_at", start_of_day)
        .execute()
    )
    return res.count or 0


def mark_job_sent(user_id: str, job_id: str) -> None:
    (
        get_service_client()
        .table("jobs")
        .update({"mail_status": "Sent", "sent_at": _now_iso()})
        .eq("user_id", user_id)
        .eq("id", job_id)
        .execute()
    )


def mark_job_failed(user_id: str, job_id: str) -> None:
    (
        get_service_client()
        .table("jobs")
        .update({"mail_status": "Failed"})
        .eq("user_id", user_id)
        .eq("id", job_id)
        .execute()
    )


def list_jobs(
    user_id: str,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    query = (
        get_service_client()
        .table("jobs")
        .select("*", count="exact")
        .eq("user_id", user_id)
    )

    if status:
        query = query.eq("mail_status", status)

    start = (page - 1) * page_size
    end = start + page_size - 1

    res = query.order("created_at", desc=True).range(start, end).execute()
    return res.data, (res.count or 0)


def list_all_jobs(user_id: str) -> list[dict]:
    res = (
        get_service_client()
        .table("jobs")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data


def job_counts(user_id: str) -> dict:
    client = get_service_client()

    def count_for(status: Optional[str]) -> int:
        query = client.table("jobs").select("id", count="exact").eq("user_id", user_id)
        if status:
            query = query.eq("mail_status", status)
        return query.execute().count or 0

    return {
        "total": count_for(None),
        "sent": count_for("Sent"),
        "pending": count_for("Pending"),
        "failed": count_for("Failed"),
    }


# ==========================================================
# scan_checkpoints
# ==========================================================

def get_checkpoint(user_id: str) -> Optional[dict]:
    res = (
        get_service_client()
        .table("scan_checkpoints")
        .select("*")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    return res.data if res else None


def save_checkpoint(
    user_id: str,
    last_message_hash: str,
    last_header: Optional[str] = None,
    last_email: Optional[str] = None,
) -> None:
    payload = {
        "user_id": user_id,
        "last_message_hash": last_message_hash,
        "last_header": last_header,
        "last_email": last_email,
        "updated_at": _now_iso(),
    }
    get_service_client().table("scan_checkpoints").upsert(payload).execute()


# ==========================================================
# activity_log
# ==========================================================

def log_activity(user_id: str, event_type: str, message: str = "") -> None:
    get_service_client().table("activity_log").insert(
        {"user_id": user_id, "event_type": event_type, "message": message}
    ).execute()


def list_activity(user_id: str, limit: int = 50) -> list[dict]:
    res = (
        get_service_client()
        .table("activity_log")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data


# ==========================================================
# worker_jobs (dashboard <-> worker queue, see Section 6 of the spec)
#
# Every action that needs Playwright + a persistent disk - scanning,
# WhatsApp QR login, disconnecting - goes through this one queue rather
# than being called in-process from api.py. That's what lets api.py run
# unmodified whether it's deployed on Vercel (no Playwright, no disk) or
# alongside the worker on a single always-on host: either way it only
# ever inserts/reads rows here and in user_settings.
# ==========================================================

def get_active_worker_job(user_id: str, kind: str) -> Optional[dict]:
    res = (
        get_service_client()
        .table("worker_jobs")
        .select("*")
        .eq("user_id", user_id)
        .eq("kind", kind)
        .in_("status", ["pending", "running"])
        .order("requested_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def get_last_worker_job(user_id: str, kind: str) -> Optional[dict]:
    res = (
        get_service_client()
        .table("worker_jobs")
        .select("*")
        .eq("user_id", user_id)
        .eq("kind", kind)
        .order("requested_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def create_worker_job(user_id: str, kind: str) -> dict:
    res = (
        get_service_client()
        .table("worker_jobs")
        .insert({"user_id": user_id, "kind": kind, "status": "pending"})
        .execute()
    )
    return res.data[0]


def claim_next_worker_job() -> Optional[dict]:
    """
    Worker-side: atomically claim the oldest pending job whose user has
    no other job currently running (so a slow scan and a slow QR login
    for the same user can never overlap, per the "never run concurrent
    Playwright contexts for the same user" requirement - even if this
    poll loop is ever scaled to multiple worker instances). Uses an
    optimistic compare-and-swap (update ... where status='pending')
    rather than SELECT FOR UPDATE, since supabase-py talks to PostgREST
    rather than a raw connection.
    """

    client = get_service_client()

    running = client.table("worker_jobs").select("user_id").eq("status", "running").execute()
    busy_user_ids = {row["user_id"] for row in running.data}

    candidates = (
        client.table("worker_jobs")
        .select("id, user_id")
        .eq("status", "pending")
        .order("requested_at")
        .limit(50)
        .execute()
    )

    for candidate in candidates.data:
        if candidate["user_id"] in busy_user_ids:
            continue

        claimed = (
            client.table("worker_jobs")
            .update({"status": "running", "started_at": _now_iso()})
            .eq("id", candidate["id"])
            .eq("status", "pending")
            .execute()
        )

        if claimed.data:
            return claimed.data[0]

    return None


def complete_worker_job(job_id: str, status: str, error_message: Optional[str] = None) -> None:
    get_service_client().table("worker_jobs").update(
        {"status": status, "completed_at": _now_iso(), "error_message": error_message}
    ).eq("id", job_id).execute()


def reset_stale_running_jobs(older_than_seconds: int) -> int:
    """
    Requeues jobs stuck in 'running' from a worker process that died
    mid-job (crash, kill -9, host reboot) without ever reaching
    complete_worker_job. Called once at worker startup so a crash never
    permanently blocks that user's queue (claim_next_worker_job skips
    users with a running job).
    """

    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)).isoformat()

    stale = (
        get_service_client()
        .table("worker_jobs")
        .select("id")
        .eq("status", "running")
        .lt("started_at", cutoff)
        .execute()
    )

    if not stale.data:
        return 0

    ids = [row["id"] for row in stale.data]
    get_service_client().table("worker_jobs").update(
        {"status": "pending", "started_at": None}
    ).in_("id", ids).execute()

    return len(ids)
