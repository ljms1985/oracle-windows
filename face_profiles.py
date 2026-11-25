"""
Local face-feature recognition for Oracle (Windows).

LOCAL ONLY — no cloud service, no outside database, no face data
sent anywhere. Profiles live in a ``faces/`` folder next to the app
(JSON metadata + face crops + feature vectors as .npy files).
``faces/`` is in .gitignore — it must never be committed, emailed,
or uploaded. Embeddings are never printed or logged.

Two backends, in order:
  1. ``face_recognition`` if it is installed (128-d embeddings,
     Euclidean distance, threshold 0.6 — the library's usual value).
     Optional only: it needs cmake/dlib and is NOT a hard dependency.
  2. OpenCV-only fallback (always available with opencv-python 4.x):
     Haar face detection, aligned 128x128 grayscale crop, normalised
     feature vector (HOG gradient orientations + pixel vector +
     32-bin histogram), cosine-distance matching with a conservative
     threshold. This is a *starter* matcher, not a biometric-grade
     one: it is deliberately strict so it says "unknown" rather
     than guessing a wrong name.

Never auto-label when unsure: below threshold the answer is always
``(None, confidence, box)`` — "unknown" — never a name.

Learning flow: a face seen repeatedly that matches nobody is
counted by :class:`UnknownTracker` (in-memory, per session). The
caller (camera Watcher / GUI) asks Lorenza who it is, then calls
:func:`enrol`. Known faces are greeted/identified without asking.

Version note: opencv-python 5.x removed ``CascadeClassifier`` and
``HOGDescriptor``. This module (and tracking.py) needs the 4.x
line — requirements.txt pins ``opencv-python==4.11.0.86``. If the
cascades are missing anyway, detection reports that honestly and
every face is "unknown" instead of crashing.
"""

import json
import math
import os
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _faces_dir():
    """Where profiles live. Overridable with ORACLE_FACES_DIR.

    Frozen .exe: the folder CONTAINING Oracle.exe (writable, survives
    reinstalls) — same rule camera.py uses via oracle_paths.app_dir().
    Source run: faces/ next to the .py files.
    """
    override = os.environ.get("ORACLE_FACES_DIR")
    if override:
        return Path(override)
    try:
        from oracle_paths import app_dir as _oracle_app_dir
        return _oracle_app_dir() / "faces"
    except Exception:
        return BASE_DIR / "faces"


FACES_DIR = _faces_dir()

# OpenCV-fallback matching: cosine distance between normalised
# feature vectors. 0.0 = identical, ~1.0 = unrelated. Deliberately
# conservative — a false NAME is far worse than a false "unknown".
# Measured on synthetic faces (Linux VM, opencv 4.11, no real photo
# available here): same person shifted/noisier = 0.034, same person
# brighter = 0.000, genuinely different drawn faces = 0.109 / 0.242.
# 0.08 sits between those with margin on both sides, but synthetic
# faces understate real-world variation (pose, expression, box
# alignment), so treat 0.08 as a starting point: the LIVE PC test
# must confirm Lorenza is recognised and strangers are "unknown",
# and the threshold may need raising if she is too often unknown
# (enrolling several samples — up to 5 per profile — helps first).
# Anything at or above this is "unknown".
OPENCV_MATCH_THRESHOLD = 0.08
# face_recognition's usual threshold (Euclidean distance on 128-d
# embeddings; 0.6 is the library's own default recommendation).
FACE_RECOGNITION_THRESHOLD = 0.6
MAX_SAMPLES_PER_PROFILE = 5
FACE_CROP_SIZE = 128


def backend():
    """Which matcher is available: 'face_recognition' or 'opencv'."""
    try:
        import face_recognition  # noqa: F401
        return "face_recognition"
    except Exception:
        return "opencv"


def _cv2():
    import cv2
    return cv2


# ------------------------------------------------------------------ detect

_FACE_CASCADE_OBJ = None
_FACE_CASCADE_TRIED = False


def _face_cascade():
    """Haar frontal-face cascade, or None if OpenCV 5.x / files missing."""
    global _FACE_CASCADE_OBJ, _FACE_CASCADE_TRIED
    if _FACE_CASCADE_TRIED:
        return _FACE_CASCADE_OBJ
    _FACE_CASCADE_TRIED = True
    try:
        cv2 = _cv2()
        if not hasattr(cv2, "CascadeClassifier"):
            return None
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        if not os.path.exists(path):
            return None
        cascade = cv2.CascadeClassifier(path)
        _FACE_CASCADE_OBJ = cascade if not cascade.empty() else None
    except Exception:
        _FACE_CASCADE_OBJ = None
    return _FACE_CASCADE_OBJ


