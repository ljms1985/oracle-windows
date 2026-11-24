"""
Voice for Oracle - speak replies and listen continuously, no wake word.

Speech (default): OpenAI TTS, model "tts-1", voice "nova" (warm,
natural), WAV output, played through PyAudio. The API key is read
from the OPENAI_API_KEY environment variable; it is never printed,
logged, or stored - only presence / non-empty checks are done.

Lip-sync: while a WAV is playing, each chunk's real RMS amplitude is
measured and smoothed (fast attack, slower release) and reported live
via on_level(level, shape). ``level`` is real audio RMS, 0.0-1.0.
``shape`` is an ESTIMATE only, guessed from the word being spoken at
that moment (round for O/U sounds, wide for A/E, open otherwise) using
elapsed time vs. the chunk's total duration and the words' lengths.
It is not measured from the audio itself.

Fallbacks, in order - speak() never raises into the GUI thread:
  1. OpenAI TTS (when a key is set and PyAudio is available).
  2. pyttsx3 / Windows SAPI, with an estimated envelope (a smoothed
     sine driven by word timing) fed to on_level so lip-sync still
     moves even though there is no real audio to measure.
  3. If that also fails, print a clear error and return.

Listening is unchanged: Google Speech Recognition, no wake word
(see listen_once() below).

Install on Windows:
  pip install pyttsx3 SpeechRecognition PyAudio
  (PyAudio can be tricky on Windows - if pip fails, try:
   pip install pipwin && pipwin install pyaudio)
  No `openai` package is needed: TTS uses plain urllib, like
  agent.py's call_llm() does. OPENAI_API_KEY must be set as a
  User environment variable.

IMPORTANT - always listening, read this:
  * "Always listening" here means: while this GUI is open and the
    toggle is ON, the microphone is active and speech is transcribed.
    Anyone nearby, a TV, or a podcast can trigger it. That is the
    trade-off of having NO wake word.
  * Transcription in this starter uses Google Speech Recognition over
    the internet by default (SpeechRecognition's recognize_google).
    That means audio snippets go to Google. If you do not want that,
    swap in an offline engine like Vosk - see the TODO in listen_once().
  * There is ALWAYS a visible LISTENING indicator in the GUI, and a
    button to pause listening instantly. Never run this hidden.
  * This is for YOUR own PC, in YOUR own home, by your choice. Do not
    run always-listening in a shared / public space without telling
    people nearby.

Usage (GUI interface - keep these exact names):
  from voice import speak, speak_async, get_level, is_speaking, stop_speaking
  speak_async("Hello, I'm Oracle.", on_level=gui.on_level, on_done=gui.on_done)
  text = listen_once(timeout=5)  # returns "" if nothing heard / error
"""

import io
import json
import math
import os
import re
import struct
import threading
import time
import urllib.error
import urllib.request
import wave

# ---------------------------------------------------------------- config

OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"
OPENAI_TTS_MODEL = "tts-1"
OPENAI_TTS_VOICE = "nova"          # warm, natural
OPENAI_TTS_FORMAT = "wav"          # WAV is essential: stdlib `wave` decodes it
_TTS_TIMEOUT = 60                  # seconds per TTS request
_MAX_CHUNK_CHARS = 800             # split long replies into ~sentence chunks
_SENTENCE_PAUSE = 0.28             # seconds of silence between sentences
_SAPI_WORDS_PER_MINUTE = 175       # matches the old SAPI rate=175

# Smoothing: attack fast, release slower (level rises quickly, falls gently).
_ALPHA_ATTACK = 0.6
_ALPHA_RELEASE = 0.15

# ---------------------------------------------------------------- state (thread-safe)

_level = 0.0
_level_lock = threading.Lock()
_speaking = False
_speaking_lock = threading.Lock()
_tts_engine = None
_tts_lock = threading.Lock()
_current_stop = None               # threading.Event for the utterance in progress
_current_stop_lock = threading.Lock()


def get_level():
    """Current smoothed level, 0.0-1.0. Thread-safe."""
    with _level_lock:
        return _level


