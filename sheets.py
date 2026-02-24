import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials


def get_steps_raw(sheet_name: str):
    """
    Reads steps from Google Sheet.
    Ignores first 3 rows automatically.
    """

    # ✅ SCOPES MUST BE LIST OF STRINGS (NOT ...)
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    # ✅ Load credentials from ENV (Render)
    creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON env var not set")

    creds_dict = json.loads(creds_json)

    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        creds_dict,
        scope
    )

    client = gspread.authorize(creds)

    sheet = client.open(sheet_name).sheet1
    rows = sheet.get_all_values()

    # ✅ Ignore first 3 rows
    rows = rows[3:]

    steps = []
    for r in rows:
        if len(r) >= 3 and r[2].strip():
            steps.append({
                "description": r[2].strip()
            })

    return steps
