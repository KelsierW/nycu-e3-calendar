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


def test_submission_completion_is_idempotent_and_stops_reminders(tmp_path):
    from datetime import timedelta
    from nycu_e3.calendar import CalendarSync
    from nycu_e3.state import State
    start = datetime(2026, 11, 9, 23, 59, tzinfo=TZ)
    now = datetime(2026, 11, 4, tzinfo=TZ)
    e = Entry('deadline:a:hw1', 'deadline', 'a', 'HW1 deadline', start, start+timedelta(minutes=1), now, 'https://example.com/hw1')
    fake, state = FakeCalendar(), State(tmp_path / 'a.db')
    sync = CalendarSync(fake, state)
    sync.sync([e], now)
    receipts = {('a', 'hw1')}
    assert sync.mark_submitted([e], receipts, write=False)[0][0] == '預覽已提交'
    assert not fake.event_api.items[0]['summary'].startswith('✅')
    assert sync.mark_submitted([e], receipts)[0][0] == '已標註提交並取消提醒'
    assert fake.event_api.items[0]['reminders'] == {'useDefault': False, 'overrides': []}
    assert sync.mark_submitted([e], receipts) == []
    state.close()


def test_remote_identity_recovers_after_local_record_loss(tmp_path):
    from datetime import timedelta
    from nycu_e3.calendar import CalendarSync
    from nycu_e3.state import State
    start = datetime(2026, 11, 9, 23, 59, tzinfo=TZ)
    now = datetime(2026, 11, 4, tzinfo=TZ)
    e = Entry('deadline:a:hw1', 'deadline', 'a', 'HW1', start, start+timedelta(minutes=1), now, 'https://example.com/hw1')
    fake, state = FakeCalendar(), State(tmp_path / 'a.db')
    sync = CalendarSync(fake, state)
    sync.sync([e], now)
    state.db.execute('DELETE FROM events')
    state.db.commit()
    assert sync.sync([e], now)[0][0] == '已同步'
    assert len(fake.event_api.items) == 1 and state.event(e.key)['owned']
    state.close()


def test_deleted_event_is_not_recreated_or_completed(tmp_path):
    from datetime import timedelta
    from nycu_e3.calendar import CalendarSync
    from nycu_e3.state import State
    from googleapiclient.errors import HttpError
    from httplib2 import Response
    start = datetime(2026, 11, 9, 23, 59, tzinfo=TZ)
    now = datetime(2026, 11, 4, tzinfo=TZ)
    e = Entry('deadline:a:hw1', 'deadline', 'a', 'HW1', start, start+timedelta(minutes=1), now, '')
    fake, state = FakeCalendar(), State(tmp_path / 'a.db')
    sync = CalendarSync(fake, state)
    sync.sync([e], now)
    fake.event_api.items.clear()
    def missing(**kwargs):
        raise HttpError(Response({'status': '410'}), b'{}')
    fake.event_api.get = missing
    assert sync.sync([e], now)[0][0] == '原事件已刪除，略過重建'
    assert sync.mark_submitted([e], {('a', 'hw1')}) == []
    assert fake.event_api.items == []
    state.close()


def test_existing_source_html_entities_and_fragments_deduplicate():
    from datetime import timedelta
    from nycu_e3.calendar import CalendarSync
    start = datetime(2026, 11, 9, 23, 59, tzinfo=TZ)
    e = Entry('k', 'deadline', 'a', '11/3 Lab', start, start+timedelta(minutes=1), start,
              'https://e3p.nycu.edu.tw/mod/assign/view.php?id=123')
    existing = {'summary': 'Different personal title', 'description': '<p>https://e3p.nycu.edu.tw/mod/assign/view.php?id=123&amp;action=view</p>'}
    assert CalendarSync._same_topic(existing, e, event_body(e))
    from dataclasses import replace
    e = replace(e, source_url='https://e3p.nycu.edu.tw/mod/forum/discuss.php?d=456#p789')
    existing['description'] = '<p>https://e3p.nycu.edu.tw/mod/forum/discuss.php?d=456</p>'
    assert CalendarSync._same_topic(existing, e, event_body(e))
    existing['description'] = '<p>Source: https://e3p.nycu.edu.tw/mod/forum/discuss.php?d=456\\nOther: https://example.org/folder</p>'
    assert CalendarSync._same_topic(existing, e, event_body(e))


def test_deleted_generated_event_adopts_existing_personal_counterpart(tmp_path):
    from datetime import timedelta
    from nycu_e3.calendar import CalendarSync
    from nycu_e3.state import State
    from googleapiclient.errors import HttpError
    from httplib2 import Response
    now = datetime(2026, 11, 5, tzinfo=TZ)
    e = Entry('exam:a:midterm', 'exam', 'a', '期中考', now+timedelta(days=1), now+timedelta(days=2), now,
              'https://example.com/exam')
    calendar, state = FakeCalendar(), State(tmp_path / 'state.db')
    state.save_event(e.key, 'deleted-generated', 'old-fingerprint', True)
    calendar.event_api.items.append({'id': 'personal', 'summary': 'My exam note',
                                    'description': e.source_url, 'start': {'date': '2026-11-06'}})
    def missing(**kwargs): raise HttpError(Response({'status': '410'}), b'{}')
    calendar.event_api.get = missing
    assert CalendarSync(calendar, state).sync([e], now)[0][0] == '已存在（保留原內容）'
    assert state.event(e.key)['event_id'] == 'personal' and not state.event(e.key)['owned']
    assert calendar.event_api.items[0]['summary'] == 'My exam note'
    state.close()


def test_submission_completes_verified_legacy_automation_but_not_private_event(tmp_path):
    from datetime import timedelta
    from nycu_e3.calendar import CalendarSync
    from nycu_e3.state import State
    now = datetime(2026, 11, 5, tzinfo=TZ)
    e = Entry('deadline:1151.123456:123', 'deadline', '1151.123456', 'CS_HW_B', now, now+timedelta(minutes=1), now,
              'https://e3p.nycu.edu.tw/mod/assign/view.php?id=123')
    calendar, state = FakeCalendar(), State(tmp_path / 'state.db')
    private = {'id': 'private', 'summary': 'CS_HW_B', 'description': e.source_url, 'reminders': {'useDefault': True}}
    legacy = {'id': 'legacy', 'summary': '截止：CS_HW_B',
              'description': '1151.123456 '+e.source_url+' 建立來源：NYCU e3 課業檢查（自動同步）',
              'reminders': {'useDefault': False, 'overrides': [{'method': 'popup', 'minutes': 1440}]}}
    calendar.event_api.items.extend([private, legacy])
    sync = CalendarSync(calendar, state)
    receipts = {('1151.123456', 'cs_hw_b')}
    assert sync.mark_submitted([e], receipts, write=False)[0][0] == '預覽已提交'
    assert not legacy['summary'].startswith('✅')
    assert sync.mark_submitted([e], receipts)[0][0] == '已標註提交並取消提醒'
    assert legacy['reminders'] == {'useDefault': False, 'overrides': []}
    assert private['reminders'] == {'useDefault': True}
    assert sync.mark_submitted([e], receipts) == []
    assert '人工修改' in sync.sync([e], now)[0][0]  # A missing receipt must not silently reopen a completed item.
    state.close()