def _set_level(value):
    global _level
    with _level_lock:
        _level = max(0.0, min(1.0, float(value)))


def is_speaking():
    """True while a speak() / speak_async() utterance is in progress."""
    with _speaking_lock:
        return _speaking


def _set_speaking(value):
    global _speaking
    with _speaking_lock:
        _speaking = bool(value)


def stop_speaking():
    """Stop the current utterance (playback and SAPI fallback). Non-blocking."""
    with _current_stop_lock:
        event = _current_stop
    if event is not None:
        event.set()
    # Best effort: interrupt SAPI if it is the one speaking.
    try:
        with _tts_lock:
            if _tts_engine is not None:
                _tts_engine.stop()
    except Exception:
        pass


def _new_stop_event():
    event = threading.Event()
    with _current_stop_lock:
        global _current_stop
        _current_stop = event
    return event


# ---------------------------------------------------------------- text prep for TTS

def _clean_text_for_tts(text):
    """Strip markdown / formatting so it is never read aloud literally."""
    if not text:
        return ""
    s = str(text)
    # Fenced code blocks and inline code: keep the words, drop the fences.
    s = re.sub(r"```.*?```", " ", s, flags=re.DOTALL)
    s = s.replace("`", "")
    # Images ![alt](url) -> alt ; links [text](url) -> text ; bare URLs dropped.
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"https?://\S+", " ", s)
    # Headings, bold/italic markers, list markers, blockquotes, rules.
    s = re.sub(r"^#{1,6}\s*", "", s, flags=re.MULTILINE)
    s = s.replace("**", "").replace("__", "")
    s = re.sub(r"(?<!\w)\*([^*]+)\*(?!\w)", r"\1", s)
    s = re.sub(r"^\s*[-*+]\s+", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s*\d+[.)]\s+", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s*>\s*", "", s, flags=re.MULTILINE)
    s = re.sub(r"^-{3,}\s*$", "", s, flags=re.MULTILINE)
    s = re.sub(r"<[^>]+>", " ", s)  # any stray HTML tags
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def _split_sentences(text):
    """Split cleaned text into speakable chunks.

    Splits on sentence boundaries first; any over-long sentence is
    split further on commas / semicolons / 'and' boundaries so no
    single TTS request is huge. Returns a list of non-empty strings.
    """
    cleaned = _clean_text_for_tts(text)
    if not cleaned:
        return []
    # Sentence boundaries: . ! ? followed by space + capital/quote, or end.
    parts = re.split(r"(?<=[.!?])\s+(?=[\"'\(\[]?[A-Z0-9])", cleaned)
    chunks = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        while len(part) > _MAX_CHUNK_CHARS:
            # Prefer a comma/semicolon break in the first 800 chars.
            cut = max(part.rfind(",", 0, _MAX_CHUNK_CHARS),
                      part.rfind(";", 0, _MAX_CHUNK_CHARS))
            if cut < 200:  # no good break: hard cut at the limit
                cut = _MAX_CHUNK_CHARS
            chunks.append(part[:cut + 1].strip())
            part = part[cut + 1:].strip()
        if part:
            chunks.append(part)
    return chunks


# ---------------------------------------------------------------- mouth-shape estimate

def _shape_for_word(word, level):
    """Estimate a mouth shape for the word currently being spoken.

    ESTIMATE ONLY - guessed from the word's vowels, not from audio:
      * level near zero            -> "closed"
      * word dominated by O / U    -> "round"
      * word dominated by A / E    -> "wide"
      * otherwise, quiet           -> "slight", louder -> "open"
    ``level`` here is the real smoothed RMS level.
    """
    if level < 0.04:
        return "closed"
    w = (word or "").lower()
    vowels = [c for c in w if c in "aeiou"]
    if not vowels:
        return "slight" if level < 0.18 else "open"
    round_count = vowels.count("o") + vowels.count("u")
    wide_count = vowels.count("a") + vowels.count("e")
    if round_count > wide_count:
        return "round"
    if wide_count > round_count:
        return "wide"
    return "slight" if level < 0.18 else "open"


