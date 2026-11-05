from datetime import datetime, timezone
from nycu_e3.gmail import Mail
from nycu_e3.parser import parse_entries, parse_submission, parse_videos, normalize

NOW = datetime(2026, 10, 29, 4, 0, tzinfo=timezone.utc)


def mail(subject, body):
    return Mail("fake-message", subject, body, NOW, "https://mail.google.com/mail/u/0/#all/fake-message")


def test_deadline_explicit_time():
    m = mail("1151.123456: Lab 3-3 結報 deadline", "截止時間：2026/11/02 23:59\nhttps://e3p.nycu.edu.tw/mod/assign/view.php?id=246440")
    e = parse_entries(m)[0]
    assert e.kind == "deadline"
    assert e.start.strftime("%Y-%m-%d %H:%M") == "2026-11-02 23:59"
    assert "246440" in e.key


def test_date_only_2359():
    e = parse_entries(mail("1151.123456: HW1 deadline", "繳交期限：2026-11-02"))[0]
    assert e.start.hour == 23 and e.start.minute == 59


def test_no_deadline_date_never_invented():
    assert parse_entries(mail("1151.123456: HW1 deadline", "繳交日期稍後公告")) == []


def test_no_late_or_no_submission():
    assert parse_entries(mail("1151.123456: HW1 遲交區", "截止時間：2026/11/02 23:59")) == []
    assert parse_entries(mail("1151.123456: Lab 4-1 預報", "下週預報不需要繳交；截止：2026/11/02")) == []


def test_submission_receipt():
    result = parse_submission(mail("You have submitted your assignment submission for Exercise#1", "1151.515505 ->Assignment"))
    assert result == ("1151.515505", normalize("Exercise#1"))


def test_exam_not_assume_end_time():
    e = parse_entries(mail("1151.515505: 期中考公告", "期中考將於11/3(二)上課時間舉行"))[0]
    assert e.kind == "exam"
    assert e.start.strftime("%Y-%m-%d") == "2026-11-03"
    assert (e.end - e.start).days == 1


def test_exact_exam_time():
    e = parse_entries(mail("1151.123456: 期中考", "考試日期 2026/10/30 時間：13:30–16:30"))[0]
    assert e.start.hour == 13 and e.start.minute == 30
    assert e.end.hour == 16 and e.end.minute == 30


def test_video_link_key_deduplicates():
    m = mail("1151.123456: 教學影片已上傳", "可觀看：https://drive.google.com/file/d/video123/view")
    videos = parse_videos(m)
    assert len(videos) == 1
    assert videos[0].key == parse_videos(m)[0].key


def test_promise_to_upload_is_not_video_available():
    assert parse_videos(mail("1151.123456: 錄影", "助教課錄影預計稍後上傳。")) == []


def test_english_deadline_month_before_day():
    e = parse_entries(mail('1151.123456: HW4', 'deadline Nov 17 23:59; details in folder'))[0]
    assert e.start.strftime('%Y-%m-%d %H:%M') == '2026-11-17 23:59'


def test_moodle_english_deadline_is_not_assignment_name_date():
    e = parse_entries(mail('Due on Monday, 9 November 2026, 11:59 PM: 11/3 Lab 4-1 結報繳交區',
        'The assignment is due soon. DUE: MONDAY, 9 NOVEMBER 2026, 11:59 PM\n1151.123456\nhttps://e3p.nycu.edu.tw/mod/assign/view.php?id=123&action=view'))[0]
    assert e.title == '11/3 Lab 4-1 結報繳交區'
    assert e.start.strftime('%Y-%m-%d %H:%M') == '2026-11-09 23:59'
    assert e.source_url.endswith('?id=123')


def test_digest_is_split_and_late_items_excluded_individually():
    body = '''The following assignments are due on MONDAY, 9 NOVEMBER 2026.
* 11/3 LAB 4-1 結報繳交區 in course 1151.123456. Fake course
DUE: 11:59 PM
Go to activity [1]
* 10/20 LAB 3-3 結報繳交區（遲交區) in course 1151.123456
DUE: 11:59 PM
Go to activity [2]
* HW4 in course 1151.654321
DUE: 12:15 AM
Go to activity [3]
Links:
[1] https://e3p.nycu.edu.tw/mod/assign/view.php?id=111&action=view
[2] https://e3p.nycu.edu.tw/mod/assign/view.php?id=222&action=view
[3] https://e3p.nycu.edu.tw/mod/assign/view.php?id=333&action=view
'''
    entries = parse_entries(mail('You have assignments due in 7 days', body))
    assert len(entries) == 2
    assert entries[0].key == 'deadline:1151.123456:111'
    assert entries[0].start.strftime('%Y-%m-%d %H:%M') == '2026-11-09 23:59'
    assert entries[1].key == 'deadline:1151.654321:333'
    assert entries[1].start.strftime('%Y-%m-%d %H:%M') == '2026-11-09 00:15'


def test_digest_without_confirmed_date_does_not_use_assignment_title_date():
    assert parse_entries(mail('You have assignments due in 7 days',
        'The following assignments are due on a date to be confirmed.\n* 11/3 LAB in course 1151.123456\nDUE: 11:59 PM')) == []


def test_administrative_deadline_is_not_homework():
    assert parse_entries(mail('NYCU Course Withdrawal Deadline – 5:00 PM on Friday, December 4',
        '停修申請期限。Deadline December 4 5:00 PM.')) == []


def test_explicit_report_deadline_remains_supported():
    entry = parse_entries(mail('1151.123456: Project report deadline', 'Deadline November 17 11:59 PM'))[0]
    assert entry.start.strftime('%Y-%m-%d %H:%M') == '2026-11-17 23:59'


def test_forum_post_timestamp_is_not_an_exam_date():
    body = '''1151.123456 -> Forums -> 公告 -> 期中考座位分配
by Fictional TA - Thursday, 5 November 2026, 11:49 AM
---------------------------------------------------------------------
期中考座位請見附件，教室 A101。
---------------------------------------------------------------------
This is a copy of a message.
'''
    assert parse_entries(mail('1151.123456: 期中考座位分配', body)) == []
    dated = body.replace('教室 A101。', '教室 A101。考試日期：2026/11/06。')
    entry = parse_entries(mail('1151.123456: 期中考座位分配', dated))[0]
    assert entry.start.strftime('%Y-%m-%d') == '2026-11-06'


def test_exam_paper_collection_is_not_an_exam():
    assert parse_entries(mail('1151.123456: 期中考卷領取', '期中考卷請於 2026/11/06 領取。')) == []


def test_moodle_assignment_with_custom_name_is_recognized():
    e = parse_entries(mail('Due on Friday, 6 November 2026, 11:59 PM: CS_HW_B',
        'The assignment CS_HW_B in course 1151.123456 is due soon.\nDUE: FRIDAY, 6 NOVEMBER 2026, 11:59 PM\nhttps://e3p.nycu.edu.tw/mod/assign/view.php?id=123'))[0]
    assert e.title == 'CS_HW_B' and e.start.strftime('%Y-%m-%d %H:%M') == '2026-11-06 23:59'
