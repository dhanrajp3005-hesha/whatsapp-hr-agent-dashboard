"""
On-demand Excel export of a user's jobs table (replaces the old
always-on-disk output/jobs.xlsx). Generates the workbook in memory so it
works equally on a persistent-disk worker host or a stateless Vercel
function - nothing is written to disk.
"""

from io import BytesIO

from openpyxl import Workbook

from app import repository

HEADERS = [
    "Date",
    "Company",
    "Job Title",
    "Email",
    "Location",
    "Experience",
    "Apply Link",
    "Mail Status",
]


def _write_sheet(sheet, jobs: list[dict]) -> None:
    sheet.append(HEADERS)
    for job in jobs:
        sheet.append(
            [
                job.get("created_at"),
                job.get("company"),
                job.get("job_title"),
                job.get("email"),
                job.get("location"),
                job.get("experience"),
                job.get("apply_link"),
                job.get("mail_status"),
            ]
        )


def export_jobs_xlsx(user_id: str) -> BytesIO:
    all_jobs = repository.list_all_jobs(user_id)
    whatsapp_jobs = [job for job in all_jobs if job.get("source") == "whatsapp"]
    upload_jobs = [job for job in all_jobs if job.get("source") == "upload"]

    workbook = Workbook()
    workbook.active.title = "WhatsApp Scanned"
    _write_sheet(workbook.active, whatsapp_jobs)
    _write_sheet(workbook.create_sheet("Uploaded Sheet"), upload_jobs)

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer
