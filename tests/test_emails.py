from applypilot.emails import Recipient, assemble_body, first_name, greeting_names
from applypilot.validate import ungrounded_numbers

A, B, C = Recipient("A One", "a@x.com"), Recipient("B Two", "b@x.com"), Recipient("C Three", "c@x.com")


def test_greeting_names():
    assert greeting_names([A]) == "A"
    assert greeting_names([A, B]) == "A and B"
    assert greeting_names([A, B, C]) == "A, B and C"


def test_first_name_and_assemble():
    assert first_name("Siva Prasad S. S") == "Siva"
    body = assemble_body("Core text.", "Siva and Karthik", "Reply to opt out.", "Priyangshu")
    assert body == "Hi Siva and Karthik,\nCore text. Reply to opt out.\nBest,\nPriyangshu"
    assert "\n\n" not in assemble_body("A.\n\nB.", "X", "o", "s")


def test_ungrounded_numbers():
    resume = "reduced latency by 30% for 2+ years, 99.5% uptime"
    assert ungrounded_numbers("cut latency 30% over 2 years", resume) == []
    assert ungrounded_numbers("cut latency 45% and 10x throughput", resume) == ["10", "45"]


def test_parse_core():
    from applypilot.llm import parse_core

    c = parse_core("**SUBJECT:** Cut API latency 30% for Tavant\nBODY:\nHi line one.\n\nSecond para.")
    assert c.subject == "Cut API latency 30% for Tavant"
    assert c.body == "Hi line one.\n\nSecond para."


def test_ungrounded_ignores_call_length():
    assert ungrounded_numbers("Open to a 15-minute chat about 30%?", "cut latency 30%") == []


def test_clean_jd_drops_trailing_more():
    from applypilot.scrape import clean_jd

    assert clean_jd("Great perks included.\n… more") == "Great perks included."


def test_parse_core_without_body_label():
    from applypilot.llm import parse_core

    c = parse_core("SUBJECT: Cut API latency 30% - applying for X\n\nFirst para.\n\nSecond.")
    assert c.subject.startswith("Cut API") and c.body == "First para.\n\nSecond."


RESUME = """• Optimized PostgreSQL queries, reducing average latency by 30% and increasing throughput.
• Deployed WebSockets features, sustaining 99.5% uptime.
• Reduced technical debt by 25% and improved API response times."""


def test_blended_numbers():
    from applypilot.validate import blended_numbers

    assert blended_numbers("I cut latency by 30% while sustaining 99.5% uptime.", RESUME) != []
    assert blended_numbers("I cut latency by 30%. Separately, I held 99.5% uptime.", RESUME) == []
    assert blended_numbers("Open to a 15-minute chat about 30% latency.", RESUME) == []


def test_company_short():
    from applypilot.validate import company_short

    assert company_short("Standard Chartered India") == "Standard Chartered"
    assert company_short("Tavant") == "Tavant"
    assert company_short("India") == "India"


def test_build_message(tmp_path):
    from applypilot.gmail import build_message

    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    m = build_message(["a@x.com", "b@x.com"], ["c@x.com"], "Subj", "Hello", str(pdf))
    assert m["To"] == "a@x.com, b@x.com" and m["Cc"] == "c@x.com" and m["Subject"] == "Subj"
    parts = list(m.iter_attachments())
    assert len(parts) == 1 and parts[0].get_filename() == "cv.pdf"
    assert "Cc" not in build_message(["a@x.com"], [], "S", "B", None)


def test_subject_too_similar():
    from applypilot.validate import subject_too_similar

    prior = ["Reduced latency by 30% - applying for Full Stack Developer"]
    assert subject_too_similar("Lowered latency by 30% - applying for Senior Engineer", prior) is not None
    assert subject_too_similar("Building search services? I have shipped Elasticsearch", prior) is None
    assert subject_too_similar("Anything", []) is None


def test_digits_inside_names_are_not_metrics():
    from applypilot.validate import blended_numbers, ungrounded_numbers

    assert ungrounded_numbers("Building an OBSv2 to AWS S3 migration on k8s?", "cut latency 30%") == []
    assert blended_numbers("Building an OBSv2 to AWS S3 migration platform?", "cut latency 30%") == []
    assert ungrounded_numbers("I cut latency 45%", "cut latency 30%") == ["45"]


def test_subject_word_limit():
    from applypilot.validate import Draft, validate_draft

    opt = "Reply to opt out."
    body = f"Hi, Acme looks great. {opt}"
    assert "subject longer than 10 words; shorten it" in validate_draft(Draft("w " * 12, body), "Acme", opt)
    assert "subject longer than 10 words; shorten it" not in validate_draft(Draft("Short subject here", body), "Acme", opt)
