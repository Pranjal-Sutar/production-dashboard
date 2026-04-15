import os
import json
import gspread
from google.oauth2.service_account import Credentials

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds_dict = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))

creds = Credentials.from_service_account_info(creds_dict, scopes=scope)

client = gspread.authorize(creds)

def get_steps_raw(sheet_name):
    scope = [...]
    
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        creds_dict, scope
    )

    client = gspread.authorize(creds)

    sheet = client.open(sheet_name).sheet1

    data = sheet.get_all_values()

    steps = []
    for row in data[3:]:  # skip first 3 rows
        if row[2]:
            steps.append({"description": row[2]})

    return steps
