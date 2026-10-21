import subprocess
import time
from pathlib import Path

import httpx
from playwright.sync_api import Browser as PwBrowser
from playwright.sync_api import Playwright

from applypilot.config import Browser


def cdp_url(cfg: Browser) -> str:
    return f"http://127.0.0.1:{cfg.cdp_port}"


def is_running(cfg: Browser) -> bool:
    try:
        return httpx.get(f"{cdp_url(cfg)}/json/version", timeout=1).status_code == 200
    except httpx.HTTPError:
        return False


def launch_brave(cfg: Browser, urls: list[str] | None = None) -> None:
    """Start a dedicated Brave instance with remote debugging (no-op if already up)."""
    if is_running(cfg):
        return
    data_dir = Path(cfg.user_data_dir).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [cfg.brave_path, f"--user-data-dir={data_dir}", f"--profile-directory={cfg.profile_directory}", f"--remote-debugging-port={cfg.cdp_port}",
         "--no-first-run", "--no-default-browser-check", *(urls or [])],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    for _ in range(40):
        if is_running(cfg):
            return
        time.sleep(0.5)
    raise RuntimeError("Brave did not expose the debugging port")


def connect(pw: Playwright, cfg: Browser) -> PwBrowser:
    return pw.chromium.connect_over_cdp(cdp_url(cfg))
