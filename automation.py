"""
automation.py — Notepad desktop automation via pyautogui and pygetwindow.

Handles all mouse/keyboard interaction after the grounding engine has
returned coordinates: launching Notepad, typing content, saving files,
and closing the application.
"""

import logging
import time
from pathlib import Path
from typing import Optional

import pyautogui
import pygetwindow as gw
import pyperclip

log = logging.getLogger(__name__)

# Guard: never move the mouse faster than this (safety for automated runs)
pyautogui.PAUSE = 0.05          # 50 ms between every pyautogui call
pyautogui.FAILSAFE = True       # move mouse to top-left corner to abort

NOTEPAD_LAUNCH_TIMEOUT = 8.0    # seconds to wait for Notepad window to appear
NOTEPAD_WINDOW_KEYWORDS = ("notepad", "untitled")  # case-insensitive window-title matches
SAVE_DIALOG_SETTLE = 0.6        # seconds to wait after Ctrl+S for dialog to appear
CLOSE_SETTLE = 0.5              # seconds after Alt+F4 before next action


class NotepadAutomation:
    """
    Controls Notepad for a single write-save-close cycle.

    All methods log their actions and raise descriptive exceptions on failure
    so the orchestrator can decide whether to retry.
    """

    # ------------------------------------------------------------------
    # Launch
    # ------------------------------------------------------------------

    def launch(self, x: int, y: int) -> bool:
        """
        Double-click the Notepad icon at (x, y) and wait for it to open.

        Args:
            x, y: Screen coordinates returned by the grounding engine.

        Returns:
            True if Notepad window was confirmed open; False on timeout.
        """
        log.info("Double-clicking Notepad icon at (%d, %d)", x, y)
        pyautogui.moveTo(x, y, duration=0.3)
        pyautogui.doubleClick(x, y)

        return self._wait_for_notepad(timeout=NOTEPAD_LAUNCH_TIMEOUT)

    def _wait_for_notepad(self, timeout: float) -> bool:
        """Poll for a Notepad window to appear within `timeout` seconds."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._find_notepad_window() is not None:
                log.info("Notepad window confirmed open")
                return True
            time.sleep(0.3)
        log.warning("Notepad did not open within %.1fs", timeout)
        return False

    def _find_notepad_window(self) -> Optional[object]:
        """Return the first window whose title contains a Notepad keyword, or None."""
        try:
            all_windows = gw.getAllWindows()
        except Exception as exc:
            log.debug("pygetwindow error: %s", exc)
            return None

        for win in all_windows:
            title_lower = (win.title or "").lower()
            if any(kw in title_lower for kw in NOTEPAD_WINDOW_KEYWORDS):
                return win
        return None

    def is_running(self) -> bool:
        """Return True if a Notepad window is currently open."""
        return self._find_notepad_window() is not None

    def focus(self) -> None:
        """Bring the Notepad window to the foreground."""
        win = self._find_notepad_window()
        if win:
            try:
                win.activate()
                time.sleep(0.2)
            except Exception as exc:
                log.debug("Could not activate Notepad window: %s", exc)

    # ------------------------------------------------------------------
    # Content entry
    # ------------------------------------------------------------------

    def type_post(self, title: str, body: str) -> None:
        """
        Paste the formatted post content into the active Notepad window.

        Uses clipboard paste (Ctrl+V) instead of pyautogui.write() to
        correctly handle unicode characters, newlines, and special chars.
        """
        self.focus()
        content = f"Title: {title}\n\n{body}"
        log.info("Pasting content (%d chars) into Notepad", len(content))

        # Ensure any existing text is cleared first
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.1)

        pyperclip.copy(content)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.2)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save_as(self, filepath: Path) -> None:
        """
        Save the current Notepad document to `filepath` via the Save As dialog.

        Strategy: Ctrl+S opens 'Save As' for an unsaved document; we type the
        full absolute path into the filename field and press Enter.
        Handles the "file already exists — overwrite?" confirmation automatically.

        Args:
            filepath: Full path including filename (e.g. Desktop/tjm-project/post_1.txt)
        """
        self.focus()
        filepath.parent.mkdir(parents=True, exist_ok=True)

        log.info("Saving to: %s", filepath)
        pyautogui.hotkey("ctrl", "s")
        time.sleep(SAVE_DIALOG_SETTLE)

        # On first save of an unsaved Notepad document, a Save As dialog opens.
        # Type the full path directly into the filename field.
        # Using clipboard to avoid issues with backslashes in pyautogui.write()
        pyperclip.copy(str(filepath))

        # Clear any pre-filled filename and type ours
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.1)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.2)
        pyautogui.press("enter")
        time.sleep(0.4)

        # If a "file already exists" confirmation dialog appeared, confirm it
        pyautogui.press("enter")
        time.sleep(0.3)

        log.info("Save complete: %s", filepath.name)

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def close(self) -> None:
        """
        Close Notepad.

        After saving via save_as(), the document is already saved so the
        close prompt should not appear. If it does (e.g. content changed),
        we dismiss it without saving to avoid blocking the loop.
        """
        self.focus()
        log.info("Closing Notepad")
        pyautogui.hotkey("alt", "f4")
        time.sleep(CLOSE_SETTLE)

        # If a "save changes?" dialog appeared, click "Don't Save"
        # (We've already saved via save_as; this is a safety net)
        _dismiss_unsaved_changes_dialog()

        # Brief wait to let the OS fully close the window
        time.sleep(0.3)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _dismiss_unsaved_changes_dialog() -> None:
    """
    Dismiss a potential 'Do you want to save changes?' dialog after closing.

    Notepad shows this if the buffer changed after the last save. We press
    Tab to move to "Don't Save" (the second button) and press Enter,
    avoiding any accidental overwrites of already-saved files.
    """
    time.sleep(0.3)
    # Check for a dialog by looking for a window with "notepad" in title
    # that is small (dialog-sized). Simpler: just press 'n' for "Don't Save".
    # Windows Notepad "Don't Save" shortcut is Alt+N or just 'n' when focused.
    try:
        all_windows = gw.getAllWindows()
        for win in all_windows:
            title_lower = (win.title or "").lower()
            if "notepad" in title_lower or "save" in title_lower:
                # Press 'n' for "Don't Save" (works in English Windows locale)
                pyautogui.press("n")
                time.sleep(0.2)
                return
    except Exception:
        pass
