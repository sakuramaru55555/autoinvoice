from __future__ import annotations

"""Spreadsheet data parser for payroll records.

Handles both single sub-section and double sub-section layouts.

Single sub-section example (4/10支給分):
  Row: "2026年2月21日〜2026年3月20日"
  Row: "4/10支給分"
  Header: 氏名 | 総時間 | 出勤日数 | 時給 | 給与 | 消費税 | 交通費 | 支給金額合計 | 総合計支給金額
  Data:   長谷川清子 | 113.5 | 19 | 2,700 | 306,450 | 30,645 | 10,140 | 347,235 | 347,235

Double sub-section example (3/10支給分):
  Row: "2026年1月21日〜2026年1月31日"
  Row: "3/10支給分"
  Header + Data (sub-section 1)  ...  支給金額合計  |  総合計支給金額
  Row: "2026年2月1日〜2026年2月20日"
  Row: "3/10支給分"
  Header + Data (sub-section 2)  ...  支給金額合計  |  378,705  <-- combined total
"""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

# --- Patterns ---

PERIOD_PATTERN = re.compile(
    r"(\d{4})年(\d{1,2})月(\d{1,2})日[〜~～](\d{4})年(\d{1,2})月(\d{1,2})日"
)

PAYMENT_LABEL_PATTERN = re.compile(r"(\d{1,2})/(\d{1,2})支給分")

HEADER_KEYWORDS = ["氏名", "総時間", "出勤日数", "時給", "給与"]

ATTENDANCE_PATTERN = re.compile(r"出社[：:]\s*(\d+)日")
REMOTE_PATTERN = re.compile(r"テレ[：:]\s*(\d+)日")


# --- Data Classes ---


@dataclass
class PayrollSubSection:
    """One period within a payment (e.g., 1/21-1/31 portion of 3/10支給分)."""

    period_start: date
    period_end: date
    payment_label: str  # e.g., "3/10支給分"
    name: str  # 長谷川清子
    total_hours: Decimal
    work_days: int
    hourly_rate: int
    salary: int  # 給与 (pre-tax)
    tax: int  # 消費税 (10% of salary)
    transport: int  # 交通費
    subtotal: int  # 支給金額合計
    office_days: Optional[int] = None
    remote_days: Optional[int] = None

    @property
    def period_str(self) -> str:
        """Short period label like '2/21〜3/20'."""
        return (
            f"{self.period_start.month}/{self.period_start.day}"
            f"〜{self.period_end.month}/{self.period_end.day}"
        )


@dataclass
class PayrollRecord:
    """Complete payment record, possibly containing 1-2 sub-sections."""

    sub_sections: list[PayrollSubSection] = field(default_factory=list)
    grand_total: int = 0  # 総合計支給金額
    payment_date_label: str = ""  # e.g., "4/10支給分"

    @property
    def total_salary(self) -> int:
        return sum(s.salary for s in self.sub_sections)

    @property
    def total_tax(self) -> int:
        return sum(s.tax for s in self.sub_sections)

    @property
    def total_transport(self) -> int:
        return sum(s.transport for s in self.sub_sections)

    @property
    def billing_period(self) -> str:
        """Combined period string for invoice title."""
        if len(self.sub_sections) == 1:
            s = self.sub_sections[0]
            return (
                f"{s.period_start.year}年{s.period_start.month}月{s.period_start.day}日"
                f"〜{s.period_end.year}年{s.period_end.month}月{s.period_end.day}日"
            )
        first = self.sub_sections[0]
        last = self.sub_sections[-1]
        return (
            f"{first.period_start.year}年{first.period_start.month}月{first.period_start.day}日"
            f"〜{last.period_end.year}年{last.period_end.month}月{last.period_end.day}日"
        )

    @property
    def is_double(self) -> bool:
        return len(self.sub_sections) == 2


# --- Parsing Functions ---


def _parse_int(s: str) -> int:
    """Parse a Japanese-formatted number string to int. '306,450' -> 306450."""
    cleaned = s.replace(",", "").replace("，", "").strip()
    if not cleaned:
        return 0
    return int(cleaned)


def _parse_decimal(s: str) -> Decimal:
    """Parse a decimal number string. '113.5' -> Decimal('113.5')."""
    cleaned = s.replace(",", "").replace("，", "").strip()
    if not cleaned:
        return Decimal(0)
    return Decimal(cleaned)


def _parse_period(text: str) -> tuple[date, date] | None:
    """Extract start and end dates from a period string."""
    m = PERIOD_PATTERN.search(text)
    if not m:
        return None
    start = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    end = date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
    return start, end


def _find_green_section_rows(
    backgrounds: list[list[dict | None]],
    is_green_fn,
) -> tuple[int, int]:
    """Find the row range of the green (latest) section.

    Returns (start_row, end_row) as 0-based indices.
    The green section is the first contiguous block of rows
    that contain at least one green cell.
    """
    start = None
    end = None
    for i, row_colors in enumerate(backgrounds):
        has_green = any(is_green_fn(c) for c in row_colors)
        if has_green:
            if start is None:
                start = i
            end = i
        elif start is not None:
            # We've exited the green block
            break

    if start is None:
        raise ValueError("緑色のセクションが見つかりませんでした")
    return start, end


