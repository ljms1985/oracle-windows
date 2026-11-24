"""
Voice for Oracle - speak replies and listen continuously, no wake word.

Install on Windows:
  pip install pyttsx3 SpeechRecognition PyAudio
  (PyAudio can be tricky on Windows - if pip fails, try:
   pip install pipwin && pipwin install pyaudio)

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

Usage:
  from voice import speak, listen_once
  speak("Hello, I'm Oracle.")
  text = listen_once(timeout=5)  # returns "" if nothing heard / error
"""

import threading

_tts_engine = None
_tts_lock = threading.Lock()


def speak(text):
    """Speak text aloud on Windows (offline, via SAPI through pyttsx3)."""
    if not text:
        return
    try:
        import pyttsx3
    except ImportError:
        print("[voice] pyttsx3 not installed - cannot speak aloud. pip install pyttsx3")
        return
    global _tts_engine
    with _tts_lock:
        try:
            if _tts_engine is None:
                _tts_engine = pyttsx3.init()
                _tts_engine.setProperty("rate", 175)
            _tts_engine.say(text)
            _tts_engine.runAndWait()
        except Exception as e:
            print(f"[voice] TTS failed: {e}")


def speak_async(text):
    threading.Thread(target=speak, args=(text,), daemon=True).start()


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
