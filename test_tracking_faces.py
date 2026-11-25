"""Synthetic test for tracking.py + face_profiles.py (no camera, no PC).

Draws face-like shapes with numpy/OpenCV, enrols one, and checks:
  * same person (shifted/noisier variant) -> identified by name
  * different person -> unknown (None), never a false name
  * unknown-face repeat counting works
  * tracker: off-centre person -> PTZ step + digital crop shift,
    centred person -> no step (dead zone), frame None -> camera_lost
    with no move, no person >15s -> gentle return to centre

Run on Windows (or any machine with the repo's requirements):
    python test_tracking_faces.py
Needs: opencv-python==4.11.0.86, numpy (from requirements.txt).
Face profiles go to a temp dir, never to the real faces/ folder.
NOTE: drawn faces are only a code-path check. Haar/HOG detection
on REAL people and live tracking can only be verified with a real
camera — see NEXT_BUILD_FEATURES.md items 7/9 live-test steps.
"""
import os
import shutil
import sys
import tempfile
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.environ["ORACLE_FACES_DIR"] = os.path.join(
    tempfile.gettempdir(), "oracle-test-faces")
shutil.rmtree(os.environ["ORACLE_FACES_DIR"], ignore_errors=True)

import numpy as np
import cv2
import face_profiles as fp
import tracking as tr


