"""Teach on any website: a browser opens at the URL, you do the task once (narrating if you like), then press Enter.

The recording is saved like a studio recording and compiles with the Compile button in the app.
Usage: uv run teach_live.py <url> [--csv examples/orangehrm-candidates.csv] [--no-mic]
Needs a display (and a microphone for narration), so it runs on your computer, not in a headless sandbox.
"""
import argparse
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

import config
import recording
import teach
from run import VIEWPORT

SCRIPTS = [config.ROOT / "static" / "describe.js", config.ROOT / "static" / "live.js"]
MIC_INPUT = {"linux": ["-f", "pulse", "-i", "default"], "darwin": ["-f", "avfoundation", "-i", ":0"]}


def start_mic(path: Path) -> subprocess.Popen | None:
    """ffmpeg records the default microphone while you teach. None (no narration) if that doesn't work."""
    if sys.platform not in MIC_INPUT:
        print("No microphone capture on this OS: recording without narration.")
        return None
    proc = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", *MIC_INPUT[sys.platform], "-ac", "1",
                             "-c:a", "libopus", str(path)], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(0.5)
    if proc.poll() is not None:
        print(f"No microphone ({proc.stderr.read().decode().strip()[:200]}): recording without narration.")
        return None
    return proc


def launch(p, headless: bool):
    if headless or config.CHROMIUM_PATH:
        return p.chromium.launch(headless=headless, executable_path=config.CHROMIUM_PATH)
    try:
        return p.chromium.launch(channel="chrome", headless=False)
    except PlaywrightError:
        return p.chromium.launch(headless=False)


def open_session(p, url: str, headless: bool = False) -> dict:
    """A browser with the recorder injected into every page, recording the screen, at the start URL."""
    browser = launch(p, headless)
    context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1, record_video_size=VIEWPORT,
                                  record_video_dir=tempfile.mkdtemp(prefix="teach_live_"))
    events = []
    context.expose_binding("__teachOnceEvent", lambda source, event: events.append(event))
    for script in SCRIPTS:
        context.add_init_script(path=script)
    page = context.new_page()
    started = time.time()

    def navigated(frame):
        u = urlsplit(frame.url)
        if frame == page.main_frame and u.scheme.startswith("http"):
            events.append({"ts": time.time() * 1000, "type": "navigation", "url": u.path + (f"?{u.query}" if u.query else ""),
                           "target": None})

    page.on("framenavigated", navigated)
    page.goto(url)
    return {"browser": browser, "context": context, "page": page, "events": events, "started": started, "url": url,
            "user_agent": page.evaluate("navigator.userAgent")}


def finish(session: dict, csv: Path | None = None, mic: bytes | None = None) -> str:
    """Close the browser (that writes the video) and save the recording. Returns the rec_id."""
    page = session["page"]
    video = page.video.path()
    try:
        page.evaluate("document.activeElement?.blur()")  # a field typed into last only reports its value on blur
        page.wait_for_timeout(100)
        session["context"].close()
    except PlaywrightError:  # the browser was closed by hand
        pass
    session["browser"].close()
    t0 = session["started"] * 1000
    events = [{k: v for k, v in e.items() if k != "ts"} | {"ts_ms": max(0, round(e["ts"] - t0))}
              for e in session["events"]]
    meta = {
        "start_url": session["url"],
        "started_at": datetime.fromtimestamp(session["started"], timezone.utc).isoformat(),
        "user_agent": session["user_agent"],
        "viewport": [VIEWPORT["width"], VIEWPORT["height"]],
        "site": urlsplit(session["url"]).hostname,
        "csv": str(csv.resolve().relative_to(config.ROOT)) if csv and csv.resolve().is_relative_to(config.ROOT) else
        str(csv) if csv else None,
    }
    return recording.save(meta, events, Path(video).read_bytes(), mic)


def wait_until_done(page):
    """Until Enter is pressed in the terminal or the tab is closed."""
    done = threading.Event()
    threading.Thread(target=lambda: (sys.stdin.readline(), done.set()), daemon=True).start()
    while not done.is_set():
        try:
            page.wait_for_timeout(200)
        except PlaywrightError:  # tab or browser closed
            return


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--csv", type=Path, help="the CSV the task will run on (its columns name the per-row values)")
    ap.add_argument("--no-mic", action="store_true")
    args = ap.parse_args()
    if args.csv and not args.csv.exists():
        raise SystemExit(f"{args.csv} not found")

    mic_path = Path(tempfile.mkdtemp(prefix="teach_live_")) / "mic.webm"
    mic = None if args.no_mic else start_mic(mic_path)
    with sync_playwright() as p:
        session = open_session(p, args.url)
        print("Do the task once in the browser window" + (", saying what you do." if mic else ".")
              + " Use fake data only. Press Enter here when you're done (or close the tab).")
        wait_until_done(session["page"])
        if mic:
            mic.communicate(b"q", timeout=10)
        print("Saving and converting…")
        rec_id = finish(session, args.csv, mic_path.read_bytes() if mic and mic_path.exists() else None)

    events = recording.load(rec_id)["events"]
    print(f"Saved {rec_id}: {len(events)} events. Compile it at {config.PORTAL_URL}/app/teach/{rec_id}")
    if any(e.get("value") == "***" for e in events):
        print(f"A password was typed: set {teach.password_env(args.url)} in .env before compiling.")
