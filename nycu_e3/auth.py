"""Interactive setup is explicit; scheduled checks never open a browser."""
import json
import os
from pathlib import Path
from .runtime import SetupError

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly",
          "https://www.googleapis.com/auth/calendar.events"]
KEYRING_SERVICE = "nycu-e3-crawler"


def windows_store():
    if os.name != "nt":
        return None
    import keyring
    if "Windows" not in type(keyring.get_keyring()).__module__:
        raise SetupError("Windows Credential Manager 無法使用；停止以避免明文儲存 Token。")
    return keyring


def auth_status(secrets_dir: Path):
    store = windows_store()
    saved = store.get_password(KEYRING_SERVICE, "oauth_token") if store else None
    return {
        "storage": "Windows Credential Manager" if store else "local files",
        "client_present": bool((store and store.get_password(KEYRING_SERVICE, "client_id")
                                and store.get_password(KEYRING_SERVICE, "client_secret"))
                               or (secrets_dir / "credentials.json").exists()),
        "token_present": bool(saved or (secrets_dir / "token.json").exists()),
    }


def credentials(secrets_dir: Path, interactive=False, client_file=None):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    store = windows_store()
    client = Path(client_file) if client_file else secrets_dir / "credentials.json"
    token = secrets_dir / "token.json"
    saved = store.get_password(KEYRING_SERVICE, "oauth_token") if store else None
    creds = None
    if saved:
        creds = Credentials.from_authorized_user_info(json.loads(saved))
    elif token.exists():
        creds = Credentials.from_authorized_user_file(str(token))
    if creds and not creds.has_scopes(SCOPES):
        creds = None
    if interactive and client_file:
        creds = None
    if creds and creds.expired and creds.refresh_token:
        try:
            request = Request()
            creds.refresh(lambda **kw: request(**{**kw, "timeout": 30}))
        except Exception:
            if interactive:
                creds = None
            else:
                raise SetupError("OAuth 更新失敗；請執行 python -m nycu_e3 auth 重新授權。") from None
    if not creds or not creds.valid:
        if not interactive:
            raise SetupError("缺少有效 OAuth 授權；請執行 python -m nycu_e3 auth --client-file <本機憑證JSON路徑>。排程不會開啟瀏覽器。")
        if client.exists():
            config = json.loads(client.read_text(encoding="utf-8-sig"))
            installed = config.get("installed", {})
            if not installed.get("client_id") or not installed.get("client_secret"):
                raise SetupError("OAuth JSON 必須是 Desktop app 類型。")
            if store:
                for name in ("client_id", "client_secret"):
                    store.set_password(KEYRING_SERVICE, name, installed[name])
        elif store:
            client_id = store.get_password(KEYRING_SERVICE, "client_id")
            secret = store.get_password(KEYRING_SERVICE, "client_secret")
            if not client_id or not secret:
                raise SetupError("缺少 Desktop OAuth 憑證；請使用 auth --client-file <本機JSON路徑>。")
            config = {"installed": {"client_id": client_id, "client_secret": secret,
                      "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                      "token_uri": "https://oauth2.googleapis.com/token"}}
        else:
            raise SetupError("缺少 Desktop OAuth 憑證；請使用 auth --client-file <本機JSON路徑>。")
        flow = InstalledAppFlow.from_client_config(config, SCOPES)
        print("正在等待本機瀏覽器授權（最多 10 分鐘）；看到本機程式顯示授權完成才表示 Token 已保存。", flush=True)
        try:
            creds = flow.run_local_server(port=0, timeout_seconds=600, prompt="consent")
        except Exception as exc:
            if type(exc).__name__ == "WSGITimeoutError":
                raise SetupError("授權等待逾時，尚未保存新 Token。請重新執行 auth，並在新開啟的頁面完成授權。") from None
            raise
        if not creds.refresh_token:
            raise SetupError("Google 未回傳可供排程使用的 Refresh Token；請重新執行 auth 並完成同意授權。")
    if store:
        store.set_password(KEYRING_SERVICE, "oauth_token", creds.to_json())
    else:
        secrets_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(token, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        os.chmod(token, 0o600)
    return creds


def services(secrets_dir: Path, interactive=False, client_file=None):
    from googleapiclient.discovery import build
    import google_auth_httplib2
    import httplib2
    creds = credentials(secrets_dir, interactive=interactive, client_file=client_file)
    def build_service(name, version):
        http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=30))
        return build(name, version, http=http, cache_discovery=False)
    return build_service("gmail", "v1"), build_service("calendar", "v3")
