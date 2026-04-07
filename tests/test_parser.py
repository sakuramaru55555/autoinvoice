"""Tests for spreadsheet parser."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from autoinvoice.sheets.parser import (
    PayrollRecord,
    PayrollSubSection,
    _parse_int,
    _parse_decimal,
    _parse_period,
    parse_latest_payroll,
)


# --- Unit tests for helper functions ---


class TestParseInt:
    def test_plain_number(self):
        assert _parse_int("306450") == 306450

    def test_comma_formatted(self):
        assert _parse_int("306,450") == 306450

    def test_large_number(self):
        assert _parse_int("1,234,567") == 1234567

    def test_empty_string(self):
        assert _parse_int("") == 0

    def test_whitespace(self):
        assert _parse_int("  2,700  ") == 2700


class TestParseDecimal:
    def test_integer(self):
        assert _parse_decimal("113") == Decimal("113")

    def test_decimal(self):
        assert _parse_decimal("113.5") == Decimal("113.5")

    def test_comma_formatted(self):
        assert _parse_decimal("1,234.5") == Decimal("1234.5")


class TestParsePeriod:
    def test_standard_period(self):
        result = _parse_period("2026年2月21日〜2026年3月20日")
        assert result == (date(2026, 2, 21), date(2026, 3, 20))

    def test_wave_dash(self):
        result = _parse_period("2025年10月21日~2025年11月20日")
        assert result is not None
        assert result[0] == date(2025, 10, 21)

    def test_no_match(self):
        result = _parse_period("some random text")
        assert result is None


# --- Integration tests for full parsing ---


# Fixture data simulating a single sub-section spreadsheet
SINGLE_SECTION_DATA = [
    ["", "2026年2月21日〜2026年3月20日分", "", "", "", "", "", "", "", ""],
    ["4/10支給分", "", "", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", "", "", ""],
    ["氏 名", "総時間", "出勤 日数", "時給", "給与", "消費税", "交通費", "支給金額合計", "総合計支給金額", ""],
    ["長谷川清子", "113.5", "19", "2,700", "306,450", "30,645", "10,140", "347,235", "347,235", ""],
    ["", "", "", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "出社：13日間", "", "", "", ""],
    ["", "", "", "", "", "テレ：6日間", "", "", "", ""],
    ["", "", "", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", "", "", ""],
]


# Fixture data simulating a double sub-section spreadsheet
DOUBLE_SECTION_DATA = [
    ["", "2026年2月1日〜2026年2月20日分", "", "", "", "", "", "", "", ""],
    ["3/10支給分", "", "", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", "", "", ""],
    ["氏 名", "総時間", "出勤 日数", "時給", "給与", "消費税", "交通費", "支給金額合計", "", ""],
    ["長谷川清子", "84.5", "14", "2,700", "228,150", "22,815", "7,920", "258,885", "", ""],
    ["", "", "", "", "", "出社：11日間", "", "", "", ""],
    ["", "", "", "", "", "テレ：3日間", "", "", "", ""],
    ["", "", "", "", "", "", "", "", "", ""],
    ["", "2026年1月21日〜2026年1月31日分", "", "", "", "", "", "", "", ""],
    ["3/10支給分", "", "", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", "", "", ""],
    ["氏 名", "総時間", "出勤 日数", "時給", "給与", "消費税", "交通費", "支給金額合計", "総合計支給金額", ""],
    ["長谷川清子", "42", "7", "2,500", "105,000", "10,500", "4,320", "119,820", "378,705", ""],
    ["", "", "", "", "", "出社：6日間", "", "", "", ""],
    ["", "", "", "", "", "テレ：1日間", "", "", "", ""],
    ["", "", "", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", "", "", ""],
]


class TestParseSingleSection:
    def test_parse_basic(self):
        record = parse_latest_payroll(SINGLE_SECTION_DATA)
        assert len(record.sub_sections) == 1
        assert record.payment_date_label == "4/10支給分"
        assert record.grand_total == 347235

    def test_subsection_values(self):
        record = parse_latest_payroll(SINGLE_SECTION_DATA)
        sub = record.sub_sections[0]
        assert sub.name == "長谷川清子"
        assert sub.period_start == date(2026, 2, 21)
        assert sub.period_end == date(2026, 3, 20)
        assert sub.total_hours == Decimal("113.5")
        assert sub.work_days == 19
        assert sub.hourly_rate == 2700
        assert sub.salary == 306450
        assert sub.tax == 30645
        assert sub.transport == 10140
        assert sub.subtotal == 347235

    def test_attendance_info(self):
        record = parse_latest_payroll(SINGLE_SECTION_DATA)
        sub = record.sub_sections[0]
        assert sub.office_days == 13
        assert sub.remote_days == 6

    def test_billing_period(self):
        record = parse_latest_payroll(SINGLE_SECTION_DATA)
        assert "2026年2月21日" in record.billing_period
        assert "3月20日" in record.billing_period

    def test_is_not_double(self):
        record = parse_latest_payroll(SINGLE_SECTION_DATA)
        assert not record.is_double


class TestParseDoubleSection:
    def test_parse_two_subsections(self):
        record = parse_latest_payroll(DOUBLE_SECTION_DATA)
        assert len(record.sub_sections) == 2
        assert record.is_double

    def test_grand_total(self):
        record = parse_latest_payroll(DOUBLE_SECTION_DATA)
        assert record.grand_total == 378705

    def test_first_subsection(self):
        record = parse_latest_payroll(DOUBLE_SECTION_DATA)
        sub1 = record.sub_sections[0]
        assert sub1.salary == 228150
        assert sub1.hourly_rate == 2700

    def test_second_subsection(self):
        record = parse_latest_payroll(DOUBLE_SECTION_DATA)
        sub2 = record.sub_sections[1]
        assert sub2.salary == 105000
        assert sub2.hourly_rate == 2500

    def test_total_properties(self):
        record = parse_latest_payroll(DOUBLE_SECTION_DATA)
        assert record.total_salary == 228150 + 105000
        assert record.total_tax == 22815 + 10500
        assert record.total_transport == 7920 + 4320


class TestPayrollSubSection:
    def test_period_str(self):
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
            transport=10140,
            subtotal=347235,
        )
        assert sub.period_str == "2/21〜3/20"
