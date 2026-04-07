"""Google Sheets API reader with cell value and formatting support."""

from __future__ import annotations

from typing import Any

import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


# Required scopes for reading Google Sheets
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]


class SheetReader:
    """Reads data and formatting from a Google Spreadsheet."""

    def __init__(self, service_account_path: str, spreadsheet_id: str):
        self._credentials = Credentials.from_service_account_file(
            service_account_path, scopes=_SCOPES
        )
        self._spreadsheet_id = spreadsheet_id

        # gspread client for cell values
        self._gc = gspread.authorize(self._credentials)
        self._spreadsheet = self._gc.open_by_key(spreadsheet_id)

        # Google Sheets API v4 client for formatting info
        self._sheets_service = build(
            "sheets", "v4", credentials=self._credentials
        )

    def get_worksheet_by_gid(self, gid: int) -> gspread.Worksheet:
        """Find a worksheet by its GID (sheet ID)."""
        for ws in self._spreadsheet.worksheets():
            if ws.id == gid:
                return ws
        raise ValueError(
            f"Worksheet with gid={gid} not found in spreadsheet. "
            f"Available: {[(ws.title, ws.id) for ws in self._spreadsheet.worksheets()]}"
        )

    def get_all_values(self, gid: int) -> list[list[str]]:
        """Return all cell values as a 2D list of strings."""
        ws = self.get_worksheet_by_gid(gid)
        return ws.get_all_values()

    def get_cell_backgrounds(self, gid: int) -> list[list[dict | None]]:
        """Get cell background colors using Sheets API v4.

        Returns a 2D list of RGB dicts like:
            {"red": 0.2, "green": 0.8, "blue": 0.2}
        or None if no background color is set.
        """
        ws = self.get_worksheet_by_gid(gid)
        sheet_title = ws.title

        result = (
            self._sheets_service.spreadsheets()
            .get(
                spreadsheetId=self._spreadsheet_id,
                ranges=f"'{sheet_title}'",
                fields="sheets.data.rowData.values.effectiveFormat.backgroundColor",
            )
            .execute()
        )

        backgrounds: list[list[dict | None]] = []
        sheets_data = result.get("sheets", [])
        if not sheets_data:
            return backgrounds

        grid_data = sheets_data[0].get("data", [])
        if not grid_data:
            return backgrounds

        for row_data in grid_data[0].get("rowData", []):
            row_colors: list[dict | None] = []
            for cell in row_data.get("values", []):
                fmt = cell.get("effectiveFormat", {})
                bg = fmt.get("backgroundColor")
                row_colors.append(bg)
            backgrounds.append(row_colors)

        return backgrounds

    def is_green_cell(self, bg_color: dict | None) -> bool:
        """Check if a background color is green-ish.

        The spreadsheet uses a bright green for the latest section.
        Google Sheets API omits color components that are 0, so
        {'green': 1} means red=0, green=1, blue=0.
        """
        if bg_color is None:
            return False
        r = bg_color.get("red", 0.0)
        g = bg_color.get("green", 0.0)
        b = bg_color.get("blue", 0.0)
        return g > 0.6 and r < 0.5 and b < 0.5
