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


def _ensure_header(ws: gspread.Worksheet) -> None:
    """Make sure row 1 holds the canonical header.

    If the stored header has the same column count we leave existing data
    alone. If the schema shape has changed (new columns added), we wipe the
    whole sheet so we don't interleave rows with different shapes — the sheet
    is a historical log; the old shape is unreadable once mixed.
    """
    try:
        existing = ws.row_values(1)
    except Exception:
        existing = []
    if existing == HEADER:
        return
    if existing and len(existing) != len(HEADER):
        log.warning(
            "sheets: schema shape changed (%d -> %d columns), clearing '%s'",
            len(existing), len(HEADER), ws.title,
        )
        ws.clear()
    ws.update(range_name="A1", values=[HEADER], value_input_option="USER_ENTERED")
    log.info("sheets: rewrote header row on '%s'", ws.title)


def append_rows(
    service_account_path: Path,
    sheet_id: str,
    sheet_gid: int,
    rows: Iterable[PriceRow],
) -> int:
    """Append rows to the sheet without clearing prior data. Keeps a full history."""
    rows_list = list(rows)
    if not rows_list:
        raise ValueError("append_rows refuses empty rows list")

    client = _client(service_account_path)
    sh = client.open_by_key(sheet_id)
    ws = _worksheet_by_gid(sh, sheet_gid)

    _ensure_header(ws)

    values = [r.to_row() for r in rows_list]
    ws.append_rows(
        values,
        value_input_option="USER_ENTERED",
        insert_data_option="INSERT_ROWS",
    )
    log.info(
        "sheets: appended %d rows to '%s' (gid=%d)",
        len(values), ws.title, sheet_gid,
    )
    return len(values)


# Backwards-compat alias: legacy callers used write_rows to overwrite.
# We now always append; the old "wipe sheet" behaviour is gone on purpose.
write_rows = append_rows
