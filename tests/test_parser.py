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