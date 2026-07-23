import base64
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app import repository
from app.auth import CurrentUser, clear_session_cookie, create_session_cookie, get_current_user, get_current_user_optional
from app.config import (
    BASE_DIR,
    DAILY_SEND_CAP,
    MAX_UPLOAD_BYTES,
    MIN_SCAN_INTERVAL_SECONDS,
    RESUME_BUCKET,
    SUPABASE_ANON_KEY,
    SUPABASE_URL,
)
from app.db import get_service_client
from app.excel import export_jobs_xlsx
from app.mailer import send_test_email
from app.models import CommunitySelectIn, MailContentIn, SessionIn, SmtpSettingsIn
from app.upload_parser import parse_uploaded_file

app = FastAPI(title="WhatsApp HR Agent Dashboard")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# ==========================================================
# Security headers
# ==========================================================
# CSP allows exactly the three CDN scripts the templates load
# (Tailwind, HTMX, supabase-js) plus 'unsafe-inline' for our own
# inline <script> blocks (all use addEventListener, not inline
# onclick= attributes - confirmed, but CSP's script-src covers both the
# same way, so this is the honest tradeoff without a template-wide
# nonce refactor). connect-src allows the Supabase project directly,
# since supabase-js in the browser calls it straight from the client
# for login/signup, never through our own backend.

_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
    "img-src 'self' data:; "
    "connect-src 'self' https://*.supabase.co; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = _CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


def _onboarding_step(settings: Optional[dict]) -> str:
    settings = settings or {}

    if not settings.get("smtp_password_encrypted") or not settings.get("resume_storage_path"):
        return "setup"
    if settings.get("whatsapp_session_status") != "connected":
        return "whatsapp"
    if not settings.get("selected_community_name"):
        return "community"
    return "done"


def _dashboard_summary(user_id: str) -> dict:
    settings = repository.get_user_settings(user_id) or {}
    counts = repository.job_counts(user_id)
    upload_sent_today = repository.count_sent_today(user_id, source="upload")
    has_pending_upload = bool(repository.list_pending_job_emails(user_id, source="upload", limit=1))

    return {
        **counts,
        "whatsapp_status": settings.get("whatsapp_session_status", "disconnected"),
        "smtp_configured": bool(settings.get("smtp_password_encrypted")),
        "selected_community": settings.get("selected_community_name"),
        "upload_sent_today": upload_sent_today,
        "daily_send_cap": DAILY_SEND_CAP,
        "upload_remaining_today": max(DAILY_SEND_CAP - upload_sent_today, 0),
        "upload_sending_paused": bool(settings.get("upload_sending_paused")),
        "upload_send_active": bool(repository.get_active_worker_job(user_id, "send_pending_mail")),
        "has_pending_upload": has_pending_upload,
    }


# ==========================================================
# Health
# ==========================================================

@app.get("/health")
def health():
    return {"status": "running"}


@app.get("/")
def index(request: Request):
    user = get_current_user_optional(request)
    if not user:
        return RedirectResponse("/login", status.HTTP_303_SEE_OTHER)

    step = _onboarding_step(repository.get_user_settings(user.id))
    destination = "/dashboard" if step == "done" else "/onboarding"
    return RedirectResponse(destination, status.HTTP_303_SEE_OTHER)


# ==========================================================
# Auth pages + session bridge
# ==========================================================
# Supabase Auth itself runs client-side via supabase-js with the public
# anon key (embedded below) - the backend never sees a password. After
# supabase-js signs a user in, the page POSTs the resulting tokens here
# so we can set an httponly session cookie; the anon/service-role split
# described in Section 4 is preserved because the service role key never
# appears in any template.

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if get_current_user_optional(request):
        return RedirectResponse("/", status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        request, "login.html", {"supabase_url": SUPABASE_URL, "supabase_anon_key": SUPABASE_ANON_KEY}
    )


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    if get_current_user_optional(request):
        return RedirectResponse("/", status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        request, "signup.html", {"supabase_url": SUPABASE_URL, "supabase_anon_key": SUPABASE_ANON_KEY}
    )


@app.post("/auth/session")
def create_session(payload: SessionIn, response: Response):
    create_session_cookie(response, payload.access_token, payload.refresh_token)
    return {"ok": True}


@app.post("/auth/logout")
def logout():
    response = RedirectResponse("/login", status.HTTP_303_SEE_OTHER)
    clear_session_cookie(response)
    return response


# ==========================================================
# Onboarding + Settings pages
# ==========================================================