def detect_faces(frame):
    """Return [(x, y, w, h), ...] face boxes in a BGR frame.

    Empty list if no face is found — or if face detection is
    unavailable on this OpenCV build (never raises for that).
    """
    if frame is None:
        return []
    cascade = _face_cascade()
    if cascade is None:
        return []
    try:
        cv2 = _cv2()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
        return [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in faces]
    except Exception:
        return []


def largest_face(frame):
    """Largest detected face box, or None."""
    faces = detect_faces(frame)
    if not faces:
        return None
    return max(faces, key=lambda b: b[2] * b[3])


# ------------------------------------------------------- feature extraction

def _hog_feature(gray128):
    """HOG-style gradient feature: 8x8 cells x 9 orientation bins.

    Raw pixels alone are a weak identity signal (two different
    cartoon faces can score 0.08 apart while the same face shifted
    scores 0.05 — no usable threshold). Gradient orientations
    capture eyes / nose / mouth geometry, which is what actually
    differs between people. Magnitude-weighted, L2-normalised.
    """
    import numpy as np
    cv2 = _cv2()
    gx = cv2.Sobel(gray128, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray128, cv2.CV_32F, 0, 1, ksize=3)
    mag, ang = cv2.cartToPolar(gx, gy, angleInDegrees=True)
    ang = (ang % 180.0) / 20.0  # 9 bins over 0..180
    feats = []
    cell = FACE_CROP_SIZE // 8  # 16 px cells
    for cy in range(8):
        for cx in range(8):
            m = mag[cy * cell:(cy + 1) * cell, cx * cell:(cx + 1) * cell]
            a = ang[cy * cell:(cy + 1) * cell, cx * cell:(cx + 1) * cell]
            hist, _ = np.histogram(a, bins=9, range=(0, 9), weights=m)
            feats.append(hist)
    hog = np.concatenate(feats).astype("float32")
    norm = float(np.linalg.norm(hog))
    return hog / norm if norm > 1e-9 else hog


def _opencv_feature(frame, box):
    """Aligned 128x128 grayscale crop -> normalised feature vector.

    Feature = L2-normalised [0.5 * flattened pixels (0..1),
    1.0 * HOG gradient orientations, 0.3 * 32-bin histogram].
    Pixels alone cannot separate people (see _hog_feature); the
    gradient term carries the identity signal. Returns a numpy
    array, or None if the crop is unusable. The vector itself is
    never logged.
    """
    import numpy as np
    cv2 = _cv2()
    x, y, w, h = (int(v) for v in box)
    fh, fw = frame.shape[:2]
    x, y = max(0, x), max(0, y)
    w, h = min(w, fw - x), min(h, fh - y)
    if w < 20 or h < 20:
        return None
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    crop = gray[y:y + h, x:x + w]
    crop = cv2.resize(crop, (FACE_CROP_SIZE, FACE_CROP_SIZE))
    crop = cv2.equalizeHist(crop)
    pixels = crop.astype("float32").ravel() / 255.0
    # Normalise EACH component to unit length BEFORE weighting:
    # otherwise the 16k-dim pixel vector (norm ~30) swamps the
    # HOG term (norm 1) and gradients contribute nothing.
    pn = float(np.linalg.norm(pixels))
    pixels = pixels / pn if pn > 1e-9 else pixels
    hist = cv2.calcHist([crop], [0], None, [32], [0, 256]).ravel().astype("float32")
    hist = hist / (hist.sum() + 1e-9)
    hn = float(np.linalg.norm(hist))
    hist = hist / hn if hn > 1e-9 else hist
    hog = _hog_feature(crop)
    feat = np.concatenate([pixels * 0.5, hog, hist * 0.3]).astype("float32")
    norm = float(np.linalg.norm(feat))
    if norm < 1e-9:
        return None
    return feat / norm


def _face_recognition_encoding(frame, box=None):
    """128-d embedding via face_recognition, or None.

    Returns (encoding, box) for the largest face, or None if the
    library is missing or no face encodes.
    """
    try:
        import face_recognition
    except Exception:
        return None
    try:
        rgb = frame[:, :, ::-1]
        if box is not None:
            x, y, w, h = (int(v) for v in box)
            locations = [(y, x + w, y + h, x)]  # top, right, bottom, left
        else:
            locations = face_recognition.face_locations(rgb)
        encodings = face_recognition.face_encodings(rgb, locations)
        if not encodings:
            return None
        if box is None and locations:
            # face_locations order matches encodings order; take the
            # largest face's encoding.
            areas = [(b - t) * (r - l) for (t, r, b, l) in locations]
            idx = int(max(range(len(areas)), key=lambda i: areas[i]))
            top, right, bottom, left = locations[idx]
            box = (left, top, right - left, bottom - top)
            return encodings[idx], box
        return encodings[0], box
    except Exception:
        return None


def _profile_dir(name):
    return FACES_DIR / name


