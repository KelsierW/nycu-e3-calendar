"""Persist video watched state and calendar event identities locally in SQLite."""
import sqlite3
from pathlib import Path
from datetime import datetime


class State:
    def __init__(self, filename: Path):
        filename.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(filename)
        # The DB contains private course and video URLs; restrict local access.
        import os
        if os.name == "posix":
            os.chmod(filename, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS videos (
          key TEXT PRIMARY KEY, course TEXT, title TEXT, announced TEXT,
          url TEXT, status TEXT NOT NULL CHECK(status IN ('未觀看','已觀看')) DEFAULT '未觀看'
        );
        CREATE TABLE IF NOT EXISTS events (
          item_key TEXT PRIMARY KEY, event_id TEXT, fingerprint TEXT,
          owned INTEGER NOT NULL DEFAULT 1
        );
        """)
        self.db.commit()

    def add_video(self, v):
        self.db.execute("INSERT OR IGNORE INTO videos(key,course,title,announced,url,status) VALUES(?,?,?,?,?,'未觀看')",
                        (v.key, v.course, v.title, v.announced.isoformat(), v.url))
        self.db.commit()

    def list_videos(self, status=None):
        if status:
            return [dict(x) for x in self.db.execute("SELECT * FROM videos WHERE status=? ORDER BY announced, title", (status,))]
        return [dict(x) for x in self.db.execute("SELECT * FROM videos ORDER BY announced, title")]

    def set_video_status(self, key, status):
        if status not in ("未觀看", "已觀看"):
            raise ValueError("觀看狀態只允許 未觀看 或 已觀看")
        cur = self.db.execute("UPDATE videos SET status=? WHERE key LIKE ?", (status, key + "%"))
        self.db.commit()
        return cur.rowcount

    def event(self, key):
        row = self.db.execute("SELECT * FROM events WHERE item_key=?", (key,)).fetchone()
        return dict(row) if row else None

    def save_event(self, key, event_id, fingerprint, owned):
        self.db.execute("""INSERT INTO events(item_key,event_id,fingerprint,owned) VALUES(?,?,?,?)
          ON CONFLICT(item_key) DO UPDATE SET event_id=excluded.event_id,
          fingerprint=excluded.fingerprint, owned=excluded.owned""", (key, event_id, fingerprint, int(owned)))
        self.db.commit()

    def close(self):
        self.db.close()