"""
Vercel entrypoint for the dashboard half of this project only (see
README "Deployment"). Re-exports the same FastAPI app used locally -
none of the routes it pulls in (app.api -> app.repository/app.mailer/
app.excel/app.auth) import Playwright, so this is safe to run in a
stateless serverless function. Do not import app.scanner or
app.whatsapp_session here or anywhere reachable from this file - both
require a persistent disk and a real browser that Vercel cannot provide.
"""

from app.api import app  # noqa: F401
