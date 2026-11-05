"""Unattended local runner: exclusive lock, rotating logs and machine-readable health."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from .cli import load_config, run
from .parser import TZ
from .runtime import runtime_dir, safe_error


def acquire_lock(handle):
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Windows 本地排程執行器")
    parser.add_argument("--project-dir", type=Path, default=Path.cwd())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    root = args.project_dir.resolve()
    try:
        cfg = load_config(root / "config.yaml")
    except Exception as exc:
        print(safe_error(exc), file=sys.stderr)
        return 1
    out = runtime_dir(root, cfg) / "out"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "check.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        try:
            acquire_lock(lock)
        except OSError:
            print("已有課業檢查正在執行，略過重複啟動。")
            return 0
        logfile = out / "check.log"
        if logfile.exists() and logfile.stat().st_size > 2_000_000:
            for i in range(4, 0, -1):
                old = out / f"check.log.{i}"
                if old.exists():
                    old.replace(out / f"check.log.{i + 1}")
            logfile.replace(out / "check.log.1")
        started = datetime.now(TZ).isoformat()
        status = {"started_at": started, "dry_run": args.dry_run, "success": False}
        code = 0
        with logfile.open("a", encoding="utf-8") as log, redirect_stdout(log), redirect_stderr(log):
            print(f"\n[{started}] START dry_run={args.dry_run}", flush=True)
            try:
                run(root, dry_run=args.dry_run)
                status["success"] = True
            except Exception as exc:
                code = 1
                status["error"] = safe_error(exc)
                print("ERROR: " + status["error"], flush=True)
            status.update(finished_at=datetime.now(TZ).isoformat(), exit_code=code)
            print(f"[{status['finished_at']}] END exit_code={code}", flush=True)
        target = out / ("last-preview.json" if args.dry_run else "last-run.json")
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)
        print(f"exit_code={code}; log={logfile}; status={target}")
        return code


if __name__ == "__main__":
    raise SystemExit(main())
