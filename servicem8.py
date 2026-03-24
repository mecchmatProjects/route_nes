import os
import requests
import webbrowser
import urllib.parse
import sys

AUTH_URL = "https://api.servicem8.com/oauth/authorize"
TOKEN_URL = "https://api.servicem8.com/oauth/token"
API_BASE_URL = "https://api.servicem8.com/api_1.0"


def get_config():
    client_id = os.getenv("SERVICEM8_CLIENT_ID")
    client_secret = os.getenv("SERVICEM8_CLIENT_SECRET")
    redirect_uri = os.getenv("SERVICEM8_REDIRECT_URI", "http://localhost/callback")
    scope = os.getenv("SERVICEM8_SCOPE", "staff job")

    missing = []
    if not client_id:
        missing.append("SERVICEM8_CLIENT_ID")
    if not client_secret:
        missing.append("SERVICEM8_CLIENT_SECRET")

    if missing:
        raise ValueError(
            "Missing ServiceM8 configuration: " + ", ".join(missing)
        )

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "scope": scope,
    }

# ==== STEP 1: Get Authorization Code ====
def get_authorization_code():
    config = get_config()
    params = {
        "response_type": "code",
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "scope": config["scope"],
    }
    auth_link = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    print(f"Open this URL in your browser to authorize:\n{auth_link}")
    webbrowser.open(auth_link)
    code = input("Paste the 'code' parameter from the redirected URL here: ").strip()
    return code

# ==== STEP 2: Exchange Code for Access Token ====
def get_access_token(auth_code):
    try:
        config = get_config()
        response = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": config["redirect_uri"],
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
            },
            timeout=30,
        )
        response.raise_for_status()
        token_data = response.json()
        return token_data["access_token"]
    except (requests.RequestException, ValueError) as e:
        print(f"Error getting access token: {e}")
        sys.exit(1)

# ==== STEP 3: Call ServiceM8 API ====
def fetch_jobs(access_token):
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.get(
            f"{API_BASE_URL}/job.json",
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        jobs = response.json()
        print(f"Retrieved {len(jobs)} jobs:")
        for job in jobs[:5]:  # Show first 5 jobs
            print(f"- {job.get('uuid')} | {job.get('description')}")
    except requests.RequestException as e:
        print(f"Error fetching jobs: {e}")


def main():
    try:
        auth_code = get_authorization_code()
    except ValueError as e:
        print(e)
        sys.exit(1)

    token = get_access_token(auth_code)
    fetch_jobs(token)

# ==== MAIN FLOW ====
if __name__ == "__main__":
    main()
