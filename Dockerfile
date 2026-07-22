# Bundles Chromium + all its apt-level system dependencies pre-baked,
# matching the exact Playwright pip version pinned in
# requirements-worker.txt - avoids hand-maintaining an apt-get list on
# a plain python:3.12 base.
FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

WORKDIR /app

# Install deps first (separate layer from app code, so code-only
# changes don't force a reinstall).
COPY requirements.txt requirements-worker.txt ./
RUN pip install --no-cache-dir -r requirements-worker.txt

COPY app/ ./app/
COPY worker/ ./worker/
COPY templates/ ./templates/
# templates/ is needed here too: the worker (via app.scanner ->
# app.mailer.send_pending_emails) reads templates/mail.html at runtime
# for the default email body when a user hasn't set custom mail content.

# Chromium refuses to launch as root without --no-sandbox, and neither
# launch_persistent_context() call in app/scanner.py or
# app/whatsapp_session.py passes that flag (intentionally - it would
# weaken Chromium's renderer sandbox against untrusted web content).
# The base image already ships a non-root "pwuser" at uid/gid 1001:1001,
# which happens to match this host's own user - so the bind-mounted
# ./browser_data volume (owned by the host user) stays writable from
# inside the container with no uid remapping needed.
RUN mkdir -p /app/browser_data /app/logs \
    && chown -R pwuser:pwuser /app

USER pwuser

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "worker.run_worker"]
