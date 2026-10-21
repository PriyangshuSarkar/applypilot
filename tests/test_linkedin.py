from applypilot.config import Salary, Search
from applypilot.linkedin import build_search_url, parse_search_url

URL = ("https://www.linkedin.com/jobs/search-results/?currentJobId=4479091194&keywords=software%20engineer"
       "&origin=JOB_SEARCH_PAGE_LOCATION_SUGGESTION&geoId=106473691&f_TPR=r86400")


def test_parse_pasted_url():
    got = parse_search_url(URL)
    assert got == {"keywords": "software engineer", "geo_id": "106473691", "date_posted": "past_24h", "experience": [], "salary": None}


def test_build_url_with_entry_level():
    s = Search(queries=["software engineer"], geo_id="106473691", experience=["entry"], date_posted="past_24h")
    out = build_search_url("software engineer", s)
    assert out == ("https://www.linkedin.com/jobs/search/?keywords=software+engineer"
                   "&f_TPR=r86400&geoId=106473691&f_E=2")


SAL_URL = ("https://www.linkedin.com/jobs/search-results/?keywords=software%20engineer&geoId=106473691"
           "&f_TPR=r86400&f_SAL=f_SA_id_227001%3A276001%2C277001")


def test_parse_and_build_salary():
    assert parse_search_url(SAL_URL)["salary"] == {"facet": "227001", "values": ["276001", "277001"]}
    s = Search(queries=["software engineer"], geo_id="106473691", date_posted="past_24h",
               salary=Salary(facet="227001", values=["276001", "277001"]))
    assert build_search_url("software engineer", s) == (
        "https://www.linkedin.com/jobs/search/?keywords=software+engineer&f_TPR=r86400"
        "&geoId=106473691&f_SAL=f_SA_id_227001%3A276001%2C277001")
