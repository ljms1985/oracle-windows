"""
Camera watch for Oracle - EMEET PIXY Dual-Camera AI PTZ 4K.

What we verified about the PIXY:
  * It is a USB UVC webcam (4K@30 / 1080p@60, Sony 1/2.55" sensor,
    73° FOV, 310° pan / 180° tilt, AI tracking up to ~6m, palm gesture).
  * Its PTZ, presets, and AI tracking are officially controlled by
    EMEET Studio software (and by the optional remote), not by a
    public EMEET SDK/API that we could find. That matters for code:
    there is NO guaranteed Python API to drive the PIXY motor directly.

So this module uses three layers, in order:
  1. Native AI tracking in the camera itself - leave EMEET Studio's
     AI tracking ON, and the PIXY will already pan/tilt to follow a
     person. Oracle does not need to fight it.
  2. UVC PTZ via OpenCV - many UVC PTZ cameras accept
     CAP_PROP_PAN / TILT / ZOOM through DirectShow on Windows.
     We TRY this, report success/failure honestly, and fall back if
     the PIXY ignores it (which it may, since EMEET routes PTZ
     through Studio).
  3. Digital PTZ - crop + zoom inside a 1080p/4K frame. This always
     works for framing, even if the motor does not move. It is not
     the same as physically rotating, and the code says so.

Watch / abnormal alerts:
  * OpenCV motion detection (background subtraction) runs locally.
    Nothing is sent anywhere until motion passes a threshold AND
    the watcher is ARMED.
  * Only then is ONE snapshot sent to OpenAI Vision for a detailed
    description, and only if OPENAI_API_KEY is set and CAMERA_VISION=1.
    That means that snapshot goes to a cloud model - if you do not
    want that, set CAMERA_VISION=0 and you will get motion alerts
    with time + size, but no AI description.
  * An alert is then texted via sms.py (Twilio, see sms.py) with a
    detailed description, time, and where the snapshot was saved
    locally (alerts/). SMS text cannot carry a local photo file
    without a public URL, so the description is the message.
  * Cooldown (default 5 minutes) stops spam from one long event.
  * Privacy mode: stop the watcher and tilt the camera down if PTZ
    works, matching PIXY's own privacy tilt. The GUI shows a clear
    WATCHING / OFF indicator at all times.

Install on Windows:
  pip install opencv-python
  (pip install pillow   # only needed for the GUI live preview)

Run alone for a test:
  python camera.py
    Probes indexes 0-3 x DSHOW/MSMF/ANY (open + read one real frame
    each), prints the table, then saves one test frame under alerts/.
    Run this on the PC to prove the PIXY actually yields frames -
    "opened" alone is NOT proof, a saved frame is.
"""

import base64
import os
import threading
import time
from datetime import datetime
from pathlib import Path

# Frozen (.exe) builds: writable data (memory, workspace, credentials,
# prints, alerts, ...) must live NEXT TO Oracle.exe, not in PyInstaller's
# temp _MEIPASS folder (deleted on exit). oracle_paths.app_dir() returns
# exactly that when frozen, and the source folder when running from source.
try:
    from oracle_paths import app_dir as _oracle_app_dir
    BASE_DIR = _oracle_app_dir()
except Exception:
    BASE_DIR = Path(__file__).resolve().parent
ALERTS_DIR = BASE_DIR / "alerts"

# Auto-tracking + local face recognition (v1.0.8, items 7/9) — ported
# from the Mac build. Both are OpenCV-only by default and degrade
# gracefully if OpenCV 5.x is installed (no Haar/HOG there) or
# face_recognition is absent.
try:
    from tracking import AutoTracker
except Exception:
    AutoTracker = None
try:
    import face_profiles as face_profiles
except Exception:
    face_profiles = None

CAMERA_INDEX = int(os.environ.get("CAMERA_INDEX", "0"))
ARMED = os.environ.get("CAMERA_ARMED", "1") == "1"
VISION_ENABLED = os.environ.get("CAMERA_VISION", "1") == "1"
MOTION_MIN_AREA = int(os.environ.get("CAMERA_MOTION_MIN_AREA", "5000"))
ALERT_COOLDOWN_SEC = int(os.environ.get("CAMERA_ALERT_COOLDOWN", "300"))

latest_frame = None  # shared with the GUI preview, if it is open
# Monotonic counter, bumped on every real frame read. The GUI preview
# uses it to skip re-rendering when no new frame arrived, so a slow
# preview timer can never re-draw the same frame and a fast timer
# never wastes work. (Preview fluidity fix, v1.0.9, 2026-11-24.)
latest_frame_id = 0
# Face tags for the preview (v1.0.9): list of (box, name_or_None,
# confidence) in full-frame pixels, updated by the Watcher about
# once a second. The GUI draws these on the preview frame itself,
# so a tag follows the person as they move. Unknown faces carry
# name=None and are drawn as "Unknown" — never a guessed name.
latest_faces = []
latest_faces_at = 0.0
_latest_lock = threading.Lock()


def _cv2():
    try:
        import cv2
        return cv2
    except ImportError:
        raise RuntimeError("opencv-python is not installed. Run: pip install opencv-python")


# DirectShow error seen on Lorenza's PC when the PIXY "opens" but yields
# nothing: -2147483638 (0x8000000A). OpenCV does not surface that code
# itself, so we detect the CONDITION it describes - isOpened() True but
# read() returns ok=False / an empty frame - and report the code with it,
# so the GUI message and the test output name the exact failure.
NO_FRAME_ERROR = "-2147483638 / 0x8000000A"