def _word_at_time(words, elapsed, total_duration):
    """Word being spoken at ``elapsed`` seconds into a chunk.

    Words are assumed to take time in proportion to their length
    (characters, plus a space each) - an estimate, not measured timing.
    """
    if not words or total_duration <= 0:
        return ""
    weights = [len(w) + 1 for w in words]
    total_weight = float(sum(weights))
    target = (elapsed / total_duration) * total_weight
    acc = 0.0
    for word, weight in zip(words, weights):
        acc += weight
        if target <= acc:
            return word
    return words[-1]


def _smooth_level(previous, rms):
    """Exponential smoothing: fast attack, slower release."""
    alpha = _ALPHA_ATTACK if rms > previous else _ALPHA_RELEASE
    return previous + alpha * (rms - previous)


def _rms_of_chunk(raw, sampwidth):
    """RMS amplitude of one raw audio chunk, normalised to 0.0-1.0."""
    if not raw:
        return 0.0
    if sampwidth == 2:
        count = len(raw) // 2
        if count == 0:
            return 0.0
        samples = struct.unpack(f"<{count}h", raw[: count * 2])
        scale = 32768.0
    elif sampwidth == 1:
        # 8-bit WAV is unsigned, centred on 128.
        samples = [b - 128 for b in raw]
        scale = 128.0
    elif sampwidth == 4:
        count = len(raw) // 4
        if count == 0:
            return 0.0
        samples = struct.unpack(f"<{count}i", raw[: count * 4])
        scale = 2147483648.0
    else:
        return 0.0
    if not samples:
        return 0.0
    mean_sq = sum(float(s) * float(s) for s in samples) / len(samples)
    raw_rms = math.sqrt(mean_sq) / scale
    # Remap for lip-sync visibility: real speech RMS sits at roughly
    # 0.03-0.15 of full scale (the PC test peaked at 0.10), so raw
    # RMS would leave the mouth almost closed. A sqrt curve maps
    # 0.15 -> 1.0, 0.05 -> ~0.58, 0.03 -> ~0.45, 0 -> 0. The audio
    # itself is untouched — only the reported level is scaled.
    return min(1.0, math.sqrt(raw_rms / 0.15)) if raw_rms > 0 else 0.0


# ---------------------------------------------------------------- OpenAI TTS (urllib, no `openai` package)

def _synthesize_wav(text_chunk):
    """One OpenAI TTS request. Returns WAV bytes. Raises on failure.

    The API key is read from the environment and sent only as the
    Authorization header. It is never printed, logged, or stored.
    """
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    payload = json.dumps({
        "model": OPENAI_TTS_MODEL,
        "voice": OPENAI_TTS_VOICE,
        "input": text_chunk,
        "response_format": OPENAI_TTS_FORMAT,
    }).encode("utf-8")
    req = urllib.request.Request(
        OPENAI_TTS_URL,
        data=payload,
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TTS_TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        # Status code only - never print the response body / headers.
        raise RuntimeError(f"OpenAI TTS request failed (HTTP {e.code})") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"OpenAI TTS request failed ({e.reason})") from e


def _play_wav_bytes(wav_bytes, chunk_text, on_level, stop_event):
    """Stream WAV bytes through PyAudio, reporting live RMS levels.

    Returns True if the whole chunk played, False if stopped early.
    Raises if PyAudio is missing or playback fails.
    """
    try:
        import pyaudio
    except ImportError as e:
        raise RuntimeError("PyAudio is not installed") from e

    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        total_duration = n_frames / framerate if framerate else 0.0
        words = (chunk_text or "").split()

        audio = pyaudio.PyAudio()
        try:
            stream = audio.open(
                format=audio.get_format_from_width(sampwidth),
                channels=channels,
                rate=framerate,
                output=True,
            )
            try:
                frames_per_chunk = 1024
                frames_played = 0
                level = get_level()
                while not stop_event.is_set():
                    raw = wf.readframes(frames_per_chunk)
                    if not raw:
                        break
                    rms = _rms_of_chunk(raw, sampwidth)
                    level = _smooth_level(level, rms)
                    _set_level(level)
                    elapsed = frames_played / framerate if framerate else 0.0
                    word = _word_at_time(words, elapsed, total_duration)
                    if on_level is not None:
                        try:
                            on_level(level, _shape_for_word(word, level))
                        except Exception:
                            pass  # a GUI callback must never kill playback
                    stream.write(raw)
                    frames_played += len(raw) // (sampwidth * max(channels, 1))
                return not stop_event.is_set()
            finally:
                try:
                    stream.stop_stream()
                except Exception:
                    pass
                stream.close()
        finally:
            audio.terminate()
    # Let the level decay to closed once the chunk ends.
    _set_level(0.0)
    return True


