"""MoneyForward invoice creation via API v3."""

from autoinvoice.moneyforward.client import MFClient


def create_invoice(client: MFClient, invoice_data: dict) -> dict:
    """Create an invoice in MoneyForward Cloud Invoice.

    Uses POST /invoice_template_billings (v3 endpoint).
    The old POST /billings endpoint is deprecated and returns 404.

    Args:
        client: MFClient instance.
        invoice_data: Invoice data dict built by InvoiceBuilder.

    Returns:
        API response dict containing the created invoice data,
        including 'id' field for the billing ID.
    """
    resp = client.post("/invoice_template_billings", data=invoice_data)

    # Extract the billing data from the response
    billing = resp.get("data", resp)

    billing_id = billing.get("id", "unknown")
    pdf_url = billing.get("pdf_url", "")

    return {
        "id": billing_id,
        "pdf_url": pdf_url,
        "raw": billing,
    }


def get_invoice(client: MFClient, billing_id: str) -> dict:
    """Retrieve an existing invoice by ID.

    Args:
        client: MFClient instance.
        billing_id: The invoice/billing ID.

    Returns:
        Invoice data dict.
    """
    resp = client.get(f"/invoice_template_billings/{billing_id}")
    return resp.get("data", resp)
