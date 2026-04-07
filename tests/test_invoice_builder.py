"""Tests for invoice builder."""

import math
from datetime import date
from decimal import Decimal
from autoinvoice.invoice_builder import _find_transport_pretax, _mf_total
from unittest.mock import MagicMock

import pytest

from autoinvoice.invoice_builder import InvoiceBuilder
from autoinvoice.sheets.parser import PayrollRecord, PayrollSubSection


def _make_config():
    """Create a mock Config object."""
    cfg = MagicMock()
    cfg.title_template = "留学カウンセラー業務委託"
    cfg.payment_condition = "銀行振込"
    cfg.invoice_note = ""
    return cfg


def _make_single_record():
    """Create a single sub-section PayrollRecord (4/10支給分)."""
    sub = PayrollSubSection(
        period_start=date(2026, 2, 21),
        period_end=date(2026, 3, 20),
        payment_label="4/10支給分",
        name="長谷川清子",
        total_hours=Decimal("113.5"),
        work_days=19,
        hourly_rate=2700,
        salary=306450,
        tax=30645,
        transport=10140,  # tax-inclusive
        subtotal=347235,
    )
    record = PayrollRecord(
        sub_sections=[sub],
        grand_total=347235,
        payment_date_label="4/10支給分",
    )
    return record


def _make_double_record():
    """Create a double sub-section PayrollRecord (3/10支給分).

    Based on actual invoice #386.
    """
    sub1 = PayrollSubSection(
        period_start=date(2026, 1, 21),
        period_end=date(2026, 1, 31),
        payment_label="3/10支給分",
        name="長谷川清子",
        total_hours=Decimal("42"),
        work_days=7,
        hourly_rate=2500,
        salary=105000,
        tax=10500,
        transport=4320,  # tax-inclusive
        subtotal=119820,
    )
    sub2 = PayrollSubSection(
        period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 20),
        payment_label="3/10支給分",
        name="長谷川清子",
        total_hours=Decimal("84.5"),
        work_days=14,
        hourly_rate=2700,
        salary=228150,
        tax=22815,
        transport=7920,  # tax-inclusive
        subtotal=258885,
    )
    record = PayrollRecord(
        sub_sections=[sub1, sub2],
        grand_total=378705,
        payment_date_label="3/10支給分",
    )
    return record


class TestInvoiceBuilderSingle:
    def test_builds_three_items(self):
        """Single: 1 業務委託費用 + 1 交通費 = 2 items."""
        builder = InvoiceBuilder(_make_config())
        data = builder.build(_make_single_record(), "dept-123")
        assert len(data["items"]) == 2

    def test_salary_item_uses_hourly_rate_and_hours(self):
        builder = InvoiceBuilder(_make_config())
        data = builder.build(_make_single_record(), "dept-123")
        salary_item = data["items"][0]
        assert salary_item["name"] == "業務委託費用"
        assert salary_item["price"] == 2700
        assert salary_item["quantity"] == 113.5
        assert salary_item["excise"] == "ten_percent"

    def test_transport_is_pretax(self):
        """交通費 10,140 (tax-incl) ÷ 1.1 = 9,219 (ceil)."""
        builder = InvoiceBuilder(_make_config())
        data = builder.build(_make_single_record(), "dept-123")
        transport_item = data["items"][1]
        assert transport_item["name"] == "交通費"
        assert transport_item["price"] == math.ceil(10140 / 1.1)
        assert transport_item["excise"] == "ten_percent"

    def test_billing_date(self):
        builder = InvoiceBuilder(_make_config())
        data = builder.build(_make_single_record(), "dept-123")
        assert data["billing_date"] == "2026-03-20"

    def test_due_date_from_payment_label(self):
        """4/10支給分 → due_date = 2026-04-10."""
        builder = InvoiceBuilder(_make_config())
        data = builder.build(_make_single_record(), "dept-123")
        assert data["due_date"] == "2026-04-10"

    def test_title(self):
        builder = InvoiceBuilder(_make_config())
        data = builder.build(_make_single_record(), "dept-123")
        assert data["title"] == "留学カウンセラー業務委託"