def _pause_between_sentences(on_level, stop_event, seconds=_SENTENCE_PAUSE):
    """A short natural pause: level decays to closed, shape closed."""
    if seconds <= 0:
        return
    level = get_level()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not stop_event.is_set():
        level = _smooth_level(level, 0.0)
        _set_level(level)
        if on_level is not None:
            try:
                on_level(level, "closed")
            except Exception:
                pass
        time.sleep(0.05)
    _set_level(0.0)


def _speak_openai(text, on_level, stop_event):
    """Default engine: OpenAI TTS, chunk by chunk. Raises on failure."""
    chunks = _split_sentences(text)
    if not chunks:
        return
    for i, chunk in enumerate(chunks):
        if stop_event.is_set():
            return
        wav_bytes = _synthesize_wav(chunk)
        if stop_event.is_set():
            return
        played = _play_wav_bytes(wav_bytes, chunk, on_level, stop_event)
        if not played:
            return
        if i < len(chunks) - 1:
            _pause_between_sentences(on_level, stop_event)


# ---------------------------------------------------------------- SAPI fallback (estimated envelope)

def _speak_sapi_fallback(text, on_level, stop_event):
    """Fallback (a): pyttsx3 / Windows SAPI with an estimated envelope.

    There is no real audio to measure, so on_level is driven by a
    smoothed sine wave timed to the words: each word gets roughly
    60/175 seconds (rate 175), the envelope rises and falls inside
    each word, and the shape is estimated from that word's vowels.
    Lip-sync still moves; the level is an estimate, not real RMS.
    """
    try:
        import pyttsx3
    except ImportError as e:
        raise RuntimeError("pyttsx3 is not installed") from e

    cleaned = _clean_text_for_tts(text)
    words = cleaned.split()
    if not words:
        return
    word_duration = 60.0 / _SAPI_WORDS_PER_MINUTE
    total_duration = len(words) * word_duration

    # Drive the estimated envelope on its own thread while SAPI speaks.
    level_holder = {"level": 0.0}
    envelope_done = threading.Event()

    def _envelope_loop():
        start = time.monotonic()
        level = 0.0
        while not stop_event.is_set() and not envelope_done.is_set():
            elapsed = time.monotonic() - start
            if elapsed >= total_duration:
                break
            word = _word_at_time(words, elapsed, total_duration)
            # Sine within the current word: 0 at the edges, peak mid-word.
            within = (elapsed % word_duration) / word_duration if word_duration else 0.0
            target = 0.15 + 0.65 * abs(math.sin(math.pi * within))
            level = _smooth_level(level, target)
            level_holder["level"] = level
            _set_level(level)
            if on_level is not None:
                try:
                    on_level(level, _shape_for_word(word, level))
                except Exception:
                    pass
            time.sleep(0.03)
        _set_level(0.0)
        if on_level is not None:
            try:
                on_level(0.0, "closed")
            except Exception:
                pass

    envelope_thread = threading.Thread(target=_envelope_loop, daemon=True)
    envelope_thread.start()
    try:
        global _tts_engine
        with _tts_lock:
            try:
                if _tts_engine is None:
                    _tts_engine = pyttsx3.init()
                    _tts_engine.setProperty("rate", 175)
                _tts_engine.say(cleaned)
                _tts_engine.runAndWait()
            except Exception as e:
                raise RuntimeError(f"SAPI speech failed: {e}") from e
    finally:
        envelope_done.set()
        envelope_thread.join(timeout=1.0)
        _set_level(0.0)


