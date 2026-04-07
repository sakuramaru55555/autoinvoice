"""Invoice email sending via SendGrid with PDF from MoneyForward.

Flow:
  1. Download invoice PDF from MF API
  2. Send email with PDF attached via SendGrid API

Fully server-side — no browser or MacBook required.
"""

from __future__ import annotations

import base64

import requests
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Attachment,
    Cc,
    ContentId,
    Disposition,
    FileContent,
    FileName,
    FileType,
    Mail,
    To,
)

from autoinvoice.moneyforward.client import MFClient


def download_invoice_pdf(client: MFClient, billing_id: str) -> bytes:
    """Download invoice PDF from MoneyForward API."""
    token = client._auth.get_access_token()
    url = f"https://invoice.moneyforward.com/api/v3/billings/{billing_id}.pdf"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/pdf",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.content


def send_invoice_mail(
    client: MFClient,
    billing_id: str,
    to: str,
    cc: str = "",
    subject: str = "",
    body: str = "",
    sendgrid_api_key: str = "",
    from_email: str = "",
    **kwargs,
) -> dict:
    """Send invoice email with PDF attachment via SendGrid.

    Args:
        client: MFClient instance (for PDF download).
        billing_id: The billing/invoice ID.
        to: Recipient email address.
        cc: CC email addresses (comma-separated).
        subject: Email subject.
        body: Email body text.
        sendgrid_api_key: SendGrid API key.
        from_email: Sender email address.

    Returns:
        dict with status info.
    """
    # Step 1: Download PDF from MF
    pdf_data = download_invoice_pdf(client, billing_id)

    # Step 2: Build SendGrid email
    message = Mail(
        from_email=from_email,
        to_emails=to,
        subject=subject,
        plain_text_content=body,
    )

    # Add CC recipients
    if cc:
        for addr in cc.split(","):
            addr = addr.strip()
            if addr:
                message.add_cc(Cc(addr))

    # Attach PDF
    encoded_pdf = base64.b64encode(pdf_data).decode("utf-8")
    attachment = Attachment(
        FileContent(encoded_pdf),
        FileName(f"invoice_{billing_id}.pdf"),
        FileType("application/pdf"),
        Disposition("attachment"),
    )
    message.attachment = attachment

    # Step 3: Send via SendGrid API
    sg = SendGridAPIClient(sendgrid_api_key)
    response = sg.send(message)

    if response.status_code not in (200, 201, 202):
        raise RuntimeError(
            f"SendGrid送信エラー: status={response.status_code} body={response.body}"
        )

    return {
        "status": "sent",
        "to": to,
        "cc": cc,
        "pdf_size": len(pdf_data),
        "sendgrid_status": response.status_code,
    }
