from dataclasses import replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import pytest
from nycu_e3 import cli, scheduled, auth
from nycu_e3.gmail import Mail
from nycu_e3.parser import TZ, Entry, Video, normalize, submission_matches
from nycu_e3.runtime import SetupError, safe_error
from nycu_e3.state import State


def test_preview_database_is_unchanged(tmp_path):
    path = tmp_path / 'state.db'
    s = State(path)
    v = Video('one', '1151.123456', 'video', datetime.now(TZ), 'https://example.org/video')
    s.add_video(v)
    s.set_video_status('one', '已觀看')
    s.close()
    before = path.read_bytes()
    preview = State(path, preview=True)
    preview.add_video(replace(v, key='two'))
    assert preview.list_videos()[0]['status'] == '已觀看'
    preview.close()
    assert path.read_bytes() == before
    absent = tmp_path / 'absent' / 'state.db'
    State(absent, preview=True).close()
    assert not absent.parent.exists()


def test_submission_course_and_number_are_required():
    now = datetime.now(TZ)
    entry = Entry('k', 'deadline', '1151.123456', 'HW1 deadline', now, now, now, '')
    receipt = {('1151.123456', normalize('HW1'))}
    assert submission_matches(entry, receipt)
    assert not submission_matches(replace(entry, title='HW10 deadline'), receipt)
    assert not submission_matches(replace(entry, course='1151.999999'), receipt)
    assert not submission_matches(entry, {('', normalize('HW1'))})


def test_missing_auth_does_not_open_browser_or_write_token(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, 'windows_store', lambda: None)
    from google_auth_oauthlib.flow import InstalledAppFlow
    monkeypatch.setattr(InstalledAppFlow, 'run_local_server', lambda *a, **k: pytest.fail('browser opened'))
    with pytest.raises(SetupError):
        auth.credentials(tmp_path / 'absent')
    assert not (tmp_path / 'absent').exists()


def test_errors_do_not_disclose_exception_details():
    assert 'private-token' not in safe_error(ValueError('private-token'))


def test_runner_failure_and_recovery_health(tmp_path, monkeypatch):
    (tmp_path / 'config.yaml').write_text('timezone: Asia/Taipei', encoding='utf-8')
    monkeypatch.setattr(scheduled, 'runtime_dir', lambda *a: tmp_path)
    def fail(*a, **k):
        raise ValueError('private-token')
    monkeypatch.setattr(scheduled, 'run', fail)
    args = ['--project-dir', str(tmp_path), '--dry-run']
    assert scheduled.main(args) == 1
    health = json.loads((tmp_path / 'out/last-preview.json').read_text(encoding='utf-8'))
    assert not health['success'] and health['exit_code'] == 1
    assert 'private-token' not in (tmp_path / 'out/check.log').read_text(encoding='utf-8')
    monkeypatch.setattr(scheduled, 'run', lambda *a, **k: None)
    assert scheduled.main(args) == 0
    assert json.loads((tmp_path / 'out/last-preview.json').read_text(encoding='utf-8'))['success']


def test_full_check_preview_uses_read_only_calendar(tmp_path, monkeypatch, capsys):
    now = datetime.now(TZ)
    due = (now + timedelta(days=2)).strftime('%Y/%m/%d')
    (tmp_path / 'config.yaml').write_text('timezone: Asia/Taipei\n', encoding='utf-8')
    monkeypatch.setattr(cli, 'runtime_dir', lambda *a: tmp_path)
    class Calendar:
        def events(self): return self
        def list(self, **kwargs): return self
        def execute(self): return {'items': []}
        def insert(self, **kwargs): pytest.fail('Calendar insert in dry-run')
        def patch(self, **kwargs): pytest.fail('Calendar patch in dry-run')
    monkeypatch.setattr(cli, 'services', lambda *a: (object(), Calendar()))
    def mail(subject, body): return Mail('fake', subject, body, now, 'https://example.org/mail')
    mails = [
        mail('1151.123456: HW1 deadline', f'截止：{due} 23:59'),
        mail('1151.123456: HW10 deadline', f'截止：{due} 23:59'),
        mail('1151.123456: HW2 補交', f'截止：{due} 23:59'),
        mail('You have submitted your assignment submission for HW1', '1151.123456'),
        mail('1151.123456: 教學影片已上傳', '可觀看 https://youtu.be/fake'),
    ]
    monkeypatch.setattr(cli, 'search', lambda *a: mails)
    cli.run(tmp_path, dry_run=True)
    output = capsys.readouterr().out
    assert '待交 1' in output and '未觀看 1' in output
    assert 'HW10' in output and 'HW2' not in output
    assert not (tmp_path / 'data').exists()


def test_second_runner_is_skipped(tmp_path, monkeypatch):
    (tmp_path / 'config.yaml').write_text('timezone: Asia/Taipei', encoding='utf-8')
    monkeypatch.setattr(scheduled, 'runtime_dir', lambda *a: tmp_path)
    def locked(handle): raise OSError('locked')
    monkeypatch.setattr(scheduled, 'acquire_lock', locked)
    monkeypatch.setattr(scheduled, 'run', lambda *a, **k: pytest.fail('duplicate run'))
    assert scheduled.main(['--project-dir', str(tmp_path)]) == 0
    assert not (tmp_path / 'out/last-run.json').exists()


def test_interactive_auth_recovers_stale_token_and_saves_refresh_token(tmp_path, monkeypatch):
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    class Stale:
        expired, valid, refresh_token = True, False, 'old-fixture'
        def has_scopes(self, scopes): return True
        def refresh(self, request): raise RuntimeError('invalid_grant')
    class Fresh:
        refresh_token = 'new-fixture'
        def to_json(self): return 'serialized-fixture'
    class Store:
        saved = None
        def get_password(self, service, name):
            return {'oauth_token': '{}', 'client_id': 'fixture-id', 'client_secret': 'fixture-secret'}[name]
        def set_password(self, service, name, value): self.saved = (name, value)
    class Flow:
        options = None
        def run_local_server(self, **kwargs):
            self.options = kwargs
            return Fresh()
    store, flow = Store(), Flow()
    monkeypatch.setattr(auth, 'windows_store', lambda: store)
    monkeypatch.setattr(Credentials, 'from_authorized_user_info', lambda *a: Stale())
    monkeypatch.setattr(InstalledAppFlow, 'from_client_config', lambda *a: flow)
    assert auth.credentials(tmp_path, interactive=True).refresh_token == 'new-fixture'
    assert flow.options['timeout_seconds'] == 600 and flow.options['prompt'] == 'consent'
    assert store.saved == ('oauth_token', 'serialized-fixture')
