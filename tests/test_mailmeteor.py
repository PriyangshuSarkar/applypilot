import pytest

from applypilot.mailmeteor import Blocked, parse_result
from applypilot.store import Store

PAGE = """Find email from LinkedIn profile:
FIND EMAIL
{result}
Example: https://www.linkedin.com/in/rbranson
The most powerful LinkedIn email discovery tool"""


def page(result: str) -> str:
    return PAGE.format(result=result)


def test_valid_result():
    got = parse_result(page("PS\nPriyangshu Sarkar\nValid\nPriyangshu.Sarkar@pointo.in\nSde-1"))
    assert got == {"email": "priyangshu.sarkar@pointo.in", "status": "valid", "name": "Priyangshu Sarkar"}


def test_risky_and_unknown_status():
    assert parse_result(page("AB\nA B\nRisky\na@b.com\nHR"))["status"] == "risky"
    assert parse_result(page("AB\nA B\nUnknown\na@b.com\nHR"))["status"] == "unknown"


def test_no_results():
    assert parse_result(page("No results found"))["status"] == "none"


def test_block_messages_raise():
    with pytest.raises(Blocked):
        parse_result(page("Too many requests, try again later"))
    with pytest.raises(Blocked):
        parse_result(page("Something went wrong (error code 429)"))


def test_lookup_cache(tmp_path):
    store = Store(tmp_path / "t.db")
    assert store.get_lookup("u") is None
    store.save_lookup("u", None, "none")
    assert store.get_lookup("u") == (None, "none")
    store.save_lookup("v", "a@b.com", "valid")
    assert store.get_lookup("v") == ("a@b.com", "valid")


def test_gate_blocks_only_when_early():
    from applypilot.mailmeteor import Gate

    now, slept = [100.0], []
    gate = Gate((3, 3), clock=lambda: now[0], sleep=slept.append)
    gate.wait()                  # first call never waits
    now[0] += 1
    gate.wait()                  # 1s later, 3s gap -> waits the remaining 2s
    assert slept == [2]
    now[0] += 10 + 3             # well past the timer
    gate.wait()
    assert slept == [2]


def test_gate_runs_idle_work_while_waiting():
    from applypilot.mailmeteor import Gate

    now, slept, jobs = [0.0], [], [4, 4]  # two chunks of useful work, 4s each

    def idle():
        if not jobs:
            return False
        now[0] += jobs.pop()
        return True

    gate = Gate((10, 10), clock=lambda: now[0], sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    gate.wait(idle)              # first call: no wait, no idle work
    gate.wait(idle)              # 10s gap: 8s spent on idle work, only 2s slept
    assert slept == [2] and not jobs


def test_find_email_types_with_delay(monkeypatch):
    from unittest.mock import MagicMock
    from applypilot.mailmeteor import find_email, URL

    monkeypatch.setattr("time.sleep", lambda s: None)

    mock_page = MagicMock()
    mock_box = MagicMock()
    mock_btn = MagicMock()

    mock_page.locator.return_value = mock_box
    mock_page.get_by_role.return_value = mock_btn
    mock_page.inner_text.return_value = page("PS\nPriyangshu\nValid\np@pointo.in\nSDE")

    res = find_email(mock_page, "https://linkedin.com/in/test")

    mock_page.goto.assert_called_once_with(URL)
    mock_page.wait_for_selector.assert_called_once_with("#linkedin-url")
    mock_page.locator.assert_called_once_with("#linkedin-url")
    mock_box.click.assert_called_once()
    mock_box.fill.assert_called_once_with("")
    assert mock_box.press_sequentially.called
    args, kwargs = mock_box.press_sequentially.call_args
    assert args[0] == "https://linkedin.com/in/test"
    assert "delay" in kwargs and kwargs["delay"] > 0
    mock_btn.click.assert_called_once()
    assert res["email"] == "p@pointo.in"