def _find_latest_section_by_text(
    values: list[list[str]],
) -> tuple[int, int]:
    """Fallback: find the latest section by scanning for period patterns.

    Returns (start_row, end_row) as 0-based indices.
    The latest section starts at the first period pattern found from the top.
    It ends at the next period pattern that belongs to a different payment label,
    or after a gap of 3+ empty rows.
    """
    start = None
    first_payment_label = None
    end = None
    empty_count = 0

    for i, row in enumerate(values):
        row_text = " ".join(row)

        # Look for period row
        if PERIOD_PATTERN.search(row_text):
            if start is None:
                start = i

        # Look for payment label
        pm = PAYMENT_LABEL_PATTERN.search(row_text)
        if pm and start is not None:
            label = pm.group(0)
            if first_payment_label is None:
                first_payment_label = label

        # Track empty rows after we found the start
        if start is not None:
            if all(c.strip() == "" for c in row):
                empty_count += 1
                if empty_count >= 3:
                    end = i - empty_count
                    break
            else:
                empty_count = 0
                end = i

    if start is None:
        raise ValueError("期間パターンが見つかりませんでした")
    if end is None:
        end = len(values) - 1

    return start, end


def _parse_section_rows(
    values: list[list[str]],
    start_row: int,
    end_row: int,
) -> PayrollRecord:
    """Parse rows within a section into a PayrollRecord.

    Handles both single and double sub-section layouts.
    """
    record = PayrollRecord()
    section_rows = values[start_row : end_row + 1]

    # Collect all sub-section blocks
    current_period = None
    current_payment_label = None
    header_col_map: dict[str, int] = {}
    pending_attendance_info: dict[str, int] = {}

    i = 0
    while i < len(section_rows):
        row = section_rows[i]
        row_text = " ".join(row)

        # Check for period row
        period = _parse_period(row_text)
        if period:
            current_period = period
            i += 1
            continue

        # Check for payment label (may be on same row as header)
        pm = PAYMENT_LABEL_PATTERN.search(row_text)
        if pm:
            current_payment_label = pm.group(0)
            if not record.payment_date_label:
                record.payment_date_label = current_payment_label

        # Check for header row (may also contain payment label)
        if any(kw in row_text for kw in HEADER_KEYWORDS):
            header_col_map = {}
            for col_idx, cell in enumerate(row):
                cell_stripped = cell.strip()
                if cell_stripped:
                    header_col_map[cell_stripped] = col_idx
            # Also check if the NEXT row has "氏 名" or "氏名" (column label)
            next_i = i + 1
            if next_i < len(section_rows):
                next_row_text = " ".join(section_rows[next_i])
                if "氏" in next_row_text and "名" in next_row_text:
                    # Map 氏名 to col 0 from next row
                    for col_idx, cell in enumerate(section_rows[next_i]):
                        stripped = cell.strip()
                        if stripped and stripped not in header_col_map:
                            header_col_map[stripped] = col_idx
            i += 1
            continue

        # If only payment label (no header keywords), skip
        if pm:
            i += 1
            continue

        # Skip rows that only contain "氏 名" header label
        if row_text.strip() in ("氏 名", "氏名"):
            i += 1
            continue

        # Check for data row (contains 長谷川清子)
        if "長谷川清子" in row_text and header_col_map and current_period:
            sub = _extract_subsection(
                row,
                header_col_map,
                current_period,
                current_payment_label or record.payment_date_label,
            )
            record.sub_sections.append(sub)

            # Check for 総合計支給金額 in the same row
            if "総合計支給金額" in header_col_map:
                gt_col = header_col_map["総合計支給金額"]
                if gt_col < len(row) and row[gt_col].strip():
                    record.grand_total = _parse_int(row[gt_col])

            i += 1
            continue

        # Check for attendance info
        att_match = ATTENDANCE_PATTERN.search(row_text)
        rem_match = REMOTE_PATTERN.search(row_text)
        if att_match or rem_match:
            if record.sub_sections:
                latest = record.sub_sections[-1]
                if att_match:
                    latest.office_days = int(att_match.group(1))
                if rem_match:
                    latest.remote_days = int(rem_match.group(1))
            i += 1
            continue

        i += 1

    # If grand_total not set, use the last sub-section's subtotal
    if record.grand_total == 0 and record.sub_sections:
        record.grand_total = sum(s.subtotal for s in record.sub_sections)

    return record


def _extract_subsection(
    row: list[str],
    header_map: dict[str, int],
    period: tuple[date, date],
    payment_label: str,
) -> PayrollSubSection:
    """Extract a PayrollSubSection from a data row using the header column mapping."""

    def _get(key: str) -> str:
        col = header_map.get(key)
        if col is None or col >= len(row):
            return ""
        return row[col]

    # Alternative header names
    name_keys = ["氏名", "氏 名"]
    name = ""
    for k in name_keys:
        name = _get(k)
        if name:
            break

    return PayrollSubSection(
        period_start=period[0],
        period_end=period[1],
        payment_label=payment_label,
        name=name.strip() or "長谷川清子",
        total_hours=_parse_decimal(_get("総時間")),
        work_days=_parse_int(_get("出勤日数") or _get("出勤 日数")),
        hourly_rate=_parse_int(_get("時給")),
        salary=_parse_int(_get("給与")),
        tax=_parse_int(_get("消費税")),
        transport=_parse_int(_get("交通費")),
        subtotal=_parse_int(_get("支給金額合計")),
    )


def parse_latest_payroll(
    values: list[list[str]],
    backgrounds: list[list[dict | None]] | None = None,
    is_green_fn=None,
) -> PayrollRecord:
    """Parse the latest (green) payroll section from spreadsheet data.

    Args:
        values: 2D list of cell values from the spreadsheet.
        backgrounds: Optional 2D list of cell background colors.
        is_green_fn: Function to check if a color is green.

    Returns:
        PayrollRecord with the latest payroll data.
    """
    # Try green section detection first
    if backgrounds and is_green_fn:
        try:
            start, end = _find_green_section_rows(backgrounds, is_green_fn)
            return _parse_section_rows(values, start, end)
        except ValueError:
            pass

    # Fallback to text-based detection
    start, end = _find_latest_section_by_text(values)
    return _parse_section_rows(values, start, end)