# Resolutions tried per candidate, best first. 720p first since
# v1.0.9: at 1080p the capture + resize + HOG + face work per frame
# cost enough that the Watcher loop only delivered ~2-3 fps and the
# preview played frame-by-frame. 720p is plenty for the preview,
# motion, tracking and face ID (pan-and-describe still downscales
# to 960 wide for Vision anyway); 1080p stays as a fallback.
RESOLUTIONS = [(1280, 720), (1920, 1080), (640, 480)]


def _backends(cv2):
    """Backend candidates in priority order, as (name, value) pairs.

    DSHOW first: best for UVC PTZ on Windows. MSMF second (Windows
    Media Foundation, sometimes works where DSHOW grabs nothing).
    ANY last: lets OpenCV pick. Duplicates are dropped (e.g. if a
    backend constant is missing and falls back to the same value).
    """
    wanted = [
        ("DSHOW", getattr(cv2, "CAP_DSHOW", None)),
        ("MSMF", getattr(cv2, "CAP_MSMF", None)),
        ("ANY", getattr(cv2, "CAP_ANY", 0)),
    ]
    seen = set()
    out = []
    for name, value in wanted:
        if value is None or value in seen:
            continue
        seen.add(value)
        out.append((name, value))
    return out


def _frame_ok(ok, frame):
    """True only for a real, non-empty frame. isOpened() alone is not proof."""
    return bool(ok) and frame is not None and getattr(frame, "size", 0) > 0


def enumerate_cameras(max_index=4):
    """Probe indexes 0..max_index-1 x backends DSHOW/MSMF/ANY.

    For each combination: open AND read one real frame. Returns a list of
    dicts, one per combination, in probe order:
      {"index": int, "backend": "DSHOW"|"MSMF"|"ANY",
       "opened": bool,            # cap.isOpened()
       "frame_ok": bool,          # a real non-empty frame was read
       "width": int|None, "height": int|None,   # frame size when read
       "error": str|None}         # failure reason when not frame_ok
    Never raises for a single camera failure - the failure is recorded
    in that entry's "error" field and probing continues. (If OpenCV
    itself is missing, every entry carries that as its error.)
    """
    try:
        cv2 = _cv2()
    except RuntimeError as e:
        return [
            {"index": i, "backend": name, "opened": False, "frame_ok": False,
             "width": None, "height": None, "error": str(e)}
            for i in range(max_index) for name in ("DSHOW", "MSMF", "ANY")
        ]
    results = []
    for index in range(max_index):
        for name, backend in _backends(cv2):
            entry = {"index": index, "backend": name, "opened": False,
                     "frame_ok": False, "width": None, "height": None,
                     "error": None}
            cap = None
            try:
                cap = cv2.VideoCapture(index, backend)
                if not cap.isOpened():
                    entry["error"] = ("open failed (isOpened() False - no camera at "
                                      "this index, or camera in use by EMEET Studio / "
                                      "Zoom / OBS)")
                else:
                    entry["opened"] = True
                    try:
                        cap.set(cv2.CAP_PROP_FOURCC,
                                cv2.VideoWriter_fourcc(*"MJPG"))
                    except Exception:
                        pass
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                    ok, frame = cap.read()
                    if _frame_ok(ok, frame):
                        entry["frame_ok"] = True
                        entry["height"], entry["width"] = frame.shape[:2]
                    else:
                        entry["error"] = (
                            f"camera opened but returned no frames (error "
                            f"{NO_FRAME_ERROR} - try closing EMEET Studio, "
                            f"unplugging/replugging the PIXY, or a different "
                            f"USB port)")
            except Exception as e:
                entry["error"] = f"probe failed: {e}"
            finally:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
            results.append(entry)
    return results