def make_face(cx=320, cy=240, rx=60, ry=80, skin=190, eye_dx=24, mouth="smile", seed=0,
              eye_y=-15, glasses=False, beard=False):
    rng = np.random.default_rng(seed)
    img = np.full((480, 640, 3), 60, dtype=np.uint8)
    cv2.ellipse(img, (cx, cy), (rx, ry), 0, 0, 360, (skin, skin - 30, skin - 60), -1)
    cv2.ellipse(img, (cx, cy - ry // 2), (rx, ry // 2), 0, 180, 360, (40, 40, 40), -1)
    for ex in (cx - eye_dx, cx + eye_dx):
        cv2.circle(img, (ex, cy + eye_y), 7, (20, 20, 20), -1)
    if glasses:
        for ex in (cx - eye_dx, cx + eye_dx):
            cv2.rectangle(img, (ex - 16, cy + eye_y - 12), (ex + 16, cy + eye_y + 12), (20, 20, 20), 2)
        cv2.line(img, (cx - eye_dx + 16, cy + eye_y), (cx + eye_dx - 16, cy + eye_y), (20, 20, 20), 2)
    cv2.line(img, (cx, cy + 2), (cx - 4, cy + 22), (skin - 70, skin - 90, skin - 110), 2)
    cv2.line(img, (cx - 6, cy + 12), (cx + 6, cy + 12), (30, 30, 30), 2)
    if beard:
        cv2.ellipse(img, (cx, cy + ry // 2), (rx - 8, ry // 3), 0, 0, 180, (50, 50, 50), -1)
    if mouth == "smile":
        cv2.ellipse(img, (cx, cy + 35), (22, 10), 0, 0, 180, (30, 30, 30), 2)
    else:
        cv2.line(img, (cx - 18, cy + 38), (cx + 18, cy + 38), (30, 30, 30), 3)
    noise = rng.normal(0, 4, img.shape).astype(np.int16)
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def face_box(cx=320, cy=240, rx=60, ry=80):
    return (cx - rx, cy - ry, rx * 2, ry * 2)


def main():
    print("backend:", fp.backend())
    print("haar available:", fp._face_cascade() is not None)

    fa = make_face(seed=1)
    fa2 = make_face(cx=330, cy=245, seed=2)
    fa_bright = np.clip(fa.astype(int) + 50, 0, 255).astype(np.uint8)
    fb = make_face(rx=78, ry=58, skin=150, eye_dx=34, eye_y=-28, mouth="flat",
                   glasses=True, seed=3)
    fc = make_face(rx=48, ry=92, skin=210, eye_dx=18, eye_y=-8, mouth="flat",
                   beard=True, seed=4)
    ba, bb, bc = face_box(), face_box(rx=78, ry=58), face_box(rx=48, ry=92)
    va = fp._opencv_feature(fa, ba)
    va2 = fp._opencv_feature(fa2, face_box(cx=330, cy=245))
    vab = fp._opencv_feature(fa_bright, ba)
    vb = fp._opencv_feature(fb, bb)
    vc = fp._opencv_feature(fc, bc)
    print("dist same-person (A vs A-shifted): %.3f" % float(1 - np.dot(va, va2)))
    print("dist same-person (A vs A-brighter): %.3f" % float(1 - np.dot(va, vab)))
    print("dist different-person (A vs B):    %.3f" % float(1 - np.dot(va, vb)))
    print("dist different-person (A vs C):    %.3f" % float(1 - np.dot(va, vc)))
    print("threshold:", fp.OPENCV_MATCH_THRESHOLD)

    print("enrol:", fp.enrol("TestA", fa, ba))
    name, conf, box = fp.identify(fa2, face_box(cx=330, cy=245))
    print("identify same person ->", name, "conf", conf, "box", box)
    assert name == "TestA", "same person should be identified"
    name2, conf2, _ = fp.identify(fb, bb)
    print("identify different person B ->", name2, "conf", conf2)
    assert name2 is None, "different person B must be UNKNOWN, not a false name"
    name2c, conf2c, _ = fp.identify(fc, bc)
    print("identify different person C ->", name2c, "conf", conf2c)
    assert name2c is None, "different person C must be UNKNOWN, not a false name"

    ut = fp.UnknownTracker(repeat_threshold=5)
    for i in range(5):
        rep, cnt, _ = ut.note_unknown(fb, bb)
    assert rep is True and cnt == 5, "unknown repeat counting failed"
    print("unknown repeat counting: OK (repeat after 5 sightings)")

    print("delete:", fp.delete_profile("TestA"))
    assert fp.list_profiles() == []
    assert fp.identify(fa, ba)[0] is None

    class FakeController:
        def __init__(self):
            self.pan = 0; self.tilt = 0; self.zoom = 1.0
            self.crop_x = 0.5; self.crop_y = 0.5
            self.ptz_calls = []
        def ptz(self, pan_delta=0, tilt_delta=0, zoom_delta=0.0):
            self.pan = max(-155, min(155, self.pan + pan_delta))
            self.tilt = max(-90, min(90, self.tilt + tilt_delta))
            self.zoom = max(1.0, min(1.5, self.zoom + zoom_delta))
            self.ptz_calls.append((pan_delta, tilt_delta, round(zoom_delta, 2)))
            return {"pan": self.pan, "tilt": self.tilt, "zoom": self.zoom,
                    "uvc_pan_ok": False, "uvc_tilt_ok": False, "uvc_zoom_ok": False}

    ctrl = FakeController()
    tk = tr.AutoTracker(controller=ctrl)
    blank = np.full((480, 640, 3), 60, dtype=np.uint8)
    st = tk.update(blank, motion_box=(480, 150, 100, 220))
    assert st["moved"] and ctrl.ptz_calls, "off-centre person must trigger a PTZ step"
    assert ctrl.zoom >= 1.25, "UVC ignored -> digital zoom should ease up"
    assert ctrl.crop_x > 0.5, "digital crop centre should shift toward the person"
    print("off-centre -> PTZ step + digital follow: OK", ctrl.ptz_calls)

    n_before = len(ctrl.ptz_calls)
    tk._last_step = time.time()
    tk._last_detect = 0
    st = tk.update(blank, motion_box=(270, 130, 100, 220))
    assert not st["moved"] and len(ctrl.ptz_calls) == n_before, "dead zone must suppress moves"
    print("centred -> dead zone, no move: OK")

    n_before = len(ctrl.ptz_calls)
    st = tk.update(None)
    assert st["action"] == "camera_lost" and st["camera_lost"] and len(ctrl.ptz_calls) == n_before
    print("frame None -> camera_lost, no move, no crash: OK")

    tk.last_seen = time.time() - 5
    tk._last_detect = 0
    assert tk.update(blank, motion_box=None)["action"] == "holding"
    print("no person 5s -> hold, no hunt: OK")
    ctrl.pan = 40; ctrl.tilt = -20; ctrl.crop_x = 0.7
    tk.last_seen = time.time() - 20
    tk._last_detect = 0
    tk._last_step = 0
    st = tk.update(blank, motion_box=None)
    assert st["action"] == "returning" and ctrl.pan < 40
    print("no person 20s -> gentle return to centre: OK")

    tk2 = tr.AutoTracker(controller=FakeController())
    tk2.set_target("TestA")
    tk2._last_detect = 0
    st = tk2.update(blank, motion_box=(480, 150, 100, 220),
                    identified_faces=[((100, 100, 80, 80), "TestA", 0.9)])
    assert st["box"] == (100, 100, 80, 80)
    print("target face preferred over largest person: OK")

    import camera as cam
    w = cam.Watcher()
    assert w.auto_track is True and w.tracker is not None
    w.set_auto_track(False)
    assert w.track_me("Lorenza").startswith("Tracking Lorenza")
    assert w.stop_tracking().startswith("Auto-tracking is off")
    assert "isn't running" in w.enrol_current("Nobody")
    print("Watcher wiring (default ON, track_me, stop_tracking, enrol guard): OK")

    print("\nALL SYNTHETIC TESTS PASSED")


if __name__ == "__main__":
    main()