@app.get("/onboarding", response_class=HTMLResponse)
def onboarding_page(request: Request):
    user = get_current_user_optional(request)
    if not user:
        return RedirectResponse("/login", status.HTTP_303_SEE_OTHER)

    settings = repository.get_user_settings(user.id)
    step = _onboarding_step(settings)

    if step == "done":
        return RedirectResponse("/dashboard", status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        request, "onboarding.html", {"step": step, "settings": settings or {}}
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request):
    user = get_current_user_optional(request)
    if not user:
        return RedirectResponse("/login", status.HTTP_303_SEE_OTHER)

    step = _onboarding_step(repository.get_user_settings(user.id))
    if step != "done":
        return RedirectResponse("/onboarding", status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        request, "dashboard.html", {"summary": _dashboard_summary(user.id)}
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    user = get_current_user_optional(request)
    if not user:
        return RedirectResponse("/login", status.HTTP_303_SEE_OTHER)

    settings = repository.get_user_settings(user.id) or {}
    communities = repository.list_communities(user.id)
    return templates.TemplateResponse(
        request, "settings.html", {"settings": settings, "communities": communities}
    )


# ==========================================================
# HTMX partials
# ==========================================================

@app.get("/partials/jobs-table", response_class=HTMLResponse)
def jobs_table_partial(
    request: Request,
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    user: CurrentUser = Depends(get_current_user),
):
    jobs, total = repository.list_jobs(user.id, status=status_filter, page=page, page_size=20)
    total_pages = max(1, (total + 19) // 20)

    return templates.TemplateResponse(
        request,
        "partials/jobs_table.html",
        {"jobs": jobs, "page": page, "total_pages": total_pages, "status_filter": status_filter or ""},
    )


@app.get("/partials/activity-feed", response_class=HTMLResponse)
def activity_feed_partial(request: Request, user: CurrentUser = Depends(get_current_user)):
    activity = repository.list_activity(user.id, limit=50)
    return templates.TemplateResponse(request, "partials/activity_feed.html", {"activity": activity})


@app.get("/partials/summary-cards", response_class=HTMLResponse)
def summary_cards_partial(request: Request, user: CurrentUser = Depends(get_current_user)):
    return templates.TemplateResponse(
        request, "partials/summary_cards.html", {"summary": _dashboard_summary(user.id)}
    )


@app.get("/partials/whatsapp-status", response_class=HTMLResponse)
def whatsapp_status_partial(request: Request, user: CurrentUser = Depends(get_current_user)):
    settings = repository.get_user_settings(user.id) or {}
    return templates.TemplateResponse(
        request,
        "partials/whatsapp_status.html",
        {"status": settings.get("whatsapp_session_status", "disconnected")},
    )


# ==========================================================
# Settings API
# ==========================================================

@app.post("/api/settings/smtp")
def save_smtp_settings(payload: SmtpSettingsIn, user: CurrentUser = Depends(get_current_user)):
    repository.save_smtp_settings(
        user.id,
        smtp_host=payload.smtp_host,
        smtp_port=payload.smtp_port,
        smtp_username=payload.smtp_username,
        smtp_password=payload.smtp_password,
        from_email=payload.from_email,
    )
    return {"ok": True}


@app.post("/api/settings/smtp/test")
def send_smtp_test(payload: SmtpSettingsIn, user: CurrentUser = Depends(get_current_user)):
    try:
        send_test_email(
            user.id,
            {
                "smtp_host": payload.smtp_host,
                "smtp_port": payload.smtp_port,
                "smtp_username": payload.smtp_username,
                "smtp_password": payload.smtp_password,
                "from_email": payload.from_email,
            },
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Test email failed: {exc}") from exc

    return {"ok": True}


@app.post("/api/settings/resume")
def upload_resume(resume: UploadFile = File(...), user: CurrentUser = Depends(get_current_user)):
    content = resume.file.read()

    if content[:5] != b"%PDF-":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is not a valid PDF.")

    storage_path = f"{user.id}/resume.pdf"

    get_service_client().storage.from_(RESUME_BUCKET).upload(
        storage_path,
        content,
        {"content-type": "application/pdf", "upsert": "true"},
    )

    repository.set_resume_path(user.id, storage_path)
    return {"ok": True}


@app.post("/api/settings/community")
def select_community(payload: CommunitySelectIn, user: CurrentUser = Depends(get_current_user)):
    repository.set_selected_community(user.id, payload.community_name)
    return {"ok": True}


@app.post("/api/settings/mail-content")
def save_mail_content(payload: MailContentIn, user: CurrentUser = Depends(get_current_user)):
    repository.save_mail_content(user.id, payload.subject, payload.body)
    return {"ok": True}


# ==========================================================
# WhatsApp connection API
# ==========================================================

@app.post("/api/whatsapp/connect")
def whatsapp_connect(user: CurrentUser = Depends(get_current_user)):
    if repository.get_active_worker_job(user.id, "whatsapp_connect"):
        raise HTTPException(status.HTTP_409_CONFLICT, "A connection attempt is already in progress.")

    repository.create_worker_job(user.id, "whatsapp_connect")
    return {"status": "pending_qr"}


@app.get("/api/whatsapp/status")
def whatsapp_status(user: CurrentUser = Depends(get_current_user)):
    settings = repository.get_user_settings(user.id) or {}
    return {"status": settings.get("whatsapp_session_status", "disconnected")}


@app.get("/api/whatsapp/qr-image")
def whatsapp_qr_image(user: CurrentUser = Depends(get_current_user)):
    qr_b64 = repository.get_qr_image(user.id)
    if not qr_b64:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No QR code available yet.")

    return Response(content=base64.b64decode(qr_b64), media_type="image/png")


@app.post("/api/whatsapp/disconnect")
def whatsapp_disconnect(user: CurrentUser = Depends(get_current_user)):
    if repository.get_active_worker_job(user.id, "whatsapp_disconnect"):
        raise HTTPException(status.HTTP_409_CONFLICT, "A disconnect is already in progress.")

    repository.create_worker_job(user.id, "whatsapp_disconnect")
    return {"status": "disconnecting"}


@app.get("/api/whatsapp/communities")
def whatsapp_communities(user: CurrentUser = Depends(get_current_user)):
    return {"communities": repository.list_communities(user.id)}


# ==========================================================
# Scan API
# ==========================================================

@app.post("/api/scan")
def trigger_scan(user: CurrentUser = Depends(get_current_user)):
    settings = repository.get_user_settings(user.id) or {}
    if not settings.get("selected_community_name"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Select a community before scanning.")
    if settings.get("whatsapp_session_status") != "connected":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "WhatsApp is not connected.")

    if repository.get_active_worker_job(user.id, "scan"):
        raise HTTPException(status.HTTP_409_CONFLICT, "A scan is already in progress.")

    last = repository.get_last_worker_job(user.id, "scan")
    if last and last.get("requested_at"):
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last["requested_at"])).total_seconds()
        if elapsed < MIN_SCAN_INTERVAL_SECONDS:
            wait_for = int(MIN_SCAN_INTERVAL_SECONDS - elapsed)
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS, f"Please wait {wait_for}s before scanning again."
            )

    repository.create_worker_job(user.id, "scan")
    repository.log_activity(user.id, "scan_requested", settings["selected_community_name"])
    return {"status": "queued"}


