"""
screenshot.py — Desktop screen capture and annotation utilities.

Provides fast screenshot capture via mss and PIL-based annotation
for drawing detection markers on captured images.
"""

import sys
import time
import logging
from pathlib import Path
from io import BytesIO

import mss
import mss.tools
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

# Directory where annotated screenshots are saved (deliverable)
ANNOTATED_DIR = Path(__file__).parent / "annotated_screenshots"
ANNOTATED_DIR.mkdir(exist_ok=True)


def capture_desktop() -> Image.Image:
    """Capture the full primary monitor desktop as a PIL Image."""
    with mss.mss() as sct:
        # Monitor 1 is the primary display
        monitor = sct.monitors[1]
        raw = sct.grab(monitor)
        # mss returns BGRA; convert to RGB PIL Image
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    log.debug("Captured desktop: %dx%d", img.width, img.height)
    return img


def image_to_bytes(img: Image.Image, fmt: str = "PNG") -> bytes:
    """Convert a PIL Image to raw bytes for API upload."""
    buf = BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def annotate_detection(
    img: Image.Image,
    x: int,
    y: int,
    label: str = "Detected",
    radius: int = 30,
    color: str = "#FF3B3B",
) -> Image.Image:
    """
    Draw a circle and label at the detected coordinates on a copy of the image.

    Args:
        img:    Source PIL Image (not modified in place).
        x, y:  Center of detected element in pixels.
        label: Text label shown near the marker.
        radius: Radius of the circle in pixels.
        color:  Hex color for the annotation.

    Returns:
        Annotated PIL Image copy.
    """
    annotated = img.copy().convert("RGBA")
    overlay = Image.new("RGBA", annotated.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Outer filled circle (semi-transparent)
    draw.ellipse(
        [x - radius, y - radius, x + radius, y + radius],
        fill=(*_hex_to_rgb(color), 60),
        outline=(*_hex_to_rgb(color), 230),
        width=3,
    )

    # Crosshair lines
    line_len = radius + 15
    draw.line([(x - line_len, y), (x + line_len, y)], fill=(*_hex_to_rgb(color), 200), width=2)
    draw.line([(x, y - line_len), (x, y + line_len)], fill=(*_hex_to_rgb(color), 200), width=2)

    annotated = Image.alpha_composite(annotated, overlay).convert("RGB")

    # Draw label text with a dark background for readability
    draw_final = ImageDraw.Draw(annotated)
    font_size = 20
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except (OSError, IOError):
        font = ImageFont.load_default()

    text = f" {label} ({x}, {y}) "
    bbox = draw_final.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # Position label below-right of circle, keep within image bounds
    tx = min(x + radius + 5, img.width - text_w - 5)
    ty = min(y + radius + 5, img.height - text_h - 5)

    draw_final.rectangle([tx - 2, ty - 2, tx + text_w + 2, ty + text_h + 2], fill=(0, 0, 0, 180))
    draw_final.text((tx, ty), text, fill=_hex_to_rgb(color), font=font)

    return annotated


def save_annotated(img: Image.Image, filename: str) -> Path:
    """Save an annotated image to the annotated_screenshots directory."""
    out_path = ANNOTATED_DIR / filename
    img.save(out_path)
    log.info("Saved annotated screenshot: %s", out_path)
    return out_path


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert '#RRGGBB' to (R, G, B) tuple."""
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ---------------------------------------------------------------------------
# Demo entry point  (uv run demo)
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Demo tool for generating annotated screenshot deliverables.

    Usage:
        uv run demo

    Move the Notepad icon to the desired position (top-left, center, bottom-right)
    before running. The tool captures the desktop, runs grounding, annotates the
    result, and saves it to annotated_screenshots/.

    Requires GEMINI_API_KEY in .env.
    """
    import os
    from dotenv import load_dotenv
    from grounding import GroundingEngine

    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set. Copy .env.example to .env and add your key.")
        sys.exit(1)

    positions = ["top_left", "center", "bottom_right"]
    grounder = GroundingEngine(api_key=api_key)

    for position in positions:
        input(
            f"\n[DEMO] Move the Notepad icon to the {position.replace('_', '-')} area, "
            f"then press ENTER to capture..."
        )

        print(f"  Capturing desktop...")
        screenshot = capture_desktop()

        print(f"  Grounding Notepad icon...")
        coords = grounder.find_element(screenshot, "Notepad shortcut desktop icon")

        if coords is None:
            print(f"  WARNING: Could not detect Notepad icon for position '{position}'. Skipping.")
            continue

        x, y = coords
        print(f"  Detected at ({x}, {y})")

        annotated = annotate_detection(
            screenshot, x, y,
            label=f"Notepad [{position}]"
        )
        filename = f"notepad_detected_{position}.png"
        path = save_annotated(annotated, filename)
        print(f"  Saved: {path}")

    print("\n[DEMO] Done. Check annotated_screenshots/ for results.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    main()
