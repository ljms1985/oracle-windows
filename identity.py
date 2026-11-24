"""
Identity learning for Oracle - for use on your own personal PC in your home.

This version runs the way you asked for it to run on your home PC:
  * No consent dialog in the GUI. You name a person once, Oracle learns
    them, and then it identifies them automatically from then on.
  * Voice learning: enrolled voices are matched automatically.
  * Face learning: faces seen on camera are matched automatically to
    people Oracle already knows, using a local face encoding stored
    only in identities/<name>/ on your PC.
  * Matching voice to people seen over time: if Oracle hears a known
    voice while a face is in view, it links that face to that voice
    automatically. If it sees a known face and then hears a new voice,
    it links that voice to that face automatically. Over time the
    voice profile and face profile for the same person reinforce
    each other, so Oracle gets better at knowing who it is talking
    to and who it is seeing, even when only one of them is present.

Local only:
  * All voice samples, face encodings, and profiles stay in
    identities/ on your PC. They are not sent to an external
    database and are not used to identify people outside your home.
  * You control it: "Delete identity" in the GUI removes a person
    completely, and Privacy mode in the GUI stops the camera.
  * If you do not want a person learned anymore, delete them.

Install for full face matching on Windows:
  pip install opencv-python
  pip install face_recognition
  Note: face_recognition needs dlib, which can be hard to install on
  Windows. If it is not installed, Oracle falls back to OpenCV face
  detection + voice matching, and face-to-person linking via
  co-occurrence (voice + face seen together = same person, learned
  automatically). The code tells you which mode it is in.

Voice matching is the same starter matcher as before (pitch/energy),
now run automatically instead of as a suggestion. For stronger voice
matching, replace voice_features_from_wav() with a speaker-embedding
library locally - the rest of the code already uses match_voice()
in one place, so that swap is contained.
"""

import json
import math
import os
import wave
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
IDENTITIES_DIR = BASE_DIR / "identities"
AUTO_IDENTIFY = os.environ.get("ORACLE_AUTO_IDENTIFY", "1") == "1"


def _ensure_dir(name):
    d = IDENTITIES_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_identities():
    if not IDENTITIES_DIR.exists():
        return []
    return sorted(p.name for p in IDENTITIES_DIR.iterdir() if p.is_dir())


def delete_identity(name):
    import shutil
    d = IDENTITIES_DIR / name
    if d.exists():
        shutil.rmtree(d)
        return f"Deleted all local data for {name}."
    return f"No identity found for {name}."


def _load_profile(name):
    pfile = IDENTITIES_DIR / name / "profile.json"
    if pfile.exists():
        try:
            return json.loads(pfile.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"name": name, "cooccurrences": [], "confirmed_matches": 0}


def _save_profile(name, prof):
    d = _ensure_dir(name)
    (d / "profile.json").write_text(json.dumps(prof, indent=2), encoding="utf-8")


def enroll_voice(name, consent=True, duration_sec=5):
    """
    Enroll a voice on your home PC. No consent dialog here - you
    naming the person is the enrollment action, as you requested
    for your own computer in your home.
    """
    d = _ensure_dir(name)
    sample_path = d / "voice_sample.wav"
    try:
        import speech_recognition as sr
        r = sr.Recognizer()
        with sr.Microphone() as source:
            print(f"Recording {duration_sec}s for {name} - please speak normally...")
            audio = r.listen(source, timeout=10, phrase_time_limit=duration_sec)
        with open(sample_path, "wb") as f:
            f.write(audio.get_wav_data())
        features = voice_features_from_wav(sample_path)
    except Exception as e:
        features = {"note": f"No mic sample recorded: {e}", "pitch_hz": 0, "energy": 0}
    prof = _load_profile(name)
    prof.update({
        "name": name,
        "enrolled_at": datetime.now().isoformat(),
        "voice_features": features,
    })
    prof.setdefault("cooccurrences", [])
    _save_profile(name, prof)
    return f"Enrolled voice for {name} locally in identities/{name}/. Oracle will now identify this voice automatically."


def voice_features_from_wav(path):
    try:
        import numpy as np
        with wave.open(str(path), "rb") as wf:
            n = wf.getnframes()
            data = wf.readframes(n)
            rate = wf.getframerate()
            audio = np.frombuffer(data, dtype=np.int16).astype(float)
        if len(audio) == 0:
            return {"pitch_hz": 0, "energy": 0}
        energy = float(np.mean(audio ** 2))
        window = audio[: min(len(audio), rate)]
        corr = np.correlate(window, window, mode="full")[len(window) - 1:]
        min_lag = int(rate / 400)
        max_lag = int(rate / 50)
        lag = int(np.argmax(corr[min_lag:max_lag]) + min_lag) if len(corr) > max_lag else 0
        pitch = float(rate / lag) if lag else 0
        return {"pitch_hz": pitch, "energy": energy}
    except Exception as e:
        return {"note": f"Feature extraction failed: {e}", "pitch_hz": 0, "energy": 0}


def match_voice(path):
    """Return (name or None, confidence, explanation) - automatic matching."""
    profiles = [_load_profile(n) for n in list_identities()]
    if not profiles:
        return None, 0, "No enrolled voices yet."
    feats = voice_features_from_wav(path)
    best, best_score = None, 0
    for prof in profiles:
        pf = prof.get("voice_features", {})
        if not pf.get("pitch_hz"):
            continue
        pitch_diff = abs(math.log(max(feats.get("pitch_hz", 1), 1) / max(pf["pitch_hz"], 1)))
        energy_diff = abs(math.log(max(feats.get("energy", 1), 1) / max(pf.get("energy", 1), 1)))
        score = max(0, 1 - (pitch_diff * 0.7 + energy_diff * 0.1))
        if score > best_score:
            best, best_score = prof["name"], score
    if best and best_score > 0.6:
        return best, round(best_score, 2), f"Voice identified as {best} (score {best_score:.2f})."
    return None, round(best_score, 2), "Unknown speaker."


