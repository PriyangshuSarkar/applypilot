import json

from applypilot.records import ContactInfo, EmailDraft, JobInfo, JobRecord, job_id_from_url, write_record


def test_job_id_from_url():
    assert job_id_from_url("https://www.linkedin.com/jobs/search-results/?currentJobId=4478408449&x=1") == "4478408449"
    assert job_id_from_url("https://www.linkedin.com/jobs/view/123/") == "123"
    assert job_id_from_url("https://example.com") is None


def test_write_record(tmp_path):
    rec = JobRecord(
        job=JobInfo(url="u", linkedin_job_id="42", title="SWE", company="Acme", description="Build things"),
        contacts=[ContactInfo(name="A", role="Recruiter", email="a@acme.com")],
        emails=[EmailDraft(to="a@acme.com", subject="s", body="b")],
    )
    path = write_record(rec, tmp_path)
    data = json.loads(path.read_text())
    assert path.name == "42.json"
    assert data["job"]["description"] == "Build things"
    assert data["emails"][0]["status"] == "drafted"
