"""Gmail trigger: detect new invoice request emails.

Detection criteria (all must match):
  - From: hasegawa.s@tseminar.co.jp
  - Subject: contains 「月分給与」
  - Body: contains the spreadsheet URL
  - Date: 2026-04-01 or later
  - Not already processed (tracked in processed_emails.json)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# The spreadsheet ID we're looking for in the email body
SPREADSHEET_ID = "1iHoGzsu7StMGxa5eqWQHFxlNZDs37YHOUexuYQqhgGw"

# Gmail search query
# from: sender, subject contains 月分給与, after 2026/03/31
GMAIL_QUERY = 'from:hasegawa.s@tseminar.co.jp subject:月分給与 after:2026/03/31'

# Default path for tracking processed emails
DEFAULT_PROCESSED_PATH = "credentials/processed_emails.json"


def _load_processed(path: Path) -> dict:
    """Load processed email records. Returns {message_id: {date, subject}}."""
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_processed(path: Path, data: dict) -> None:
    """Save processed email records."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _mark_processed(path: Path, message_id: str, subject: str) -> None:
    """Mark an email as processed."""
    data = _load_processed(path)
    data[message_id] = {
        "subject": subject,
        "processed_at": datetime.now().isoformat(),
    }
    _save_processed(path, data)


def check_for_new_email(processed_path: Optional[str] = None) -> Optional[dict]:
    """Check Gmail for unprocessed invoice request emails.

    This function uses the Gmail MCP tools indirectly via a Python subprocess
    that calls the CLI. For direct integration, the CLI `trigger` command
    calls the Gmail MCP directly.

    Returns:
        dict with 'message_id', 'subject', 'date' if a new email is found.
        None if no new email.
    """
    # This is a data structure helper; actual Gmail API calls happen in cli.py
    raise NotImplementedError(
        "Use cli.py trigger command which calls Gmail MCP directly"
    )


def is_invoice_email(
    from_addr: str,
    subject: str,
    body: str,
    date_str: str,
) -> bool:
    """Check if an email matches the invoice trigger criteria.

    Args:
        from_addr: Sender email address.
        subject: Email subject.
        body: Email body text.
        date_str: Email date string (RFC2822 or ISO format).

    Returns:
        True if this is an invoice request email.
    """
    # Check sender
    if "hasegawa.s@tseminar.co.jp" not in from_addr:
        return False

    # Check subject contains 月分給与
    if "月分給与" not in subject:
        return False

    # Check body contains the spreadsheet link
    if SPREADSHEET_ID not in body:
        return False

    return True


def get_processed_ids(processed_path: str) -> set:
    """Get set of already-processed message IDs."""
    data = _load_processed(Path(processed_path))
    return set(data.keys())


def mark_as_processed(processed_path: str, message_id: str, subject: str) -> None:
    """Mark an email as processed after successful invoice creation."""
    _mark_processed(Path(processed_path), message_id, subject)