# ==========================================================
# Jobs / activity / summary API
# ==========================================================

@app.get("/api/jobs")
def api_jobs(
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    user: CurrentUser = Depends(get_current_user),
):
    jobs, total = repository.list_jobs(user.id, status=status_filter, page=page, page_size=20)
    return {"jobs": jobs, "total": total, "page": page}


@app.get("/api/jobs/export")
def api_jobs_export(user: CurrentUser = Depends(get_current_user)):
    buffer = export_jobs_xlsx(user.id)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=jobs.xlsx"},
    )


@app.post("/api/jobs/upload")
def upload_jobs_file(file: UploadFile = File(...), user: CurrentUser = Depends(get_current_user)):
    filename = file.filename or ""

    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"File too large - max {MAX_UPLOAD_BYTES // (1024 * 1024)}MB.",
        )

    try:
        result = parse_uploaded_file(filename, content)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    inserted = 0
    jobs = result["jobs"]
    for i in range(0, len(jobs), 500):
        inserted += repository.insert_jobs(user.id, jobs[i:i + 500], source="upload")

    repository.log_activity(
        user.id,
        "upload_processed",
        f"{result['extracted']} email(s) extracted from {filename}, {inserted} new, "
        f"{result['skipped_unparseable']} row(s) skipped as unparseable.",
    )

    settings = repository.get_user_settings(user.id) or {}
    queued = False
    if (
        inserted > 0
        and not settings.get("upload_sending_paused")
        and not repository.get_active_worker_job(user.id, "send_pending_mail")
    ):
        repository.create_worker_job(user.id, "send_pending_mail")
        queued = True

    return {
        "extracted": result["extracted"],
        "new": inserted,
        "skipped_unparseable": result["skipped_unparseable"],
        "skipped_samples": result["skipped_samples"],
        "queued_for_sending": queued,
    }


@app.post("/api/jobs/send/pause")
def pause_upload_sending(user: CurrentUser = Depends(get_current_user)):
    """
    Stops the uploaded-sheet pipeline at any time: prevents future sends
    from starting (checked in send_pending_emails), and interrupts an
    already-running batch after its current email (see cancel_requested
    in app/mailer.py). WhatsApp-scanned leads are unaffected.
    """

    repository.set_upload_sending_paused(user.id, True)

    active_job = repository.get_active_worker_job(user.id, "send_pending_mail")
    if active_job:
        repository.request_worker_job_cancel(active_job["id"])

    repository.log_activity(user.id, "send_paused", "Uploaded-sheet sending stopped by user.")
    return {"paused": True, "interrupted_running_batch": bool(active_job)}


@app.post("/api/jobs/send/resume")
def resume_upload_sending(user: CurrentUser = Depends(get_current_user)):
    repository.set_upload_sending_paused(user.id, False)
    repository.log_activity(user.id, "send_resumed", "Uploaded-sheet sending resumed by user.")

    queued = False
    has_pending_upload = repository.list_pending_job_emails(user.id, source="upload", limit=1)
    if has_pending_upload and not repository.get_active_worker_job(user.id, "send_pending_mail"):
        repository.create_worker_job(user.id, "send_pending_mail")
        queued = True

    return {"paused": False, "queued_for_sending": queued}


@app.get("/api/activity")
def api_activity(user: CurrentUser = Depends(get_current_user)):
    return {"activity": repository.list_activity(user.id, limit=50)}


@app.get("/api/dashboard/summary")
def api_dashboard_summary(user: CurrentUser = Depends(get_current_user)):
    return _dashboard_summary(user.id)
