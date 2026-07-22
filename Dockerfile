# Slim base + only the one browser we actually use (p.chromium, never
# firefox/webkit anywhere in this codebase) - the official
# playwright/python image bundles all three (~2.4GB before app deps),
# most of which would just be dead weight here.
FROM python:3.12-slim

WORKDIR /app

# Install deps first (separate layer from app code, so code-only
# changes don't force a reinstall).
COPY requirements.txt requirements-worker.txt ./
RUN pip install --no-cache-dir -r requirements-worker.txt

# `--with-deps` asks Playwright's own installer to figure out and apt-get
# the exact system libraries Chromium needs on this distro, rather than
# hand-maintaining an apt-get list here. PLAYWRIGHT_BROWSERS_PATH pins
# the install to a fixed, chown-able location instead of root's default
# cache dir, since we switch to a non-root user below.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* \
    # ffmpeg is downloaded alongside chromium by default - we never
    # record video. chromium_headless_shell is NOT dead weight despite
    # the name similarity to regular chromium: Playwright actually
    # launches that binary instead of full chromium whenever
    # headless=True is requested (our config's default) - confirmed by
    # testing removal, which broke launch_persistent_context outright.
    && rm -rf /ms-playwright/ffmpeg-*

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
# Create a non-root user matching this host's own uid/gid so the
# bind-mounted ./browser_data volume (owned by the host user) stays
# writable from inside the container with no remapping needed.
ARG UID=1001
ARG GID=1001
RUN groupadd -g ${GID} pwuser \
    && useradd -u ${UID} -g ${GID} -m -s /bin/bash pwuser \
    && mkdir -p /app/browser_data /app/logs \
    && chown -R pwuser:pwuser /app /ms-playwright

USER pwuser

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "worker.run_worker"]
