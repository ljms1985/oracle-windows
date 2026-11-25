"""
Camera auto-tracking for Oracle (Windows) — EMEET PIXY Dual-Camera AI PTZ 4K.

HARMONY MODE ONLY (decided 2026-11-24, Lorenza): the PIXY's own
native AI tracking leads all physical movement — it is hardware,
smooth, 310° pan — and Oracle NEVER drives the motor on its own.
There is no Oracle-only tracking mode and no toggle to switch to
one: the two trackers fought each other and the camera "freaked
out", constantly moving with no scan command. Oracle's role is
observe-only: identify faces (invisibly — no boxes or name tags
are ever drawn on the preview, 2026-11-24 22:02), watch
for motion, send alerts, remember who was seen. It intervenes
with ONE small UVC correction only if the tracked person stays
clearly off-centre (outside the dead zone) for more than 5 seconds
with no PIXY correction, then waits at least 5 seconds before
another. Never during a pan-and-describe sweep, never while the
camera is already moving. A "hold still" / "stop tracking" command
is a pause inside Harmony, not a separate mode — it freezes all
movement until she says track again.

Calm rules (why the camera stopped hunting):
  * Bigger dead zone (0.10 of frame): small movements move nothing.
  * Target lock: once locked onto a person, Oracle does not switch
    to another person / motion blob unless that person leaves frame
    for more than 10 seconds.
  * Sticky box: a detection whose centre jumps >0.25 of the frame
    from the last box within a second is ignored — that is a
    detector flip or a TV flicker, not a person teleporting.
  * Motion fallback is person-shaped only (taller than wide) and
    must cover >=5% of the frame — a TV screen flickering is wide,
    not a person, and no longer steers the camera.
  * Face boxes are expanded symmetrically around the face centre
    (the old 3x-wide / 4x-tall expansion biased the centre
    downwards and let faces win over full-body boxes, so the
    target jumped between detectors every run).
  * No return-to-centre hunting: when nobody is in view, Harmony
    holds still — the PIXY owns the position.
  * At most 1 correction per 5s, steps are small (<=8°), errors are
    exponentially smoothed — never spin.
  * Frame read fails: do not move, do not crash — report
    ``camera_lost`` and hold still until frames come back.
  * Tracking data stays local on the PC.

Detection layers, in order: HOG people + Haar face / full-body
cascades (OpenCV 4.x). The largest person box wins, subject to the
sticky-box and target-lock rules above. Motion (background
subtraction) is only a fallback when no person detector fires.

Version note: opencv-python 5.x removed ``HOGDescriptor`` and
``CascadeClassifier``. This module needs the 4.x line —
requirements.txt pins ``opencv-python==4.11.0.86``. If a detector
is missing on the installed OpenCV, that detector is skipped
(and reported in :attr:`AutoTracker.detector_status`) and the
remaining detectors + motion carry on.
"""

import time

DEAD_ZONE = 0.10          # fraction of frame w/h: inside this, no move
SMOOTHING = 0.35          # exponential smoothing alpha for centre error
MIN_STEP_INTERVAL = 0.75  # seconds between PTZ steps (at most 1 per 0.75s)
MAX_PAN_STEP = 12         # degrees per step (Harmony intervention cap)
MAX_TILT_STEP = 10        # degrees per step
MIN_STEP = 4              # degrees: smallest step worth sending
HOLD_AFTER_NO_PERSON = 3.0    # seconds with no person: hold, do not hunt
# Harmony: the PIXY leads; Oracle only nudges when the PIXY has
# clearly not corrected an off-centre person for this long.
HARMONY_OFF_CENTRE_SECONDS = 5.0
HARMONY_CORRECTION_COOLDOWN = 5.0
HARMONY_MAX_STEP = 8     # degrees: one small correction, never a swing
TARGET_LOCK_SECONDS = 10.0  # keep a locked target this long after it vanishes
STICKY_JUMP = 0.25       # frame fraction: a bigger centre jump is a flip, not a move
DETECT_EVERY = 0.3        # seconds between person-detection runs
MOTION_MIN_FRACTION = 0.05  # motion box must cover >=5% of the frame
DIGITAL_ZOOM_WHEN_TRACKING = 1.25  # zoom used when UVC PTZ is ignored


def _cv2():
    import cv2
    return cv2


