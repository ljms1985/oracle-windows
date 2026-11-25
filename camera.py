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
import json
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

# ------------------------------------------------------------ camera home position
# (2026-11-24, Lorenza — CORRECTED 22:12-22:13 EST, supersedes the
# 22:01 "current position is home" rule): home is FIXED at directly
# forward — pan centred, tilt level — facing the individual in the
# chair directly in front of the computer monitor. The chair at the
# desk is the reference, not an abstract centre. The camera must
# NEVER be left stuck facing a wall, the ceiling, or the floor.
# Home NEVER moves: deliberate PTZ moves are temporary and must NOT
# update it, and no sweep or tracking move updates it either. The
# only way home changes is an explicit calibration: with Lorenza
# sitting in the chair, the forward pan/tilt that frames her is
# saved once (save_camera_home, via the "set this as home" voice
# command) and then never changed again without her saying so.
# Stored in oracle_settings.json next to Oracle.exe (the same file
# that holds the data-drive choice). With no calibration saved yet,
# home is pan 0, tilt 0, zoom 1.0, crop centred.
DEFAULT_HOME = {"pan": 0, "tilt": 0, "zoom": 1.0,
                "crop_x": 0.5, "crop_y": 0.5}
_HOME_SETTINGS_PATH_OVERRIDE = None  # tests only


def _home_settings_path():
    if _HOME_SETTINGS_PATH_OVERRIDE is not None:
        return Path(_HOME_SETTINGS_PATH_OVERRIDE)
    try:
        from oracle_paths import settings_path as _settings_path
        return Path(_settings_path())
    except Exception:
        return BASE_DIR / "oracle_settings.json"


def load_camera_home(settings_path=None):
    """Saved home position, or None when none is saved / the file
    is missing or unreadable. Values are clamped to the ranges
    CameraController.ptz() accepts. Never raises."""
    path = Path(settings_path) if settings_path is not None \
        else _home_settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        home = data.get("camera_home") if isinstance(data, dict) else None
        if not isinstance(home, dict):
            return None
        return {
            "pan": max(-155, min(155, float(home.get("pan", 0)))),
            "tilt": max(-90, min(90, float(home.get("tilt", 0)))),
            "zoom": max(1.0, min(1.5, float(home.get("zoom", 1.0)))),
            "crop_x": max(0.0, min(1.0, float(home.get("crop_x", 0.5)))),
            "crop_y": max(0.0, min(1.0, float(home.get("crop_y", 0.5)))),
        }
    except Exception:
        return None


