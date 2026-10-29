from datetime import datetime, timezone
from nycu_e3.parser import Video
from nycu_e3.state import State


def test_watched_status_persists_and_video_deduplicates(tmp_path):
    db = tmp_path / "state.db"
    v = Video("videokey", "1151.123456", "第 3 章錄影", datetime.now(timezone.utc), "https://example.com/v")
    s = State(db)
    s.add_video(v)
    s.set_video_status("videokey", "已觀看")
    s.add_video(v)
    s.close()
    other = State(db)
    assert len(other.list_videos()) == 1
    assert other.list_videos()[0]["status"] == "已觀看"
    other.close()