<div align="center">

# 📱 WhatsApp HR Agent — Multi-User Dashboard

### A multi-tenant SaaS dashboard that automates job-hunting on WhatsApp

Scans WhatsApp placement communities for job posts, extracts recruiter emails,
and sends your resume automatically — with each user bringing their own
WhatsApp session, SMTP credentials, and resume through a self-serve
onboarding flow.

![Python](https://img.shields.io/badge/Python-3.12-blue?style=for-the-badge&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-Web_Framework-009688?style=for-the-badge&logo=fastapi)
![Supabase](https://img.shields.io/badge/Supabase-Postgres_%2B_Auth-3ECF8E?style=for-the-badge&logo=supabase)
![Playwright](https://img.shields.io/badge/Playwright-Browser_Automation-2EAD33?style=for-the-badge&logo=playwright)
![HTMX](https://img.shields.io/badge/HTMX-Frontend-3D72D7?style=for-the-badge)

</div>

---

## What this is

This started as a personal script that scanned one WhatsApp group and
emailed a resume to any HR contact it found. This repo turns that into
a **proper multi-user product**: anyone can sign up, connect their own
WhatsApp account, and run the same automation for themselves — fully
isolated from every other user's data.

It's a good example of taking a working single-user script and
re-architecting it for multiple tenants under real constraints: no
shared file state, encrypted secrets, database-enforced data isolation,
and a browser-automation workload that can't run on typical serverless
hosting.

## Features

- 🔐 **Email/password auth** via Supabase Auth, session-cookie based
- 🧙 **Guided onboarding** — SMTP setup → WhatsApp QR login → pick a
  community/group to scan
- 📲 **Live QR code login** for WhatsApp Web, streamed to the browser
  via polling — no shared/shell access needed
- 📊 **Dashboard** — job counts, connection status, a filterable jobs
  table, activity feed, and a manual "Scan now" button
- ✉️ **Customizable email content** — per-user subject line and body,
  falling back to a sensible default
- 📥 **One-click Excel export** of your jobs table
- 🛡️ **Full multi-tenant data isolation** via Postgres Row-Level
  Security — not just an app-level `WHERE user_id = ...` filter
- 🔒 **Encrypted credentials at rest** — SMTP passwords are
  Fernet-encrypted, decrypted only in memory, right before use

## Architecture

The interesting engineering problem here: **Vercel's serverless
functions can't keep a logged-in Playwright/Chromium session alive**
(no persistent disk, no long-running processes). But WhatsApp Web
automation fundamentally needs exactly that — a browser profile that
stays logged in indefinitely.

The fix is a **two-process architecture that only communicates through
the database**:

```
                    ┌─────────────────────────┐
                    │   Browser (any user)    │
                    │  login, settings,       │
                    │  dashboard, onboarding   │
                    └────────────┬────────────┘
                                 │ HTTPS
                                 ▼
                    ┌─────────────────────────┐
                    │   FastAPI dashboard      │  ← deploys to Vercel
                    │   (Jinja2 + HTMX)        │    (stateless, no disk,
                    │                          │     no Playwright)
                    └────────────┬────────────┘
                                 │ reads/writes
                                 ▼
                    ┌─────────────────────────┐
                    │        Supabase          │
                    │  Postgres (RLS) + Auth   │
                    │  + Storage (resumes)     │
                    │  worker_jobs queue table │
                    └────────────┬────────────┘
                                 │ polls worker_jobs
                                 ▼
                    ┌─────────────────────────┐
                    │   Always-on worker       │  ← local machine, VPS,
                    │   Playwright + per-user  │    or small container
                    │   browser_data/{user_id} │    host
                    └─────────────────────────┘
```

The dashboard never calls the worker directly (and vice versa). The
dashboard inserts rows into a `worker_jobs` queue table (`scan`,
`whatsapp_connect`, `whatsapp_disconnect`) and polls plain database
columns for status; the worker polls that same queue, claims one job
at a time **per user** (so a user's scan and their WhatsApp login can
never run concurrently), and writes results back to the same tables.
Neither process needs to know the other exists or is reachable — they
just need to agree on a schema.

If you'd rather not split deployment at all, that's fine too — running
`uvicorn app.api:app` and `python -m worker.run_worker` side by side on
one machine works with zero code changes, since both just talk to
Supabase.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Backend | FastAPI | Async-friendly, typed, minimal boilerplate |
| Frontend | Jinja2 + HTMX | Server-rendered, no JS build step, still feels dynamic |
| Database | Supabase (Postgres) | Row-Level Security gives real multi-tenant isolation for free |
| Auth | Supabase Auth | Email/password + JWT sessions without rolling my own |
| Storage | Supabase Storage | Private per-user resume PDFs |
| Browser automation | Playwright | Headless Chromium driving WhatsApp Web |
| Secrets | `cryptography` (Fernet) | Symmetric encryption for stored SMTP passwords |
| Sessions | `itsdangerous` | Signed session cookies |
| Worker coordination | Postgres table as a queue | Simplest thing that works across two independent processes |

## Setup

### 1. Create a Supabase project

1. Go to [supabase.com](https://supabase.com) and create a new project.
2. Open **SQL Editor** → New query, and run each file in
   [`supabase/migrations/`](supabase/migrations/) **in order**
   (`0001_init.sql`, `0002_storage.sql`, `0003_mail_customization.sql`).
   Each one is a single paste-and-run.
3. From **Project Settings → API**, copy three values:
   - **Project URL**
   - **anon / public** key
   - **service_role** key (keep this one secret — never goes in the browser)

That's the only manual setup Supabase needs — no JWT secret to hunt
down, since auth is verified by asking Supabase directly rather than
decoding tokens locally.

### 2. Clone and configure

```bash
git clone https://github.com/dhanrajp3005-hesha/whatsapp-hr-agent-dashboard.git
cd whatsapp-hr-agent-dashboard
cp .env.example .env
```

Open `.env` and fill in the three Supabase values from step 1, plus
generate two local secrets:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # → APP_ENCRYPTION_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"                                 # → SESSION_SECRET
```

### 3. Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium     # only needed on whichever machine runs the worker
```

### 4. Run it

Two processes, in two terminals:

```bash
# Terminal 1 — the dashboard
uvicorn app.api:app --reload --port 8001

# Terminal 2 — the worker (does the actual WhatsApp/Playwright work)
python -m worker.run_worker
```

Open **http://localhost:8001**, sign up, and follow the onboarding
wizard:

1. **Email setup** — SMTP host/port/username/app-password + upload your resume PDF
2. **WhatsApp** — click *Start connection*, scan the QR code with WhatsApp
   (Linked Devices → Link a device)
3. **Community** — pick which group/community to scan from your chat list

Then hit **Scan now** on the dashboard.

## Deployment

**Dashboard → Vercel:**

```bash
vercel --prod
```

Set the same Supabase env vars in the Vercel project settings. `vercel.json`
routes everything through `api/index.py`, which only imports the parts of
the app that never touch Playwright.

**Worker → anywhere with a persistent disk:**

Your own machine, a small VPS, or a container on Railway/Render/Fly.io —
run `python -m worker.run_worker` under a process supervisor (systemd,
`pm2`, or a restart-always Docker container). It needs the same `.env`
and a persistent volume for `browser_data/`.

## Security notes

- SMTP passwords: Fernet-encrypted at rest, decrypted only in memory
  immediately before opening an SMTP connection.
- Service-role key: used only server-side (`app/db.py`); templates only
  ever embed the public anon key.
- Every table has Row-Level Security enabled (`auth.uid() = user_id`),
  in addition to explicit `user_id` filters in application code —
  defense in depth, not reliance on one layer.
- Resume uploads are validated by magic bytes (`%PDF-`), not just file
  extension.
- Manual scans are rate-limited: one active scan per user, plus a
  minimum interval between triggers.

## Known limitations

Being upfront about tradeoffs made under time constraints:

- **Single worker instance assumed.** The job queue uses an optimistic
  compare-and-swap rather than a row-level database lock, which is
  correct for one worker process. Scaling to multiple workers would
  need a real `SELECT ... FOR UPDATE`.
- **WhatsApp Web's DOM is a moving target.** Selectors for the QR
  code, chat list, and community search are all tied to WhatsApp's
  current markup and will need updating if/when WhatsApp ships a UI
  change. During development this actually broke twice — a headless
  browser fingerprint (`HeadlessChrome` in the user-agent) got blocked
  outright, and a "What's new" announcement modal silently intercepted
  every click — both fixed, both documented in the commit history as a
  reminder of where to look first if scanning stops working.
- **No automated test suite yet.** The app was verified by running it
  end-to-end against a real Supabase project and a real WhatsApp
  account (signup → onboarding → QR login → scan → email sent), not by
  unit tests.

## Project structure

```
app/
├── api.py                 # All HTTP routes (dashboard half — deploys to Vercel)
├── auth.py                 # Session/JWT verification
├── db.py, repository.py     # Supabase client + all data access
├── crypto.py                 # Fernet encryption for SMTP passwords
├── mailer.py                  # Per-user email sending
├── scanner.py                  # WhatsApp scan loop (worker-only)
├── whatsapp_session.py          # QR login / disconnect (worker-only)
└── search.py, reader.py, ...     # Playwright DOM helpers (worker-only)
worker/run_worker.py       # Always-on queue poller
api/index.py                # Vercel entrypoint
templates/                   # Jinja2 + HTMX pages
supabase/migrations/           # SQL schema, RLS policies, storage bucket
```

## Author

**Dhanraj P** — Cloud & DevOps Engineer, Chennai, India

AWS · DevOps · Python · Linux · Docker · Kubernetes · Terraform ·
Jenkins · GitHub Actions · Playwright · FastAPI

[GitHub](https://github.com/dhanrajp3005-hesha)