def save_camera_home(position, settings_path=None):
    """Persist ``position`` (pan/tilt/zoom/crop_x/crop_y) as the
    FIXED home — calibration only, called explicitly ("set this as
    home"), NEVER automatically from a move or a sweep. Returns the
    saved dict, or None when the file could not be written. Never
    raises."""
    path = Path(settings_path) if settings_path is not None \
        else _home_settings_path()
    try:
        saved = {
            "pan": max(-155, min(155, float(position.get("pan", 0)))),
            "tilt": max(-90, min(90, float(position.get("tilt", 0)))),
            "zoom": max(1.0, min(1.5, float(position.get("zoom", 1.0)))),
            "crop_x": max(0.0, min(1.0, float(position.get("crop_x", 0.5)))),
            "crop_y": max(0.0, min(1.0, float(position.get("crop_y", 0.5)))),
        }
        data = {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        data["camera_home"] = saved
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return saved
    except Exception:
        return None

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
# Identified faces (internal only, 2026-11-24 22:02 — face tags
# CANCELLED): list of (box, name_or_None, confidence) in full-frame
# pixels, updated by the Watcher about once a second. Used ONLY for
# tracking-target preference and the status line ("Tracking:
# Lorenza"). NOTHING is ever drawn from this on the preview frame —
# recognition stays invisible in the background; no boxes, no name
# tags. Unknown faces carry name=None and are never given a name.
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

    def current_position(self):
        """Current pan/tilt/zoom + digital-crop centre, as a dict."""
        return {"pan": self.pan, "tilt": self.tilt, "zoom": self.zoom,
                "crop_x": self.crop_x, "crop_y": self.crop_y}

    def save_home(self):
        """Save the current position as the FIXED home (calibration
        only — explicit "set this as home", never called from a
        move or a sweep). Returns the saved dict or None."""
        return save_camera_home(self.current_position())

    def go_home(self):
        """Return the camera to its FIXED home: directly forward,
        facing the chair in front of the monitor (the saved
        calibration when one exists, else pan 0 / tilt 0 / zoom
        1.0 / crop centred). Moves via ptz() so the UVC motor is
        tried and the digital state follows either way. Returns
        (position, was_calibrated) — was_calibrated False means
        the default forward position was used because no
        calibration is saved yet. Never raises."""
        try:
            home = load_camera_home()
            was_calibrated = home is not None
            if home is None:
                home = dict(DEFAULT_HOME)
            self.ptz(pan_delta=home["pan"] - self.pan,
                     tilt_delta=home["tilt"] - self.tilt,
                     zoom_delta=home["zoom"] - self.zoom)
            self.crop_x = home["crop_x"]
            self.crop_y = home["crop_y"]
            return self.current_position(), was_calibrated
        except Exception:
            return self.current_position(), False

    def is_at_home(self, pan_tol=25, tilt_tol=20):
        """True when the camera is already (nearly) home — used by
        the idle guard, which brings it back when it is found
        pointing at a wall / ceiling / floor while idle."""
        try:
            home = load_camera_home() or DEFAULT_HOME
            return (abs(self.pan - home["pan"]) <= pan_tol
                    and abs(self.tilt - home["tilt"]) <= tilt_tol)
        except Exception:
            return True

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

# One sweep at a time, ever: the commanded pan-and-describe and the
# Watcher's automatic minute sweep share this lock, so they can
# never move the camera against each other. pan_and_describe holds
# it for its whole run; the minute sweep takes it non-blocking and
# defers when it is busy.
_SWEEP_LOCK = threading.Lock()

# Automatic minute sweep (Lorenza, 2026-11-24 22:12 EST): while
# camera watch is on, the camera pans FULLY left-to-right and
# right-to-left every minute, smooth and steady, feeding the visual
# memory log. It must NOT yank away from a person being tracked
# (defer until tracking releases), never during a "what do you
# see?" describe sweep or an alert description, and must return
# to its saved home position (or resume tracking) afterwards.
# No Vision call is made on a minute sweep — that would be an
# OpenAI call every minute. The sweep samples the Watcher's own
# 1 Hz face identification at each stop instead, and logs who /
# whether anyone was seen at each position, noting what changed
# since the previous sweep.
MINUTE_SWEEP_INTERVAL_SEC = 60.0   # between completed sweeps
MINUTE_SWEEP_DEFER_SEC = 15.0      # retry delay when it must defer
MINUTE_SWEEP_SETTLE_SEC = 0.9      # wait after each move (as pan-and-describe)

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

    # One sweep at a time: wait for any automatic minute sweep to
    # finish before moving the camera (it holds _SWEEP_LOCK for
    # ~10 s at most, and always releases it).
    _SWEEP_LOCK.acquire()
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
        try:
            _SWEEP_LOCK.release()
        except Exception:
            pass
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
        self.last_faces = []  # [(box, name_or_None, conf)] — identified
        # faces, internal only (tracking target + status line). Never
        # drawn on the preview: face tags were cancelled 2026-11-24.
        self._last_track_report = None
        self._last_track_report_at = 0.0
        self._camera_lost_reported = False
        # --- Automatic minute sweep (2026-11-24 22:12, see
        # MINUTE_SWEEP_* above) ---
        self.minute_sweep_enabled = True  # set_minute_sweep() turns it off
        self._minute_sweep_next = time.time() + MINUTE_SWEEP_INTERVAL_SEC
        self._minute_sweeping = False
        self._minute_sweep_thread = None
        self._alert_describing = False  # True while _alert runs Vision
        # Visual memory log: one entry per completed minute sweep,
        # newest last, capped at 200. Each entry: {"time": iso,
        # "positions": [{label, names, person}], "changes": [...],
        # "summary": str}. gui "where did I leave X?" answers from
        # this log plus the note_sighting facts in memory.json.
        self.visual_log = []
        self._last_sweep_presence = None  # {label: bool person seen}

    def start(self):
        if self.running:
            return "Watcher is already running."
        self.controller.open()
        # Camera home (2026-11-24, Lorenza — CORRECTED 22:12-22:13):
        # home is FIXED directly forward, facing the chair in front
        # of the monitor. Return to it BEFORE the watch loop starts
        # moving anything — the saved calibration when one exists,
        # else pan 0 / tilt 0 (directly forward).
        try:
            home_pos, home_calibrated = self.controller.go_home()
            home_text = (f" Camera returned to home, directly forward "
                         f"facing the chair (pan {home_pos['pan']}°, "
                         f"tilt {home_pos['tilt']}°, zoom "
                         f"{home_pos['zoom']}x"
                         f"{'' if home_calibrated else ', default — no calibration saved yet'}).")
        except Exception:
            home_text = ""
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        info = getattr(self.controller, "open_info", None) or {}
        return (f"Watcher started. Armed={self.armed}. Camera index "
                f"{info.get('index', self.controller.index)} via "
                f"{info.get('backend')} at {info.get('width')}x"
                f"{info.get('height')}.{home_text}")

    def stop(self):
        self.running = False
        self.controller.close()
        return "Watcher stopped."

    # -- Auto-track / face recognition (v1.0.8, items 7 + 9) --------
    def set_auto_track(self, enabled):
        """Turn Harmony tracking on/off. ON resumes Harmony (the
        PIXY leads, Oracle observes); OFF is a hold-still pause
        inside Harmony — the camera freezes until tracking is
        turned back on. Returns a short status string."""
        self.auto_track = bool(enabled)
        if self.tracker is not None:
            if not self.auto_track:
                self.tracker.stop()
                self.last_tracked_box = None
                self.last_track_status = "disabled"
            else:
                self.tracker.resume()
                self.last_track_status = "idle"
        return ("Harmony tracking: ON (PIXY leads, Oracle watches)."
                if self.auto_track
                else "Harmony tracking: PAUSED — holding still.")

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
            return (f"Tracking {name} in Harmony mode — the PIXY "
                    f"follows, and I'll quietly keep track of who is "
                    f"in frame (no boxes or name tags on the picture).")
        return ("Tracking you in Harmony mode — the PIXY follows the "
                "person in frame, and I'll quietly keep track of who "
                "is in frame (no boxes or name tags on the picture).")

    def stop_tracking(self):
        """'Stop tracking' / 'hold still' voice command: freeze all
        movement (a pause inside Harmony), keep watching."""
        if self.tracker is not None:
            self.tracker.stop()
        self.auto_track = False
        self.last_track_status = "disabled"
        return ("Tracking paused — the camera will hold still until "
                "you say track again.")

    # -- Automatic minute sweep (2026-11-24 22:12) ----------------
    def set_minute_sweep(self, enabled):
        """Turn the automatic minute sweep on/off. ON is the agreed
        behaviour (sweep every minute while watching); OFF leaves
        only the commanded pan-and-describe sweep."""
        self.minute_sweep_enabled = bool(enabled)
        if not self.minute_sweep_enabled:
            self._minute_sweep_next = (
                time.time() + MINUTE_SWEEP_INTERVAL_SEC)
        return ("Minute sweep: ON — full left-to-right and back "
                "every minute while watching."
                if self.minute_sweep_enabled else
                "Minute sweep: OFF — only pan-and-describe on request.")

    def _maybe_start_minute_sweep(self):
        """Called once per captured frame (cheap guard): start the
        minute sweep when it is due, or defer it. Defer — never
        yank — when a person is being tracked, while an alert
        description is running, or while the commanded
        pan-and-describe holds the sweep lock. The sweep itself
        runs on its own thread so the capture loop (and the
        preview) never stalls; while it runs, _loop skips tracker
        updates so tracking cannot fight it."""
        if (not self.minute_sweep_enabled or self._minute_sweeping
                or time.time() < self._minute_sweep_next):
            return
        now = time.time()
        if self.last_tracked_box is not None or self.last_identified_name:
            # A person is being tracked: defer until tracking
            # releases — never pull away from them mid-conversation.
            self._minute_sweep_next = now + MINUTE_SWEEP_DEFER_SEC
            return
        if self._alert_describing:
            self._minute_sweep_next = now + MINUTE_SWEEP_DEFER_SEC
            return
        if not _SWEEP_LOCK.acquire(blocking=False):
            # Commanded pan-and-describe is sweeping: wait for it.
            self._minute_sweep_next = now + MINUTE_SWEEP_DEFER_SEC
            return
        # Lock held until _run_minute_sweep releases it in finally.
        self._minute_sweeping = True
        try:
            thread = threading.Thread(target=self._run_minute_sweep,
                                      daemon=True)
            self._minute_sweep_thread = thread
            thread.start()
        except Exception:
            self._minute_sweeping = False
            self._minute_sweep_thread = None
            self._minute_sweep_next = now + MINUTE_SWEEP_DEFER_SEC
            try:
                _SWEEP_LOCK.release()
            except Exception:
                pass

    def _run_minute_sweep(self):
        """Full sweep left-to-right and back, on the sweep thread.
        Physical UVC pan when the PIXY obeys it, digital crop pan
        otherwise (same probe as pan_and_describe). At each stop it
        samples the loop's 1 Hz face identification — no Vision
        call, no saved frames — then returns to the FIXED home and
        resumes tracking. Logs who / whether anyone was seen at
        each position, and what changed since the last sweep, in
        visual_log (+ one throttled memory note when something
        changed or someone was seen). Never raises; the lock is
        always released and home is always restored."""
        try:
            controller = self.controller
            if controller is None:
                return
            start_pan = getattr(controller, "pan", 0)
            start_zoom = getattr(controller, "zoom", 1.0)
            start_crop_x = getattr(controller, "crop_x", 0.5)
            start_crop_y = getattr(controller, "crop_y", 0.5)
            # Probe: does the motor obey UVC pan? (Same as
            # pan_and_describe: one move to the far left.)
            probe = controller.ptz(pan_delta=-PAN_SWEEP_DEG)
            time.sleep(MINUTE_SWEEP_SETTLE_SEC)
            physical = bool(probe.get("uvc_pan_ok"))
            if not physical:
                # The probe polluted the logical pan — reset it,
                # then sweep digitally (zoom 1.5x, slide the crop).
                controller.pan = start_pan
                try:
                    controller.ptz(zoom_delta=0.5)
                except Exception:
                    pass
            positions = []
            for i in range(PAN_SWEEP_STOPS):
                frac = (i / (PAN_SWEEP_STOPS - 1)
                        if PAN_SWEEP_STOPS > 1 else 0.5)
                positions.append(-PAN_SWEEP_DEG
                                 + 2 * PAN_SWEEP_DEG * frac)
            order = positions + list(reversed(positions))
            labels = PAN_POSITION_LABELS
            seen_positions = []
            for rel_pan in order:
                label = labels[positions.index(rel_pan)]
                try:
                    if physical:
                        target = start_pan + rel_pan
                        controller.ptz(
                            pan_delta=target - getattr(controller, "pan", 0))
                    else:
                        controller.crop_x = (
                            0.5 + (rel_pan / PAN_SWEEP_DEG) * 0.3
                            if PAN_SWEEP_DEG else 0.5)
                except Exception:
                    pass
                time.sleep(MINUTE_SWEEP_SETTLE_SEC)
                # Sample the loop's face ID (best effort: it runs
                # at most once a second, so a stop may still show
                # the previous stop's faces — presence per stop is
                # coarse, never a claim about exact positions).
                try:
                    faces = list(getattr(self, "last_faces", []) or [])
                except Exception:
                    faces = []
                names = sorted({n for (_b, n, _c) in faces if n})
                seen_positions.append({
                    "label": label,
                    "names": names,
                    "person": bool(faces),
                })
            # What changed since the last sweep, per position.
            presence = {}
            for pos in seen_positions:
                # A position appears twice (there and back): a
                # person counts as present if seen on either pass.
                presence[pos["label"]] = (
                    presence.get(pos["label"], False) or pos["person"])
            changes = []
            prev = self._last_sweep_presence
            if prev is not None:
                for label in labels:
                    now_here = presence.get(label, False)
                    was_here = prev.get(label, False)
                    if now_here and not was_here:
                        changes.append(f"someone appeared at {label}")
                    elif was_here and not now_here:
                        changes.append(f"no longer anyone at {label}")
            self._last_sweep_presence = presence
            all_names = sorted({n for pos in seen_positions
                                for n in pos["names"]})
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if all_names:
                summary = (f"Minute sweep {stamp}: saw "
                           + ", ".join(all_names))
            elif any(presence.values()):
                where = ", ".join(l for l in labels if presence.get(l))
                summary = (f"Minute sweep {stamp}: someone in frame "
                           f"at {where} (unknown)")
            else:
                summary = f"Minute sweep {stamp}: nobody in frame"
            if changes:
                summary += " — changed since last sweep: " + "; ".join(changes)
            entry = {"time": stamp, "positions": seen_positions,
                     "changes": changes, "summary": summary}
            self.visual_log.append(entry)
            if len(self.visual_log) > 200:
                del self.visual_log[:-200]
            # One throttled memory note when something changed or
            # someone was seen (continuous_memory throttles per key,
            # so this cannot spam memory.json).
            if changes or all_names:
                try:
                    from continuous_memory import note_sighting as _note
                    _note(_oracle_app_dir(), summary, key="minute-sweep")
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            # Always return to the FIXED home (directly forward,
            # facing the chair), then resume tracking: the loop
            # picks tracker updates back up as soon as
            # _minute_sweeping clears.
            try:
                if getattr(self, "controller", None) is not None:
                    self.controller.go_home()
            except Exception:
                pass
            self._minute_sweeping = False
            self._minute_sweep_next = (
                time.time() + MINUTE_SWEEP_INTERVAL_SEC)
            try:
                _SWEEP_LOCK.release()
            except Exception:
                pass

    def visual_log_text(self, max_entries=10):
        """Readable text of the recent minute sweeps, newest last —
        the log 'where did I leave X?' answers from (together with
        the sighting facts in memory.json)."""
        entries = list(getattr(self, "visual_log", []) or [])[-max_entries:]
        if not entries:
            return "No minute sweeps logged yet."
        return "\n".join(e.get("summary", "") for e in entries if e.get("summary"))

    def find_in_visual_log(self, thing):
        """Last minute-sweep summary mentioning ``thing`` (a name or
        an object word), or None when no sweep ever mentioned it.
        The sweep log records people/presence per position, not
        objects — an object is only found here when a pan-and-
        describe or motion-alert sighting fact named it (see
        continuous_memory.find_last_seen)."""
        needle = " ".join(str(thing or "").lower().split())
        if not needle:
            return None
        for entry in reversed(list(getattr(self, "visual_log", []) or [])):
            summary = str(entry.get("summary", ""))
            if needle in summary.lower():
                return summary
        return None

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
            return "Tracking: paused — hold still"
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
            # Automatic minute sweep: due-check is cheap (a time
            # comparison) and runs once per frame; the sweep itself
            # runs on its own thread and pauses tracker updates.
            self._maybe_start_minute_sweep()
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
            if self.tracker is not None and self.auto_track \
                    and not self._minute_sweeping:
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
                        # frame together and each needs their own
                        # (invisible) identification; nothing is drawn.
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
        # The minute sweep must never run during an alert
        # description: flag it while Vision describes the snapshot.
        self._alert_describing = True
        try:
            description = describe_snapshot(path)
        except Exception as e:
            description = f"Vision analysis failed: {e}. Motion area was {int(motion_area)}."
        finally:
            self._alert_describing = False
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
