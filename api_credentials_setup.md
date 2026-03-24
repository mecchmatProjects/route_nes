# API Credentials Setup

This repository contains draft integration scripts for Airtable and ServiceM8. Real credentials must be created in the corresponding vendor accounts. They cannot be generated locally from this repository.

## 1. Airtable

The script [airtable.py](f:/BuisnessAlgo/VRP2/airtable.py) now expects these environment variables:

- `AIRTABLE_API_KEY`
- `AIRTABLE_BASE_ID`
- `AIRTABLE_TABLE_NAME`

### How to obtain them

1. Sign in to Airtable.
2. Create a Personal Access Token in your developer or account settings.
3. Grant the token access to the target base and the required table permissions.
4. Open the target Airtable base and copy the Base ID.
   It usually starts with `app`.
5. Identify the table name exactly as it appears in Airtable.

### Example on Windows PowerShell

```powershell
$env:AIRTABLE_API_KEY="pat_xxx"
$env:AIRTABLE_BASE_ID="appxxxxxxxxxxxxxx"
$env:AIRTABLE_TABLE_NAME="Tasks"
python .\airtable.py
```

## 2. ServiceM8

The script [servicem8.py](f:/BuisnessAlgo/VRP2/servicem8.py) now expects these environment variables:

- `SERVICEM8_CLIENT_ID`
- `SERVICEM8_CLIENT_SECRET`
- `SERVICEM8_REDIRECT_URI`
- `SERVICEM8_SCOPE`

### How to obtain them

1. Sign in to the ServiceM8 developer or app registration portal.
2. Create an OAuth application.
3. Set the redirect URI to match the value you will use locally, for example `http://localhost/callback`.
4. Copy the generated client ID and client secret.
5. Confirm the OAuth scopes required for your script. The current default is `staff job`.

### Example on Windows PowerShell

```powershell
$env:SERVICEM8_CLIENT_ID="your_client_id"
$env:SERVICEM8_CLIENT_SECRET="your_client_secret"
$env:SERVICEM8_REDIRECT_URI="http://localhost/callback"
$env:SERVICEM8_SCOPE="staff job"
python .\servicem8.py
```

## 3. Recommended local workflow

1. Copy `.env.example` to `.env` if you want a local reference file.
2. Do not commit real credentials.
3. Prefer environment variables or your terminal profile over hardcoding secrets in Python files.

## 4. What I changed in the scripts

1. Removed hardcoded placeholders as the primary configuration path.
2. Added explicit config validation with readable error messages.
3. Added request timeouts so failed API calls do not hang indefinitely.

## 5. Current limitation

The scripts are now ready for real credentials, but they will not work until you create the Airtable token and the ServiceM8 OAuth app in your own accounts.