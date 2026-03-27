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

def get_steps_raw():
    sheet = client.open("YOUR_SHEET_NAME").sheet1
    return sheet.get_all_records()
