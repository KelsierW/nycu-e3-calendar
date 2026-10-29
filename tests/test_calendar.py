from datetime import datetime
from zoneinfo import ZoneInfo
from nycu_e3.calendar import event_body
from nycu_e3.parser import Entry

TZ = ZoneInfo("Asia/Taipei")


def test_calendar_deadline_event_and_reminders():
    start = datetime(2026, 11, 2, 23, 59, tzinfo=TZ)
    e = Entry("deadline:a:hw1", "deadline", "a", "HW1", start, start.replace(day=3, hour=0, minute=0), start, "https://example.com")
    body = event_body(e)
    assert body["start"]["dateTime"].startswith("2026-11-02T23:59")
    assert [x["minutes"] for x in body["reminders"]["overrides"]] == [1440, 180]
    assert body["extendedProperties"]["private"]["nycuE3Key"] == e.key


def test_exam_all_day_when_unknown_time():
    start = datetime(2026, 11, 6, tzinfo=TZ)
    from datetime import timedelta
    e = Entry("exam:a:midterm", "exam", "a", "期中考", start, start + timedelta(days=1), start, "")
    body = event_body(e)
    assert body["start"] == {"date": "2026-11-06"}

class FakeRequest:
    def __init__(self, outcome):
        self.outcome = outcome
    def execute(self):
        return self.outcome


class FakeEvents:
    def __init__(self):
        self.items = []
        self.seq = 0
    def list(self, **kwargs):
        return FakeRequest({"items": list(self.items)})
    def insert(self, **kwargs):
        self.seq += 1
        obj = dict(kwargs["body"], id=f"e{self.seq}", htmlLink=f"https://example.com/e{self.seq}")
        self.items.append(obj)
        return FakeRequest(obj)
    def get(self, **kwargs):
        return FakeRequest(next(x for x in self.items if x["id"] == kwargs["eventId"]))
    def patch(self, **kwargs):
        obj = next(x for x in self.items if x["id"] == kwargs["eventId"])
        obj.update(kwargs["body"])
        return FakeRequest(obj)


class FakeCalendar:
    def __init__(self):
        self.event_api = FakeEvents()
    def events(self):
        return self.event_api


def test_idempotent_calendar_and_date_change(tmp_path):
    from datetime import timedelta
    from nycu_e3.calendar import CalendarSync
    from nycu_e3.state import State
    start = datetime(2026, 11, 2, 23, 59, tzinfo=TZ)
    now = datetime(2026, 10, 29, tzinfo=TZ)
    e = Entry("deadline:a:hw1", "deadline", "a", "HW1", start, start+timedelta(minutes=1), now, "https://example.com/hw1")
    fake, state = FakeCalendar(), State(tmp_path / "a.db")
    sync = CalendarSync(fake, state)
    assert sync.sync([e], now)[0][0] == "已新增"
    assert sync.sync([e], now)[0][0] == "已同步"
    assert len(fake.event_api.items) == 1
    changed = Entry(e.key, e.kind, e.course, e.title, start+timedelta(days=14), e.end+timedelta(days=14), now, e.source_url)
    assert sync.sync([changed], now)[0][0] == "已更新"
    assert len(fake.event_api.items) == 1
    assert fake.event_api.items[0]["start"]["dateTime"].startswith("2026-11-16T23:59")
    state.close()


def test_existing_manual_event_is_not_overwritten(tmp_path):
    from datetime import timedelta
    from nycu_e3.calendar import CalendarSync
    from nycu_e3.state import State
    start = datetime(2026, 11, 2, 23, 59, tzinfo=TZ)
    now = datetime(2026, 10, 29, tzinfo=TZ)
    e = Entry("deadline:a:hw1", "deadline", "a", "HW1", start, start+timedelta(minutes=1), now, "https://example.com/hw1")
    fake, state = FakeCalendar(), State(tmp_path / "a.db")
    fake.event_api.items.append({"id": "mine", "summary": "HW1", "description":"Personal notes", "start":{"dateTime":start.isoformat()}, "end":{"dateTime":e.end.isoformat()}, "htmlLink":"https://example.com/mine"})
    result = CalendarSync(fake, state).sync([e], now)
    assert result[0][0] == "已存在（保留原內容）"
    assert len(fake.event_api.items) == 1
    assert fake.event_api.items[0]["description"] == "Personal notes"
    state.close()


def test_manual_change_blocks_automatic_overwrite(tmp_path):
    from datetime import timedelta
    from nycu_e3.calendar import CalendarSync
    from nycu_e3.state import State
    start = datetime(2026, 11, 2, 23, 59, tzinfo=TZ)
    now = datetime(2026, 10, 29, tzinfo=TZ)
    e = Entry("deadline:a:hw1", "deadline", "a", "HW1", start, start+timedelta(minutes=1), now, "https://example.com/hw1")
    fake, state = FakeCalendar(), State(tmp_path / "a.db")
    sync = CalendarSync(fake, state)
    sync.sync([e], now)
    fake.event_api.items[0]["summary"] = "My customized homework note"
    changed = Entry(e.key, e.kind, e.course, e.title, start+timedelta(days=1), e.end+timedelta(days=1), now, e.source_url)
    res = sync.sync([changed], now)
    assert "人工修改" in res[0][0]
    assert fake.event_api.items[0]["summary"] == "My customized homework note"
    assert fake.event_api.items[0]["start"]["dateTime"].startswith("2026-11-02")
    state.close()