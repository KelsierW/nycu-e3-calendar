"""Conservative, rule-based parsing of common e3 notification emails.

Unknown formats are intentionally not interpreted as confirmed deadlines. Use
manual_events in config.yaml for course-specific exceptions.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import hashlib
import re
import html
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from .gmail import Mail

TZ = ZoneInfo("Asia/Taipei")
DATE_PATTERN = r"(?:20\d{2}[-/]\d{1,2}[-/]\d{1,2}|20\d{2}年\d{1,2}月\d{1,2}日|(?<!\d)\d{1,2}/\d{1,2}(?!\d))"
MONTH_PATTERN = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
DATE_PATTERN = rf"(?:{DATE_PATTERN}|(?<!\w)\d{{1,2}}\s+{MONTH_PATTERN}(?:\s+20\d{{2}})?\b|\b{MONTH_PATTERN}\s+\d{{1,2}}(?:,?\s+20\d{{2}})?\b)"
DATE_RE = re.compile(DATE_PATTERN, re.I)
MONTH_NUMBERS = {m: i for i, m in enumerate(('jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'), 1)}
TIME_RE = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)\s*(AM|PM)?(?!\d)", re.I)
DUE_WORDS = re.compile(r"截止(?:日期|時間)?|繳交期限|繳交截止|due\s*date|deadline|\bis due\b|\bdue\b", re.I)
ASSIGN_WORDS = re.compile(r"作業|報告|結報|預報|實驗|\bHW\s*[#\d]|exercise|assignment|\blab\b|\breport\b|\bproject\b", re.I)
EXAM_WORDS = re.compile(r"期中考|期末考|小考|考試|midterm|final exam|quiz", re.I)
VIDEO_WORDS = re.compile(r"(?:教學|課程|上課|助教課|補課)?(?:影片|錄影|錄影檔)|lecture\s+video|video|recording|\.mp4", re.I)
VIDEO_AVAILABLE = re.compile(r"已上傳|上傳完成|可以觀看|可觀看|觀看連結|影片連結|請觀看|video.*(?:upload|avail)|recording.*(?:upload|avail)|\.mp4", re.I)
EXCLUDED = re.compile(r"遲交|補交|late\s*(?:submission|work|area)|resubmission|make[\s-]?up", re.I)
NOT_REQUIRED = re.compile(r"免交|不需要繳交|無須繳交|不用繳交|no submission required", re.I)
SUBMITTED = re.compile(r"You have submitted your assignment submission(?:\s+for\s+(.+))?", re.I)
CANCELLED = re.compile(r"停課|本週不上課|課程取消|class cancel", re.I)
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
COURSE_RE = re.compile(r"(?<!\d)(11\d\d\.\d{6})(?!\d)")


@dataclass(frozen=True)
class Entry:
    key: str
    kind: str  # deadline | exam | cancellation
    course: str
    title: str
    start: datetime | None
    end: datetime | None
    announced: datetime
    source_url: str
    details: str = ""
    location: str = ""


@dataclass(frozen=True)
class Video:
    key: str
    course: str
    title: str
    announced: datetime
    url: str


def tidy(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize(text: str) -> str:
    # Normalize common e3 subject variations to compare confirmations and notices.
    text = re.sub(r"11\d\d\.\d{6}", "", text, flags=re.I)
    text = re.sub(r"(?:you have submitted.*?for|assignment submission for|deadline for|due date for)", "", text, flags=re.I)
    text = re.sub(r"[^\w\u3400-\u9fff#-]", "", text.lower())
    return text


def submission_matches(entry, submitted):
    """Require the same known course; HW1 must never complete HW10."""
    name = normalize(entry.title)
    return any(course and entry.course and course == entry.course and title
               and re.search(re.escape(title) + r"(?=$|[^a-z0-9]|deadline|duedate)", name)
               for course, title in submitted)


def _date(text: str, announced: datetime):
    match = DATE_RE.search(text)
    if not match:
        return None, None
    raw = match.group(0).replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-")
    try:
        if re.search(r"[a-z]", raw, re.I):
            parts = re.split(r"[\s,]+", raw.strip())
            if parts[0].isdigit():
                day, month = int(parts[0]), MONTH_NUMBERS[parts[1][:3].lower()]
            else:
                month, day = MONTH_NUMBERS[parts[0][:3].lower()], int(parts[1])
            chunks = [int(parts[2]), month, day] if len(parts) > 2 else [month, day]
        else:
            chunks = [int(n) for n in raw.split("-")]
        if len(chunks) == 2:
            year = announced.astimezone(TZ).year
            # Past/future crossing Dec/Jan is resolved toward the closest 6 months.
            base = datetime(year, chunks[0], chunks[1], tzinfo=TZ)
            if (base - announced.astimezone(TZ)).days < -180:
                year += 1
            elif (base - announced.astimezone(TZ)).days > 180:
                year -= 1
            chunks = [year, *chunks]
        return datetime(*chunks, tzinfo=TZ), match.end()
    except (ValueError, TypeError, KeyError):
        return None, None


def _time(text: str) -> time | None:
    m = TIME_RE.search(text)
    if not m:
        return None
    hour = int(m.group(1))
    meridiem = (m.group(3) or '').upper()
    if meridiem and not 1 <= hour <= 12:
        return None
    if meridiem == 'PM' and hour < 12:
        hour += 12
    elif meridiem == 'AM' and hour == 12:
        hour = 0
    return time(hour, int(m.group(2)))


def _due_date(text: str, announced: datetime):
    # Only trust dates near deadline language; avoid unrelated announcement dates.
    for word in DUE_WORDS.finditer(text):
        fragment = text[word.end():word.end() + 170]
        d, last = _date(fragment, announced)
        if not d:
            continue
        t = _time(fragment[last:last + 40]) if last is not None else None
        if not t:
            # When time is directly before the date, capture if plainly adjacent.
            t = _time(fragment[:fragment.find(DATE_RE.search(fragment).group(0))])
        return d.replace(hour=t.hour, minute=t.minute) if t else d.replace(hour=23, minute=59)
    return None


def _event_date(text: str, announced: datetime):
    # Search date close to examination/cancellation, not e3 footer timestamp.
    words = EXAM_WORDS if EXAM_WORDS.search(text) else CANCELLED
    for m in words.finditer(text):
        fragment = text[max(0, m.start() - 45):m.end() + 135]
        d, last = _date(fragment, announced)
        if d:
            return d, fragment
    return None, ""


def _times(fragment: str):
    found = list(TIME_RE.finditer(fragment))
    if len(found) >= 2:
        first, second = found[0], found[1]
        between = fragment[first.end():second.start()]
        if re.search(r"[-~～–—至到]|to", between, re.I):
            return _time(first.group(0)), _time(second.group(0))
    return (_time(found[0].group(0)), None) if found else (None, None)


def _name(subject: str) -> str:
    subject = re.sub(r"^\s*Due on .+?:\s+(?=\S)", "", subject, flags=re.I)
    subject = re.sub(r"^\s*(?:11\d\d\.\d{6}\s*[:»\-]?\s*)+", "", subject)
    subject = re.sub(r"^\s*(?:\[e3\]|\[提醒\]|\[公告\])\s*", "", subject, flags=re.I)
    return tidy(subject)[:130]


def canonical_source(url: str) -> str:
    parts = urlsplit(html.unescape(url.rstrip('.,;)]】')))
    query = parse_qsl(parts.query)
    if parts.path.endswith('/mod/assign/view.php'):
        query = [(k, v) for k, v in query if k == 'id']
    elif parts.path.endswith('/mod/forum/discuss.php'):
        query = [(k, v) for k, v in query if k == 'd']
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), ''))


def _source(mail: Mail) -> str:
    matches = URL_RE.findall(mail.body)
    for part in ("/mod/assign/view.php", "/mod/forum/discuss.php"):
        for url in matches:
            if part in url:
                return canonical_source(url.rstrip(".),;］】"))
    return mail.url


def _assignment_identity(text: str) -> str:
    m = re.search(r"/mod/assign/view\.php\?id=(\d+)", text)
    return m.group(1) if m else ""


def parse_submission(mail: Mail):
    subject = mail.subject
    match = SUBMITTED.search(subject)
    if not match:
        return None
    title = tidy(match.group(1) or "")
    if not title:
        m = re.search(r"(?:assignment submission for|submitted.*?for)\s*[\'\"]?([^\n\'\"]+)", mail.body, re.I)
        title = tidy(m.group(1)) if m else ""
    course = (COURSE_RE.search(subject + " " + mail.body) or [""])[0]
    return (course, normalize(title)) if title else None


def _digest_entries(mail: Mail):
    """Split Moodle multi-assignment reminders before applying item exclusions."""
    body = mail.body.replace('\r', '')
    header = re.search(r"The following assignments are due on\s+([^\n]+)", body, re.I)
    if not header:
        return None
    day, _ = _date(header.group(1), mail.date)
    if not day:
        return []
    links = dict(re.findall(r"\[(\d+)\]\s+(https?://[^\s<>]+)", body))
    entries = []
    for match in re.finditer(r"^\s*\*\s*(.+?)(?=^\s*\*\s*|^\s*Links:|\Z)", body, re.M | re.S):
        chunk = match.group(1)
        item = re.search(r"(.+?)\s+in\s+course\s+(11\d\d\.\d{6})", chunk, re.I | re.S)
        if not item:
            continue
        title, course = tidy(item.group(1)), item.group(2)
        if EXCLUDED.search(title) or NOT_REQUIRED.search(title):
            continue
        due_line = re.search(r"\bDUE:\s*([^\n]+)", chunk, re.I)
        clock = _time(due_line.group(1)) if due_line else None
        clock = clock or time(23, 59)
        due = day.replace(hour=clock.hour, minute=clock.minute)
        reference = re.search(r"Go to activity\s*\[(\d+)\]", chunk, re.I)
        source = canonical_source(links[reference.group(1)]) if reference and reference.group(1) in links else mail.url
        aid = _assignment_identity(source)
        key = f'deadline:{course}:{aid or normalize(title)}'
        entries.append(Entry(key, 'deadline', course, title, due, due+timedelta(minutes=1), mail.date, source, '來源：e3/Gmail 多項作業截止提醒。'))
    return entries


def _forum_content(body):
    """Publication timestamps in Moodle envelopes are not event/deadline dates."""
    plain = body.replace('\r', '')
    if re.search(r'->\s*Forums?\s*->', plain, re.I):
        parts = re.split(r'(?m)^-{10,}\s*$', plain)
        if len(parts) >= 3:
            return parts[1]
    return body


def parse_entries(mail: Mail) -> list[Entry]:
    if SUBMITTED.search(mail.subject):
        return []
    digest = _digest_entries(mail)
    if digest is not None:
        return digest
    raw = mail.subject + "\n" + mail.body
    both = mail.subject + "\n" + _forum_content(mail.body)
    name = _name(mail.subject)
    course = (COURSE_RE.search(raw) or [""])[0]
    src = _source(mail)
    result = []
    # Exclusion is based on the notification/title; an email that mentions a
    # regular and late area together may require an explicit manual override.
    assignment_notice = ASSIGN_WORDS.search(name) or re.search(r'\bThe assignment\b.+?\bin course\b', both, re.I | re.S)
    if assignment_notice and DUE_WORDS.search(both) and not EXCLUDED.search(name) and not NOT_REQUIRED.search(both):
        due = _due_date(both, mail.date)
        if due:
            aid = _assignment_identity(raw)
            key = f"deadline:{course}:{aid or normalize(name)}"
            result.append(Entry(key, "deadline", course, name, due, due + timedelta(minutes=1), mail.date, src, "來源：e3/Gmail 截止通知。"))
    exam_notice = EXAM_WORDS.search(name) or (re.search(r"考場|考試時間|exam", name, re.I) and EXAM_WORDS.search(both))
    results_notice = re.search(r'考卷.*(?:領取|發還)|(?:領取|發還).*考卷|考試成績|期中.*(?:解答|成績)', name)
    if exam_notice and not results_notice:
        day, fragment = _event_date(both, mail.date)
        if day:
            start_t, end_t = _times(fragment)
            if start_t and end_t:
                start = day.replace(hour=start_t.hour, minute=start_t.minute)
                end = day.replace(hour=end_t.hour, minute=end_t.minute)
                if end <= start:
                    end += timedelta(days=1)
            else:
                start = day
                end = day + timedelta(days=1)
            label = "期中考" if re.search(r"期中考|midterm", both, re.I) else "期末考" if re.search(r"期末考|final exam", both, re.I) else "考試"
            key = f"exam:{course}:{label}"
            details = "來源：e3/Gmail 考試公告。" + (f" 已知開始時間：{start_t.strftime('%H:%M')}；結束待確認。" if start_t and not end_t else "")
            display_name = name if EXAM_WORDS.search(name) else f"{label}｜{name}"
            result.append(Entry(key, "exam", course, display_name, start, end, mail.date, src, details))
    if CANCELLED.search(name):
        day, _ = _event_date(both, mail.date)
        if day:
            key = f"cancellation:{course}:{day.date().isoformat()}"
            result.append(Entry(key, "cancellation", course, "停課｜" + name, day, day + timedelta(days=1), mail.date, src, "課程異動公告（全天標記，不表示整天有課）。"))
    return result


def parse_videos(mail: Mail) -> list[Video]:
    both = mail.subject + "\n" + mail.body
    if not VIDEO_WORDS.search(both) or not VIDEO_AVAILABLE.search(both):
        return []
    course = (COURSE_RE.search(both) or [""])[0]
    urls = [u.rstrip(".,;)") for u in URL_RE.findall(mail.body)]
    videos = [u for u in urls if re.search(r"drive\.google\.com/file/|youtu(?:\.be|be\.com)/|/mod/supervideo/|\.mp4(?:\?|$)", u, re.I)]
    if not videos:
        videos = [u for u in urls if "/mod/forum/discuss.php" in u][:1]
    if not videos:
        videos = [mail.url]
    videos = list(dict.fromkeys(videos))
    result = []
    for idx, url in enumerate(videos):
        title = _name(mail.subject)
        if len(videos) > 1:
            title += f"（連結 {idx + 1}）"
        key = hashlib.sha256(url.encode()).hexdigest()[:24]
        result.append(Video(key, course, title, mail.date, url))
    return result


def from_manual_events(config: dict, now: datetime) -> list[Entry]:
    entries = []
    for item in config.get("manual_events", []):
        kind = item["kind"]
        course = str(item.get("course", ""))
        title = item["title"]
        d = datetime.fromisoformat(str(item["date"])).replace(tzinfo=TZ)
        if kind == "deadline":
            t = _time(str(item.get("time") or "23:59")) or time(23, 59)
            start = d.replace(hour=t.hour, minute=t.minute)
            end = start + timedelta(minutes=1)
        elif kind == "exam":
            start_t, end_t = _time(str(item.get("start", ""))), _time(str(item.get("end", "")))
            if start_t and end_t:
                start = d.replace(hour=start_t.hour, minute=start_t.minute)
                end = d.replace(hour=end_t.hour, minute=end_t.minute)
                if end <= start:
                    end += timedelta(days=1)
            else:
                start, end = d, d + timedelta(days=1)
        elif kind == "cancellation":
            start, end = d, d + timedelta(days=1)
        else:
            raise ValueError(f"不支援的人工事件類型：{kind}")
        key = f"{kind}:{course}:{normalize(title)}"
        entries.append(Entry(key, kind, course, title, start, end, now, str(item.get("source_url", "")), "經使用者手動確認的課務資訊。", str(item.get("location", ""))))
    return entries
