"""
grounding.py — Visual grounding engine powered by Gemini 2.5 Flash.

Uses Gemini's native bounding box format (0–1000 normalized coordinates)
for accurate spatial grounding. This is the coordinate system the model
was trained on, so it gives the best precision.

Coordinate conversion:
    pixel_x = (x_1000 / 1000) * image_width
    pixel_y = (y_1000 / 1000) * image_height
"""

import json
import logging
import re
import time
from typing import Optional

from google import genai
from google.genai import types
from PIL import Image

from screenshot import image_to_bytes

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts — coordinates in Gemini's native 0–1000 range
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

Is any UNEXPECTED popup, dialog box, error message, or confirmation prompt \
blocking the normal workflow? Do NOT flag the main application window.

Return a bounding box around the dismiss button (OK, Close, X, Cancel, etc.) \
using NORMALIZED coordinates in the range 0 to 1000:
- 0 = top/left edge of the image
- 1000 = bottom/right edge of the image

Return ONLY a JSON object (no markdown, no explanation):

If popup exists:
{{"popup_exists": true, "description": "<what the popup says>", "dismiss_box": [y_min, x_min, y_max, x_max], "action": "<click|escape|enter>"}}

If no popup:
{{"popup_exists": false}}
"""


# ---------------------------------------------------------------------------
# GroundingEngine
# ---------------------------------------------------------------------------

class GroundingEngine:
    """
    Visual grounding engine using Gemini's native bounding box output.

    All coordinates returned to callers are in the original image's pixel space.
    """

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash-lite"):
        self.client = genai.Client(api_key=api_key)
        self.model = model
        log.info("GroundingEngine initialized (model=%s)", model)

    def find_element(
        self,
        screenshot: Image.Image,
        description: str,
    ) -> Optional[tuple[int, int]]:
        """
        Locate a UI element by description. Returns (x, y) center pixel coords or None.
        """
        log.info("Grounding: '%s'", description)

        prompt = _FIND_ELEMENT_PROMPT.format(description=description)
        raw = self._query_model(screenshot, prompt)
        if raw is None:
            return None

        parsed = _parse_json(raw)
        if parsed is None:
            log.warning("Could not parse response: %s", raw[:300])
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

        # Convert from 0–1000 normalized to pixel coordinates
        cx = int(((x_min + x_max) / 2) / 1000 * w)
        cy = int(((y_min + y_max) / 2) / 1000 * h)

        # Clamp to image bounds
        cx = max(0, min(cx, w - 1))
        cy = max(0, min(cy, h - 1))

        log.info("Box [%d, %d, %d, %d] → center pixel (%d, %d)",
                 y_min, x_min, y_max, x_max, cx, cy)
        return (cx, cy)

    def detect_blocking_popup(
        self,
        screenshot: Image.Image,
    ) -> Optional[dict]:
        """Detect any unexpected popup. Returns dismiss info dict or None."""
        log.debug("Checking for blocking popups...")

        raw = self._query_model(screenshot, _POPUP_DETECTION_PROMPT)
        if raw is None:
            return None

        parsed = _parse_json(raw)
        if parsed is None:
            log.warning("Could not parse popup response")
            return None

        if not parsed.get("popup_exists"):
            return None

        w, h = screenshot.width, screenshot.height
        dismiss_box = parsed.get("dismiss_box")
        dismiss_x, dismiss_y = None, None

        if dismiss_box and len(dismiss_box) == 4:
            y_min, x_min, y_max, x_max = dismiss_box
            dismiss_x = int(((x_min + x_max) / 2) / 1000 * w)
            dismiss_y = int(((y_min + y_max) / 2) / 1000 * h)

        result = {
            "popup_exists": True,
            "description": parsed.get("description", "unknown"),
            "action": parsed.get("action", "click"),
            "dismiss_x": dismiss_x,
            "dismiss_y": dismiss_y,
        }
        log.info("Popup: '%s' — dismiss at (%s, %s) via %s",
                 result["description"], dismiss_x, dismiss_y, result["action"])
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _query_model(
        self,
        img: Image.Image,
        prompt: str,
        retries: int = 2,
    ) -> Optional[str]:
        """Send image + prompt to Gemini, return raw text."""
        img_bytes = image_to_bytes(img, fmt="PNG")
        img_part = types.Part.from_bytes(data=img_bytes, mime_type="image/png")
        text_part = types.Part.from_text(text=prompt)

        for attempt in range(retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
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
                    log.warning("Gemini API error (attempt %d/%d): %s — retrying in %ds",
                                attempt + 1, retries + 1, exc, wait)
                    time.sleep(wait)
                else:
                    log.error("Gemini API failed after %d attempts: %s", retries + 1, exc)
                    return None
        return None


def _parse_json(text: str) -> Optional[dict]:
    """Parse a JSON object from model output, stripping markdown fences."""
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
