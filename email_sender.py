"""
Send donation receipt PDFs via Gmail SMTP using an App Password.
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders


GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")


def send_receipt_email(to_email: str, donor_name: str, year: int, pdf_bytes: bytes) -> None:
    """
    Send a receipt PDF to a donor via Gmail SMTP.

    Raises smtplib.SMTPException on failure.
    """
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        raise ValueError(
            "GMAIL_USER and GMAIL_APP_PASSWORD environment variables must be set."
        )

    org_name = os.environ.get("ORG_NAME", "Our Organisation")
    subject = f"{org_name} — Your {year} Donation Receipt"

    body_text = (
        f"Dear {donor_name},\n\n"
        f"Thank you for your generous donations to {org_name} during {year}.\n\n"
        f"Please find your tax receipt attached as a PDF.\n\n"
        f"If you have any questions, please don't hesitate to contact us.\n\n"
        f"Kind regards,\n{org_name}"
    )

    body_html = f"""
    <html>
      <body>
        <p>Dear {donor_name},</p>
        <p>Thank you for your generous donations to <strong>{org_name}</strong> during {year}.</p>
        <p>Please find your tax receipt attached as a PDF.</p>
        <p>If you have any questions, please don't hesitate to contact us.</p>
        <p>Kind regards,<br>{org_name}</p>
      </body>
    </html>
    """

    msg = MIMEMultipart("mixed")
    msg["From"] = f"{org_name} <{GMAIL_USER}>"
    msg["To"] = to_email
    msg["Subject"] = subject

    # Attach plain text + HTML body
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(body_text, "plain"))
    alt.attach(MIMEText(body_html, "html"))
    msg.attach(alt)

    # Attach PDF
    attachment = MIMEBase("application", "pdf")
    attachment.set_payload(pdf_bytes)
    encoders.encode_base64(attachment)
    safe_name = donor_name.replace(" ", "_").replace("/", "_")
    attachment.add_header(
        "Content-Disposition",
        "attachment",
        filename=f"{org_name.replace(' ', '_')}_Receipt_{year}_{safe_name}.pdf",
    )
    msg.attach(attachment)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        smtp.sendmail(GMAIL_USER, to_email, msg.as_string())
