"""One private Google Calendar summary per morning, with a mobile popup at 08:00."""
from datetime import timedelta
from hashlib import sha256
from googleapiclient.errors import HttpError

from .runtime import SetupError


def digest_body(now, pending, other, videos):
    morning = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if morning <= now:
        morning += timedelta(days=1)
    day = morning.date().isoformat()
    lines = ["NYCU e3 每日課業摘要", f"最近成功檢查：{now:%Y-%m-%d %H:%M}（台灣時間）",
             "提醒時間：每日 08:00。內容為上方時間的通知信檢查結果；若電腦未開機或未登入，可能尚未更新。",
             "", f"待交作業：{len(pending)} 項"]
    for e in pending[:50]:
        lines.append(f"{e.start:%m/%d %H:%M}｜{e.course} {e.title}\n{e.source_url}")
    if not pending:
        lines.append("目前沒有從通知信辨識到尚待繳交的作業，重要期限仍請核對 e3。")
    lines.extend(["", f"近期考試／異動：{len(other)} 項"])
    for e in other[:15]:
        lines.append(f"{e.start:%m/%d}｜{e.title}\n{e.source_url}")
    lines.extend(["", f"待看影片：{len(videos)} 項"])
    for v in videos[:30]:
        lines.append(f"{v['course']} {v['title']}\n{v['url']}")
    lines.extend(["", "已排除遲交／補交與已確認繳交的作業。完成作業後，後續檢查會依提交確認信更新。"])
    return {
        "summary": f"NYCU e3｜待交 {len(pending)}・待看 {len(videos)}",
        "description": "\n".join(lines),
        "start": {"dateTime": morning.isoformat(), "timeZone": "Asia/Taipei"},
        "end": {"dateTime": (morning+timedelta(minutes=5)).isoformat(), "timeZone": "Asia/Taipei"},
        "transparency": "transparent", "visibility": "private",
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 0}]},
        "extendedProperties": {"private": {"nycuE3DigestDate": day}},
    }


def sync_digest(calendar, calendar_id, now, pending, other, videos, write=True):
    body = digest_body(now, pending, other, videos)
    day = body['extendedProperties']['private']['nycuE3DigestDate']
    event_id = sha256(f"nycu-e3-digest:{calendar_id}:{day}".encode()).hexdigest()
    api = calendar.events()
    existing = None
    try:
        existing = api.get(calendarId=calendar_id, eventId=event_id).execute()
    except HttpError as exc:
        if exc.resp.status == 410:
            return ('摘要已刪除，保留刪除狀態', body['summary'], '')
        if exc.resp.status != 404:
            raise
    if existing:
        if existing.get('status') == 'cancelled':
            return ('摘要已刪除，保留刪除狀態', body['summary'], '')
        if existing.get('extendedProperties', {}).get('private', {}).get('nycuE3DigestDate') != day:
            raise SetupError('每日摘要事件識別不符，停止以免更動私人事件。')
    if not write:
        return ('預覽每日08:00摘要', body['summary'], (existing or {}).get('htmlLink', ''))
    if existing:
        result = api.patch(calendarId=calendar_id, eventId=event_id, body=body, sendUpdates='none').execute()
        return ('已更新每日08:00摘要', body['summary'], result.get('htmlLink', ''))
    try:
        result = api.insert(calendarId=calendar_id, body={**body, 'id': event_id}, sendUpdates='none').execute()
    except HttpError as exc:
        if exc.resp.status != 409:
            raise
        # Resolve a single concurrent insert without an unbounded retry loop.
        existing = api.get(calendarId=calendar_id, eventId=event_id).execute()
        if existing.get('extendedProperties', {}).get('private', {}).get('nycuE3DigestDate') != day:
            raise SetupError('每日摘要事件識別不符，停止以免更動私人事件。')
        result = api.patch(calendarId=calendar_id, eventId=event_id, body=body, sendUpdates='none').execute()
        return ('已更新每日08:00摘要', body['summary'], result.get('htmlLink', ''))
    return ('已新增每日08:00摘要', body['summary'], result.get('htmlLink', ''))
