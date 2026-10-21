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