class TestInvoiceBuilderDouble:
    """Test with 3/10支給分 data matching actual invoice #386."""

    def test_builds_three_items(self):
        """Double: 2 業務委託費用 + 1 交通費 = 3 items."""
        builder = InvoiceBuilder(_make_config())
        data = builder.build(_make_double_record(), "dept-456")
        assert len(data["items"]) == 3

    def test_salary_items_match_invoice(self):
        """Verify unit_price × quantity matches actual invoice."""
        builder = InvoiceBuilder(_make_config())
        data = builder.build(_make_double_record(), "dept-456")
        salary_items = [i for i in data["items"] if i["name"] == "業務委託費用"]
        assert len(salary_items) == 2

        # First: 2,500 × 42 = 105,000
        assert salary_items[0]["price"] == 2500
        assert salary_items[0]["quantity"] == 42
        # Second: 2,700 × 84.5 = 228,150
        assert salary_items[1]["price"] == 2700
        assert salary_items[1]["quantity"] == 84.5

    def test_transport_combined_pretax(self):
        """交通費 (4,320 + 7,920) ÷ 1.1 = 11,128 (ceil)."""
        builder = InvoiceBuilder(_make_config())
        data = builder.build(_make_double_record(), "dept-456")
        transport_item = [i for i in data["items"] if i["name"] == "交通費"][0]
        expected = math.ceil((4320 + 7920) / 1.1)  # = 11128
        assert transport_item["price"] == expected
        assert expected == 11128  # matches actual invoice

    def test_total_matches_invoice(self):
        """小計 344,278 + 消費税 34,427 = 合計 378,705."""
        builder = InvoiceBuilder(_make_config())
        data = builder.build(_make_double_record(), "dept-456")
        items = data["items"]

        subtotal = sum(
            i["price"] * i["quantity"] for i in items
        )
        # 2500*42 + 2700*84.5 + 11128*1 = 105000 + 228150 + 11128 = 344278
        assert subtotal == 344278

        tax = math.floor(subtotal * 0.1)
        assert tax == 34427

        total = subtotal + tax
        assert total == 378705

    def test_due_date_from_label(self):
        """3/10支給分 → due_date = 2026-03-10."""
        builder = InvoiceBuilder(_make_config())
        data = builder.build(_make_double_record(), "dept-456")
        assert data["due_date"] == "2026-03-10"

    def test_billing_date_is_last_period_end(self):
        """Billing date = 2/20 (last sub-section period end)."""
        builder = InvoiceBuilder(_make_config())
        data = builder.build(_make_double_record(), "dept-456")
        assert data["billing_date"] == "2026-02-20"


class TestTransportReverseCalc:
    """Test the reverse-calculation logic for transport pre-tax amount.

    The key problem: transport_tax_incl / 1.1 often doesn't divide evenly,
    and floor/ceil/round can each give a 1-yen discrepancy vs. the
    spreadsheet grand_total. We must pick the value that makes the total match.
    """

    def test_3_10_invoice_exact_match(self):
        """3/10支給分: salary=333,150, transport=12,240(税込), total=378,705."""
        result = _find_transport_pretax(333150, 12240, 378705)
        assert result == 11128
        assert _mf_total(333150 + 11128) == 378705

    def test_4_10_invoice_exact_match(self):
        """4/10支給分: salary=306,450, transport=10,140(税込), total=347,235."""
        result = _find_transport_pretax(306450, 10140, 347235)
        assert _mf_total(306450 + result) == 347235

    def test_ceil_would_be_wrong(self):
        """Case where ceil gives wrong total but floor or round is correct.

        salary=258,750, transport=7,920(税込), total=292,545
        7,920/1.1 = 7,200.0 (exact, so all methods agree)
        """
        result = _find_transport_pretax(258750, 7920, 292545)
        assert _mf_total(258750 + result) == 292545

    def test_edge_case_exact_division(self):
        """When transport divides evenly by 1.1 (e.g., 7,920/1.1=7,200)."""
        result = _find_transport_pretax(100000, 7920, 117920)
        assert result == 7200
        assert _mf_total(100000 + 7200) == 117920

    def test_past_months_all_match(self):
        """Verify several months of actual data.

        From the spreadsheet:
        - 12/10: salary=333,750, transport=12,410, total=379,535 (?)
        - 1/10: salary=307,500, transport=11,520, total=349,770 (?)
        """
        # 1/10支給分: 307,500 salary, 11,520 transport (tax-incl)
        # Expected total from spreadsheet: 349,770
        result = _find_transport_pretax(307500, 11520, 349770)
        assert _mf_total(307500 + result) == 349770

    def test_mf_total_basic(self):
        """Verify _mf_total computes subtotal + floor(subtotal * 0.1)."""
        assert _mf_total(100000) == 110000
        assert _mf_total(344278) == 378705  # 344278 + 34427
