# Vision-Based Desktop Automation

A Python application that uses **Gemini 2.5 Flash** as a visual grounding engine to dynamically locate desktop icons and automate Notepad — without hardcoded coordinates, template images, or OCR rules.

Built for Windows 10/11 at 1920×1080.

---

## How It Works

The core idea: instead of searching for a specific image or hardcoded position, we send a screenshot to Gemini and describe what we want in plain English. Gemini reasons about the screen like a human would and returns pixel coordinates.

```
Desktop Screenshot  →  Gemini 2.5 Flash  →  (x, y)  →  pyautogui.doubleClick(x, y)
```

This approach is inspired by the **ScreenSeekeR** cascaded search method from [ScreenSpot-Pro (arXiv 2504.07981)](https://arxiv.org/abs/2504.07981):

1. **Full-screen pass** — Gemini receives the entire screenshot and returns coordinates + confidence.
2. **Cascaded crop pass** — If confidence is low, Gemini first identifies the screen quadrant containing the icon, then receives a zoomed crop of that quadrant for more precise localisation.

The same engine handles **unexpected popups**: after any action, a screenshot is sent to Gemini asking whether any dialog is blocking the workflow. If one is found, Gemini returns coordinates to dismiss it — without needing to know what the popup looks like in advance.

---

## Project Structure

```
tjm-project/
├── main.py                  # Orchestrator / entry point
├── grounding.py             # Gemini visual grounding engine (core)
├── automation.py            # pyautogui Notepad control
├── api_client.py            # JSONPlaceholder API client
├── screenshot.py            # mss capture + PIL annotation + demo tool
├── pyproject.toml           # uv project config + dependencies
├── .python-version          # Python 3.11
├── .env.example             # API key template
├── .gitignore
└── annotated_screenshots/   # Deliverable: 3 annotated detection screenshots
```

---

## Prerequisites

- Windows 10 or 11 at 1920×1080 resolution
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- A **Notepad shortcut icon on the desktop** (right-click desktop → New → Shortcut → `notepad.exe`)
- A Gemini API key (free tier available)

---

## Setup

### 1. Get a Gemini API key

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Sign in with a Google account
3. Click **Create API key**
4. Copy the key

### 2. Configure environment

```bash
# In the project directory:
cp .env.example .env
```

Open `.env` and replace `your_gemini_api_key_here` with your actual key:

```
GEMINI_API_KEY=AIza...your_key_here
```

### 3. Install dependencies

```bash
uv sync
```

That's it — uv reads `pyproject.toml` and installs everything into an isolated virtual environment.

---

## Running the Automation

Make sure the Notepad shortcut icon is visible on the desktop, then:

```bash
uv run python main.py
```

The script will:
1. Fetch 10 blog posts from JSONPlaceholder
2. Pause for 3 seconds (time to switch focus to the desktop)
3. For each post: capture screenshot → ground icon → launch Notepad → write → save → close
4. Save files as `post_1.txt` through `post_10.txt` in this project folder
5. Print a summary of successes/failures

A full run log is written to `automation.log`.

---

## Generating Annotated Screenshots (Deliverable)

The demo tool captures a screenshot, runs grounding, and saves an annotated PNG showing where the icon was detected:

```bash
uv run python screenshot.py
```

You will be prompted three times (for top-left, center, and bottom-right positions). Move the Notepad icon to each position before pressing Enter. Results are saved to `annotated_screenshots/`.

---

## Grounding Engine Details

`grounding.py` exposes two public methods:

| Method | Description |
|--------|-------------|
| `find_element(screenshot, description)` | Locate any UI element by plain-English description. Returns `(x, y)` or `None`. |
| `detect_blocking_popup(screenshot)` | Detect any unexpected dialog/popup and return dismiss coordinates. Returns `dict` or `None`. |

Both methods are **element-agnostic** — they work for any icon, button, text field, or dialog by changing the description string. The Notepad icon description can be swapped for any other target without code changes.

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| Icon not found | Retry up to 3× with 1.5s delay; skip post and log error |
| Notepad doesn't open | 8s timeout on window title check; retry or skip |
| Unexpected popup | Gemini detects and dismisses automatically (up to 5 cycles) |
| File already exists | Save dialog "overwrite" confirmation pressed automatically |
| API unavailable | Empty list returned; graceful error log; script exits cleanly |
| Gemini API error | Exponential backoff retry (2×); falls back to None on failure |

---

## Configuration

Environment variables (in `.env`):

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | (required) | Your Google AI Studio API key |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model to use for grounding |

---

## Discussion Notes

**Why VLM-based grounding instead of template matching?**
Template matching requires a reference image and breaks when the icon changes size, theme, or background. A VLM reasons semantically — it finds "the Notepad icon" the same way a human would scan the screen.

**Failure cases:**
- Very small icons (< 20px) may be hard for the model to localise precisely → two-stage crop helps
- Heavily occluded icons (< 30% visible) → retry + user prompt
- Non-English Windows locale → the text description may not match; extend with localised terms

**Performance:**
A single Gemini call takes roughly 1–3 seconds depending on network latency. The two-stage path adds one extra call when confidence is low. Total per-post overhead is ~5–8 seconds.

**Scaling to other resolutions / icons:**
Change `NOTEPAD_TARGET` in `main.py` to any plain-English description. The grounding engine is fully generic.
