"""Tests for Gmail trigger email detection."""

from autoinvoice.gmail_trigger import is_invoice_email, get_processed_ids, mark_as_processed
import json
import tempfile
from pathlib import Path


class TestIsInvoiceEmail:
    """Test email matching logic."""

    def test_valid_april_email(self):
        assert is_invoice_email(
            from_addr='"Hasegawa, Sayako" <hasegawa.s@tseminar.co.jp>',
            subject="Fwd: ４月分給与",
            body="請求書発行してね\nhttps://docs.google.com/spreadsheets/d/1iHoGzsu7StMGxa5eqWQHFxlNZDs37YHOUexuYQqhgGw/edit",
            date_str="Mon, 6 Apr 2026 11:27:41 +0900",
        )

    def test_valid_march_email(self):
        assert is_invoice_email(
            from_addr='"Hasegawa, Sayako" <hasegawa.s@tseminar.co.jp>',
            subject="Fwd: ３月分給与",
            body="請求書発行してね\nhttps://docs.google.com/spreadsheets/d/1iHoGzsu7StMGxa5eqWQHFxlNZDs37YHOUexuYQqhgGw/edit?usp=sharing",
            date_str="Fri, 27 Feb 2026 18:00:50 +0900",
        )

    def test_wrong_sender(self):
        assert not is_invoice_email(
            from_addr="someone@example.com",
            subject="Fwd: ４月分給与",
            body="https://docs.google.com/spreadsheets/d/1iHoGzsu7StMGxa5eqWQHFxlNZDs37YHOUexuYQqhgGw",
            date_str="Mon, 6 Apr 2026 11:27:41 +0900",
        )

    def test_wrong_subject(self):
        assert not is_invoice_email(
            from_addr="hasegawa.s@tseminar.co.jp",
            subject="Re: 26年契約書添付",
            body="https://docs.google.com/spreadsheets/d/1iHoGzsu7StMGxa5eqWQHFxlNZDs37YHOUexuYQqhgGw",
            date_str="Mon, 6 Apr 2026 11:27:41 +0900",
        )

    def test_no_spreadsheet_link(self):
        assert not is_invoice_email(
            from_addr="hasegawa.s@tseminar.co.jp",
            subject="Fwd: ４月分給与",
            body="請求書発行してね。リンクなし。",
            date_str="Mon, 6 Apr 2026 11:27:41 +0900",
        )

    def test_unrelated_email(self):
        """Class action settlement email should not match."""
        assert not is_invoice_email(
            from_addr="hasegawa.s@tseminar.co.jp",
            subject="Re: Legal Notice of Class Action Settlement",
            body="一人数ドルしかもらえないみたいね。",
            date_str="Fri, 3 Apr 2026 08:04:11 +0900",
        )


class TestProcessedTracking:
    """Test processed email tracking."""

    def test_empty_processed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "processed.json")
            assert get_processed_ids(path) == set()

    def test_mark_and_get(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "processed.json")
            mark_as_processed(path, "msg123", "Fwd: ４月分給与")
            assert "msg123" in get_processed_ids(path)

    def test_multiple_marks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "processed.json")
            mark_as_processed(path, "msg1", "March")
            mark_as_processed(path, "msg2", "April")
            ids = get_processed_ids(path)
            assert "msg1" in ids
            assert "msg2" in ids
            assert len(ids) == 2

    def test_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "processed.json")
            mark_as_processed(path, "msg1", "Test")
            # Read file directly
            with open(path) as f:
                data = json.load(f)
            assert "msg1" in data
            assert data["msg1"]["subject"] == "Test"
