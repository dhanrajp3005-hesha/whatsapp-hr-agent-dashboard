# WhatsApp HR Agent - Multi-User Dashboard

A multi-tenant web dashboard on top of the original WhatsApp HR Agent
automation. Each user signs up, connects their own WhatsApp Web session,
configures their own SMTP credentials and resume, and picks which
community/group to scan - all backed by Supabase (Postgres + Auth +
Storage) instead of local files.

This is a from-scratch rebuild of the original single-user, file-based
project (`output/jobs.xlsx`, `checkpoint.json`, hardcoded `config.py`
values) into a proper multi-user product. It lives in its own repo
folder, independent of the original local install.

---

## Table of contents

- [Architecture](#architecture)
- [Why two deployment targets](#why-two-deployment-targets)
- [Folder structure](#folder-structure)
- [Setup](#setup)
- [Running locally](#running-locally)
- [Deployment](#deployment)
- [Security notes](#security-notes)
- [Known limitations / open items](#known-limitations--open-items)

---

## Architecture

```
                    ┌─────────────────────────┐
                    │   Browser (any user)    │
                    │  login/signup, settings,│
                    │  dashboard, onboarding   │
                    └────────────┬────────────┘
                                 │ HTTPS
                                 ▼
                    ┌─────────────────────────┐
                    │   FastAPI dashboard      │  <- deploys to Vercel
                    │   app/api.py + templates │     (stateless, no disk,
                    │   (Jinja2 + HTMX)         │      no Playwright)
                    └────────────┬────────────┘
                                 │ reads/writes
                                 ▼
                    ┌─────────────────────────┐
                    │        Supabase          │
                    │  Postgres (RLS) + Auth   │
                    │  + Storage (resumes)      │
                    │  worker_jobs queue table  │
                    └────────────┬────────────┘
                                 │ polls worker_jobs
                                 ▼
                    ┌─────────────────────────┐
                    │   worker/run_worker.py   │  <- always-on host
                    │   app/scanner.py         │     (local machine, VPS,
                    │   app/whatsapp_session.py│      Railway/Render/Fly/
                    │   Playwright + per-user  │      a Docker container)
                    │   browser_data/{user_id} │
                    └─────────────────────────┘
```

The dashboard and the worker never talk to each other directly - they
only ever read/write the same Supabase project. The dashboard inserts
rows into `worker_jobs` (`scan`, `whatsapp_connect`,
`whatsapp_disconnect`) and polls `user_settings` /
`whatsapp_qr_image` for status; the worker polls `worker_jobs`, claims
one at a time per user, and updates the same tables as it progresses.

## Why two deployment targets

Vercel's Python functions are stateless and short-lived - they cannot
keep a logged-in Playwright/Chromium browser profile alive between
requests, and `browser_data/{user_id}/` needs to persist indefinitely
between scans. So:

- **Vercel**: `api/index.py` -> `app.api:app`. Login/signup, onboarding
  forms, settings, jobs table, summary cards, activity feed, Excel
  export. None of these routes import `app.scanner` or
  `app.whatsapp_session`, so no Playwright/Chromium ever needs to run
  in this process.
- **Not Vercel**: `worker/run_worker.py`. Needs a persistent disk and,
  unless `WHATSAPP_HEADLESS=true` (the default), an X display. Run it
  on your local machine, a small always-on VPS/container
  (Railway/Render/Fly.io/a Docker host), or alongside the dashboard on
  a single always-on box if you'd rather not split deployment at all -
  the code doesn't care, since both halves only ever touch Supabase.

If you'd prefer to skip Vercel entirely and just run the dashboard +
worker together on one always-on host, that works with zero code
changes - just run `uvicorn app.api:app` and
`python -m worker.run_worker` as two processes on the same box.

## Folder structure

```
whatsapp-hr-agent-dashboard/
├── app/
│   ├── api.py                # FastAPI app - all HTTP routes (deployed to Vercel)
│   ├── auth.py                # JWT verification + session cookie handling
│   ├── config.py               # Global config only (Supabase, encryption key, defaults)
│   ├── crypto.py                # Fernet encrypt/decrypt for SMTP passwords
│   ├── db.py                     # Supabase client wrapper (service role + anon)
│   ├── repository.py              # All Supabase table reads/writes
│   ├── models.py                    # Pydantic request models
│   ├── mailer.py                     # Per-user SMTP sending (DB-backed)
│   ├── excel.py                       # On-demand jobs export to .xlsx
│   ├── scanner.py                      # Per-user WhatsApp scan (worker-only)
│   ├── whatsapp_session.py              # QR login / disconnect (worker-only)
│   ├── search.py, reader.py, ...          # Playwright helpers (worker-only)
│   └── parser.py                           # Email extraction (unchanged)
├── worker/
│   └── run_worker.py           # Always-on poller: claims worker_jobs, runs them
├── api/
│   └── index.py               # Vercel entrypoint, re-exports app.api:app
├── templates/                # Jinja2 + HTMX pages and partials
├── supabase/migrations/      # SQL: tables, RLS policies, storage bucket
├── vercel.json
└── requirements.txt
```

`browser_data/{user_id}/`, `logs/`, and any local `.env` are created at
runtime and are gitignored - see [Security notes](#security-notes).

## Setup

### 1. Supabase project

1. Create a project at [supabase.com](https://supabase.com).
2. Run the migrations in `supabase/migrations/` against it, in order
   (via the SQL editor, or `supabase db push` if you use the Supabase
   CLI locally).
3. From **Project Settings -> API**, copy:
   - Project URL -> `SUPABASE_URL`
   - `anon` `public` key -> `SUPABASE_ANON_KEY`
   - `service_role` key -> `SUPABASE_SERVICE_ROLE_KEY` (**backend only, never in a template/JS file**)
4. Confirm the `resumes` storage bucket was created (private) by
   migration `0002_storage.sql`.

No JWT secret is needed: `app/auth.py` verifies access tokens by asking
Supabase Auth (`client.auth.get_user(token)`) rather than decoding them
locally, which works whether your project uses the legacy shared HS256
secret or the newer asymmetric JWT signing keys - one less credential
to track down, and one less thing to get subtly wrong.

### 2. Environment

```bash
cp .env.example .env
```

Fill in the Supabase values above, plus:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # -> APP_ENCRYPTION_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"                                  # -> SESSION_SECRET
```

### 3. Python environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # only needed on the machine running the worker
```

## Running locally

Run both processes (they only share state via Supabase, not memory):

```bash
# Terminal 1 - dashboard
uvicorn app.api:app --reload --port 8001

# Terminal 2 - worker (needs Playwright + disk; set WHATSAPP_HEADLESS=false
# for your very first QR scan if you want to watch it happen)
python -m worker.run_worker
```

Visit `http://localhost:8001`, sign up, and follow the onboarding
wizard: SMTP + resume -> WhatsApp QR connect -> pick a community.

Port 8001 is used deliberately (not 8000) so this can run side by side
with an existing single-user instance of the original project during
testing.

## Deployment

**Dashboard (Vercel):**

```bash
vercel --prod
```

Set the same env vars from `.env` in the Vercel project settings
(**except** anything Playwright/worker-specific - the dashboard never
needs `WHATSAPP_HEADLESS` etc.). Point your Vercel domain at this
project as usual.

**Worker (always-on host):**

Run `python -m worker.run_worker` under a process supervisor (systemd,
supervisord, `pm2`, or a Docker container with a restart policy) on
whichever host you choose - a personal machine, a small VPS, or a
platform like Railway/Render/Fly.io. It needs:

- The same `.env` values as the dashboard.
- A persistent volume/disk for `browser_data/`.
- `playwright install chromium` run once during image build/setup.

Only one worker process should run at a time (see
[Known limitations](#known-limitations--open-items)).

## Security notes

- SMTP passwords are Fernet-encrypted at rest (`app/crypto.py`) and
  only ever decrypted in-memory, right before an SMTP connection, in
  `app/mailer.py`. `APP_ENCRYPTION_KEY` lives only in server env vars.
- The Supabase **service role key** is used only in `app/db.py`
  (backend). Templates only ever embed the **anon** key, which is safe
  to expose (it's subject to Row Level Security).
- Every table has RLS enabled with a `auth.uid() = user_id` policy -
  the service-role client bypasses RLS by design, so `app/repository.py`
  still scopes every query to an explicit `user_id` as defense in depth.
- Resume uploads are checked for a real PDF magic byte (`%PDF-`) before
  being stored, not just the file extension.
- `/api/scan` is rate-limited: one active scan per user
  (`worker_jobs` status check) plus a minimum interval between manual
  triggers (`MIN_SCAN_INTERVAL_SECONDS`, default 300s).
- `.env`, `browser_data/`, `output/`, `state/`, and `checkpoint.json`
  are gitignored. The previous repo had `output/jobs.xlsx`,
  `state/state.json`, and `checkpoint.json` committed to git - those
  were removed from tracking as part of this rebuild (see below).

### About `n8n_data/`

`n8n_data/` (an n8n automation runtime directory) was carried over from
the original repo but is **not used by any code in this project** - it
looks like a leftover experiment (a single inactive workflow,
`manualTrigger -> httpRequest`, calling the old `/scan` endpoint). It's
left in place rather than deleted, but flagged here because
`n8n_data/config` contains a plaintext n8n encryption key and
`n8n_data/database.sqlite` has `credentials_entity`/`user` tables - both
committed to git in the original repo. Decide whether to keep, migrate,
or purge this directory (and scrub it from git history if it's ever
pushed anywhere public) before this repo goes anywhere public.

## Known limitations / open items

- **Single worker instance assumed.** `claim_next_worker_job()` uses an
  optimistic compare-and-swap (`update ... where status='pending'`)
  rather than a database-level lock, which is safe with one worker
  process. Running multiple worker instances concurrently would need a
  real `SELECT ... FOR UPDATE` (i.e., a direct Postgres connection
  instead of the PostgREST-based supabase-py client).
- **WhatsApp Web selectors are inherently fragile.** Both
  `app/search.py` (community search/discovery) and the QR/chat-list
  detection in `app/whatsapp_session.py` depend on WhatsApp Web's
  current DOM - as in the original project, these are the first thing
  to check if scanning or connecting stops working after a WhatsApp
  Web UI update.
- **No end-to-end test against a real Supabase project or real
  WhatsApp session was possible while building this** (no live
  credentials available in the build environment). Every module was
  import-checked and the FastAPI app was smoke-tested locally (routing,
  auth/JWT handling, template rendering, redirects) with a dummy
  Supabase project - see the commit history for what that covered.
  Before relying on this, run through Setup above against a real
  Supabase project and confirm signup -> onboarding -> scan -> email
  end-to-end.
