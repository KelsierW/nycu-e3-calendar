"""CLI entry point; runs locally in the student's own Google account."""
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import sys

import yaml

from .auth import services, auth_status
from .runtime import runtime_dir, safe_error, SetupError
from .calendar import CalendarSync
from .gmail import search
from .parser import TZ, Entry, from_manual_events, normalize, parse_entries, parse_submission, parse_videos, submission_matches
from .state import State
from .digest import sync_digest


def load_config(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"找不到 {path}，請先複製 config.example.yaml 為 config.yaml")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("config.yaml 必須是 YAML 物件")
    return value


def run(root: Path, dry_run=False):
    cfg = load_config(root / "config.yaml")
    if cfg.get("timezone", "Asia/Taipei") != "Asia/Taipei":
        raise SetupError("本地排程要求 timezone: Asia/Taipei。")
    storage = runtime_dir(root, cfg)
    gmail, calendar = services(storage / ".secrets")
    now = datetime.now(TZ)
    days = int(cfg.get("since_days", 120))
    since = (now - timedelta(days=days)).strftime("%Y/%m/%d")
    query = f"after:{since} -in:trash -in:spam {cfg.get('gmail_query', '')}"
    mails = search(gmail, query, int(cfg.get("max_messages", 1200)))
    whitelist = set(map(str, cfg.get("course_whitelist", [])))
    state = State(storage / "data" / "state.db", preview=dry_run)
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
            return submission_matches(e, submitted)
        pending = sorted((e for e in known if e.kind == "deadline"
                          and not is_submitted(e) and e.end > now), key=lambda e: e.start)
        other = sorted((e for e in known if e.kind != "deadline" and e.end > now), key=lambda e: e.start)
        sync = CalendarSync(calendar, state, str(cfg.get("calendar_id", "primary")))
        write = bool(cfg.get("calendar_write", True)) and not dry_run
        # Calendar only receives unsubmitted homework plus exams and cancellations.
        actions = sync.sync(pending + other, now, write=write)
        actions += sync.mark_submitted(known, submitted, write=write)
        unwatched = state.list_videos("未觀看")
        if cfg.get('daily_digest', False):
            actions.append(sync_digest(calendar, str(cfg.get('calendar_id', 'primary')),
                                       now, pending, other, unwatched, write=write))
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
    auth = sub.add_parser("auth", help="進行個人 Google OAuth 授權（唯一會開瀏覽器的命令）")
    auth.add_argument("--client-file", type=Path, help="Desktop OAuth JSON 本機路徑")
    sub.add_parser("doctor", help="只檢查設定與 OAuth 是否存在；不輸出密鑰、不連接 Google")
    check = sub.add_parser("check", help="檢查通知並同步 Calendar")
    check.add_argument("--dry-run", action="store_true", help="不寫入日曆或正式課務資料庫；影片變更僅保留在記憶體")
    videos = sub.add_parser("videos", help="列出影片；更新狀態用 --watched/--unwatched")
    group = videos.add_mutually_exclusive_group()
    group.add_argument("--watched", metavar="VIDEO_KEY", help="將對應影片標為已觀看")
    group.add_argument("--unwatched", metavar="VIDEO_KEY", help="將對應影片標為未觀看")
    args = parser.parse_args(argv)
    root = Path(args.project_dir).expanduser().resolve()
    try:
        if args.command == "auth":
            cfg = load_config(root / "config.yaml")
            services(runtime_dir(root, cfg) / ".secrets", interactive=True, client_file=args.client_file)
            print("個人 Gmail 和 Google Calendar 授權完成。")
        elif args.command == "doctor":
            import json
            cfg = load_config(root / "config.yaml")
            storage = runtime_dir(root, cfg)
            status = auth_status(storage / ".secrets")
            print(json.dumps({"runtime_dir": str(storage), **status}, ensure_ascii=False))
            return 0 if status["token_present"] else 2
        elif args.command == "check":
            run(root, dry_run=args.dry_run)
        elif args.command == "videos":
            cfg = load_config(root / "config.yaml")
            state = State(runtime_dir(root, cfg) / "data" / "state.db")
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
        print(f"錯誤：{safe_error(exc)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
