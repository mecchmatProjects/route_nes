import requests
import webbrowser
import urllib.parse
import sys

# ==== CONFIGURATION ====
CLIENT_ID = "YOUR_CLIENT_ID"
CLIENT_SECRET = "YOUR_CLIENT_SECRET"
REDIRECT_URI = "http://localhost/callback"  # Must match your app settings
AUTH_URL = "https://api.servicem8.com/oauth/authorize"
TOKEN_URL = "https://api.servicem8.com/oauth/token"
API_BASE_URL = "https://api.servicem8.com/api_1.0"

# ==== STEP 1: Get Authorization Code ====
def get_authorization_code():
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": "staff job",  # Adjust scopes as needed
    }
    auth_link = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    print(f"Open this URL in your browser to authorize:\n{auth_link}")
    webbrowser.open(auth_link)
    code = input("Paste the 'code' parameter from the redirected URL here: ").strip()
    return code

# ==== STEP 2: Exchange Code for Access Token ====
def get_access_token(auth_code):
    try:
        response = requests.post(TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        })
        response.raise_for_status()
        token_data = response.json()
        return token_data["access_token"]
    except requests.RequestException as e:
        print(f"Error getting access token: {e}")
        sys.exit(1)

# ==== STEP 3: Call ServiceM8 API ====
def fetch_jobs(access_token):
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.get(f"{API_BASE_URL}/job.json", headers=headers)
        response.raise_for_status()
        jobs = response.json()
        print(f"Retrieved {len(jobs)} jobs:")
        for job in jobs[:5]:  # Show first 5 jobs
            print(f"- {job.get('uuid')} | {job.get('description')}")
    except requests.RequestException as e:
        print(f"Error fetching jobs: {e}")

# ==== MAIN FLOW ====
if __name__ == "__main__":
    auth_code = get_authorization_code()
    token = get_access_token(auth_code)
    fetch_jobs(token)
