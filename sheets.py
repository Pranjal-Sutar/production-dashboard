import gspread
from oauth2client.service_account import ServiceAccountCredentials

def get_steps_raw(sheet_name):
    scope = [...]
    creds_dict = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        creds_dict, scope
    )

    client = gspread.authorize(creds)
    sheet = client.open(sheet_name).sheet1

    rows = sheet.get_all_values()

    tasks = []
    for r in rows[1:]:  # skip header
        if len(r) < 3:
            continue

        tasks.append({
            "description": r[2]
        })

    return tasks

