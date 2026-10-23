import json

from applypilot import jsonstore


def test_remove_job_and_atomic_save(tmp_path):
    f = tmp_path / "x.json"
    jsonstore.save(f, [{"job_id": "1"}, {"job_id": "2"}])
    assert jsonstore.remove_job(f, "1") is True
    assert json.loads(f.read_text()) == [{"job_id": "2"}]
    assert jsonstore.remove_job(f, "nope") is False
    assert jsonstore.remove_job(f, "2") is True
    assert json.loads(f.read_text()) == []
    assert not list(tmp_path.glob("*.tmp"))


def test_load_missing_file(tmp_path):
    assert jsonstore.load(tmp_path / "missing.json") == []


def test_update_job_and_prune(tmp_path):
    from datetime import datetime, timedelta, timezone

    f = tmp_path / "c.json"
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    new = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    jsonstore.save(f, [{"job_id": "old", "collected_at": old}, {"job_id": "new", "collected_at": new}])
    assert jsonstore.update_job(f, "new", sent_at="t") is True
    assert jsonstore.update_job(f, "nope", sent_at="t") is False
    assert jsonstore.prune(f, 7) == 1
    assert json.loads(f.read_text()) == [{"job_id": "new", "collected_at": new, "sent_at": "t"}]