# ---------------------------------------------------------------- public interface

def speak(text, on_level=None, on_done=None):
    """Speak text aloud - synchronous (blocks until done or stopped).

    Default: OpenAI TTS ("nova"). Fallbacks, in order, never raise:
    (a) OpenAI fails / no key / PyAudio missing -> pyttsx3 SAPI with
    an estimated envelope; (b) that fails -> print a clear error and
    return. ``on_level(level, shape)`` is called from the playback
    thread; ``on_done()`` is called once at the end, whatever happened.
    """
    if not text or not str(text).strip():
        if on_done is not None:
            try:
                on_done()
            except Exception:
                pass
        return
    stop_event = _new_stop_event()
    _set_speaking(True)
    _set_level(0.0)
    try:
        key_present = bool(os.environ.get("OPENAI_API_KEY", ""))
        if key_present:
            try:
                _speak_openai(text, on_level, stop_event)
                return
            except Exception as e:
                print(f"[voice] OpenAI TTS failed ({e}) - falling back to SAPI.")
        else:
            print("[voice] OPENAI_API_KEY is not set - using SAPI fallback.")
        try:
            _speak_sapi_fallback(text, on_level, stop_event)
        except Exception as e:
            # Fallback (b): clear error, no raise into the GUI thread.
            print(f"[voice] Speech failed: SAPI fallback also failed ({e}). "
                  "Check pyttsx3 is installed and OPENAI_API_KEY is set.")
    finally:
        _set_speaking(False)
        _set_level(0.0)
        if on_done is not None:
            try:
                on_done()
            except Exception:
                pass


def speak_async(text, on_level=None, on_done=None):
    """Speak text aloud without blocking; returns the playback thread.

    Stops any utterance already in progress first. ``on_level`` /
    ``on_done`` behave exactly as in speak().
    """
    stop_speaking()
    thread = threading.Thread(
        target=speak, args=(text,), kwargs={"on_level": on_level, "on_done": on_done},
        daemon=True,
    )
    thread.start()
    return thread


def listen_once(timeout=5, phrase_time_limit=12):
    """
    Listen once from the default microphone and return transcribed text,
    or "" if nothing was heard or transcription failed.
    No wake word is checked - any intelligible speech is returned.
    """
    try:
        import speech_recognition as sr
    except ImportError:
        print("[voice] SpeechRecognition not installed. pip install SpeechRecognition PyAudio")
        return ""
    r = sr.Recognizer()
    r.energy_threshold = 300
    r.dynamic_energy_threshold = True
    try:
        with sr.Microphone() as source:
            r.adjust_for_ambient_noise(source, duration=0.5)
            audio = r.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        # TODO: swap this for an offline recogniser (e.g. Vosk) if you
        # do not want audio sent to a cloud speech service.
        return r.recognize_google(audio)
    except Exception:
        # Includes WaitTimeoutError, UnknownValueError, RequestError.
        return ""


if __name__ == "__main__":
    # PC test: run `python voice.py` and listen.
    # Prints the key's presence only - never the key value.
    print("[voice] test: OPENAI_API_KEY set:",
          bool(os.environ.get("OPENAI_API_KEY", "")))
    try:
        import pyaudio  # noqa: F401
        print("[voice] test: PyAudio available")
    except ImportError:
        print("[voice] test: PyAudio NOT installed - OpenAI path will fall back to SAPI")

    _last_print = {"t": 0.0}

    def _on_level(level, shape):
        now = time.monotonic()
        if now - _last_print["t"] >= 0.1:  # throttle: ~10 lines/sec max
            _last_print["t"] = now
            bar = "#" * int(level * 30)
            print(f"[voice] level={level:.2f} shape={shape:<6} |{bar}")

    def _on_done():
        print("[voice] test: done speaking. "
              f"is_speaking={is_speaking()} level={get_level():.2f}")

    speak("Hi Lorenza, this is Oracle, and I should sound a lot more natural now.",
          on_level=_on_level, on_done=_on_done)
