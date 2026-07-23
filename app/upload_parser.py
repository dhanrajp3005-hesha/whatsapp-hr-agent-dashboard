"""
Extracts HR email leads from a user-uploaded CSV, Excel (.xlsx), or PDF
file - the same job/email pipeline the WhatsApp scanner feeds, just from
a different source (see app/api.py's /api/jobs/upload).

Cleaning philosophy: fix obvious FORMATTING noise (stray whitespace,
trailing junk after an email, multiple emails jammed in one cell,
markdown-bracket artifacts) - never GUESS at fundamentally broken entries
(no '@' at all, garbled/mangled unicode). A wrong guess would silently
send a resume to a real but wrong mailbox, which is worse than skipping
and reporting it back to the user.
"""

import csv
import io
import re
from datetime import datetime

import openpyxl
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.logger import logger
from app.mailer import is_valid_email
from app.parser import EMAIL_PATTERN

SUPPORTED_EXTENSIONS = {"csv", "xlsx", "pdf"}

MAX_SKIPPED_SAMPLES = 20

# Real-world sheets separate multiple emails in one cell with any of
# these - split on them before running EMAIL_PATTERN, so two emails
# glued with no separator at all can never splice into one
# corrupted-but-valid-shaped hybrid address (worse than skipping, since
# it would look legitimate and silently go to nobody real).
_SEPARATOR_PATTERN = re.compile(r"[|,;]+")


def _extract_from_units(units: list[str]) -> dict:
    """
    Shared core for CSV/XLSX/PDF: given raw per-row/per-line text units,
    returns {"jobs": [...], "extracted": N, "skipped_unparseable": N,
    "skipped_samples": [...]} using the same normalize + in-batch-dedup
    approach as app.parser.extract_jobs, plus per-unit skip reporting
    that function doesn't provide (needed here since the user asked to
    see what got skipped, not just silently drop it).
    """

    jobs = []
    seen = set()
    skipped = 0
    samples = []
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for unit in units:
        if not unit or not unit.strip():
            continue  # blank line/row - not garbage, don't count as skipped

        found_any = False

        for token in _SEPARATOR_PATTERN.split(unit):
            for raw_email in EMAIL_PATTERN.findall(token):
                email = raw_email.lower().strip()

                if not is_valid_email(email):
                    # Belt-and-suspenders: EMAIL_PATTERN's own charset
                    # already guarantees this passes, but guards against
                    # future drift between the two patterns.
                    continue

                found_any = True

                if email in seen:
                    continue

                seen.add(email)
                jobs.append({"date": current_time, "email": email, "status": "Pending"})

        if not found_any:
            skipped += 1
            if len(samples) < MAX_SKIPPED_SAMPLES:
                samples.append(unit.strip()[:80])

    logger.info(
        "upload_parser: extracted %s email(s), skipped %s unparseable unit(s)",
        len(jobs), skipped,
    )

    return {
        "jobs": jobs,
        "extracted": len(jobs),
        "skipped_unparseable": skipped,
        "skipped_samples": samples,
    }


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _units_from_csv(content: bytes) -> list[str]:
    text = _decode_text(content)
    reader = csv.reader(io.StringIO(text))
    return [" ".join(cell for cell in row if cell) for row in reader]


def _units_from_xlsx(content: bytes) -> list[str]:
    # Any failure here (BadZipFile for a non-.xlsx-format file - which is
    # exactly what a legacy .xls upload looks like, since it's a
    # completely different container format - or any other corruption)
    # maps to the same clean message rather than a raw library traceback.
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError(
            "Could not read this Excel file. If it's a legacy .xls file "
            "(Excel 97-2003), save it as .xlsx or .csv instead."
        ) from exc

    sheet = workbook.active
    units = []
    for row in sheet.iter_rows(values_only=True):
        cells = [str(cell) for cell in row if cell is not None]
        units.append(" ".join(cells))
    workbook.close()
    return units


def _units_from_pdf(content: bytes) -> list[str]:
    try:
        reader = PdfReader(io.BytesIO(content))
    except PdfReadError as exc:
        raise ValueError("Could not read this PDF file - it may be corrupted.") from exc

    units = []
    for page in reader.pages:
        text = page.extract_text() or ""
        units.extend(text.splitlines())

    if not units:
        raise ValueError(
            "No text could be extracted from this PDF. If it's a scanned "
            "or photographed document (image only, no text layer), try "
            "uploading a CSV or Excel file instead."
        )

    return units


def parse_uploaded_file(filename: str, content: bytes) -> dict:
    """
    Raises ValueError on unsupported or unparseable input - callers
    (app/api.py) catch this and turn it into a 400, matching the
    existing separation where parsing helpers never raise HTTPException
    themselves.
    """

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError("Upload a .csv, .xlsx, or .pdf file.")

    if ext == "csv":
        units = _units_from_csv(content)
    elif ext == "xlsx":
        units = _units_from_xlsx(content)
    else:
        units = _units_from_pdf(content)

    return _extract_from_units(units)
