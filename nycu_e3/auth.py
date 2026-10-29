"""Each user authorizes their own Google account; credentials never ship in code."""
from pathlib import Path
import os

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


def credentials(secrets_dir: Path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    secrets_dir.mkdir(parents=True, exist_ok=True)
    token = secrets_dir / "token.json"
    client = secrets_dir / "credentials.json"
    if not client.exists():
        raise FileNotFoundError(
            f"缺少 {client}：請先在 Google Cloud 建立 Desktop OAuth client，並下載憑證。"
        )
    creds = None
    if token.exists():
        creds = Credentials.from_authorized_user_file(str(token), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(client), SCOPES)
        creds = flow.run_local_server(port=0)
    # Create owner-only token file where POSIX permissions are supported.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(token, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    finally:
        if os.name == "posix":
            os.chmod(token, 0o600)
    return creds


def services(secrets_dir: Path):
    from googleapiclient.discovery import build
    creds = credentials(secrets_dir)
    return (
        build("gmail", "v1", credentials=creds, cache_discovery=False),
        build("calendar", "v3", credentials=creds, cache_discovery=False),
    )