def _load_meta(name):
    pfile = _profile_dir(name) / "profile.json"
    if pfile.exists():
        try:
            return json.loads(pfile.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"name": name, "backend": backend(), "samples": [],
            "created": datetime.now().isoformat()}


def _save_meta(name, meta):
    d = _profile_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    (d / "profile.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _load_samples(name):
    """[(vector ndarray, sample-dict), ...] for a profile; skips bad files."""
    import numpy as np
    meta = _load_meta(name)
    out = []
    for sample in meta.get("samples", []):
        vec_path = _profile_dir(name) / sample.get("vector_file", "")
        if not vec_path.exists():
            continue
        try:
            out.append((np.load(str(vec_path)), sample))
        except Exception:
            continue
    return out


# ------------------------------------------------------------------- public

def list_profiles():
    """[{name, backend, samples, created, last_seen}, ...], sorted by name.

    No embeddings, no file contents — metadata only.
    """
    if not FACES_DIR.exists():
        return []
    profiles = []
    for d in sorted(p for p in FACES_DIR.iterdir() if p.is_dir()
                    and not p.name.startswith(".")):
        meta = _load_meta(d.name)
        profiles.append({
            "name": d.name,
            "backend": meta.get("backend", "?"),
            "samples": len(meta.get("samples", [])),
            "created": meta.get("created", "?"),
            "last_seen": meta.get("last_seen"),
        })
    return profiles


def delete_profile(name):
    """Delete one person's whole local face profile. Returns a message."""
    import shutil
    d = _profile_dir(name)
    if not d.exists():
        return f"No face profile found for {name}."
    shutil.rmtree(d)
    return f"Deleted the local face profile for {name} (faces/{name}/)."


def enrol(name, frame, box=None):
    """Enrol (or add a sample for) a person from a BGR frame.

    Finds the largest face if no box is given. Saves a 128x128 face
    crop (JPG) + feature vector (.npy) under faces/<name>/, locally
    only. Returns a human-readable message (never the vector).
    """
    import numpy as np
    if frame is None:
        return "Enrol failed: no camera frame to learn from."
    name = (name or "").strip()
    if not name:
        return "Enrol failed: give me a name first — e.g. 'enrol this person as Lorenza'."
    if box is None:
        box = largest_face(frame)
    if box is None:
        if _face_cascade() is None:
            return ("Enrol failed: face detection is unavailable on this "
                    "PC (OpenCV 5.x removed Haar cascades — install "
                    "opencv-python==4.11.0.86, see requirements.txt).")
        return "Enrol failed: I can't see a face in the frame. Face the camera and try again."
    be = backend()
    if be == "face_recognition":
        got = _face_recognition_encoding(frame, box)
        if got is None:
            return f"Enrol failed: no face encoding could be made for {name}."
        vector, box = got
        threshold = FACE_RECOGNITION_THRESHOLD
    else:
        vector = _opencv_feature(frame, box)
        if vector is None:
            return f"Enrol failed: the face crop for {name} was unusable."
        threshold = OPENCV_MATCH_THRESHOLD
    d = _profile_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    meta = _load_meta(name)
    samples = meta.get("samples", [])
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    idx = len(samples)
    crop_file = f"face-{stamp}-{idx}.jpg"
    vector_file = f"vector-{stamp}-{idx}.npy"
    try:
        cv2 = _cv2()
        x, y, w, h = (int(v) for v in box)
        crop = frame[max(0, y):y + h, max(0, x):x + w]
        if crop.size:
            cv2.imwrite(str(d / crop_file), cv2.resize(crop, (128, 128)))
        np.save(str(d / vector_file), vector)
    except Exception as e:
        return f"Enrol failed: could not save the profile for {name} ({e})."
    samples.append({"crop_file": crop_file, "vector_file": vector_file,
                    "created": datetime.now().isoformat(),
                    "threshold": threshold, "backend": be})
    meta["samples"] = samples[-MAX_SAMPLES_PER_PROFILE:]
    meta["backend"] = be
    meta["created"] = meta.get("created") or datetime.now().isoformat()
    _save_meta(name, meta)
    return (f"Learned {name}'s face locally (faces/{name}/, {len(meta['samples'])} "
            f"sample(s), {be} backend). I'll recognise {name} from now on — "
            "nothing was uploaded anywhere.")


def _match_opencv(feature):
    """Best (name, cosine-distance) over all OpenCV profiles, or (None, inf)."""
    import numpy as np
    best_name, best_dist = None, float("inf")
    for prof in list_profiles():
        if prof["backend"] not in ("opencv",):
            continue
        for vector, _sample in _load_samples(prof["name"]):
            if vector.shape != feature.shape:
                continue
            dist = float(1.0 - np.dot(vector, feature))
            if dist < best_dist:
                best_name, best_dist = prof["name"], dist
    return best_name, best_dist


def _match_face_recognition(encoding):
    """Best (name, Euclidean distance) over face_recognition profiles."""
    import numpy as np
    best_name, best_dist = None, float("inf")
    for prof in list_profiles():
        if prof["backend"] not in ("face_recognition",):
            continue
        for vector, _sample in _load_samples(prof["name"]):
            if vector.shape != encoding.shape:
                continue
            dist = float(np.linalg.norm(vector - encoding))
            if dist < best_dist:
                best_name, best_dist = prof["name"], dist
    return best_name, best_dist


def identify(frame, box=None):
    """Identify the largest face in a BGR frame.

    Returns (name_or_None, confidence_0_to_1, box_or_None).
    name is None when no face is found OR when the best match is
    below threshold — that is "unknown", never a guessed name.
    Confidence is 0..1 and only meaningful alongside a name; for
    unknown faces it is the best (below-threshold) score, so the
    caller can tell "close but not sure" from "no idea".
    """
    if frame is None:
        return None, 0.0, None
    if box is None:
        box = largest_face(frame)
    if box is None:
        return None, 0.0, None
    be = backend()
    if be == "face_recognition":
        got = _face_recognition_encoding(frame, box)
        if got is None:
            return None, 0.0, box
        encoding, box = got
        name, dist = _match_face_recognition(encoding)
        if name is not None and dist < FACE_RECOGNITION_THRESHOLD:
            conf = max(0.0, min(1.0, 1.0 - dist / FACE_RECOGNITION_THRESHOLD))
            _touch_last_seen(name)
            return name, round(conf, 2), box
        conf = max(0.0, min(1.0, 1.0 - dist / FACE_RECOGNITION_THRESHOLD)) \
            if dist != float("inf") else 0.0
        return None, round(conf, 2), box
    feature = _opencv_feature(frame, box)
    if feature is None:
        return None, 0.0, box
    name, dist = _match_opencv(feature)
    if name is not None and dist < OPENCV_MATCH_THRESHOLD:
        conf = max(0.0, min(1.0, 1.0 - dist / OPENCV_MATCH_THRESHOLD))
        _touch_last_seen(name)
        return name, round(conf, 2), box
    conf = max(0.0, min(1.0, 1.0 - dist / OPENCV_MATCH_THRESHOLD)) \
        if dist != float("inf") else 0.0
    return None, round(conf, 2), box


def _touch_last_seen(name):
    try:
        meta = _load_meta(name)
        meta["last_seen"] = datetime.now().isoformat()
        _save_meta(name, meta)
    except Exception:
        pass


def describe_profiles():
    """One-line summary for the GUI/chat. Metadata only, no vectors."""
    profiles = list_profiles()
    if not profiles:
        return "No faces enrolled yet (local faces/ folder is empty)."
    bits = [f"{p['name']} ({p['samples']} sample(s), {p['backend']})"
            for p in profiles]
    return "Faces I know (stored locally only): " + ", ".join(bits) + "."


class UnknownTracker:
    """Counts repeated unknown faces within a session.

    The Watcher calls :meth:`note_unknown` with each unidentified
    face feature; when the same unknown face has been seen
    ``repeat_threshold`` times, the caller should ask Lorenza who
    it is and then call :func:`enrol`. Nothing is written to disk
    here — unknown faces are held in memory only, for this session.
    """

    def __init__(self, repeat_threshold=5, match_threshold=None):
        self.repeat_threshold = repeat_threshold
        self.match_threshold = (match_threshold if match_threshold is not None
                                else OPENCV_MATCH_THRESHOLD)
        self._unknowns = []  # [{feature, count, first_seen, last_seen}]

    def note_unknown(self, frame, box):
        """Record one unknown face. Returns (is_repeat, count, box).

        is_repeat is True once this face has been seen at least
        repeat_threshold times. Returns (False, 0, box) if no usable
        feature could be made from the frame.
        """
        import numpy as np
        if frame is None or box is None:
            return False, 0, box
        feature = _opencv_feature(frame, box)
        if feature is None:
            return False, 0, box
        now = time.time()
        for entry in self._unknowns:
            if entry["feature"].shape != feature.shape:
                continue
            dist = float(1.0 - np.dot(entry["feature"], feature))
            if dist < self.match_threshold:
                entry["count"] += 1
                entry["last_seen"] = now
                return entry["count"] >= self.repeat_threshold, entry["count"], box
        # Prune stale unknowns (older than 10 minutes) so the list
        # cannot grow without bound in a long session.
        self._unknowns = [e for e in self._unknowns
                          if now - e["last_seen"] < 600][:10]
        self._unknowns.append({"feature": feature, "count": 1,
                               "first_seen": now, "last_seen": now})
        return False, 1, box

    def reset(self):
        self._unknowns = []
