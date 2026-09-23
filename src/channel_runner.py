import json
import os
import time
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from sunfun_watcher import run_sunfun_watcher
from exim_watcher import run_exim_watcher
from grecos_watcher import run_grecos_watcher
from travelplanet_watcher import run_travelplanet_watcher
from watcher import chrome, dismiss_cookies, run_itaka_watcher, run_rainbow_watcher, run_tui_watcher, run_watcher

CHANNELS_PATH = Path("config/channels.json")
WATCHERS_PATH = Path("config/watchers.json")


def source_probe(channel):
    """Health/DOM probe for a registered source. Never creates offer alerts."""
    print("CHANNEL_PROBE_ONLY", channel["id"], channel["url"])
    driver = chrome()
    try:
        driver.get(channel["url"])
        WebDriverWait(driver, 40).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        time.sleep(3)
        dismiss_cookies(driver)
        print("PROBE_TITLE", driver.title)
        print("PROBE_URL", driver.current_url)
        body = driver.find_element(By.TAG_NAME, "body").text
        print("PROBE_BODY_LENGTH", len(body))
        price_hits = sum(1 for line in body.splitlines() if "zł" in line.lower())
        print("PROBE_PRICE_LINES", price_hits)
    finally:
        driver.quit()


def main():
    channel_id = os.getenv("WATCHER_CHANNEL", "").strip()
    if not channel_id:
        raise RuntimeError("WATCHER_CHANNEL is required")

    channels = json.loads(CHANNELS_PATH.read_text(encoding="utf-8"))["channels"]
    watchers = json.loads(WATCHERS_PATH.read_text(encoding="utf-8"))["watchers"]

    channel = next((x for x in channels if x["id"] == channel_id), None)
    if channel is None:
        raise RuntimeError(f"Unknown channel: {channel_id}")

    print("CHANNEL_ID", channel["id"])
    print("CHANNEL_NAME", channel["name"])
    print("CHANNEL_STATUS", channel["status"])
    print("CHANNEL_KIND", channel["kind"])

    if channel["status"] == "production":
        cfg = next((x for x in watchers if x.get("provider") == channel_id and x.get("enabled")), None)
        if cfg is None:
            raise RuntimeError(f"No enabled watcher config for production channel {channel_id}")
        if channel_id == "wakacje_pl":
            run_watcher(cfg)
        elif channel_id == "tui_pl":
            run_tui_watcher(cfg)
        elif channel_id == "itaka_pl":
            run_itaka_watcher(cfg)
        elif channel_id == "rainbow_pl":
            run_rainbow_watcher(cfg)
        elif channel_id == "sunfun_pl":
            run_sunfun_watcher(cfg)
        elif channel_id == "exim_pl":
            run_exim_watcher(cfg)
        elif channel_id == "grecos_pl":
            run_grecos_watcher(cfg)
        elif channel_id == "travelplanet_pl":
            run_travelplanet_watcher(cfg)
        else:
            raise RuntimeError(f"Production adapter missing for {channel_id}")
        return

    source_probe(channel)


if __name__ == "__main__":
    main()