class AutoTracker:
    """Tracks one person in frame and drives a CameraController."""

    def __init__(self, controller=None, dead_zone=DEAD_ZONE,
                 smoothing=SMOOTHING, min_step_interval=MIN_STEP_INTERVAL):
        self.controller = controller
        self.dead_zone = dead_zone
        self.smoothing = smoothing
        self.min_step_interval = min_step_interval
        self.enabled = True
        # Harmony only (2026-11-24 decision): "harmony" is the one
        # tracking mode — the PIXY leads, Oracle observes. "off" is
        # the hold-still pause inside Harmony, not a separate mode.
        # There is deliberately no Oracle-only driving mode.
        self.mode = "harmony"
        self.target_name = None  # "track this person": prefer this identity
        self.last_box = None     # (x, y, w, h) in full-frame pixels
        self.last_source = None  # 'hog' | 'face' | 'fullbody' | 'motion' | None
        self.last_seen = 0.0     # time a person was last detected
        self.last_seen_box = None
        self.camera_lost = False
        self.returning_to_centre = False
        self.uvc_ignored = False  # True once UVC PTZ has reported all-False
        self.detector_status = {}  # {'hog': True, 'face': True, ...}
        # Harmony state: when the tracked person first went
        # off-centre, and when Oracle last sent a correction.
        self._off_centre_since = None
        self._last_harmony_correction = 0.0
        self._target_last_seen = 0.0
        self._last_digital_follow = 0.0
        self._smooth_ex = 0.0
        self._smooth_ey = 0.0
        self._last_step = 0.0
        self._last_detect = 0.0
        self._last_detect_box = None
        self._hog = None
        self._hog_tried = False
        self._face_cascade = None
        self._face_tried = False
        self._body_cascade = None
        self._body_tried = False
        self._back_sub = None

    # ------------------------------------------------------------ detectors

    def _load_detectors(self):
        """Load each detector once; record which ones actually exist."""
        try:
            cv2 = _cv2()
        except Exception:
            self.detector_status = {"error": "opencv not installed"}
            return
        if not self._hog_tried:
            self._hog_tried = True
            try:
                if hasattr(cv2, "HOGDescriptor"):
                    hog = cv2.HOGDescriptor()
                    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
                    self._hog = hog
                    self.detector_status["hog"] = True
                else:
                    self.detector_status["hog"] = False
            except Exception:
                self.detector_status["hog"] = False
        if not self._face_tried:
            self._face_tried = True
            self._face_cascade = self._load_cascade(
                "haarcascade_frontalface_default.xml")
            self.detector_status["face"] = self._face_cascade is not None
        if not self._body_tried:
            self._body_tried = True
            self._body_cascade = self._load_cascade("haarcascade_fullbody.xml")
            self.detector_status["fullbody"] = self._body_cascade is not None

    @staticmethod
    def _load_cascade(filename):
        try:
            cv2 = _cv2()
            if not hasattr(cv2, "CascadeClassifier"):
                return None
            import os
            path = cv2.data.haarcascades + filename
            if not os.path.exists(path):
                return None
            cascade = cv2.CascadeClassifier(path)
            return cascade if not cascade.empty() else None
        except Exception:
            return None

    def detect_person(self, frame, motion_box=None):
        """Largest person box (x, y, w, h) in full-frame pixels, or None.

        Tries HOG people, then Haar face, then Haar full-body, and
        takes the largest box found. Motion is only a fallback when
        no detector fires. Detection is throttled to once per
        DETECT_EVERY seconds — between runs the last box is reused,
        so this is cheap to call every frame.
        """
        if frame is None:
            return None
        now = time.time()
        if now - self._last_detect < DETECT_EVERY and self._last_detect_box is not None:
            return self._last_detect_box
        self._last_detect = now
        self._load_detectors()
        cv2 = _cv2()
        h, w = frame.shape[:2]
        scale = min(1.0, 640.0 / max(w, 1))
        small = cv2.resize(frame, (int(w * scale), int(h * scale))) \
            if scale < 1.0 else frame
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        candidates = []  # (area, box_full_frame, source)

        def _add(box_small, source):
            x, y, bw, bh = (int(v) for v in box_small)
            box = (int(x / scale), int(y / scale),
                   int(bw / scale), int(bh / scale))
            candidates.append((box[2] * box[3], box, source))

        if self._hog is not None:
            try:
                rects, _weights = self._hog.detectMultiScale(
                    gray, winStride=(8, 8), padding=(8, 8), scale=1.05)
                for (x, y, bw, bh) in rects:
                    _add((x, y, bw, bh), "hog")
            except Exception:
                pass
        if self._face_cascade is not None:
            try:
                faces = self._face_cascade.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
                for (x, y, bw, bh) in faces:
                    # A face box alone is small; expand it to an
                    # approximate upper-body box, SYMMETRICALLY around
                    # the face centre, so framing uses the person, not
                    # just their head — and so the box centre stays on
                    # the person instead of drifting below the face
                    # (the old 3x-wide / 4x-tall expansion biased the
                    # centre down and let faces beat full-body boxes,
                    # flipping the target between detectors).
                    _add((max(0, x - bw // 2), max(0, y - bh),
                          bw * 2, bh * 3), "face")
            except Exception:
                pass
        if self._body_cascade is not None:
            try:
                bodies = self._body_cascade.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=3, minSize=(40, 80))
                for (x, y, bw, bh) in bodies:
                    _add((x, y, bw, bh), "fullbody")
            except Exception:
                pass
        if candidates:
            _area, box, source = max(candidates, key=lambda c: c[0])
            self._last_detect_box = box
            self.last_source = source
            return box
        # Fallback: motion only, and only if it is big enough AND
        # person-shaped (taller than wide) to be a person rather
        # than a curtain / pet / TV flicker. A TV screen flickering
        # is a wide blob — it must never steer the camera.
        if motion_box is not None:
            mx, my, mw, mh = motion_box
            if (mw * mh >= MOTION_MIN_FRACTION * w * h
                    and mh > mw):
                self._last_detect_box = motion_box
                self.last_source = "motion"
                return motion_box
        self._last_detect_box = None
        self.last_source = None
        return None

    def motion_box(self, frame):
        """Largest moving blob's box, for the motion fallback.

        Own background subtractor (the Watcher has its own too, and
        passes its box in — this is for standalone use / tests).
        """
        if frame is None:
            return None
        cv2 = _cv2()
        if self._back_sub is None:
            self._back_sub = cv2.createBackgroundSubtractorMOG2(
                history=500, varThreshold=50, detectShadows=False)
        small = cv2.resize(frame, (640, 360))
        mask = self._back_sub.apply(small)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        c = max(contours, key=cv2.contourArea)
        if cv2.contourArea(c) < 500:
            return None
        x, y, w, h = cv2.boundingRect(c)
        fh, fw = frame.shape[:2]
        sx, sy = fw / 640.0, fh / 360.0
        return (int(x * sx), int(y * sy), int(w * sx), int(h * sy))

    # ------------------------------------------------------------ PTZ drive

    def _step_for_error(self, error, max_step=MAX_PAN_STEP):
        """Proportional PTZ step (degrees) for a normalised error.

        error is in frame fractions (-0.5..0.5). Returns 0 inside the
        dead zone, otherwise a step between MIN_STEP and max_step.
        """
        if abs(error) < self.dead_zone:
            return 0
        return int(max(MIN_STEP, min(max_step, abs(error) * 40))) \
            * (1 if error > 0 else -1)

    def _drive(self, pan_delta, tilt_delta):
        """Send one PTZ step; record whether UVC actually moved it."""
        if self.controller is None or (pan_delta == 0 and tilt_delta == 0):
            return {}
        try:
            result = self.controller.ptz(pan_delta=pan_delta,
                                         tilt_delta=tilt_delta)
        except Exception:
            return {}
        uvc_ok = bool(result.get("uvc_pan_ok") or result.get("uvc_tilt_ok"))
        if not uvc_ok and (result.get("uvc_pan_ok") is False
                           or result.get("uvc_tilt_ok") is False):
            self.uvc_ignored = True
        return result

    def _digital_follow(self, error_x, error_y):
        """Shift the digital crop centre toward the person.

        Only meaningful while zoomed in (read() crops only when
        zoom > 1.0), so when UVC is ignored we also ease the zoom
        up to DIGITAL_ZOOM_WHEN_TRACKING first.
        """
        ctrl = self.controller
        if ctrl is None:
            return
        try:
            if self.uvc_ignored and ctrl.zoom < DIGITAL_ZOOM_WHEN_TRACKING:
                ctrl.ptz(zoom_delta=DIGITAL_ZOOM_WHEN_TRACKING - ctrl.zoom)
            if ctrl.zoom > 1.0:
                ctrl.crop_x = max(0.15, min(0.85, ctrl.crop_x + error_x * 0.5))
                ctrl.crop_y = max(0.15, min(0.85, ctrl.crop_y + error_y * 0.5))
        except Exception:
            pass

    def _return_to_centre_step(self):
        """One gentle step back toward pan/tilt 0 and crop centre."""
        ctrl = self.controller
        if ctrl is None:
            return False
        moved = False
        try:
            pan = getattr(ctrl, "pan", 0)
            tilt = getattr(ctrl, "tilt", 0)
            pan_step = -int(max(MIN_STEP, min(10, abs(pan) * 0.25))) \
                if abs(pan) >= MIN_STEP else (-pan if pan else 0)
            tilt_step = -int(max(MIN_STEP, min(10, abs(tilt) * 0.25))) \
                if abs(tilt) >= MIN_STEP else (-tilt if tilt else 0)
            if pan_step or tilt_step:
                self._drive(pan_step, tilt_step)
                moved = True
            if abs(getattr(ctrl, "crop_x", 0.5) - 0.5) > 0.02 or \
                    abs(getattr(ctrl, "crop_y", 0.5) - 0.5) > 0.02:
                ctrl.crop_x += (0.5 - ctrl.crop_x) * 0.3
                ctrl.crop_y += (0.5 - ctrl.crop_y) * 0.3
                moved = True
            if getattr(ctrl, "zoom", 1.0) > 1.0:
                ctrl.ptz(zoom_delta=-0.1)
                moved = True
        except Exception:
            pass
        return moved

    # ------------------------------------------------------------ main loop

    def update(self, frame, motion_box=None, identified_faces=None):
        """Process one frame. Returns a status dict (never raises).

        Harmony only: the PIXY's native AI tracking moves the
        camera; Oracle observes (detection + face ID, invisible —
        no boxes or name tags are drawn) and sends at most ONE small UVC correction when the
        tracked person has stayed clearly off-centre for more than
        HARMONY_OFF_CENTRE_SECONDS with no PIXY correction, then
        waits HARMONY_CORRECTION_COOLDOWN before another. Digital
        framing is throttled the same way. No hunting, no
        return-to-centre: when nobody is in view, hold still.

        identified_faces: optional [(box, name_or_None, confidence)]
        from face recognition — when ``target_name`` is set, the
        target's face box is preferred over the largest person box,
        and the lock holds for TARGET_LOCK_SECONDS after the target
        leaves frame before any switch is allowed.
        Status keys: box, source, error_x, error_y, moved,
        action ('harmony'|'harmony-correcting'|'holding'|'disabled'|
        'camera_lost'), camera_lost, uvc_ignored, target_name, mode.
        """
        status = {"box": self.last_box, "source": self.last_source,
                  "error_x": 0.0, "error_y": 0.0, "moved": False,
                  "action": "idle", "camera_lost": False,
                  "uvc_ignored": self.uvc_ignored,
                  "target_name": self.target_name,
                  "mode": self.mode}
        if not self.enabled or self.mode == "off":
            status["action"] = "disabled"
            return status
        if frame is None:
            # Camera lost: do not move, do not crash, say so.
            self.camera_lost = True
            self.last_box = None
            self._off_centre_since = None
            status.update({"box": None, "action": "camera_lost",
                           "camera_lost": True})
            return status
        self.camera_lost = False
        now = time.time()
        box = None
        if self.target_name and identified_faces:
            for (fbox, fname, _conf) in identified_faces:
                if fname == self.target_name:
                    box = fbox
                    self.last_source = "face-target"
                    self._target_last_seen = now
                    break
        if box is None and self.target_name and self.last_seen_box is not None:
            # Target lock: the named person vanished from face ID —
            # hold their last box for up to TARGET_LOCK_SECONDS
            # instead of jumping to another person / motion blob.
            if now - self._target_last_seen < TARGET_LOCK_SECONDS:
                box = self.last_seen_box
                self.last_source = "face-target-held"
        if box is None:
            box = self.detect_person(frame, motion_box=motion_box)
        if box is not None:
            fh, fw = frame.shape[:2]
            # Sticky box: a centre jump of more than STICKY_JUMP of
            # the frame within a second is a detector flip (or a TV
            # flicker), not a person teleporting — keep the last box.
            if (self.last_seen_box is not None
                    and now - self.last_seen < 1.0):
                lx = self.last_seen_box[0] + self.last_seen_box[2] / 2.0
                ly = self.last_seen_box[1] + self.last_seen_box[3] / 2.0
                cx0 = box[0] + box[2] / 2.0
                cy0 = box[1] + box[3] / 2.0
                if (abs(cx0 - lx) / fw > STICKY_JUMP
                        or abs(cy0 - ly) / fh > STICKY_JUMP):
                    box = self.last_seen_box
                    self.last_source = "held"
            self.last_box = box
            self.last_seen = now
            self.last_seen_box = box
            self.returning_to_centre = False
            cx = box[0] + box[2] / 2.0
            cy = box[1] + box[3] / 2.0
            error_x = (cx - fw / 2.0) / fw
            error_y = (cy - fh / 2.0) / fh
            # Exponential smoothing — one jumpy detection cannot
            # yank the camera.
            self._smooth_ex = (self.smoothing * error_x
                               + (1 - self.smoothing) * self._smooth_ex)
            self._smooth_ey = (self.smoothing * error_y
                               + (1 - self.smoothing) * self._smooth_ey)
            status.update({"box": box, "source": self.last_source,
                           "error_x": round(error_x, 3),
                           "error_y": round(error_y, 3),
                           "action": "harmony"})
            off_centre = (abs(self._smooth_ex) >= self.dead_zone
                          or abs(self._smooth_ey) >= self.dead_zone)
            if not off_centre:
                # Person is centred (or close): the PIXY has it.
                # Reset the off-centre clock — no correction needed.
                self._off_centre_since = None
                return status
            if self._off_centre_since is None:
                self._off_centre_since = now
            if now - self._off_centre_since < HARMONY_OFF_CENTRE_SECONDS:
                # Not yet 5s off-centre: the PIXY may still correct
                # on its own. Wait — do not chase it.
                return status
            if now - self._last_harmony_correction < HARMONY_CORRECTION_COOLDOWN:
                return status
            if now - self._last_step < self.min_step_interval:
                return status
            # The PIXY has not corrected for 5+ seconds: ONE small
            # UVC nudge (<=8°), then at least 5s before another.
            pan_step = self._step_for_error(self._smooth_ex, HARMONY_MAX_STEP)
            tilt_step = -self._step_for_error(self._smooth_ey, HARMONY_MAX_STEP)
            # Tilt sign: person below centre (error_y > 0) needs a
            # downward tilt, and camera.py treats positive tilt as up.
            if pan_step or tilt_step:
                self._drive(pan_step, tilt_step)
                self._last_step = now
                self._last_harmony_correction = now
                self._off_centre_since = None
                status["moved"] = True
                status["action"] = "harmony-correcting"
            # Digital framing follows, throttled, only while
            # off-centre — never a continuous crop drift.
            if now - self._last_digital_follow >= 1.0:
                self._digital_follow(self._smooth_ex, self._smooth_ey)
                self._last_digital_follow = now
            return status
        # No person in this frame: hold still. Harmony never hunts
        # and never drifts back to centre — the PIXY owns position.
        self.last_box = None
        self.last_source = None
        self._off_centre_since = None
        status["box"] = None
        status["source"] = None
        status["action"] = "holding"
        return status

    # Backwards-friendly alias: process(frame) == update(frame).
    def process(self, frame, motion_box=None, identified_faces=None):
        return self.update(frame, motion_box=motion_box,
                           identified_faces=identified_faces)

    def set_target(self, name=None):
        """'Track me' / 'track this person': prefer this identity's
        face when face recognition knows them; None = largest person.
        The lock holds for TARGET_LOCK_SECONDS after the target
        leaves frame before any switch is allowed."""
        self.target_name = (str(name).strip() if name else "") or None
        if self.target_name:
            self._target_last_seen = time.time()

    def set_mode(self, mode):
        """Harmony only. ``mode`` is 'harmony' (PIXY leads, Oracle
        observes) or 'off' (hold still — a pause inside Harmony).
        Anything else raises ValueError: there is deliberately no
        Oracle-only driving mode, so the two trackers can never
        fight again (decided 2026-11-24)."""
        mode = str(mode or "").strip().lower()
        if mode not in ("harmony", "off"):
            raise ValueError(
                "Tracking is Harmony only — 'harmony' or 'off'. "
                "There is no Oracle-only driving mode.")
        self.mode = mode
        if mode == "off":
            self.enabled = False
            self.target_name = None
            self._smooth_ex = 0.0
            self._smooth_ey = 0.0
            self._off_centre_since = None
            self.returning_to_centre = False
        else:
            self.enabled = True

    def stop(self):
        """Hold still: no more moves, errors reset. A pause inside
        Harmony — resume() brings Harmony back, it does not change
        the mode."""
        self.enabled = False
        self.mode = "off"
        self.target_name = None
        self._smooth_ex = 0.0
        self._smooth_ey = 0.0
        self._off_centre_since = None
        self.returning_to_centre = False

    def resume(self):
        """End a hold-still pause: back to Harmony (PIXY leads,
        Oracle observes)."""
        self.mode = "harmony"
        self.enabled = True
        self._off_centre_since = None
        self._last_harmony_correction = 0.0
