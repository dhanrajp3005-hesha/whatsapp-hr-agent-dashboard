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


def export_jobs_xlsx(user_id: str) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Jobs"
    sheet.append(HEADERS)

    for job in repository.list_all_jobs(user_id):
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

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer
