from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import gspread
from google.oauth2.service_account import Credentials

from .models import HEADER, PriceRow

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _client(service_account_path: Path) -> gspread.Client:
    if not service_account_path.exists():
        raise FileNotFoundError(
            f"Service account JSON not found at {service_account_path}. "
            "Place a Google Cloud service-account key there and share the sheet "
            "with the service account's email (Editor access)."
        )
    creds = Credentials.from_service_account_file(str(service_account_path), scopes=SCOPES)
    return gspread.authorize(creds)


def _worksheet_by_gid(spreadsheet: gspread.Spreadsheet, gid: int) -> gspread.Worksheet:
    for ws in spreadsheet.worksheets():
        if ws.id == gid:
            return ws
    raise ValueError(f"Worksheet with gid={gid} not found in spreadsheet {spreadsheet.title}")


def write_rows(
    service_account_path: Path,
    sheet_id: str,
    sheet_gid: int,
    rows: Iterable[PriceRow],
) -> int:
    client = _client(service_account_path)
    sh = client.open_by_key(sheet_id)
    ws = _worksheet_by_gid(sh, sheet_gid)

    values = [HEADER] + [r.to_row() for r in rows]
    ws.clear()
    ws.update(range_name="A1", values=values, value_input_option="USER_ENTERED")
    log.info("sheets: wrote %d rows to '%s' (gid=%d)", len(values) - 1, ws.title, sheet_gid)
    return len(values) - 1