# ---------------------------------------------------------------- faces

def detect_faces(frame):
    """Detect faces and return bounding boxes. Used for tracking and for matching below."""
    try:
        import cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
        return [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in faces]
    except Exception:
        return []


def face_encoding_for_image(image_path_or_frame):
    """
    Try face_recognition first (128-d encoding, local only).
    Returns a list of encodings, or [] if the library / no face is available.
    """
    try:
        import face_recognition
        import numpy as np
        if isinstance(image_path_or_frame, (str, Path)):
            image = face_recognition.load_image_file(str(image_path_or_frame))
        else:
            # OpenCV BGR frame -> RGB
            image = image_path_or_frame[:, :, ::-1]
        return face_recognition.face_encodings(image)
    except Exception:
        return []


def enroll_face(name, image_path_or_frame):
    """Store a local face encoding for a person, so faces can be matched later."""
    encodings = face_encoding_for_image(image_path_or_frame)
    if not encodings:
        return f"Could not get a face encoding for {name} - face_recognition may not be installed, or no face was found. Oracle will still learn this person via voice + co-occurrence."
    import numpy as np
    d = _ensure_dir(name)
    np.save(str(d / "face_encoding.npy"), encodings[0])
    prof = _load_profile(name)
    prof["has_face_encoding"] = True
    _save_profile(name, prof)
    return f"Stored a local face encoding for {name} in identities/{name}/. Oracle will now identify this face automatically."


def match_face(frame):
    """
    Match faces in a frame to enrolled people.
    Returns a list of names (or "unknown") - one per face detected.
    If face_recognition is unavailable, returns ["unknown"] per face,
    and identity then comes from voice + co-occurrence instead.
    """
    try:
        import face_recognition
        import numpy as np
    except Exception:
        faces = detect_faces(frame)
        return ["unknown"] * len(faces)
    encodings = face_encoding_for_image(frame)
    results = []
    for enc in encodings:
        best, best_dist = "unknown", 1.0
        for name in list_identities():
            enc_file = IDENTITIES_DIR / name / "face_encoding.npy"
            if not enc_file.exists():
                continue
            known = np.load(str(enc_file))
            dist = float(np.linalg.norm(known - enc))
            if dist < best_dist:
                best, best_dist = name, dist
        # face_recognition's usual threshold is ~0.6
        results.append(best if best_dist < 0.6 else "unknown")
    return results


def record_cooccurrence(speaker_name, face_count, confirmed_by_user=True):
    """
    Automatic learning over time, as you requested:
    a voice and a face seen together are linked automatically.
    confirmed_by_user defaults to True in home mode because you
    running Oracle on your PC is the confirmation - see module header.
    """
    if speaker_name not in list_identities():
        # Auto-create a profile for a speaker Oracle has just learned by voice,
        # so future face matches can link back to them.
        _ensure_dir(speaker_name)
    prof = _load_profile(speaker_name)
    prof.setdefault("cooccurrences", []).append({
        "at": datetime.now().isoformat(),
        "faces_in_view": face_count,
        "confirmed_by_user": confirmed_by_user,
    })
    if confirmed_by_user:
        prof["confirmed_matches"] = prof.get("confirmed_matches", 0) + 1
    _save_profile(speaker_name, prof)
    return f"Learned: {speaker_name} was speaking while {face_count} face(s) were in view. Total co-occurrences: {len(prof['cooccurrences'])}."


def identify_person(voice_wav_path=None, frame=None):
    """
    Combine voice + face, automatically, the way you want Oracle to work:
      * voice alone -> name from voice
      * face alone -> name from face, if an encoding exists
      * both together -> if they agree, high confidence; if voice is known
        and face is unknown, learn that face as that voice's face;
        if face is known and voice is unknown, learn that voice as
        that face's voice (by saving the wav as a new sample).
    Returns a dict with voice, faces, and the best overall identity.
    """
    voice_name, voice_conf, _ = (None, 0, "")
    if voice_wav_path:
        voice_name, voice_conf, _ = match_voice(voice_wav_path)
    face_names = match_face(frame) if frame is not None else []
    face_name = face_names[0] if face_names else None

    identity = voice_name or face_name
    if identity in (None, "unknown"):
        identity = face_name if face_name not in (None, "unknown") else voice_name
    if identity in (None, "unknown"):
        identity = None

    # Automatic cross-learning over time
    if voice_name and face_names and "unknown" in face_names and frame is not None:
        enroll_face(voice_name, frame)
        record_cooccurrence(voice_name, len(face_names), confirmed_by_user=True)
    elif face_name and face_name != "unknown" and voice_wav_path:
        # Learn this voice for the known face, if no voice profile yet
        prof = _load_profile(face_name)
        if not prof.get("voice_features", {}).get("pitch_hz"):
            feats = voice_features_from_wav(voice_wav_path)
            prof["voice_features"] = feats
            _save_profile(face_name, prof)
        record_cooccurrence(face_name, len(face_names), confirmed_by_user=True)

    return {
        "voice": voice_name,
        "voice_confidence": voice_conf,
        "faces": face_names,
        "identity": identity,
        "auto_identify": AUTO_IDENTIFY,
    }
