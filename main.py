"""
main.py — Vision-based desktop automation orchestrator.

Entry point for the full automation workflow:
  1. Fetch 10 blog posts from JSONPlaceholder API.
  2. For each post:
     a. Capture a fresh desktop screenshot.
     b. Use Gemini visual grounding to find the Notepad icon (any position).
     c. Double-click to launch Notepad.
     d. Handle any unexpected popups automatically.
     e. Paste the post content.
     f. Save as post_{id}.txt in this project directory.
     g. Close Notepad.
  3. Repeat.

Usage:
    uv run automate

Prerequisites:
    - GEMINI_API_KEY in .env (see .env.example)
    - Notepad shortcut icon on the desktop
"""

import logging
import os
import sys
import time
from pathlib import Path

import pyautogui
from dotenv import load_dotenv

from api_client import Post, fetch_posts
from automation import NotepadAutomation
from grounding import GroundingEngine
from screenshot import capture_desktop, annotate_detection, save_annotated

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_ICON_FIND_ATTEMPTS = 3      # retries if the Notepad icon is not found
ICON_RETRY_DELAY = 1.5          # seconds between icon-find retries
MAX_POPUP_DISMISS_CYCLES = 5    # max popup dismiss loops before giving up
NOTEPAD_TARGET = "Notepad shortcut desktop icon"  # grounding description

# Where post files are saved (this project's directory)
PROJECT_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(PROJECT_DIR / "automation.log", encoding="utf-8"),
        ],
    )

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core workflow helpers
# ---------------------------------------------------------------------------

def handle_popups(grounder: GroundingEngine, max_cycles: int = MAX_POPUP_DISMISS_CYCLES) -> None:
    """
    Detect and dismiss any blocking popups in a loop.

    This is what makes the system flexible: Gemini identifies and dismisses
    ANY unexpected dialog without knowing its content in advance.
    """
    for cycle in range(max_cycles):
        shot = capture_desktop()
        popup = grounder.detect_blocking_popup(shot)

        if popup is None:
            if cycle > 0:
                log.info("All popups cleared after %d cycle(s)", cycle)
            return

        action = popup.get("action", "click")
        dx = popup.get("dismiss_x")
        dy = popup.get("dismiss_y")
        desc = popup.get("description", "unknown popup")

        log.info("Popup detected: '%s' — dismissing via %s at (%s, %s)", desc, action, dx, dy)

        if action == "escape":
            pyautogui.press("escape")
        elif action == "enter":
            pyautogui.press("enter")
        elif action == "click" and dx is not None and dy is not None:
            pyautogui.click(dx, dy)
        else:
            log.warning("Unknown popup action '%s'; pressing Escape as fallback", action)
            pyautogui.press("escape")

        time.sleep(0.5)

    log.warning("Reached max popup dismiss cycles (%d); proceeding anyway", max_cycles)


def find_and_launch_notepad(
    grounder: GroundingEngine,
    automation: NotepadAutomation,
    post_id: int,
) -> bool:
    """
    Locate the Notepad icon via visual grounding and double-click to launch.

    Retries up to MAX_ICON_FIND_ATTEMPTS times with ICON_RETRY_DELAY between attempts.

    Returns True if Notepad successfully launched; False otherwise.
    """
    for attempt in range(1, MAX_ICON_FIND_ATTEMPTS + 1):
        log.info("[Post %d] Attempt %d/%d: capturing desktop...", post_id, attempt, MAX_ICON_FIND_ATTEMPTS)
        screenshot = capture_desktop()

        log.info("[Post %d] Grounding Notepad icon...", post_id)
        coords = grounder.find_element(screenshot, NOTEPAD_TARGET)

        if coords is None:
            log.warning("[Post %d] Notepad icon not found (attempt %d)", post_id, attempt)
            if attempt < MAX_ICON_FIND_ATTEMPTS:
                time.sleep(ICON_RETRY_DELAY)
            continue

        x, y = coords
        log.info("[Post %d] Icon found at (%d, %d) — launching...", post_id, x, y)

        launched = automation.launch(x, y)
        if launched:
            # Handle any popup that appeared during/after launch
            handle_popups(grounder)
            return True

        log.warning("[Post %d] Notepad did not open after click (attempt %d)", post_id, attempt)
        time.sleep(ICON_RETRY_DELAY)

    log.error("[Post %d] Could not launch Notepad after %d attempts", post_id, MAX_ICON_FIND_ATTEMPTS)
    return False


def process_post(
    post: Post,
    grounder: GroundingEngine,
    automation: NotepadAutomation,
) -> bool:
    """
    Full write cycle for a single post: launch → type → save → close.

    Returns True on success, False on failure (caller decides whether to continue).
    """
    log.info("=" * 60)
    log.info("Processing post %d: '%s'", post.id, post.title[:50])
    log.info("=" * 60)

    # 1. Find and launch Notepad
    launched = find_and_launch_notepad(grounder, automation, post.id)
    if not launched:
        return False

    # 2. Type content
    try:
        automation.type_post(post.title, post.body)
    except Exception as exc:
        log.error("[Post %d] Failed to type content: %s", post.id, exc)
        automation.close()
        return False

    # 3. Check for popups that might have appeared during typing
    handle_popups(grounder)

    # 4. Save file
    save_path = PROJECT_DIR / post.filename
    try:
        automation.save_as(save_path)
    except Exception as exc:
        log.error("[Post %d] Failed to save file: %s", post.id, exc)
        automation.close()
        return False

    # 5. Verify file was actually written
    if save_path.exists():
        log.info("[Post %d] File saved: %s (%d bytes)", post.id, save_path.name, save_path.stat().st_size)
    else:
        log.warning("[Post %d] File not found after save: %s", post.id, save_path)

    # 6. Close Notepad
    automation.close()
    time.sleep(0.5)

    # 7. Handle any popup from close (e.g. "save changes?")
    handle_popups(grounder)

    log.info("[Post %d] Done.", post.id)
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    _setup_logging()
    load_dotenv()

    log.info("Vision-Based Desktop Automation — starting up")
    log.info("Project dir: %s", PROJECT_DIR)

    # Validate API key
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        log.error("GEMINI_API_KEY not set. Copy .env.example to .env and add your key.")
        log.error("Get a free key at: https://aistudio.google.com/app/apikey")
        sys.exit(1)

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
    log.info("Using Gemini model: %s", model)

    # Initialise components
    grounder = GroundingEngine(api_key=api_key, model=model)
    automation = NotepadAutomation()

    # Fetch posts (falls back to bundled sample data if API is unreachable)
    posts = fetch_posts(limit=10)
    log.info("Will process %d posts", len(posts))

    # Brief pause so the user can switch focus to the desktop
    log.info("Starting in 3 seconds — make sure the desktop is visible...")
    time.sleep(3)

    # Main loop
    results = {"success": 0, "failed": 0}
    for post in posts:
        success = process_post(post, grounder, automation)
        if success:
            results["success"] += 1
        else:
            results["failed"] += 1
            log.warning("Skipping post %d due to errors", post.id)

        # Small pause between posts
        time.sleep(1.0)

    # Summary
    log.info("")
    log.info("=" * 60)
    log.info("Automation complete.")
    log.info("  Succeeded: %d / %d", results["success"], len(posts))
    log.info("  Failed:    %d / %d", results["failed"], len(posts))
    log.info("  Files in:  %s", PROJECT_DIR)
    log.info("=" * 60)

    if results["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