class CameraController:
    def __init__(self, index=CAMERA_INDEX):
        self.index = index
        self.cap = None
        self.pan = 0
        self.tilt = 0
        self.zoom = 1.0
        # Digital crop centre (0.5 = middle of frame)
        self.crop_x = 0.5
        self.crop_y = 0.5
        # Set by open(): {"index", "backend", "width", "height", "tried"}.
        # "tried" is a list of human-readable per-attempt outcomes.
        # On total failure index/backend/width/height are None and "tried"
        # lists everything that was attempted.
        self.open_info = None
        # Last failure reason (open or read), as a plain string.
        self.last_error = None

    def open(self):
        """Open the camera, verified by a real frame - not isOpened() alone.

        Open order (priority):
          1. Requested index (CAMERA_INDEX, default 0), backends
             DSHOW -> MSMF -> ANY.
          2. Then every other index 0..3, same backend order.
        For each (index, backend) candidate: open, set FOURCC MJPG, then
        try resolutions 1920x1080 -> 1280x720 -> 640x480, reading a frame
        at each. A candidate only counts as OPEN if cap.isOpened() AND
        cap.read() returns a real non-empty frame.

        On success sets self.cap, self.index, self.open_info and returns
        True. On total failure raises RuntimeError naming every
        index/backend tried, the last error, and the likely cause.
        """
        cv2 = _cv2()
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        tried = []
        last_error = ""
        any_opened_but_no_frame = False
        indexes = [self.index] + [i for i in range(4) if i != self.index]
        for index in indexes:
            for backend_name, backend in _backends(cv2):
                cap = None
                try:
                    cap = cv2.VideoCapture(index, backend)
                    if not cap.isOpened():
                        msg = (f"index {index} / {backend_name}: open failed "
                               f"(isOpened() False)")
                        tried.append(msg)
                        last_error = (msg + " - no camera at this index, or "
                                      "camera in use by EMEET Studio / Zoom / OBS")
                        continue
                    try:
                        cap.set(cv2.CAP_PROP_FOURCC,
                                cv2.VideoWriter_fourcc(*"MJPG"))
                    except Exception:
                        pass
                    for width, height in RESOLUTIONS:
                        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                        ok, frame = cap.read()
                        if _frame_ok(ok, frame):
                            self.cap = cap
                            self.index = index
                            tried.append(
                                f"index {index} / {backend_name} @ "
                                f"{width}x{height}: OK "
                                f"({frame.shape[1]}x{frame.shape[0]})")
                            self.open_info = {
                                "index": index, "backend": backend_name,
                                "width": int(frame.shape[1]),
                                "height": int(frame.shape[0]),
                                "tried": list(tried)}
                            self.last_error = None
                            return True
                        tried.append(
                            f"index {index} / {backend_name} @ "
                            f"{width}x{height}: opened but no frame")
                    any_opened_but_no_frame = True
                    last_error = (
                        f"index {index} / {backend_name}: opened but "
                        f"returned no frames (error {NO_FRAME_ERROR})")
                except Exception as e:
                    msg = f"index {index} / {backend_name}: {e}"
                    tried.append(msg)
                    last_error = msg
                finally:
                    # Release failures here; the success path returns above
                    # with self.cap still holding the working capture.
                    if self.cap is not cap and cap is not None:
                        try:
                            cap.release()
                        except Exception:
                            pass
        self.cap = None
        self.open_info = {"index": None, "backend": None, "width": None,
                          "height": None, "tried": tried}
        self.last_error = last_error
        if any_opened_but_no_frame:
            cause = (f"camera opened but returned no frames (error "
                     f"{NO_FRAME_ERROR} - try closing EMEET Studio, "
                     f"unplugging/replugging the PIXY, or a different "
                     f"USB port)")
        else:
            cause = ("camera in use by EMEET Studio / Zoom / OBS, unplugged, "
                     "or no camera found at any tried index")
        raise RuntimeError(
            f"Could not open any camera. Tried indexes "
            f"{indexes} with backends DSHOW, MSMF, ANY "
            f"(requested index {self.index} first). Last error: "
            f"{last_error}. Likely cause: {cause}. "
            f"Attempts: {'; '.join(tried)}")

    def _apply_digital_ptz(self, frame):
        """Digital PTZ: crop around crop_x/crop_y at the current zoom."""
        if self.zoom <= 1.0:
            return frame
        import cv2 as _cv
        h, w = frame.shape[:2]
        cw, ch = int(w / self.zoom), int(h / self.zoom)
        cx, cy = int(self.crop_x * w), int(self.crop_y * h)
        x1 = max(0, min(w - cw, cx - cw // 2))
        y1 = max(0, min(h - ch, cy - ch // 2))
        return _cv.resize(frame[y1:y1 + ch, x1:x1 + cw], (w, h))

    def read(self):
        if self.cap is None:
            try:
                self.open()
            except Exception as e:
                self.last_error = str(e)
                return None
        try:
            ok, frame = self.cap.read()
        except Exception as e:
            ok, frame = False, None
            self.last_error = f"read raised: {e}"
        if not _frame_ok(ok, frame):
            self.last_error = (
                "read returned no frame - camera opened but returned no "
                f"frames (error {NO_FRAME_ERROR} - try closing EMEET "
                f"Studio, unplugging/replugging the PIXY, or a different "
                f"USB port)")
            # Reopen once (close + open) before giving up.
            try:
                self.close()
                self.open()
            except Exception as e:
                self.last_error = str(e)
                return None
            try:
                ok, frame = self.cap.read()
            except Exception as e:
                ok, frame = False, None
                self.last_error = f"read after reopen raised: {e}"
            if not _frame_ok(ok, frame):
                self.last_error = (
                    "reopen succeeded but read still returned no frame "
                    f"(error {NO_FRAME_ERROR} - try closing EMEET "
                    f"Studio, unplugging/replugging the PIXY, or a "
                    f"different USB port)")
                return None
        frame = self._apply_digital_ptz(frame)
        global latest_frame, latest_frame_id
        with _latest_lock:
            latest_frame = frame.copy()
            latest_frame_id += 1
        return frame

    def close(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    # -- PTZ: try UVC first, report honestly if it is ignored ------------
    def ptz(self, pan_delta=0, tilt_delta=0, zoom_delta=0.0):
        """Try physical PTZ. Returns a dict of what actually worked."""
        cv2 = _cv2()
        self.pan = max(-155, min(155, self.pan + pan_delta))
        self.tilt = max(-90, min(90, self.tilt + tilt_delta))
        self.zoom = max(1.0, min(1.5, self.zoom + zoom_delta))  # PIXY digital zoom is 1.5x
        result = {"pan": self.pan, "tilt": self.tilt, "zoom": self.zoom,
                  "uvc_pan_ok": False, "uvc_tilt_ok": False, "uvc_zoom_ok": False}
        if self.cap is not None:
            result["uvc_pan_ok"] = bool(self.cap.set(cv2.CAP_PROP_PAN, self.pan))
            result["uvc_tilt_ok"] = bool(self.cap.set(cv2.CAP_PROP_TILT, self.tilt))
            result["uvc_zoom_ok"] = bool(self.cap.set(cv2.CAP_PROP_ZOOM, self.zoom))
        # Digital fallback always applies (see read()).
        result["digital_zoom_applied"] = self.zoom
        result["note"] = ("If uvc_* are False, the PIXY ignored DirectShow PTZ - "
                          "use EMEET Studio presets / remote for motor control, "
                          "and Oracle will use digital framing + the camera's own AI tracking.")
        return result

    def privacy_mode(self):
        """Stop framing on people and tilt down if the motor allows it."""
        try:
            self.ptz(tilt_delta=-90)
        except Exception:
            pass
        return "Privacy mode: watcher should be stopped, camera tilted down if PTZ worked. Unplug the camera for full privacy if you want it guaranteed."


def describe_snapshot(image_path):
    """Send ONE snapshot to OpenAI Vision for a detailed description."""
    if not VISION_ENABLED:
        return "Vision analysis is off (CAMERA_VISION=0). Motion was detected, but no AI description was requested."
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return "Vision analysis skipped - OPENAI_API_KEY is not set."
    import json, urllib.request
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    payload = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": (
                    "Describe in detail what you see in this camera snapshot. "
                    "Say: how many people/animals, what they are doing, where in the room, "
                    "anything unusual, broken, fallen, or out of place, and whether this "
                    "looks like a normal everyday scene or something abnormal that a "
                    "homeowner should check. Be specific, do not guess identities.")},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
        "max_tokens": 300,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"].strip()


# ----------------------------------------------------------------------
# Pan-and-describe (2026-11-24, Lorenza's request)
#   "When I ask what it sees I need it to describe everything it sees
#    as the camera pans from left to right and right to left."
#
# Before this, "what do you see" had no camera path at all in the GUI:
# the only vision use was a SINGLE still snapshot — describe_snapshot()
# for a motion alert, and RepairSession.look_at_board() for one board
# photo. Nothing panned, nothing combined several views.
#
# pan_and_describe() is a COMMANDED sweep, not auto-tracking:
#   1. Pause auto-tracking (if any is running — the caller passes a
#      pause_tracking callable; the Watcher has set_auto_track()).
#      Resume it afterwards.
#   2. Pan left -> right in stops, capturing a frame at each stop.
#   3. Pan right -> left, capturing again at each stop (things move).
#   4. Describe each leg with OpenAI Vision, then merge the two legs
#      into ONE coherent spoken description, in left-to-right order.
#   5. Return the camera to exactly where it started (pan, zoom, crop).
#
# Physical pan: UVC CAP_PROP_PAN via controller.ptz(). The PIXY often
# ignores DirectShow PTZ (EMEET routes the motor through EMEET Studio),
# so if UVC pan reports False on the first move, the sweep falls back
# to DIGITAL pan: zoom 1.5x and slide the crop window left -> right
# across the wide frame. The result always says honestly which mode
# was used ("physical pan" vs "digital pan"), and if no frames can be
# read at all it says so plainly instead of inventing a description.
# Frames + description are saved under alerts/pan-YYYYMMDD-HHMMSS/.
# ----------------------------------------------------------------------

PAN_SWEEP_DEG = 60          # sweep +/- this many degrees from the start pan
PAN_SWEEP_STOPS = 5         # capture positions per leg (far left..far right)
PAN_SETTLE_SEC = 0.9        # wait after each move for the motor / frame to settle
PAN_VISION_MAX_WIDTH = 960  # frames are downscaled to this width for vision
PAN_POSITION_LABELS = ("far left", "left", "centre", "right", "far right")

# Phrases that mean "pan the camera and describe everything you see".
# Matched by gui.py _ask() (and the CLI) before the LLM is called.
# "Look at board" is NOT in here - that stays on the repair path.
PAN_DESCRIBE_PHRASES = (
    "what do you see", "describe what you see", "what can you see",
    "what do you see in the room", "describe the room",
    "look around", "look around the room", "scan the room",
    "pan and describe", "pan around", "pan the camera",
    "what's around", "what is around", "describe everything you see",
    "tell me what you see",
)


def is_pan_describe_request(text):
    """True if the user is asking Oracle to pan and describe the room."""
    if not text:
        return False
    low = " ".join(str(text).lower().split())
    return any(p in low for p in PAN_DESCRIBE_PHRASES)


def _encode_frame_b64(frame, max_width=PAN_VISION_MAX_WIDTH):
    """Downscale a frame and return it as a base64 JPEG string."""
    cv2 = _cv2()
    h, w = frame.shape[:2]
    if w > max_width:
        frame = cv2.resize(frame, (max_width, int(h * max_width / w)))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
    if not ok:
        raise RuntimeError("could not JPEG-encode a camera frame")
    return base64.b64encode(buf.tobytes()).decode()


def _openai_chat(payload, timeout=90):
    """One OpenAI chat-completions call. Key comes from the env var only."""
    import json
    import urllib.request
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set on this PC.")
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"].strip()


def _vision_describe_leg(frames, leg_label):
    """Describe one sweep leg (list of (label, b64) frames) with Vision.

    One call, all frames of the leg at once, so the model sees the
    whole leg in order and can say what is where, left to right.
    """
    if not VISION_ENABLED:
        raise RuntimeError("Vision is off (CAMERA_VISION=0).")
    model = os.environ.get("OPENAI_VISION_MODEL",
                           os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    content = [{
        "type": "text",
        "text": (
            f"This is a camera sweep, {leg_label}, of one room. The frames "
            "are in sweep order. Describe EVERYTHING you can see across "
            "all of these frames, in detail and in left-to-right order: "
            "every person (what they are doing, what they are wearing), "
            "every animal, every piece of furniture, objects on tables "
            "and shelves, doors, windows, screens, and anything unusual, "
            "broken, fallen, or out of place. Say which part of the room "
            "(far left / left / centre / right / far right) each thing is "
            "in. Do not guess at identities of people. If a frame is dark "
            "or blurry, say so instead of inventing what is in it."),
    }]
    for label, b64 in frames:
        content.append({"type": "text", "text": f"Frame: {label}."})
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    return _openai_chat({
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 700,
    })


def _vision_merge(leg_ltr, leg_rtl):
    """Merge the two legs' descriptions into one spoken description."""
    model = os.environ.get("OPENAI_VISION_MODEL",
                           os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    return _openai_chat({
        "model": model,
        "messages": [{
            "role": "user",
            "content": (
                "Merge these two descriptions of the same room into ONE "
                "clear spoken description, in left-to-right order, as if "
                "you are telling the homeowner what the camera saw while "
                "it panned left to right and then right to left. Keep "
                "every distinct object, person, and detail from both "
                "passes; drop exact duplicates. Mention anything that "
                "appeared in only one pass. Write it to be spoken aloud: "
                "natural sentences, contractions, no bullet lists, no "
                "headings. Start with a plain sentence like 'Panning "
                "across the room, from left to right, I can see...'.\n\n"
                f"LEFT-TO-RIGHT PASS:\n{leg_ltr}\n\n"
                f"RIGHT-TO-LEFT PASS:\n{leg_rtl}"),
        }],
        "max_tokens": 800,
    })


def pan_and_describe(controller=None, steps=PAN_SWEEP_STOPS,
                     sweep_deg=PAN_SWEEP_DEG, settle_sec=PAN_SETTLE_SEC,
                     progress=None, pause_tracking=None):
    """Pan left->right then right->left, describe everything seen.

    controller: a CameraController (opened by us if not given, or if
        not already open). If None, one is created and closed at the end.
    progress: optional fn(str) called with plain-English progress lines
        ("Panning left to right...", "Describing what I saw...").
    pause_tracking: optional fn() -> resume fn (or None). Called before
        the sweep and its result called afterwards, so auto-tracking
        does not fight the sweep. Callers pass watcher.set_auto_track.

    Returns a dict: {"ok": bool, "description": str, "pan_mode":
    "uvc"|"digital"|"none", "frames": [paths], "run_dir": str,
    "start_pan": float, "error": str|None}. On failure ok is False and
    "description" is a plain-English explanation, never invented.
    """
    def _say(msg):
        if progress is not None:
            try:
                progress(msg)
            except Exception:
                pass

    own_controller = controller is None
    if controller is None:
        controller = CameraController()
    resume_tracking = None
    if pause_tracking is not None:
        try:
            resume_tracking = pause_tracking()
        except Exception:
            resume_tracking = None
    run_dir = None
    try:
        try:
            if controller.cap is None:
                controller.open()
        except Exception as e:
            return {"ok": False,
                    "description": ("I could not open the camera to look "
                                    f"around: {e}"),
                    "pan_mode": "none", "frames": [], "run_dir": None,
                    "start_pan": getattr(controller, "pan", 0),
                    "error": str(e)}
        start_pan = getattr(controller, "pan", 0)
        start_zoom = getattr(controller, "zoom", 1.0)
        start_crop_x = getattr(controller, "crop_x", 0.5)

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir = ALERTS_DIR / f"pan-{stamp}"
        run_dir.mkdir(parents=True, exist_ok=True)

        # --- Decide physical vs digital pan with one probe move. ---
        _say("Panning the camera to the far left to start the sweep...")
        probe = controller.ptz(pan_delta=-sweep_deg)
        time.sleep(settle_sec)
        physical = bool(probe.get("uvc_pan_ok"))
        pan_mode = "uvc" if physical else "digital"
        if not physical:
            _say("The PIXY ignored the motor pan command, so I am sweeping "
                 "digitally across the wide frame instead.")
            # The probe move above already changed the controller's
            # *logical* pan even though the motor ignored it — reset it,
            # or every later PTZ move would start from a wrong position.
            controller.pan = start_pan
            try:
                controller.ptz(zoom_delta=0.5)  # zoom 1.0 -> 1.5x for cropping
            except Exception:
                pass

        positions = []
        for i in range(steps):
            frac = (i / (steps - 1)) if steps > 1 else 0.5
            positions.append(-sweep_deg + 2 * sweep_deg * frac)
        labels = PAN_POSITION_LABELS if steps == 5 else [
            f"position {i + 1} of {steps}" for i in range(steps)]

        def _capture_at(rel_pan, label, leg, idx):
            """Move to rel_pan (deg from start) and capture one frame."""
            if physical:
                # controller.pan is absolute; move to start_pan + rel_pan.
                target = start_pan + rel_pan
                controller.ptz(pan_delta=target - getattr(controller, "pan", 0))
            else:
                # Digital pan: slide the crop window across the frame.
                controller.crop_x = 0.5 + (rel_pan / sweep_deg) * 0.3 \
                    if sweep_deg else 0.5
            time.sleep(settle_sec)
            frame = controller.read()
            if frame is None:
                return None
            name = f"{leg}-{idx:02d}-{label.replace(' ', '-')}.jpg"
            path = run_dir / name
            cv2 = _cv2()
            if not cv2.imwrite(str(path), frame):
                return None
            return (label, path, frame)

        legs = {}
        for leg, leg_label, order in (
                ("ltr", "left to right", positions),
                ("rtl", "right to left", list(reversed(positions)))):
            _say(f"Panning {leg_label}...")
            shots = []
            # order is positions (ltr) or reversed(positions) (rtl); the
            # label comes from the position's index in `positions`.
            for idx, rel_pan in enumerate(order):
                label = labels[positions.index(rel_pan)]
                shot = _capture_at(rel_pan, label, leg, idx)
                if shot is not None:
                    shots.append(shot)
            legs[leg] = shots

        # --- Return the camera exactly where it started. ---
        try:
            if physical:
                controller.ptz(pan_delta=start_pan - getattr(controller, "pan", 0))
            else:
                # Digital mode never moved the motor; just fix the
                # logical pan the probe move polluted.
                controller.pan = start_pan
            controller.zoom = start_zoom
            controller.crop_x = start_crop_x
        except Exception:
            pass

        frames = [str(p) for leg in ("ltr", "rtl")
                  for (_l, p, _f) in legs[leg]]
        if not frames:
            return {"ok": False,
                    "description": ("The camera panned, but I could not "
                                    "grab any frames during the sweep — the "
                                    "camera may be in use by another app, or "
                                    f"it hit the no-frame error "
                                    f"({NO_FRAME_ERROR}). Try closing EMEET "
                                    "Studio, unplugging and replugging the "
                                    "PIXY, and asking again."),
                    "pan_mode": pan_mode, "frames": [], "run_dir": str(run_dir),
                    "start_pan": start_pan,
                    "error": "no frames captured during sweep"}

        _say("Describing everything I saw across the whole sweep...")
        try:
            leg_texts = {}
            for leg, leg_label in (("ltr", "left to right"),
                                   ("rtl", "right to left")):
                shots = legs[leg]
                if not shots:
                    leg_texts[leg] = "(no frames captured on this pass)"
                    continue
                encoded = [(label, _encode_frame_b64(frame))
                           for (label, _p, frame) in shots]
                leg_texts[leg] = _vision_describe_leg(encoded, leg_label)
            description = _vision_merge(leg_texts["ltr"], leg_texts["rtl"])
        except Exception as e:
            description = (
                "I panned across the room left to right and back, and saved "
                f"{len(frames)} frames under {run_dir}, but the vision "
                f"description failed: {e}. The frames are saved — I can "
                "try describing them again, or you can look at them.")
            (run_dir / "description.txt").write_text(description,
                                                     encoding="utf-8")
            return {"ok": False, "description": description,
                    "pan_mode": pan_mode, "frames": frames,
                    "run_dir": str(run_dir), "start_pan": start_pan,
                    "error": str(e)}

        if pan_mode == "digital":
            description = ("(The camera motor did not respond to the pan "
                           "command, so I swept the view digitally across "
                           "the wide frame instead — same room, same "
                           "left-to-right description.)\n\n" + description)
        (run_dir / "description.txt").write_text(description, encoding="utf-8")
        return {"ok": True, "description": description,
                "pan_mode": pan_mode, "frames": frames,
                "run_dir": str(run_dir), "start_pan": start_pan,
                "error": None}
    finally:
        if resume_tracking is not None:
            try:
                resume_tracking()
            except Exception:
                pass
        if own_controller:
            try:
                controller.close()
            except Exception:
                pass


def describe_what_you_see(controller=None, **kwargs):
    """Convenience alias: pan the camera and describe everything seen."""
    return pan_and_describe(controller=controller, **kwargs)


def capture_test_frame(path=None):
    """Open the camera, grab one real frame, save it as a JPEG.

    Returns (ok, path_or_error): on success (True, str(path)); on
    failure (False, error message). With no path given, saves under
    alerts/ as test-YYYYMMDD-HHMMSS.jpg. A saved file is the proof the
    camera yields frames - "opened" alone is not.
    """
    ctrl = CameraController()
    try:
        ctrl.open()
    except Exception as e:
        return (False, str(e))
    try:
        frame = ctrl.read()
        if frame is None:
            return (False, ctrl.last_error
                    or "read returned no frame - camera opened but "
                    f"returned no frames (error {NO_FRAME_ERROR})")
        cv2 = _cv2()
        if path is None:
            ALERTS_DIR.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = ALERTS_DIR / f"test-{stamp}.jpg"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(path), frame):
            return (False, f"could not write JPEG to {path}")
        return (True, str(path))
    except Exception as e:
        return (False, str(e))
    finally:
        ctrl.close()


class Watcher:
    def __init__(self, controller=None, on_alert=None, on_track=None):
        self.controller = controller or CameraController()
        self.on_alert = on_alert  # function(text) - GUI log, etc.
        self.on_track = on_track  # function(status dict) - GUI track label
        self.running = False
        self.armed = ARMED
        self.thread = None
        self.last_alert = 0
        # --- Auto-track + face recognition (v1.0.8, items 7 + 9) ---
        # Auto-track defaults ON when the camera is on (NEXT_BUILD
        # item 7). The GUI toggle flips self.auto_track via
        # set_auto_track(); the tracker itself is created here so
        # tracking works even without the GUI.
        self.tracker = AutoTracker(self.controller) if AutoTracker else None
        self.auto_track = True
        self.last_tracked_box = None    # (x, y, w, h) or None
        self.last_identified_name = None  # str, or None = unknown / no face
        self.last_confidence = 0.0
        self.last_track_status = "idle"  # tracking|holding|returning|...
        self.unknown_seen_count = 0     # repeats of the current unknown face
        self.frame_callback = None      # optional fn(frame, track_status)
        self._unknown_tracker = None
        if face_profiles is not None:
            try:
                self._unknown_tracker = face_profiles.UnknownTracker()
            except Exception:
                self._unknown_tracker = None
        self._last_frame = None
        self._frame_count = 0
        # Preview fluidity (v1.0.9): heavy work is time-throttled in
        # _loop so it never paces the frame grab. Face ID at most
        # once a second, tracker update at most ~3x a second; the
        # capture loop itself runs at camera rate (~30 fps).
        self._last_face_id_at = 0.0
        self._last_track_at = 0.0
        self.last_faces = []  # [(box, name_or_None, conf)] for tags
        self._last_track_report = None
        self._last_track_report_at = 0.0
        self._camera_lost_reported = False

    def start(self):
        if self.running:
            return "Watcher is already running."
        self.controller.open()
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        info = getattr(self.controller, "open_info", None) or {}
        return (f"Watcher started. Armed={self.armed}. Camera index "
                f"{info.get('index', self.controller.index)} via "
                f"{info.get('backend')} at {info.get('width')}x"
                f"{info.get('height')}.")

    def stop(self):
        self.running = False
        self.controller.close()
        return "Watcher stopped."

    # -- Auto-track / face recognition (v1.0.8, items 7 + 9) --------
    def set_auto_track(self, enabled):
        """Turn auto-tracking on/off. Returns a short status string."""
        self.auto_track = bool(enabled)
        if self.tracker is not None:
            self.tracker.enabled = self.auto_track
            if not self.auto_track:
                self.tracker.stop()
                self.tracker.enabled = False
                self.last_tracked_box = None
                self.last_track_status = "disabled"
            else:
                self.tracker.enabled = True
                self.last_track_status = "idle"
        return f"Auto-Track: {'ON' if self.auto_track else 'OFF'}."

    def track_me(self, name=None):
        """'Track me' / 'track this person' voice command.

        With a name, the tracker prefers that person's face once
        face recognition knows them; without one it follows the
        largest person in frame. Also (re-)enables auto-track.
        """
        self.set_auto_track(True)
        if self.tracker is not None:
            self.tracker.set_target(name)
        if name:
            return f"Tracking {name} — I'll follow you and keep you centred."
        return "Tracking you — I'll follow the person in frame and keep them centred."

    def stop_tracking(self):
        """'Stop tracking' voice command: hold still, stay watching."""
        if self.tracker is not None:
            self.tracker.stop()
        self.auto_track = False
        self.last_track_status = "disabled"
        return "Auto-tracking is off. The camera will stay where it is."

    def enrol_current(self, name):
        """Enrol the face currently in frame under ``name``.

        Used by the GUI 'Enroll face' button and the 'enrol this
        person as <name>' voice command. Local only — see
        face_profiles.py.
        """
        if face_profiles is None:
            return "Face enrolment is unavailable (face_profiles.py missing)."
        frame = self._last_frame
        if frame is None:
            return "Enrol failed: the camera isn't running — start camera watch first."
        return face_profiles.enrol(name, frame)

    def track_status_text(self):
        """One line for the GUI status/log, e.g. 'Tracking: Lorenza (0.87)'."""
        if self.last_track_status == "camera_lost":
            return "Tracking: camera lost — check the PIXY is plugged in."
        if self.last_track_status in ("disabled",):
            return "Tracking: off"
        if self.last_tracked_box is None:
            if self.last_track_status == "returning":
                return "Tracking: no person in view — returning to centre."
            return "Tracking: no person in view."
        if self.last_identified_name:
            return (f"Tracking: {self.last_identified_name} "
                    f"(confidence {self.last_confidence:.2f})")
        if self.unknown_seen_count >= 5:
            return ("Tracking: unknown person — seen repeatedly. "
                    "Ask who it is, then enrol them.")
        return "Tracking: unknown person"

    def _report_track(self, status):
        """Call on_track when something changed (or every 2s), thread-safe
        for the GUI because the GUI wraps it in _post_ui / root.after."""
        if self.on_track is None:
            return
        key = (status.get("action"), self.last_identified_name,
               self.last_tracked_box is not None)
        now = time.time()
        if key != self._last_track_report or now - self._last_track_report_at > 2.0:
            self._last_track_report = key
            self._last_track_report_at = now
            try:
                self.on_track(dict(status))
            except Exception:
                pass

    def _loop(self):
        cv2 = _cv2()
        back_sub = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=50, detectShadows=False)
        while self.running:
            frame = self.controller.read()
            if frame is None:
                # Camera lost: tracker must not move or crash.
                if self.tracker is not None and self.auto_track:
                    status = self.tracker.update(None)
                    self.last_track_status = status["action"]
                    self.last_tracked_box = None
                    self._report_track(status)
                if not self._camera_lost_reported:
                    self._camera_lost_reported = True
                    if self.on_alert:
                        try:
                            self.on_alert("Camera lost — no frame from the PIXY. "
                                          "Tracking is holding still; check the camera is plugged in.")
                        except Exception:
                            pass
                time.sleep(0.5)
                continue
            self._camera_lost_reported = False
            self._last_frame = frame
            self._frame_count += 1
            small = cv2.resize(frame, (640, 360))
            mask = back_sub.apply(small)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            motion_area = sum(cv2.contourArea(c) for c in contours if cv2.contourArea(c) > 500)
            # Largest moving blob, scaled back to full-frame pixels,
            # as the tracker's motion fallback (only used when no
            # person detector fires).
            motion_box = None
            if contours:
                big = max(contours, key=cv2.contourArea)
                if cv2.contourArea(big) > 500:
                    x, y, w, h = cv2.boundingRect(big)
                    fh, fw = frame.shape[:2]
                    motion_box = (int(x * fw / 640.0), int(y * fh / 360.0),
                                  int(w * fw / 640.0), int(h * fh / 360.0))
            # --- Auto-track + face identification (v1.0.8) ---
            track_status = {"action": self.last_track_status,
                            "box": self.last_tracked_box,
                            "camera_lost": False,
                            "uvc_ignored": bool(self.tracker.uvc_ignored) if self.tracker else False,
                            "target_name": self.tracker.target_name if self.tracker else None}
            _now = time.time()
            if self.tracker is not None and self.auto_track:
                # Face identification is the expensive step: run it
                # at most once a second (time-based, not per-frame —
                # every-10th-frame was 3 Hz at 30 fps and stalled
                # the capture loop). Tracking runs at most ~3 Hz
                # below; between runs the last box/status is reused,
                # so the preview is never paced by the tracker.
                identified = []
                if face_profiles is not None and _now - self._last_face_id_at >= 1.0:
                    self._last_face_id_at = _now
                    try:
                        # Multi-face: identify EVERY face in frame, not
                        # just the largest — Lorenza + Adonis are in
                        # frame together and each needs their own tag.
                        faces = []
                        for fbox in face_profiles.detect_faces(frame)[:4]:
                            fname, fconf, fbox2 = face_profiles.identify(frame, box=fbox)
                            faces.append((fbox2 or fbox, fname, fconf))
                        self.last_faces = faces
                        global latest_faces, latest_faces_at
                        with _latest_lock:
                            latest_faces = list(faces)
                            latest_faces_at = _now
                        named = [(b, n, c) for (b, n, c) in faces if n]
                        if named:
                            self.last_identified_name = named[0][1]
                            self.last_confidence = named[0][2]
                        elif faces:
                            # Face(s) in view but match nobody: unknown.
                            self.last_identified_name = None
                            self.last_confidence = 0.0
                            box = faces[0][0]
                            if self._unknown_tracker is not None:
                                is_repeat, count, _b = self._unknown_tracker.note_unknown(frame, box)
                                self.unknown_seen_count = count
                                if is_repeat and self.on_alert:
                                    try:
                                        self.on_alert(
                                            "Camera: an unfamiliar face has been seen repeatedly. "
                                            "Ask who it is, then say 'enrol this person as <name>'.")
                                    except Exception:
                                        pass
                        else:
                            self.last_identified_name = None
                            self.last_confidence = 0.0
                        identified = faces
                    except Exception:
                        pass
                if _now - self._last_track_at >= 0.3:
                    self._last_track_at = _now
                    track_status = self.tracker.update(
                        frame, motion_box=motion_box, identified_faces=identified or None)
                    self.last_tracked_box = track_status.get("box")
                    self.last_track_status = track_status.get("action", "idle")
                    if self.last_tracked_box is None:
                        self.last_identified_name = None
                        self.last_confidence = 0.0
                        self.unknown_seen_count = 0
                else:
                    track_status = dict(track_status)
                    track_status["box"] = self.last_tracked_box
                    track_status["action"] = self.last_track_status
                track_status["name"] = self.last_identified_name
                track_status["confidence"] = self.last_confidence
                track_status["unknown_seen_count"] = self.unknown_seen_count
                self._report_track(track_status)
            if self.frame_callback is not None:
                try:
                    self.frame_callback(frame, track_status)
                except Exception:
                    pass
            now = time.time()
            if (self.armed and motion_area > MOTION_MIN_AREA
                    and now - self.last_alert > ALERT_COOLDOWN_SEC):
                self.last_alert = now
                self._alert(frame, motion_area)
            time.sleep(0.005)  # was 0.1: capped the loop at 10 fps

    def _alert(self, frame, motion_area):
        cv2 = _cv2()
        ALERTS_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = ALERTS_DIR / f"alert-{stamp}.jpg"
        cv2.imwrite(str(path), frame)
        try:
            description = describe_snapshot(path)
        except Exception as e:
            description = f"Vision analysis failed: {e}. Motion area was {int(motion_area)}."
        text = (f"Oracle camera alert - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Motion detected (area {int(motion_area)}).\n"
                f"What Oracle sees: {description}\n"
                f"Snapshot saved locally at: {path}\n"
                "This is from your own EMEET PIXY camera, watched by Oracle on your PC.")
        if self.on_alert:
            try:
                self.on_alert(text)
            except Exception:
                pass
        # Email step - replaces SMS texting, per user choice.
        # This is an alert, not a request for permission to change code.
        try:
            from email_alerts import send_email
            sent = send_email("Oracle camera alert - motion detected", text)
            if not sent:
                print(f"[camera] Email alert not sent (SMTP not configured):\n{text}")
        except Exception as e:
            print(f"[camera] Email alert failed: {e}")
        print(text)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "pan":
        # python camera.py pan — full sweep test: pan left->right then
        # right->left, describe everything seen, return to start.
        result = pan_and_describe(progress=lambda m: print(f"[pan] {m}"))
        print(f"ok={result['ok']} pan_mode={result['pan_mode']} "
              f"frames={len(result['frames'])} run_dir={result['run_dir']}")
        print()
        print(result["description"])
        raise SystemExit(0 if result["ok"] else 1)
    print("Probing cameras (indexes 0-3 x DSHOW/MSMF/ANY) - open + read "
          "one real frame each:")
    rows = enumerate_cameras()
    print(f"{'index':>5}  {'backend':<7}  {'opened':<7}  {'frame':<6}  "
          f"{'size':<11}  error")
    for r in rows:
        size = f"{r['width']}x{r['height']}" if r["width"] else "-"
        print(f"{r['index']:>5}  {r['backend']:<7}  {str(r['opened']):<7}  "
              f"{str(r['frame_ok']):<6}  {size:<11}  {r['error'] or ''}")
    print()
    ok, result = capture_test_frame()
    if ok:
        print(f"Test frame saved: {result}")
    else:
        print(f"Test frame FAILED: {result}")
