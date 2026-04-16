"""
grounding.py — Visual grounding via Gemini.

Uses Gemini's native bounding box format (0–1000 normalized coordinates).
Coordinate conversion:
    pixel_x = (x_1000 / 1000) * image_width
    pixel_y = (y_1000 / 1000) * image_height
"""

import json
import logging
import re
import time
from typing import Dict, Optional

from google import genai
from google.genai import types
from PIL import Image

from screenshot import image_to_bytes

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_FIND_ELEMENT_PROMPT = """\
You are a desktop UI automation assistant. Analyze the screenshot below.

Your task: find the element described and return a bounding box around it.

Target element: {description}

Return the bounding box using NORMALIZED coordinates in the range 0 to 1000:
- 0 = top/left edge of the image
- 1000 = bottom/right edge of the image

Return ONLY a JSON object (no markdown, no explanation):

If found:
{{"found": true, "box": [y_min, x_min, y_max, x_max]}}

If NOT found:
{{"found": false, "box": null}}
"""

_POPUP_DETECTION_PROMPT = """\
You are a desktop UI automation assistant. Analyze the screenshot below.

Your ONLY job is to detect small SYSTEM DIALOG BOXES that are blocking the workflow.
These are things like: Windows error dialogs, UAC prompts, "File already exists" confirmations,
"Are you sure?" prompts, or crash reports.

IMPORTANT rules:
- Do NOT flag Notepad or any text editor window — that is the intended application.
- Do NOT flag the Windows taskbar, desktop icons, or normal application windows.
- ONLY flag a small modal dialog box with OK/Cancel/Yes/No/Close buttons that is blocking the screen.

Return a bounding box around the dismiss button (OK, Close, X, Cancel, etc.) \
using NORMALIZED coordinates in the range 0 to 1000:
- 0 = top/left edge of the image
- 1000 = bottom/right edge of the image

Return ONLY a JSON object (no markdown, no explanation):

If a blocking system dialog exists:
{{"popup_exists": true, "description": "<what the dialog says>", "dismiss_box": [y_min, x_min, y_max, x_max], "action": "<click|escape|enter>"}}

If no blocking dialog (including if only Notepad is visible):
{{"popup_exists": false}}
"""


# ---------------------------------------------------------------------------
# Client initialisation
# ---------------------------------------------------------------------------

def init_client(api_key: str) -> genai.Client:
    """Create and return a Gemini client."""
    client = genai.Client(api_key=api_key)
    log.info("Gemini client initialised")
    return client


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def find_element(
    client: genai.Client,
    model: str,
    screenshot: Image.Image,
    description: str,
) -> Optional[tuple[int, int]]:
    """
    Locate a UI element by natural-language description.
    Returns (x, y) center pixel coordinates, or None if not found.
    """
    log.info("Grounding: '%s'", description)
    prompt = _FIND_ELEMENT_PROMPT.format(description=description)
    raw = _query_model(client, model, screenshot, prompt)
    if raw is None:
        return None

    parsed = _parse_json(raw)
    if parsed is None:
        log.warning("Could not parse grounding response: %s", raw[:300])
        return None

    if not parsed.get("found"):
        log.info("Element not found by model")
        return None

    box = parsed.get("box")
    if not box or len(box) != 4:
        log.warning("Model returned found=true but invalid box: %s", box)
        return None

    y_min, x_min, y_max, x_max = box
    w, h = screenshot.width, screenshot.height
    cx = max(0, min(int(((x_min + x_max) / 2) / 1000 * w), w - 1))
    cy = max(0, min(int(((y_min + y_max) / 2) / 1000 * h), h - 1))

    log.info("Box [%d, %d, %d, %d] → center pixel (%d, %d)", y_min, x_min, y_max, x_max, cx, cy)
    return (cx, cy)


def detect_blocking_popup(
    client: genai.Client,
    model: str,
    screenshot: Image.Image,
) -> Optional[Dict]:
    """
    Detect any unexpected popup on screen.
    Returns a dict with dismiss coordinates and action, or None if no popup.
    """
    raw = _query_model(client, model, screenshot, _POPUP_DETECTION_PROMPT)
    if raw is None:
        return None

    parsed = _parse_json(raw)
    if parsed is None:
        log.warning("Could not parse popup response")
        return None

    if not parsed.get("popup_exists"):
        return None

    w, h = screenshot.width, screenshot.height
    dismiss_x, dismiss_y = None, None
    dismiss_box = parsed.get("dismiss_box")
    if dismiss_box and len(dismiss_box) == 4:
        y_min, x_min, y_max, x_max = dismiss_box
        dismiss_x = int(((x_min + x_max) / 2) / 1000 * w)
        dismiss_y = int(((y_min + y_max) / 2) / 1000 * h)

    result = {
        "description": parsed.get("description", "unknown"),
        "action": parsed.get("action", "click"),
        "dismiss_x": dismiss_x,
        "dismiss_y": dismiss_y,
    }
    log.info("Popup: '%s' — dismiss at (%s, %s) via %s",
             result["description"], dismiss_x, dismiss_y, result["action"])
    return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _query_model(
    client: genai.Client,
    model: str,
    img: Image.Image,
    prompt: str,
    retries: int = 2,
) -> Optional[str]:
    """Send image + prompt to Gemini and return raw response text."""
    img_bytes = image_to_bytes(img, fmt="PNG")
    img_part = types.Part.from_bytes(data=img_bytes, mime_type="image/png")
    text_part = types.Part.from_text(text=prompt)

    for attempt in range(retries + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[img_part, text_part],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                    max_output_tokens=512,
                ),
            )
            return response.text
        except Exception as exc:
            if attempt < retries:
                wait = 2 ** attempt
                log.warning("Gemini error (attempt %d/%d): %s — retrying in %ds",
                            attempt + 1, retries + 1, exc, wait)
                time.sleep(wait)
            else:
                log.error("Gemini failed after %d attempts: %s", retries + 1, exc)
                return None
    return None


def _parse_json(text: str) -> Optional[Dict]:
    """Parse a JSON object from model output, stripping any markdown fences."""
    if not text:
        return None
    clean = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError as exc:
        log.debug("JSON parse error: %s | text: %s", exc, clean[:200])
        return None
