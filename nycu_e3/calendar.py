"""Conservative upsert to the user's primary Google Calendar.

The tool never edits events it did not create. It stores the event ID in SQLite,
adds an extended private property to its own events and checks duplicates.
"""
from datetime import datetime, timedelta
from hashlib import sha256
import json

from .parser import Entry, TZ, normalize


def _all_day(entry: Entry) -> bool:
    return (entry.kind != "deadline" and entry.start.hour == 0
            and entry.start.minute == 0 and entry.end == entry.start + timedelta(days=1))


def event_body(entry: Entry) -> dict:
    desc = f"{entry.details}\n課程代碼：{entry.course or '未辨識'}\n來源：{entry.source_url}\nNYCU-E3 key: {entry.key}"
    body = {"summary": entry.title, "description": desc,
            "extendedProperties": {"private": {"nycuE3Key": entry.key}}}
    if entry.location:
        body["location"] = entry.location
    if _all_day(entry):
        body["start"] = {"date": entry.start.date().isoformat()}
        body["end"] = {"date": entry.end.date().isoformat()}
        body["reminders"] = {"useDefault": True}
    else:
        body["start"] = {"dateTime": entry.start.isoformat(), "timeZone": "Asia/Taipei"}
        body["end"] = {"dateTime": entry.end.isoformat(), "timeZone": "Asia/Taipei"}
        lead = [1440, 180] if entry.kind == "deadline" else [1440, 90]
        body["reminders"] = {"useDefault": False,
                              "overrides": [{"method": "popup", "minutes": m} for m in lead]}
    return body


def _fingerprint(body: dict) -> str:
    relevant = {k: body.get(k) for k in ("summary", "description", "location", "start", "end")}
    return sha256(json.dumps(relevant, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class CalendarSync:
    def __init__(self, api, state, calendar_id="primary"):
        self.api, self.state, self.calendar_id = api, state, calendar_id

    def list_existing(self, start: datetime, end: datetime):
        params = {"calendarId": self.calendar_id,
                  "timeMin": start.isoformat(), "timeMax": end.isoformat(),
                  "maxResults": 2500, "singleEvents": True}
        rows = []
        token = None
        while True:
            if token:
                params["pageToken"] = token
            result = self.api.events().list(**params).execute()
            rows.extend(e for e in result.get("items", []) if e.get("status") != "cancelled")
            token = result.get("nextPageToken")
            if not token:
                break
        return rows

    @staticmethod
    def _date_of(event):
        start = event.get("start", {})
        return (start.get("date") or start.get("dateTime") or "")[:10]

    @staticmethod
    def _same_topic(existing, entry, body):
        ex_key = existing.get("extendedProperties", {}).get("private", {}).get("nycuE3Key")
        if ex_key == entry.key:
            return True
        # Prefer a source-link match or a normalized title on the same day.
        if entry.source_url and entry.source_url in existing.get("description", ""):
            return True
        return (CalendarSync._date_of(existing) == entry.start.date().isoformat()
                and normalize(existing.get("summary", "")) == normalize(body["summary"]))

    def sync(self, entries: list[Entry], now: datetime, write=True):
        if not entries:
            return []
        # Only upsert active and upcoming events, not an entire history.
        entries = [e for e in entries if e.start and e.end and e.end > now - timedelta(hours=2)]
        if not entries:
            return []
        start = min(e.start for e in entries) - timedelta(days=1)
        end = max(e.end for e in entries) + timedelta(days=1)
        existing = self.list_existing(start, end)
        by_id = {e["id"]: e for e in existing}
        actions = []
        for entry in entries:
            body = event_body(entry)
            fingerprint = _fingerprint(body)
            stored = self.state.event(entry.key)
            original = by_id.get(stored["event_id"]) if stored else None
            if original is None and stored and stored["owned"]:
                # A deadline moved outside the current date window. Fetch by ID
                # before assuming the user deleted it (prevents duplicate events).
                from googleapiclient.errors import HttpError
                try:
                    fetched = self.api.events().get(calendarId=self.calendar_id, eventId=stored["event_id"]).execute()
                    if fetched.get("status") != "cancelled":
                        original = fetched
                except HttpError as exc:
                    if exc.resp.status not in (404, 410):
                        raise
            if original is None:
                original = next((e for e in existing if self._same_topic(e, entry, body)), None)
            if original is not None:
                if not stored or not stored["owned"]:
                    # Pre-existing personal event. Do not overwrite its contents.
                    if write:
                        self.state.save_event(entry.key, original["id"], fingerprint, False)
                    actions.append(("已存在（保留原內容）", entry.title, original.get("htmlLink", "")))
                    continue
                if stored["fingerprint"] == fingerprint:
                    actions.append(("已同步", entry.title, original.get("htmlLink", "")))
                    continue
                # Do not overwrite manual edits made in Google Calendar after
                # the last automatic sync. Ask the student to resolve instead.
                if _fingerprint(original) != stored["fingerprint"]:
                    actions.append(("來源已更新，但事件有人工修改，請核對", entry.title, original.get("htmlLink", "")))
                    continue
                if not write:
                    actions.append(("預覽更新", entry.title, original.get("htmlLink", "")))
                    continue
                updated = self.api.events().patch(calendarId=self.calendar_id, eventId=original["id"], body=body).execute()
                self.state.save_event(entry.key, updated["id"], fingerprint, True)
                actions.append(("已更新", entry.title, updated.get("htmlLink", "")))
                continue
            if stored and stored["owned"] and not original:
                # The user may have intentionally deleted it; do not recreate it.
                actions.append(("原事件已刪除，略過重建", entry.title, ""))
                continue
            if not write:
                actions.append(("預覽新增", entry.title, ""))
                continue
            created = self.api.events().insert(calendarId=self.calendar_id, body=body,
                                               sendUpdates="none").execute()
            existing.append(created)
            by_id[created["id"]] = created
            self.state.save_event(entry.key, created["id"], fingerprint, True)
            actions.append(("已新增", entry.title, created.get("htmlLink", "")))
        return actions

    def mark_submitted(self, entries: list[Entry], submitted: set[tuple[str, str]], write=True):
        """For locally owned reminder events, mark completion without deleting them."""
        actions = []
        for entry in entries:
            if entry.kind != "deadline":
                continue
            if not any((not course or not entry.course or course == entry.course)
                       and title and title in normalize(entry.title)
                       for course, title in submitted):
                continue
            saved = self.state.event(entry.key)
            if not saved or not saved["owned"]:
                continue
            if not write:
                actions.append(("預覽已提交", entry.title, ""))
                continue
            event = self.api.events().get(calendarId=self.calendar_id, eventId=saved["event_id"]).execute()
            if event.get("summary", "").startswith("✅ "):
                continue
            result = self.api.events().patch(calendarId=self.calendar_id, eventId=saved["event_id"],
                     body={"summary": "✅ " + event.get("summary", entry.title),
                           "reminders": {"useDefault": False, "overrides": []}}).execute()
            actions.append(("已標註提交並取消提醒", entry.title, result.get("htmlLink", "")))
        return actions