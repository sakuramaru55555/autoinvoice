"""Transform parsed payroll data into MoneyForward invoice API request.

Based on actual invoice format (e.g., invoice #386 for 3/10支給分):
  品目              単価    数量    価格
  業務委託費用      2,500   42      105,000
  業務委託費用      2,700   84.5    228,150
  交通費            11,128  1       11,128     ← スプシの税込額 ÷ 1.1

  小計: 344,278  消費税(10%): 34,427  合計: 378,705
"""

from __future__ import annotations

import math
import re
from datetime import date, timedelta

from autoinvoice.config import Config
from autoinvoice.sheets.parser import PayrollRecord


def _mf_total(subtotal_pretax: int) -> int:
    """Compute total the same way MoneyForward does: subtotal + floor(subtotal * 0.1)."""
    return subtotal_pretax + math.floor(subtotal_pretax * 0.1)


def _find_transport_pretax(
    total_salary: int,
    transport_tax_incl: int,
    grand_total: int,
) -> int:
    """Find the pre-tax transport amount that makes the invoice total
    match the spreadsheet grand_total exactly.

    Strategy: start with transport_tax_incl / 1.1 (rounded), then try
    ±1, ±2 to find the value where:
        _mf_total(total_salary + transport_pretax) == grand_total

    This handles 1-yen rounding discrepancies between floor/ceil/round.
    """
    base = round(transport_tax_incl / 1.1)

    # Try base, base±1, base±2
    for offset in [0, 1, -1, 2, -2]:
        candidate = base + offset
        if candidate < 0:
            continue
        if _mf_total(total_salary + candidate) == grand_total:
            return candidate

    # No exact match found — fall back to ceil (original behavior) and warn
    return math.ceil(transport_tax_incl / 1.1)


class InvoiceBuilder:
    """Builds MoneyForward invoice request from payroll data."""

    def __init__(self, config: Config):
        self._config = config

    def build(self, payroll: PayrollRecord, department_id: str) -> dict:
        """Convert PayrollRecord to MF API request body.

        Invoice structure:
        - 業務委託費用: 1 line per sub-section (unit_price=時給, quantity=時間)
        - 交通費: 1 combined line (tax-inclusive amount from spreadsheet ÷ 1.1)
        - All items taxed at 10%
        """
        items = self._build_items(payroll)
        billing_date = self._compute_billing_date(payroll)
        due_date = self._compute_due_date(payroll)

        title = self._config.title_template.format(
            period=payroll.billing_period
        )

        return {
            "department_id": department_id,
            "billing_date": billing_date.isoformat(),
            "due_date": due_date.isoformat(),
            "title": title,
            "payment_condition": self._config.payment_condition,
            "memo": self._config.invoice_note,
            "items": items,
        }

    def _build_items(self, payroll: PayrollRecord) -> list[dict]:
        """Build invoice line items from payroll sub-sections.

        Key rules from actual invoice:
        - 業務委託費用: unit_price=hourly_rate, quantity=total_hours (pre-tax)
        - 交通費: combined across sub-sections, divide by 1.1 (tax-inclusive→pre-tax)
        - All items: excise=ten_percent
        """
        items = []

        # 業務委託費用: one line per sub-section
        for sub in payroll.sub_sections:
            items.append(
                {
                    "name": "業務委託費用",
                    "detail": "",
                    "unit": "時間",
                    "price": sub.hourly_rate,
                    "quantity": float(sub.total_hours),
                    "excise": "ten_percent",
                    "is_deduct_withholding_tax": False,
                }
            )

        # 交通費: combined, convert tax-inclusive to pre-tax
        # Use reverse-calculation to find the exact pre-tax amount that
        # makes the invoice total match the spreadsheet grand_total.
        total_transport_tax_incl = payroll.total_transport
        if total_transport_tax_incl > 0:
            transport_pretax = _find_transport_pretax(
                payroll.total_salary, total_transport_tax_incl, payroll.grand_total
            )
            items.append(
                {
                    "name": "交通費",
                    "detail": "",
                    "unit": "式",
                    "price": transport_pretax,
                    "quantity": 1,
                    "excise": "ten_percent",
                    "is_deduct_withholding_tax": False,
                }
            )

        return items

    def _compute_billing_date(self, payroll: PayrollRecord) -> date:
        """Billing date = period_end of the last sub-section.

        Example: 3/10支給分 with periods 1/21-1/31 and 2/1-2/20
                 → billing_date = 2/20
        """
        if payroll.sub_sections:
            return payroll.sub_sections[-1].period_end
        return date.today()

    def _compute_due_date(self, payroll: PayrollRecord) -> date:
        """Due date = the payment date from the label (e.g., '3/10支給分' → 3/10).

        Falls back to end of next month if label can't be parsed.
        """
        m = re.search(r"(\d{1,2})/(\d{1,2})", payroll.payment_date_label)
        if m:
            month = int(m.group(1))
            day = int(m.group(2))
            # Determine year from billing date
            billing_date = self._compute_billing_date(payroll)
            year = billing_date.year
            # If payment month is before billing month, it's next year
            if month < billing_date.month:
                year += 1
            try:
                return date(year, month, day)
            except ValueError:
                pass

        # Fallback: end of next month
        billing_date = self._compute_billing_date(payroll)
        if billing_date.month == 12:
            next_month = date(billing_date.year + 1, 1, 1)
        else:
            next_month = date(billing_date.year, billing_date.month + 1, 1)
        if next_month.month == 12:
            return date(next_month.year, 12, 31)
        return date(next_month.year, next_month.month + 1, 1) - timedelta(days=1)
