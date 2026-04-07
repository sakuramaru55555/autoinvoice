"""MoneyForward invoice mail sending.

The v3 API may not have a documented mail endpoint.
Strategy:
  1. Try POST /billings/{id}/mail (likely from v2 compatibility)
  2. If that fails, provide the invoice URL for manual sending
"""

from autoinvoice.moneyforward.client import MFClient


def send_invoice_mail(
    client: MFClient,
    billing_id: str,
    to: str,
    cc: str = "",
    subject: str = "",
    body: str = "",
) -> dict:
    """Send an invoice by email via the MoneyForward API.

    Attempts the mail endpoint. If it fails (404), raises an
    exception with instructions for manual sending.

    Args:
        client: MFClient instance.
        billing_id: The billing/invoice ID.
        to: Recipient email address.
        cc: CC email address.
        subject: Email subject.
        body: Email body text.

    Returns:
        API response dict on success.

    Raises:
        RuntimeError: If mail sending is not available via API.
    """
    mail_data = {
        "to": to,
        "cc": cc,
        "subject": subject,
        "body": body,
    }

    try:
        resp = client.post(f"/billings/{billing_id}/mail", data=mail_data)
        return resp
    except Exception as e:
        error_msg = str(e)

        # If 404, the mail endpoint doesn't exist in v3
        if "404" in error_msg:
            raise RuntimeError(
                "MoneyForward API v3 ではメール送信エンドポイントが利用できません。\n"
                "MoneyForwardの管理画面から手動で送信してください:\n"
                f"  https://invoice.moneyforward.com/billings/{billing_id}"
            ) from e

        raise
