from datetime import datetime
import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response
from nycu_e3.digest import digest_body, sync_digest
from nycu_e3.parser import TZ, Entry
from nycu_e3.calendar import CalendarSync, event_body
from nycu_e3.runtime import SetupError


class Request:
    def __init__(self, value): self.value = value
    def execute(self): return self.value


class Calendar:
    def __init__(self): self.rows, self.inserts, self.patches = {}, 0, 0
    def events(self): return self
    def get(self, **args):
        if args['eventId'] not in self.rows:
            raise HttpError(Response({'status': '404'}), b'{}')
        return Request(self.rows[args['eventId']])
    def insert(self, **args):
        self.inserts += 1
        row = {**args['body'], 'htmlLink': 'https://example.org/digest'}
        self.rows[row['id']] = row
        return Request(row)
    def patch(self, **args):
        self.patches += 1
        self.rows[args['eventId']].update(args['body'])
        return Request(self.rows[args['eventId']])


def test_digest_targets_today_before_eight_and_tomorrow_after_eight():
    before = datetime(2026, 11, 6, 7, 45, tzinfo=TZ)
    body = digest_body(before, [], [], [])
    assert body['start']['dateTime'] == '2026-11-06T08:00:00+08:00'
    at_eight = before.replace(hour=8, minute=0)
    assert digest_body(at_eight, [], [], [])['start']['dateTime'] == '2026-11-07T08:00:00+08:00'
    assert body['reminders'] == {'useDefault': False, 'overrides': [{'method': 'popup', 'minutes': 0}]}
    assert body['transparency'] == 'transparent' and body['visibility'] == 'private'


def test_daily_digest_is_idempotent_and_dry_run_never_writes():
    now, calendar = datetime(2026, 11, 5, 22, tzinfo=TZ), Calendar()
    assert sync_digest(calendar, 'primary', now, [], [], [], write=False)[0] == '預覽每日08:00摘要'
    assert calendar.inserts == calendar.patches == 0
    sync_digest(calendar, 'primary', now, [], [], [])
    sync_digest(calendar, 'primary', now.replace(hour=23), [], [], [])
    assert len(calendar.rows) == 1 and calendar.inserts == 1 and calendar.patches == 1
    old_id = next(iter(calendar.rows))
    sync_digest(calendar, 'primary', now, [], [], [], write=False)
    assert calendar.patches == 1
    calendar.rows[old_id]['extendedProperties'] = {}
    with pytest.raises(SetupError): sync_digest(calendar, 'primary', now, [], [], [])


def test_digest_source_links_are_never_mistaken_for_deadline_events():
    now = datetime(2026, 11, 5, 22, tzinfo=TZ)
    e = Entry('k', 'deadline', '1151.123456', 'HW1', now, now, now, 'https://example.org/hw1')
    body = digest_body(now, [e], [], [])
    assert 'HW1' in body['description']
    assert not CalendarSync._same_topic(body, e, event_body(e))
