"""CLI entry point; runs locally in the student's own Google account."""
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import sys

import yaml

from .auth import services
from .calendar import CalendarSync
from .gmail import search
from .parser import TZ, Entry, from_manual_events, normalize, parse_entries, parse_submission, parse_videos
from .state import State


def load_config(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"找不到 {path}，請先複製 config.example.yaml 為 config.yaml")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("config.yaml 必須是 YAML 物件")
    return value


def run(root: Path, dry_run=False, refresh_auth=False):
    cfg = load_config(root / "config.yaml")
    gmail, calendar = services(root / ".secrets")
    now = datetime.now(TZ)
    days = int(cfg.get("since_days", 120))
    since = (now - timedelta(days=days)).strftime("%Y/%m/%d")
    query = f"after:{since} -in:trash -in:spam {cfg.get('gmail_query', '')}"
    mails = search(gmail, query, int(cfg.get("max_messages", 1200)))
    whitelist = set(map(str, cfg.get("course_whitelist", [])))
    state = State(root / "data" / "state.db")
    try:
        entries = {}
        submitted = set()
        videos_before = len(state.list_videos())
        for mail in mails:
            receipt = parse_submission(mail)
            if receipt:
                submitted.add(receipt)
            for e in parse_entries(mail):
                if whitelist and e.course not in whitelist:
                    continue
                entries[e.key] = e  # latest dated notice wins
            for video in parse_videos(mail):
                if not whitelist or video.course in whitelist:
                    state.add_video(video)
        for e in from_manual_events(cfg, now):
            # Prefer manually verified entries over auto-parsed titles of the
            # same kind and course. More than one assignment can have the same
            # deadline; use the normalized title rather than the date alone.
            for existing_key, old in list(entries.items()):
                if old.kind == e.kind and old.course == e.course and normalize(old.title) == normalize(e.title):
                    del entries[existing_key]
            entries[e.key] = e
        known = list(entries.values())
        def is_submitted(e):
            return any((not course or not e.course or course == e.course)
                       and title and title in normalize(e.title) for course, title in submitted)
        pending = sorted((e for e in known if e.kind == "deadline"
                          and not is_submitted(e) and e.end > now), key=lambda e: e.start)
        other = sorted((e for e in known if e.kind != "deadline" and e.end > now), key=lambda e: e.start)
        sync = CalendarSync(calendar, state, str(cfg.get("calendar_id", "primary")))
        write = bool(cfg.get("calendar_write", True)) and not dry_run
        # Calendar only receives unsubmitted homework plus exams and cancellations.
        actions = sync.sync(pending + other, now, write=write)
        actions += sync.mark_submitted(known, submitted, write=write)
        unwatched = state.list_videos("未觀看")
        print(f"NYCU/e3 課業檢查：{now:%Y-%m-%d %H:%M}（Asia/Taipei）")
        print(f"信件 {len(mails)} 封｜待交 {len(pending)}｜未觀看 {len(unwatched)}｜新影片 {len(state.list_videos()) - videos_before}")
        for e in pending:
            print(f"  [待交] {e.start:%Y-%m-%d %H:%M}  {e.course} {e.title}  {e.source_url}")
        for e in other:
            print(f"  [{e.kind}] {e.start:%Y-%m-%d}  {e.course} {e.title}  {e.source_url}")
        for v in unwatched:
            print(f"  [未觀看] {v['announced'][:10]} {v['course']} {v['title']}  ({v['key']})")
        for status, title, url in actions:
            print(f"  [{status}] {title} {url}")
        if not (pending or other or unwatched or any(x[0] in ("已新增", "已更新") for x in actions)):
            print("無課業異動，也沒有待辦事項。")
    finally:
        state.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="NYCU/e3 Gmail 作業與 Google Calendar 同步")
    parser.add_argument("--project-dir", default=".", help="包含 config.yaml 的資料夾")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("auth", help="進行個人 Google OAuth 授權")
    check = sub.add_parser("check", help="檢查通知並同步 Calendar")
    check.add_argument("--dry-run", action="store_true", help="不寫入日曆（影片佇列仍寫入本機資料庫）")
    videos = sub.add_parser("videos", help="列出影片；更新狀態用 --watched/--unwatched")
    group = videos.add_mutually_exclusive_group()
    group.add_argument("--watched", metavar="VIDEO_KEY", help="將對應影片標為已觀看")
    group.add_argument("--unwatched", metavar="VIDEO_KEY", help="將對應影片標為未觀看")
    args = parser.parse_args(argv)
    root = Path(args.project_dir).expanduser().resolve()
    try:
        if args.command == "auth":
            services(root / ".secrets")
            print("個人 Gmail 和 Google Calendar 授權完成。")
        elif args.command == "check":
            run(root, dry_run=args.dry_run)
        elif args.command == "videos":
            state = State(root / "data" / "state.db")
            try:
                if args.watched or args.unwatched:
                    key, status = (args.watched, "已觀看") if args.watched else (args.unwatched, "未觀看")
                    count = state.set_video_status(key, status)
                    print(f"更新 {count} 項為 {status}（找不到影片時為 0）。")
                for v in state.list_videos():
                    print(f"{v['key']}  [{v['status']}] {v['course']} {v['title']} {v['url']}")
            finally:
                state.close()
    except Exception as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())