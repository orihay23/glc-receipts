"""
Generate a PDF donation receipt from donor data using WeasyPrint.
"""

import os
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS


TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

_jinja_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))


def generate_receipt_pdf(donor: dict, year: int) -> bytes:
    """
    Render the receipt HTML template and convert to PDF bytes.

    donor dict shape:
        name: str
        email: str | None
        total: float
        transactions: list of {date, description, amount}
    """
    template = _jinja_env.get_template("receipt.html")

    context = {
        "donor_name": donor["name"],
        "year": year,
        "total": donor["total"],
        "transactions": donor.get("transactions", []),
        "generated_date": datetime.now().strftime("%B %d, %Y"),
        "org_name": os.environ.get("ORG_NAME", "Our Organisation"),
        "org_address": os.environ.get("ORG_ADDRESS", ""),
        "org_charity_number": os.environ.get("ORG_CHARITY_NUMBER", ""),
        "org_email": os.environ.get("ORG_EMAIL", ""),
    }

    html_content = template.render(**context)
    pdf_bytes = HTML(string=html_content, base_url=TEMPLATES_DIR).write_pdf()
    return pdf_bytes
