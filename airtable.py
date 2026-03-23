import os
import requests

# -----------------------------
# CONFIGURATION
# -----------------------------
AIRTABLE_API_KEY = os.getenv("AIRTABLE_API_KEY", "your_api_key_here")
BASE_ID = "appXXXXXXXXXXXXXX"  # Replace with your Base ID
TABLE_NAME = "Tasks"           # Replace with your table name

# Validate configuration
if not AIRTABLE_API_KEY or "your_api_key_here" in AIRTABLE_API_KEY:
    raise ValueError("Please set a valid AIRTABLE_API_KEY.")

# Airtable API base URL
BASE_URL = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_NAME}"

# Common headers for all requests
HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_API_KEY}",
    "Content-Type": "application/json"
}

# -----------------------------
# 1. LIST RECORDS
# -----------------------------
def list_records():
    try:
        response = requests.get(BASE_URL, headers=HEADERS)
        response.raise_for_status()
        data = response.json()
        print("=== Records ===")
        for record in data.get("records", []):
            print(f"ID: {record['id']}, Fields: {record['fields']}")
        return data.get("records", [])
    except requests.RequestException as e:
        print(f"Error listing records: {e}")
        return []

# -----------------------------
# 2. CREATE A RECORD
# -----------------------------
def create_record(fields):
    try:
        response = requests.post(BASE_URL, headers=HEADERS, json={"fields": fields})
        response.raise_for_status()
        record = response.json()
        print(f"Created record: {record}")
        return record
    except requests.RequestException as e:
        print(f"Error creating record: {e}")
        return None

# -----------------------------
# 3. UPDATE A RECORD
# -----------------------------
def update_record(record_id, fields):
    try:
        url = f"{BASE_URL}/{record_id}"
        response = requests.patch(url, headers=HEADERS, json={"fields": fields})
        response.raise_for_status()
        record = response.json()
        print(f"Updated record: {record}")
        return record
    except requests.RequestException as e:
        print(f"Error updating record: {e}")
        return None

# -----------------------------
# 4. DELETE A RECORD
# -----------------------------
def delete_record(record_id):
    try:
        url = f"{BASE_URL}/{record_id}"
        response = requests.delete(url, headers=HEADERS)
        response.raise_for_status()
        print(f"Deleted record with ID: {record_id}")
        return True
    except requests.RequestException as e:
        print(f"Error deleting record: {e}")
        return False

# -----------------------------
# MAIN EXECUTION
# -----------------------------
if __name__ == "__main__":
    # List existing records
    records = list_records()

    # Create a new record
    new_record = create_record({"Name": "New Task", "Status": "Pending"})

    # Update the first record if available
    if records:
        update_record(records[0]["id"], {"Status": "Completed"})

    # Delete the first record if available
    if records:
        delete_record(records[0]["id"])
