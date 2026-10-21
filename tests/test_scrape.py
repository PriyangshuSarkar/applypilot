from applypilot.scrape import clean_jd, parse_contacts

PANEL = """View list
Kriti Arya
Add to list
Standard Chartered India
Filters
Select all
0 selected
Dalvir Singh
India
Manager at Standard Chartered India
Ankan Das
India
Relationship Manager at SC
Reveal and save
Megha M
India
Talent Advisor at SC
Reveal and save"""


def test_parse_contacts():
    got = parse_contacts(PANEL)
    assert [c["name"] for c in got] == ["Dalvir Singh", "Ankan Das", "Megha M"]
    assert got[2]["headline"] == "Talent Advisor at SC"
    assert [c["revealed"] for c in got] == [None, False, False]


def test_clean_jd_strips_css():
    raw = "a { text-decoration: none; color: #464feb; } tr th { background-color: #f5f5f5; }  We are hiring a dev."
    assert clean_jd(raw) == "We are hiring a dev."
    assert clean_jd("Plain text") == "Plain text"


def test_parse_contacts_with_revealed_email():
    text = PANEL.replace("Ankan Das\nIndia\nRelationship Manager at SC\nReveal and save",
                         "Ankan Das\nIndia\nRelationship Manager at SC\nAnkan.Das@sc.com")
    got = parse_contacts(text)
    assert [c["name"] for c in got] == ["Dalvir Singh", "Ankan Das", "Megha M"]
    assert got[1]["email"] == "ankan.das@sc.com" and got[1]["revealed"] is True
    assert got[2]["email"] is None and got[2]["revealed"] is False
