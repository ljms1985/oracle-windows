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

CAMERA_INDEX = int(os.environ.get("CAMERA_INDEX", "0"))
ARMED = os.environ.get("CAMERA_ARMED", "1") == "1"
VISION_ENABLED = os.environ.get("CAMERA_VISION", "1") == "1"
MOTION_MIN_AREA = int(os.environ.get("CAMERA_MOTION_MIN_AREA", "5000"))
ALERT_COOLDOWN_SEC = int(os.environ.get("CAMERA_ALERT_COOLDOWN", "300"))

latest_frame = None  # shared with the GUI preview, if it is open
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

# Resolutions tried per candidate, best first. 1080p for speed; 4K is
# available but much heavier for motion + vision, and some backends only
# yield frames at lower resolutions.
RESOLUTIONS = [(1920, 1080), (1280, 720), (640, 480)]


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
        global latest_frame
        with _latest_lock:
            latest_frame = frame.copy()
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
    def __init__(self, controller=None, on_alert=None):
        self.controller = controller or CameraController()
        self.on_alert = on_alert  # function(text) - GUI log, etc.
        self.running = False
        self.armed = ARMED
        self.thread = None
        self.last_alert = 0

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

    def _loop(self):
        cv2 = _cv2()
        back_sub = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=50, detectShadows=False)
        while self.running:
            frame = self.controller.read()
            if frame is None:
                time.sleep(0.5)
                continue
            small = cv2.resize(frame, (640, 360))
            mask = back_sub.apply(small)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            motion_area = sum(cv2.contourArea(c) for c in contours if cv2.contourArea(c) > 500)
            now = time.time()
            if (self.armed and motion_area > MOTION_MIN_AREA
                    and now - self.last_alert > ALERT_COOLDOWN_SEC):
                self.last_alert = now
                self._alert(frame, motion_area)
            time.sleep(0.1)

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
