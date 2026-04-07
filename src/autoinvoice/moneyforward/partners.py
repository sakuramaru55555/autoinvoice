"""MoneyForward partner (取引先) lookup."""

from __future__ import annotations

from autoinvoice.moneyforward.client import MFClient


def find_partner(client: MFClient, partner_name: str) -> dict:
    """Find a partner by name.

    Lists all partners and matches by name (the /partners endpoint
    does not support a query search parameter in v3).
    """
    # Paginate through all partners
    all_partners: list[dict] = []
    page = 1
    while True:
        resp = client.get("/partners", params={"page": page, "per_page": 100})
        partners = resp.get("data", [])
        if not partners:
            break
        all_partners.extend(partners)
        pagination = resp.get("pagination", {})
        if page >= pagination.get("total_pages", 1):
            break
        page += 1

    if not all_partners:
        raise ValueError("取引先が1件も登録されていません")

    # Exact match
    for p in all_partners:
        if p.get("name") == partner_name:
            return p

    # Partial match
    for p in all_partners:
        if partner_name in p.get("name", ""):
            return p

    raise ValueError(f"取引先 '{partner_name}' が見つかりませんでした")


def get_department(
    client: MFClient,
    partner_id: str,
    department_name: str | None = None,
) -> dict:
    """Get department info for a partner.

    Returns the full department dict including:
      id, email, cc_emails, person_name, person_dept, etc.
    """
    resp = client.get(f"/partners/{partner_id}")

    partner = resp.get("data", resp)
    departments = partner.get("departments", [])

    if not departments:
        raise ValueError(
            f"取引先 (ID: {partner_id}) に部門が登録されていません"
        )

    # If department_name specified, try to match by person_dept field
    if department_name:
        for dept in departments:
            if dept.get("person_dept") == department_name:
                return dept
            if dept.get("name") == department_name:
                return dept

    return departments[0]


def get_department_id(
    client: MFClient,
    partner_id: str,
    department_name: str | None = None,
) -> str:
    """Get the department ID for a partner (convenience wrapper)."""
    return get_department(client, partner_id, department_name)["id"]
