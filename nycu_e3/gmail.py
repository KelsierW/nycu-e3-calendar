"""Retrieve only matching Gmail messages and extract plain-text email content."""
from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import html
import re


@dataclass(frozen=True)
class Mail:
    id: str
    subject: str
    body: str
    date: datetime
    url: str


def _decode(data: str) -> str:
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
    except (ValueError, UnicodeError):
        return ""


def _parts(payload: dict):
    """Prefer text/plain but retain link-bearing HTML if plain part has no links."""
    plain, html_parts = [], []
    def walk(part):
        mime = part.get("mimeType", "")
        if mime.startswith("multipart/"):
            for child in part.get("parts", []):
                walk(child)
        elif mime == "text/plain":
            plain.append(_decode(part.get("body", {}).get("data", "")))
        elif mime == "text/html":
            html_parts.append(_decode(part.get("body", {}).get("data", "")))
    walk(payload)
    # HTML URLs can be referenced in an <a href> not in displayed text.
    anchors = []
    for part in html_parts:
        anchors.extend(html.unescape(x) for x in re.findall(r'href\s*=\s*["\'](https?[^"\']+)', part, re.I))
    text = "\n".join(plain) or re.sub(r"<[^>]+>", " ", "\n".join(html_parts))
    return html.unescape(text) + "\n" + "\n".join(anchors)


def from_api(message: dict) -> Mail:
    payload = message.get("payload", {})
    headers = {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers", [])}
    timestamp = int(message.get("internalDate", 0)) / 1000
    return Mail(
        id=message["id"],
        subject=headers.get("subject", ""),
        body=_parts(payload),
        date=datetime.fromtimestamp(timestamp, tz=timezone.utc),
        url=f"https://mail.google.com/mail/u/0/#all/{message['id']}",
    )


def search(gmail, query: str, max_messages: int = 1200):
    ids, token = [], None
    while len(ids) < max_messages:
        args = {"userId": "me", "q": query, "maxResults": min(500, max_messages - len(ids))}
        if token:
            args["pageToken"] = token
        result = gmail.users().messages().list(**args).execute()
        ids.extend(m["id"] for m in result.get("messages", []))
        token = result.get("nextPageToken")
        if not token:
            break
    mails = []
    for mid in ids:
        payload = gmail.users().messages().get(userId="me", id=mid, format="full").execute()
        mails.append(from_api(payload))
    return sorted(mails, key=lambda m: m.date)