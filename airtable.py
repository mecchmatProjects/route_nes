import os
import requests

def get_config():
    api_key = os.getenv("AIRTABLE_API_KEY")
    base_id = os.getenv("AIRTABLE_BASE_ID")
    table_name = os.getenv("AIRTABLE_TABLE_NAME")

    missing = []
    if not api_key:
        missing.append("AIRTABLE_API_KEY")
    if not base_id:
        missing.append("AIRTABLE_BASE_ID")
    if not table_name:
        missing.append("AIRTABLE_TABLE_NAME")

    if missing:
        raise ValueError(
            "Missing Airtable configuration: " + ", ".join(missing)
        )

    base_url = f"https://api.airtable.com/v0/{base_id}/{table_name}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    return base_url, headers

# -----------------------------
# 1. LIST RECORDS
# -----------------------------
def list_records():
    try:
        base_url, headers = get_config()
        response = requests.get(base_url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        print("=== Records ===")
        for record in data.get("records", []):
            print(f"ID: {record['id']}, Fields: {record['fields']}")
        return data.get("records", [])
    except (requests.RequestException, ValueError) as e:
        print(f"Error listing records: {e}")
        return []

# -----------------------------
# 2. CREATE A RECORD
# -----------------------------
def create_record(fields):
    try:
        base_url, headers = get_config()
        response = requests.post(
            base_url,
            headers=headers,
            json={"fields": fields},
            timeout=30,
        )
        response.raise_for_status()
        record = response.json()
        print(f"Created record: {record}")
        return record
    except (requests.RequestException, ValueError) as e:
        print(f"Error creating record: {e}")
        return None

# -----------------------------
# 3. UPDATE A RECORD
# -----------------------------
def update_record(record_id, fields):
    try:
        base_url, headers = get_config()
        url = f"{base_url}/{record_id}"
        response = requests.patch(
            url,
            headers=headers,
            json={"fields": fields},
            timeout=30,
        )
        response.raise_for_status()
        record = response.json()
        print(f"Updated record: {record}")
        return record
    except (requests.RequestException, ValueError) as e:
        print(f"Error updating record: {e}")
        return None

# -----------------------------
# 4. DELETE A RECORD
# -----------------------------
def delete_record(record_id):
    try:
        base_url, headers = get_config()
        url = f"{base_url}/{record_id}"
        response = requests.delete(url, headers=headers, timeout=30)
        response.raise_for_status()
        print(f"Deleted record with ID: {record_id}")
        return True
    except (requests.RequestException, ValueError) as e:
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
