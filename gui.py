"""
Oracle GUI - modern, futuristic, Gideon-inspired interface for Windows.

NOT generic tkinter anymore. This is a dark, glassy, neon console:
  * Deep-space background with a drifting starfield
  * An animated AI head, Gideon-inspired - it blinks, looks around,
    nods, and its mouth actually moves while Oracle is speaking,
    with a live waveform below it. No ring anymore.
  * The face is now Lorenza's chosen Muse avatar (red-and-black anime
    figure, long spiky black hair, red gi) from assets/avatar.png,
    animated the same way - idle bob, blink, look-around, nod, mouth
    moving while speaking. If the image is missing, the original
    vector head drawn in code is used as a fallback, never a crash.
  * A left command deck instead of a row of grey buttons
  * Pill status indicators, a live clock, and a theme switcher
  * Chat in a dark glass panel, with a neon-bordered input

This is still *inspired-by* Gideon from The Flash, not an official
product and it uses no show assets - the head is original vector art
drawn in code. It is a screen console, not a hologram.

Run:
  python gui.py
  (set OPENAI_API_KEY first - see README.md. Do NOT paste your key
   into a chat; set it as a Windows environment variable on your PC.)

Still tkinter only - no extra packages to install on Windows Python.
The head idles with a slow bob and blink, looks up while thinking,
and talks while Oracle's reply is typing out and being spoken.
Replies come from
the same brain as agent.py (OpenAI by default, Ollama if
LLM_PROVIDER=ollama). The GUI is the face; agent.py is the brain.
"""

import math
import os
import queue
import random
import sys
import threading
import time
# BEFORE tkinter: point TCL_LIBRARY / TK_LIBRARY at the bundled Tcl/Tk
# data inside the frozen bundle (see oracle_paths.py). v1.0.0 crashed
# on Lorenza's PC with "can't find a usable init.tcl" — this overrides
# any broken TCL_LIBRARY / TK_LIBRARY already set on that PC, which is
# the most likely cause given the same build passes the smoke test on
# the GitHub Windows runner. Must run before `import tkinter`.
try:
    from oracle_paths import fix_tcl as _fix_tcl
    _fix_tcl()
except Exception:
    pass

# --- Windows DPI awareness (avatar sharpness, 2026-11-24) ---
# Without this, Windows bitmap-scales the whole Tk window at display
# scaling (125%/150%), blurring the avatar even at native resolution.
# Per-monitor aware (value 2); falls back to system-aware. Guarded so
# it never breaks startup on a non-Windows machine.
try:
    import ctypes as _ctypes
    _ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        import ctypes as _ctypes
        _ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import tkinter as tk
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Bundled read-only resources (avatar, docs): inside sys._MEIPASS when
# frozen, next to this file when running from source.
try:
    from oracle_paths import resource_path as _resource_path
    RESOURCE_DIR = _resource_path("")
except Exception:
    RESOURCE_DIR = BASE_DIR

try:
    import agent as agent_mod
    AGENT_NAME = getattr(agent_mod, "AGENT_NAME", "Oracle")
    PERSONALITY = getattr(agent_mod, "PERSONALITY", "You are Oracle, a friendly AI assistant.")
    call_llm = agent_mod.call_llm
    PROVIDER = getattr(agent_mod, "PROVIDER", "openai")
except Exception as e:
    AGENT_NAME = "Oracle"
    PERSONALITY = "You are Oracle, a friendly AI assistant."
    PROVIDER = "openai"
    call_llm = None
    print(f"Warning: could not import agent.py ({e}). GUI will run in demo mode.")

try:
    import voice as voice_mod
except Exception:
    voice_mod = None

try:
    import monitor as monitor_mod
except Exception:
    monitor_mod = None

try:
    import camera as camera_mod
except Exception:
    camera_mod = None

try:
    import identity as identity_mod
except Exception:
    identity_mod = None

try:
    import get_to_know as get_to_know_mod
except Exception:
    get_to_know_mod = None

try:
    import repair as repair_mod
except Exception:
    repair_mod = None

# Muse-memory import (v1.0.7): Oracle inherits Muse conversations
# from export files Lorenza provides. Pure stdlib, no network, no
# credentials — see memory_import.py and MEMORY_SHARING.md.
try:
    import memory_import as memory_import
except Exception:
    memory_import = None

# Continuous learning memory (v1.0.9): everything the PC agent
# hears, sees and reads is auto-saved into memory.json, so it
# keeps learning like Muse does — local only, never uploaded.
try:
    import continuous_memory as continuous_memory
except Exception:
    continuous_memory = None

# Live hardware monitoring (v1.0.9): CPU/GPU temps, clocks, fans,
# utilisation, power for the Hardware panel. NOT monitor.py (the
# self-improvement monitor). Stdlib + optional psutil.
try:
    import hardware_monitor as hardware_monitor
except Exception:
    hardware_monitor = None

# Real lips (v1.0.9, lips.py) + full avatar animation director
# (v1.0.9, avatar_anim.py): the v1.0.6 oval mouth was a hole
# opening and closing — Lorenza called it out. lips.py draws
# actual upper/lower lips with visemes; avatar_anim.py drives
# breathing, blinking, gaze, tilt and expressions at ~30 fps.
# Both are pure stdlib, so they port to the Mac build unchanged.
try:
    import lips as lips_mod
except Exception:
    lips_mod = None
# Avatar deform (v1.0.9 fix, 2026-11-24 22:31 EST): the avatar IMAGE
# itself is warped (avatar_deform.py) — mouth/eyes in the image move.
# The old blink/mouth OVERLAY drawn on top of the frozen image is
# banned (Lorenza: it looked fake) and is gone from this file.
try:
    import avatar_deform as avatar_deform_mod
except Exception:
    avatar_deform_mod = None
try:
    import avatar_anim as avatar_anim_mod
except Exception:
    avatar_anim_mod = None

# Writable home for memory.json / memory_import/: next to Oracle.exe
# when frozen (same as agent.py's MEMORY_FILE), next to the .py files
# when running from source.
try:
    from oracle_paths import app_dir as _oracle_app_dir
    APP_DIR = _oracle_app_dir()
except Exception:
    APP_DIR = BASE_DIR


# ---------------------------------------------------------------- themes
THEMES = {
    "NEON CYAN": {
        "bg": "#020617", "panel": "#0b1226", "panel2": "#131f3d",
        "accent": "#00e5ff", "accent2": "#a855f7",
        "text": "#eaf6ff", "muted": "#7d8ca8",
        "good": "#22ff9a", "warn": "#ffb020", "danger": "#ff4d6d",
    },
    "ULTRAVIOLET": {
        "bg": "#0a0218", "panel": "#1a0f33", "panel2": "#241645",
        "accent": "#c084fc", "accent2": "#00e5ff",
        "text": "#f3efff", "muted": "#9a8ab8",
        "good": "#22ff9a", "warn": "#ffb020", "danger": "#ff4d6d",
    },
    "SOLAR AMBER": {
        "bg": "#0d0702", "panel": "#1d1206", "panel2": "#2b1d0a",
        "accent": "#ffb020", "accent2": "#ff4d6d",
        "text": "#fff4e0", "muted": "#a89a7d",
        "good": "#22ff9a", "warn": "#00e5ff", "danger": "#ff4d6d",
    },
}
THEME_NAMES = list(THEMES.keys())


def _darken(hexcol, factor=0.55):
    h = hexcol.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"#{int(r*factor):02x}{int(g*factor):02x}{int(b*factor):02x}"


class OracleGUI:
    def __init__(self, root):
        self.root = root
        self.theme_idx = 0
        self.t = THEMES[THEME_NAMES[0]]
        self.root.title("ORACLE  —  Futuristic Console")
        self.root.geometry("1180x860")
        self.root.minsize(1000, 720)
        self.root.configure(bg=self.t["bg"])
        self.mode = "idle"  # idle, listening, thinking, speaking
        self.phase = 0.0
        self.history = []
        # Always listening is the designed default for this agent:
        # voice replies, always-listening, NO wake word. It must be
        # ON from startup, not left OFF behind a button tap — the
        # running instance shipped with False here, which is exactly
        # why it was not listening even though the design said it was.
        self.always_listen = True
        self.speak_replies = True
        self.busy = False
        self._ask_started = None  # datetime the current _ask thread started
        # --- Fluid lip-sync state (v1.0.6) ---
        # voice.py calls _on_speech_level(level, shape) from its
        # playback thread with the REAL audio RMS level; the GUI never
        # touches tkinter from that thread — it only stores the target
        # here, and animate() (main thread) eases lip_level towards
        # it every frame, so the mouth moves smoothly, never snaps.
        self.lip_level = 0.0       # eased 0..1, read by animate()
        self._lip_target_level = 0.0
        self._lip_shape = "closed"  # closed/slight/open/wide/round/fv
        self._typing_done = False
        self._speech_done = True
        # --- Interrupt token (v1.0.10 fix, item 3, 2026-11-25) ---
        # Every reply gets the token value current when it started;
        # interrupt_speaking() bumps it. _ask discards a reply whose
        # token went stale (interrupted during generation) and
        # _typewriter aborts a stale chain mid-typing, so an
        # interrupted reply never reaches the screen or the speaker.
        self._reply_token = 0
        # Post-interrupt listen blackout (item 3, 2026-11-25): after
        # Lorenza stops a reply, the mic still rings with the
        # stopped TTS tail and Whisper confabulates on it ("Horray!",
        # "I'm in!") — without a blackout the agent answers its own
        # echo and starts talking again on its own a second after
        # being stopped. interrupt_speaking() sets this to now+3s;
        # the listen loop drops anything heard before it.
        self._interrupt_until = 0.0
        # --- Avatar animation director (v1.0.9, avatar_anim.py) ---
        # Breathing, natural blinking, wandering gaze, nods, head
        # tilt, expressions and laugh/surprise reactions — the phone
        # avatar's observable behaviour, reproduced, not copied
        # (there is no Muse avatar source to copy). frame() is
        # called every animate() tick; None falls back to the old
        # sine motion so the GUI never breaks without the module.
        self._animator = (avatar_anim_mod.AvatarAnimator()
                          if avatar_anim_mod is not None else None)
        self._anim_last_t = time.time()
        # --- Avatar-only mode state (v1.0.6) ---
        self.avatar_win = None
        self._avatar_mode = False
        self._avatar_drag = None
        self._avatar_pil = None    # PIL image, for the avatar-only window
        # Main-thread UI queue: tkinter is NOT thread-safe. Worker
        # threads must NEVER call root.after() / widget methods
        # directly — a cross-thread root.after() can silently fail,
        # which left _ask's reply undelivered and busy=True forever
        # ("thinking forever", 2026-11-24). Workers put callables
        # here; the main thread drains them on its own clock tick.
        self._ui_queue = queue.Queue()
        self.listen_thread = None
        self.watcher = None
        self.camera_controller = None
        # Harmony tracking defaults ON when the camera is on (v1.0.8,
        # item 7; Harmony-only since 2026-11-24). Flipping this to
        # False is the hold-still pause, not a mode change.
        self.auto_track_enabled = True
        self.stars = [(random.random(), random.random(), random.choice([1, 1, 2]))
                      for _ in range(90)]
        # --- Muse avatar (Lorenza's chosen red-and-black anime avatar) ---
        # Loaded from assets/avatar.png (copy at avatar.png). If Pillow or
        # the file is missing, avatar_photo stays None and animate() falls
        # back to the drawn vector head. Never crashes on a missing image.
        self.avatar_photo = None
        self.avatar_w, self.avatar_h = 420, 386  # hi-res render (was 260x239)
        self._avatar_profile = "anime"  # "pencil" once the drawing loads
        self._load_avatar()

        self._build_top()
        self._build_main()
        self._refresh_api_key_label()
        self._refresh_key_labels()
        # Log which keys are set (SET / NOT SET only — never values),
        # so a live check can confirm the three rows without looking
        # at the GUI. ElevenLabs should read SET on Lorenza's PC
        # (its 51-char key is already in the User env var).
        try:
            self._log_listening(self._keys_log_line())
        except Exception:
            pass
        # Minimise -> avatar-only mode (v1.0.6): clicking the minimise
        # button hides the main box and leaves just the avatar.
        try:
            self.root.bind("<Unmap>", self._on_unmap)
        except Exception:
            pass
        # Esc stops Oracle mid-sentence, same as the Stop button
        # (v1.0.10 fix, item 3). bind_all so it works from the entry
        # box, the buttons, and the canvas alike.
        try:
            self.root.bind_all("<Escape>",
                               lambda e: self.interrupt_speaking("keyboard"))
        except Exception:
            pass
        self.animate()
        self._tick_clock()
        self._drain_ui_queue()

        # Muse memory (v1.0.7): pick up any export files dropped in
        # memory_import/ and say, in one line, what Oracle remembers.
        self._memory_startup()
        self.append("system", f"{AGENT_NAME} online. Ask me anything — watch the core light up when I answer.")
        if PROVIDER == "openai" and not os.environ.get("OPENAI_API_KEY"):
            self.append("system", "Note: OPENAI_API_KEY is not set yet, so replies will fail until you set it on your PC. See README.md — do not paste the key here.")
        # Always listening starts automatically at launch (no wake
        # word). _start_listening() is a no-op-safe call: it checks
        # the voice libraries, flips the button/label/pill to ON, and
        # starts the listen thread.
        self._start_listening()

        # Camera watch is ALWAYS ON from startup (2026-11-24, Lorenza:
        # "Camera watch should always be on from the start of the
        # program, from the time the AI agent opens camera watch
        # should already be running"). _start_camera_watch_auto()
        # starts it in a worker thread so a slow camera probe never
        # blocks the GUI from opening, and retries every 30 s if the
        # camera is busy / fails to open. The preview lives in its
        # OWN window ("Oracle Camera", 2026-11-24 layout change) —
        # no preview box in the main GUI any more.
        self._camera_watch_user_stopped = False
        self._cam_window_photo = None
        self._gtk_session = None  # "Get to know me" session, if one is running
        self._cam_window = None
        self._cam_window_label = None
        self._cam_window_status = None
        self._cam_window_visible = False
        self._last_noted_name = None  # last face noted in memory
        self._build_camera_window()
        self._start_camera_watch_auto()
        # Live Hardware panel (2026-11-24): background thread, ~2 s
        # refresh, main thread drains results via _post_ui — widget
        # methods are never called from the worker thread, and a
        # failed sensor read never touches the GUI.
        self._start_hardware_monitor()

    def _log_listening(self, line):
        """Append one timestamped line to voice-listening.log in the
        data dir (next to the exe, or on the dedicated data drive
        when one is set), so always-listening can be verified from
        outside the GUI (process + log, not just the on-screen label)."""
        try:
            log_path = APP_DIR / "voice-listening.log"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {line}\n")
        except Exception:
            pass

    def _post_ui(self, fn):
        """Queue a callable to run on the main (tkinter) thread.

        The ONLY way worker threads may touch the UI. Never call
        root.after() or widget methods from a worker thread."""
        try:
            self._ui_queue.put(fn)
        except Exception:
            pass

    def _drain_ui_queue(self):
        """Main-thread drain of the UI queue, every 50 ms."""
        try:
            while True:
                fn = self._ui_queue.get_nowait()
                try:
                    fn()
                except Exception as e:
                    self._log_listening(f"UI QUEUE ERROR: {e}")
        except queue.Empty:
            pass
        except Exception:
            pass
        try:
            self.root.after(50, self._drain_ui_queue)
        except Exception:
            pass

    # ------------------------------------------------------------ widgets
    def _btn(self, parent, text, command, accent=False, small=False):
        t = self.t
        b = tk.Button(
            parent, text=text, command=command, relief="flat", cursor="hand2",
            font=("Segoe UI", 10 if not small else 9, "bold"),
            bg=t["accent"] if accent else t["panel2"],
            fg="#04121a" if accent else t["text"],
            activebackground=t["accent"], activeforeground="#04121a",
            padx=10, pady=7 if not small else 5, borderwidth=0,
        )
        base = b.cget("bg")
        def _enter(_e, btn=b, base=base):
            btn.configure(bg=t["accent"] if not accent else _darken(t["accent"], 0.8))
        def _leave(_e, btn=b, base=base):
            btn.configure(bg=base)
        b.bind("<Enter>", _enter)
        b.bind("<Leave>", _leave)
        return b

    def _card(self, parent, title):
        t = self.t
        card = tk.Frame(parent, bg=t["panel"], padx=12, pady=10)
        card.pack(fill="x", pady=(0, 10))
        tk.Frame(card, bg=t["accent"], height=2).pack(fill="x", pady=(0, 8))
        tk.Label(card, text=title, font=("Segoe UI", 9, "bold"),
                 fg=t["accent"], bg=t["panel"]).pack(anchor="w", pady=(0, 8))
        return card

    def _pill(self, parent, text, colour):
        return tk.Label(parent, text=f"  {text}  ", font=("Segoe UI", 9, "bold"),
                        fg=colour, bg=self.t["panel2"])

    # ------------------------------------------------------------ layout
    def _build_top(self):
        t = self.t
        top = tk.Frame(self.root, bg=t["bg"])
        top.pack(fill="x", padx=18, pady=(14, 6))
        # Mini orb logo, drawn on a tiny canvas
        logo = tk.Canvas(top, width=52, height=52, bg=t["bg"], highlightthickness=0)
        logo.pack(side="left", padx=(0, 12))
        logo.create_oval(6, 6, 46, 46, outline=t["accent"], width=2)
        logo.create_oval(16, 16, 36, 36, fill=t["panel2"], outline=t["accent2"], width=2)
        logo.create_oval(23, 23, 29, 29, fill=t["accent"], outline="")
        title_box = tk.Frame(top, bg=t["bg"])
        title_box.pack(side="left")
        tk.Label(title_box, text="O R A C L E", font=("Segoe UI", 28, "bold"),
                 fg=t["accent"], bg=t["bg"]).pack(anchor="w")
        tk.Label(title_box, text="FUTURISTIC CONSOLE  •  GIDEON-INSPIRED  •  TALK LIKE A FRIEND",
                 font=("Segoe UI", 9, "bold"), fg=t["muted"], bg=t["bg"]).pack(anchor="w")

        right = tk.Frame(top, bg=t["bg"])
        right.pack(side="right", anchor="n")
        self.clock_label = tk.Label(right, text="--:--", font=("Segoe UI", 13, "bold"),
                                    fg=t["text"], bg=t["bg"])
        self.clock_label.pack(anchor="e")
        pills = tk.Frame(right, bg=t["bg"])
        pills.pack(anchor="e", pady=(4, 0))
        self.status = self._pill(pills, "● ONLINE", t["good"])
        self.status.pack(side="left", padx=2)
        self.brain_pill = self._pill(pills, f"BRAIN: {PROVIDER.upper()}", t["accent"])
        self.brain_pill.pack(side="left", padx=2)
        self.mic_pill = self._pill(pills, "MIC: OFF", t["muted"])
        self.mic_pill.pack(side="left", padx=2)
        self.cam_pill = self._pill(pills, "CAM: OFF", t["muted"])
        self.cam_pill.pack(side="left", padx=2)

    def _build_main(self):
        t = self.t
        main = tk.Frame(self.root, bg=t["bg"])
        main.pack(fill="both", expand=True, padx=18, pady=(0, 14))

        # ---- left command deck, scrollable so no card is ever cut off ----
        deck_outer = tk.Frame(main, bg=t["bg"], width=250)
        deck_outer.pack(side="left", fill="y", padx=(0, 14))
        deck_outer.pack_propagate(False)
        deck_canvas = tk.Canvas(deck_outer, bg=t["bg"], highlightthickness=0, width=250)
        deck_scroll = tk.Scrollbar(deck_outer, orient="vertical", command=deck_canvas.yview)
        deck_canvas.configure(yscrollcommand=deck_scroll.set)
        deck_canvas.pack(side="left", fill="both", expand=True)
        deck_scroll.pack(side="right", fill="y")
        deck = tk.Frame(deck_canvas, bg=t["bg"])
        deck_canvas.create_window((0, 0), window=deck, anchor="nw", width=232)
        def _deck_scroll(_e):
            deck_canvas.configure(scrollregion=deck_canvas.bbox("all"))
        deck.bind("<Configure>", _deck_scroll)
        def _on_wheel(e):
            deck_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        deck_canvas.bind_all("<MouseWheel>", _on_wheel)

        # API KEYS card — first in the left deck, visible on first open
        # (v1.0.6 OpenAI; 2026-11-24 ElevenLabs + spare slot, Lorenza).
        # No key is EVER shown; only SET / NOT SET and the last 4
        # characters. All three save on this PC only (User env vars).
        key_card = self._card(deck, "🔑  API KEYS")
        self._key_labels = {}
        self._extra_name_label = None
        for _service, _friendly in (("openai", "OpenAI"),
                                    ("elevenlabs", "ElevenLabs"),
                                    ("extra", None)):
            _row = tk.Frame(key_card, bg=t["panel"])
            _row.pack(fill="x", pady=1)
            _name = _friendly if _friendly else self._extra_key_label()
            _name_lbl = tk.Label(_row, text=_name, font=("Segoe UI", 9, "bold"),
                                 fg=t["text"], bg=t["panel"], width=11,
                                 anchor="w")
            _name_lbl.pack(side="left")
            if _service == "extra":
                self._extra_name_label = _name_lbl
            _status = tk.Label(_row, text="…", font=("Segoe UI", 9),
                               fg=t["muted"], bg=t["panel"], anchor="w")
            _status.pack(side="left", fill="x", expand=True)
            self._key_labels[_service] = _status
            self._btn(_row, "Change",
                      lambda s=_service: self._show_key_dialog(s),
                      small=True).pack(side="right", padx=(4, 0))
        # Alias kept so _refresh_api_key_label() still works.
        self.api_key_label = self._key_labels["openai"]
        self._btn(key_card, "Rename extra key…", self._rename_extra_key,
                  small=True).pack(fill="x", pady=2)
        tk.Label(key_card, text="Saved on this PC only. Never in source code, logs, or email.",
                 font=("Segoe UI", 8), fg=t["muted"], bg=t["panel"],
                 wraplength=200, justify="left").pack(anchor="w", pady=(2, 0))

        # MEMORY card (v1.0.7) — Muse conversation memory, local only.
        # Right under API KEY so it is visible on first open.
        mem_card = self._card(deck, "🧠  MEMORY  •  MUSE")
        self.memory_label = tk.Label(mem_card, text="Remembered: …", font=("Segoe UI", 9, "bold"),
                                     fg=t["muted"], bg=t["panel"])
        self.memory_label.pack(anchor="w", pady=(2, 4))
        self._btn(mem_card, "Import Muse memory…", self._import_memory_file).pack(fill="x", pady=2)
        self._btn(mem_card, "What do you remember?", self._show_memory_summary).pack(fill="x", pady=2)
        self._btn(mem_card, "Forget that…", self._forget_memory_gui).pack(fill="x", pady=2)
        tk.Label(mem_card, text="Drop Muse chat exports (.md / .json / .txt) in the memory_import folder next to Oracle.exe — I pick them up at startup. Local only, never uploaded.",
                 font=("Segoe UI", 8), fg=t["muted"], bg=t["panel"],
                 wraplength=200, justify="left").pack(anchor="w", pady=(2, 0))

        voice_card = self._card(deck, "◇  VOICE")
        self.listen_btn = self._btn(voice_card, "Always listen: OFF", self.toggle_listen)
        self.listen_btn.pack(fill="x", pady=2)
        self.speak_btn = self._btn(voice_card, "Speak replies: ON", self.toggle_speak)
        self.speak_btn.pack(fill="x", pady=2)
        # Stop / shut up (v1.0.10 fix, item 3, 2026-11-25, Lorenza):
        # when Oracle is long-winded she must be able to cut it off
        # at once. This button, the Esc key, and saying "stop" /
        # "shut up" / "be quiet" all do the same thing: stop TTS
        # playback now, clear the speech queue, and stop the model
        # from continuing that reply (see interrupt_speaking).
        self.stop_btn = self._btn(voice_card, "■  Stop speaking  (Esc)",
                                  lambda: self.interrupt_speaking("button"))
        self.stop_btn.pack(fill="x", pady=2)
        # Voice engine (2026-11-24): OpenAI nova (default), ElevenLabs,
        # or the offline system voice. Saved in oracle_settings.json;
        # takes effect on the next reply. ElevenLabs needs its key
        # first (API KEYS card) — picking it without a key is refused
        # with a plain message, and the engine stays where it was.
        eng_row = tk.Frame(voice_card, bg=t["panel"])
        eng_row.pack(fill="x", pady=(6, 2))
        tk.Label(eng_row, text="Voice:", font=("Segoe UI", 9, "bold"),
                 fg=t["text"], bg=t["panel"]).pack(side="left")
        _engine_labels = ([voice_mod.VOICE_ENGINE_LABELS[e]
                           for e in voice_mod.VOICE_ENGINES]
                          if voice_mod is not None else ["OpenAI (nova)"])
        self.voice_engine_var = tk.StringVar(value=self._voice_engine_display())
        self.voice_engine_menu = tk.OptionMenu(
            eng_row, self.voice_engine_var, *_engine_labels,
            command=self._on_voice_engine_change)
        try:
            self.voice_engine_menu.config(font=("Segoe UI", 9), bg=t["panel"],
                                          fg=t["text"], highlightthickness=0)
        except Exception:
            pass
        self.voice_engine_menu.pack(side="left", fill="x", expand=True)
        self.listen_label = tk.Label(voice_card, text="", font=("Segoe UI", 9, "bold"),
                                     fg=t["danger"], bg=t["panel"])
        self.listen_label.pack(anchor="w", pady=(4, 0))
        tk.Label(voice_card, text="No wake word. Tap again to pause instantly.",
                 font=("Segoe UI", 8), fg=t["muted"], bg=t["panel"],
                 wraplength=200, justify="left").pack(anchor="w", pady=(2, 0))

        cam_card = self._card(deck, "◎  VISION  •  PIXY")
        self.watch_btn = self._btn(cam_card, "Start camera watch", self.toggle_watch)
        self.watch_btn.pack(fill="x", pady=2)
        ptz = tk.Frame(cam_card, bg=t["panel"])
        ptz.pack(fill="x", pady=4)
        for i, (label, args) in enumerate([
                ("◀ Pan", (-20, 0, 0.0)), ("Pan ▶", (20, 0, 0.0)),
                ("▲ Tilt", (0, 10, 0.0)), ("▼ Tilt", (0, -10, 0.0)),
                ("Zoom +", (0, 0, 0.1)), ("Zoom −", (0, 0, -0.1))]):
            b = self._btn(ptz, label, lambda a=args: self.camera_ptz(*a), small=True)
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=2, pady=2)
        ptz.grid_columnconfigure(0, weight=1)
        ptz.grid_columnconfigure(1, weight=1)
        priv = self._btn(cam_card, "Privacy mode", self.camera_privacy)
        priv.pack(fill="x", pady=2)
        self._btn(cam_card, "Test camera (grab a frame)", self.test_camera_gui).pack(fill="x", pady=2)
        self._btn(cam_card, "Pan & describe what you see", self.pan_describe_gui).pack(fill="x", pady=2)
        # Harmony tracking (2026-11-24 decision): Harmony is the
        # ONLY tracking mode — the PIXY leads, Oracle watches.
        # "Hold still" is a pause inside Harmony, not a mode, and
        # "Show camera" reopens the separate preview window.
        self.harmony_label = tk.Label(cam_card, text="Tracking: Harmony — PIXY leads",
                                      font=("Segoe UI", 9, "bold"),
                                      fg=t["muted"], bg=t["panel"])
        self.harmony_label.pack(anchor="w", pady=(4, 0))
        self.track_btn = self._btn(cam_card, "Hold still", self.toggle_hold_still)
        self.track_btn.pack(fill="x", pady=2)
        self._btn(cam_card, "Show camera", self._show_camera_window).pack(fill="x", pady=2)
        self.track_label = tk.Label(cam_card, text="Tracking: —", font=("Segoe UI", 9, "bold"),
                                    fg=t["muted"], bg=t["panel"])
        self.track_label.pack(anchor="w", pady=(4, 0))
        self.cam_label = tk.Label(cam_card, text="Camera: OFF", font=("Segoe UI", 9, "bold"),
                                  fg=t["muted"], bg=t["panel"])
        self.cam_label.pack(anchor="w", pady=(4, 0))

        rep_card = self._card(deck, "⬢  REPAIR")
        self._btn(rep_card, "Start Apollo Twin repair", self.start_repair_gui).pack(fill="x", pady=2)
        self._btn(rep_card, "Look at board", self.look_at_board_gui).pack(fill="x", pady=2)
        tk.Label(rep_card, text="One question at a time, camera-assisted, web search when needed.",
                 font=("Segoe UI", 8), fg=t["muted"], bg=t["panel"],
                 wraplength=200, justify="left").pack(anchor="w", pady=(2, 0))

        people_card = self._card(deck, "◐  PEOPLE  •  HOME MODE")
        self._btn(people_card, "Enroll voice", self.enroll_voice_gui).pack(fill="x", pady=2)
        self._btn(people_card, "Enroll face (camera)", self.enroll_face_gui).pack(fill="x", pady=2)
        self._btn(people_card, "List enrolled",
                  lambda: self.append("system", f"Enrolled (local only): {identity_mod.list_identities() if identity_mod else 'identity module missing'}")).pack(fill="x", pady=2)
        self._btn(people_card, "Delete identity", self.delete_identity_gui).pack(fill="x", pady=2)
        self._btn(people_card, "Get to know me", self.get_to_know_gui).pack(fill="x", pady=2)
        self._btn(people_card, "What you told me",
                  lambda: self.append("system", self._review_get_to_know())).pack(fill="x", pady=2)
        self._btn(people_card, "Forget what you told me", self.forget_get_to_know_gui).pack(fill="x", pady=2)

        sys_card = self._card(deck, "⚙  SYSTEM")
        self._btn(sys_card, "Check for improvements", self.check_improvements).pack(fill="x", pady=2)
        self._btn(sys_card, "Avatar only  ◐", self._enter_avatar_only).pack(fill="x", pady=2)
        self._btn(sys_card, "Switch theme  ◐", self.switch_theme).pack(fill="x", pady=2)
        self._btn(sys_card, "Set data drive…", self._set_data_drive_gui).pack(fill="x", pady=2)
        self._data_dir_label = tk.Label(
            sys_card, text=f"Data: {APP_DIR}", font=("Segoe UI", 8),
            fg=t["muted"], bg=t["panel"], wraplength=200, justify="left")
        self._data_dir_label.pack(anchor="w", pady=(2, 0))
        tk.Label(sys_card, text="Proposals never apply without a clear YES, by email or in this GUI.",
                 font=("Segoe UI", 8), fg=t["muted"], bg=t["panel"],
                 wraplength=200, justify="left").pack(anchor="w", pady=(2, 0))

        # ---- Hardware panel (2026-11-24, Lorenza): live CPU/GPU
        # temps, clocks, pump, utilisation, power, RAM and network,
        # refreshed about every 2 s from a background thread. A
        # sensor that cannot be read shows "—" with the reason
        # underneath — never a made-up number. There is NO CPU fan
        # row: the Kraken Elite 360 AIO cools with a PUMP, so the
        # row is Pump speed (liquidctl / LHM), and CPU temp comes
        # from LibreHardwareMonitor (auto-started when needed) and
        # should match what NZXT CAM displays.
        hw_card = self._card(deck, "▦  HARDWARE  •  LIVE")
        self._hw_rows = [
            ("CPU temp", "cpu_temp_c", "°C", 0, "value"),
            ("CPU clock", "cpu_clock_mhz", "MHz", 0, "value"),
            ("Pump speed", "pump_speed_rpm", "RPM", 0, "pump"),
            ("CPU load", "cpu_util_pct", "%", 0, "value"),
            ("GPU temp", "gpu_temp_c", "°C", 0, "value"),
            ("GPU core clock", "gpu_clock_mhz", "MHz", 0, "value"),
            ("GPU mem clock", "gpu_mem_clock_mhz", "MHz", 0, "value"),
            ("GPU fan", "gpu_fan_pct", "%", 0, "value"),
            ("GPU load", "gpu_util_pct", "%", 0, "value"),
            ("GPU power", "gpu_power_w", "W", 1, "value"),
            ("RAM load", "ram_util_pct", "%", 0, "ram"),
            ("Network", "net_down_mbps", "Mbps", 1, "net"),
        ]
        self._hw_value_labels = {}
        for label_text, key, _unit, _dec, _fmt in self._hw_rows:
            row = tk.Frame(hw_card, bg=t["panel"])
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label_text, font=("Segoe UI", 9),
                     fg=t["muted"], bg=t["panel"]).pack(side="left")
            val = tk.Label(row, text="—", font=("Segoe UI", 9, "bold"),
                           fg=t["text"], bg=t["panel"])
            val.pack(side="right")
            self._hw_value_labels[key] = val
        self._hw_note_label = tk.Label(
            hw_card, text="", font=("Segoe UI", 8), fg=t["muted"],
            bg=t["panel"], wraplength=200, justify="left")
        self._hw_note_label.pack(anchor="w", pady=(2, 0))
        self._hw_running = False

        # ---- right: core + chat ----
        right = tk.Frame(main, bg=t["bg"])
        right.pack(side="left", fill="both", expand=True)

        # Glowing core canvas, in a neon-bordered frame
        core_frame = tk.Frame(right, bg=t["accent"], padx=1, pady=1)
        core_frame.pack(fill="x")
        self.canvas = tk.Canvas(core_frame, height=480, bg=t["bg"], highlightthickness=0)
        self.canvas.pack(fill="x")
        self.mode_label = tk.Label(right, text="—  IDLE  —", font=("Segoe UI", 10, "bold"),
                                   fg=t["accent"], bg=t["bg"])
        self.mode_label.pack(pady=(8, 4))

        # Input first, pinned to the bottom, so it can never be pushed off-screen
        input_frame = tk.Frame(right, bg=t["accent"], padx=1, pady=1)
        input_frame.pack(side="bottom", fill="x")

        chat_frame = tk.Frame(right, bg=t["panel"], padx=1, pady=1)
        chat_frame.pack(fill="both", expand=True, pady=(0, 10))
        self.text = tk.Text(chat_frame, bg=t["panel"], fg=t["text"], font=("Segoe UI", 11),
                            wrap="word", state="disabled", relief="flat", padx=14, pady=12)
        self.text.pack(side="left", fill="both", expand=True)
        scroll = tk.Scrollbar(chat_frame, command=self.text.yview)
        scroll.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=scroll.set)
        self.text.tag_config("oracle", foreground=t["accent"])
        self.text.tag_config("user", foreground=t["text"])
        self.text.tag_config("system", foreground=t["muted"])

        # Input: neon border frame + entry + accent send button
        inner = tk.Frame(input_frame, bg=t["panel2"])
        inner.pack(fill="x")
        self.entry = tk.Entry(inner, font=("Segoe UI", 12), bg=t["panel2"], fg=t["text"],
                              insertbackground=t["accent"], relief="flat")
        self.entry.pack(side="left", fill="x", expand=True, ipady=10, padx=12)
        self.entry.bind("<Return>", lambda e: self.on_send())
        self.entry.focus_set()
        self._btn(inner, "SEND  ➤", self.on_send, accent=True).pack(side="right", padx=6, pady=6)

    def switch_theme(self):
        self.theme_idx = (self.theme_idx + 1) % len(THEME_NAMES)
        name = THEME_NAMES[self.theme_idx]
        self.append("system", f"Theme switched to {name}. Restart the GUI to apply the full new palette everywhere — the core and pills already use it on next redraw.")
        # Core colours update live on the next animation frame:
        self.t = THEMES[name]
        self.root.configure(bg=self.t["bg"])

    # ------------------------------------------------ hardware monitor
    def _start_hardware_monitor(self):
        """Background thread: read sensors every ~2 s, post results
        to the main thread. Cheap calls only; any failure leaves
        the panel showing its last values (or '—')."""
        if hardware_monitor is None or getattr(self, "_hw_running", False):
            if hardware_monitor is None:
                try:
                    self._hw_note_label.config(
                        text="Hardware monitoring unavailable "
                             "(hardware_monitor.py missing).")
                except Exception:
                    pass
            return
        self._hw_running = True

        def _loop():
            while getattr(self, "_hw_running", False):
                try:
                    result = hardware_monitor.read_all()
                    self._post_ui(
                        lambda r=result: self._update_hardware_labels(r))
                except Exception:
                    pass
                time.sleep(2.0)

        threading.Thread(target=_loop, daemon=True).start()

    def _update_hardware_labels(self, result):
        """Main thread only: fill the Hardware panel from one
        hardware_monitor.read_all() snapshot."""
        if hardware_monitor is None:
            return
        try:
            for label_text, key, unit, dec, fmt in self._hw_rows:
                lbl = self._hw_value_labels.get(key)
                if lbl is not None:
                    if fmt == "pump":
                        text = hardware_monitor.format_pump(result)
                    elif fmt == "ram":
                        text = hardware_monitor.format_ram(result)
                    elif fmt == "net":
                        text = hardware_monitor.format_net(result)
                    else:
                        text = hardware_monitor.format_value(
                            result.get(key), unit, decimals=dec)
                    lbl.config(text=text)
            notes = result.get("notes") or []
            gpu_name = result.get("gpu_name")
            note_text = ""
            if gpu_name:
                note_text = gpu_name + "\n"
            if notes:
                note_text += "\n".join(notes)
            self._hw_note_label.config(text=note_text)
        except Exception:
            pass

    def _tick_clock(self):
        try:
            self.clock_label.config(text=datetime.now().strftime("%H:%M  •  %a %d %b"))
        except Exception:
            pass
        # Watchdog: if a reply thread started >120 s ago and busy is
        # still True, the THINKING state is stuck — reset it visibly
        # instead of ignoring every later speak/type forever.
        try:
            if self.busy and self._ask_started is not None:
                elapsed = (datetime.now() - self._ask_started).total_seconds()
                if elapsed > 120:
                    self.busy = False
                    self._ask_started = None
                    self.mode = "idle"
                    self.status.config(text="● ONLINE", fg=self.t["good"])
                    self.append("system", "That reply timed out after 120 seconds, so I reset and I'm ready again. Please try once more.")
                    self._log_listening("WATCHDOG: stuck THINKING reset after 120s")
        except Exception:
            pass
        self.root.after(1000, self._tick_clock)

    # ------------------------------------------------------------ avatar
    # PERSONAL Windows avatar (Lorenza, 2026-11-24 23:00 EST): the
    # pencil drawing of her adult daughter — childhood portrait,
    # signed ELM 2024. File: avatars/pencil-avatar-orb.jpg (410x409
    # head-and-shoulders orb crop). The red-and-black anime avatar
    # (assets/avatar.png, source workspace/avatars/
    # avatar-1795504357733091975-0.webp) stays the Mac/sale avatar
    # and is the fallback here if the drawing is missing — do NOT
    # delete the anime file. PERSONAL WINDOWS BUILD ONLY: the
    # drawing must never ship in the Mac or sale builds.
    # The pencil file is already a head-and-shoulders square crop,
    # so it is used at native size with a circular mask (the orb
    # framing) instead of the anime's (430, 0, 1170, 680) crop.
    # In the orb crop the eyes sit at (178, 156) and (241, 158) and
    # the open-smile mouth at (209, 209) — see avatar_deform.py
    # "pencil" profile, re-measured from the file itself.
    #
    # RULE (Lorenza, 2026-11-24 22:31 EST): NEVER draw an animated
    # mouth/blink layer ON TOP of the frozen avatar image — that fake
    # overlay is banned. The v1.0.9 lips/blink overlays are GONE.
    # The image ITSELF is animated instead: avatar_deform.py warps
    # the mouth and eye regions of the image's own pixels, and
    # nod/bob/tilt/look move the whole image as one piece. The drawn
    # fallback head (no image loaded) is vector art whose mouth IS a
    # real shape — that is a permitted approach, and the only place
    # lips.py is still used. Do not claim the avatar's lips move
    # until Lorenza herself says so.
    def _load_avatar(self):
        if Image is None or ImageTk is None:
            print("Avatar: Pillow not available, using drawn head fallback.")
            return
        # (relative path, profile, render size, crop box or None,
        #  circular mask?). The pencil drawing is tried first — it is
        # this personal build's avatar; the anime is the fallback.
        candidates = (
            ("avatars/pencil-avatar-orb.jpg", "pencil", (410, 409),
             None, True),
            ("assets/avatar.png", "anime", (420, 386),
             (430, 0, 1170, 680), False),
            ("avatar.png", "anime", (420, 386),
             (430, 0, 1170, 680), False),
            ("assets/avatar.webp", "anime", (420, 386),
             (430, 0, 1170, 680), False),
        )
        for rel, profile, size, crop, circular in candidates:
            path = RESOURCE_DIR / rel
            if not path.exists():
                continue
            try:
                img = Image.open(path).convert("RGBA")
                if crop is not None:
                    img = img.crop(crop)
                img = img.resize(size, Image.LANCZOS)
                try:
                    from PIL import ImageEnhance as _IE
                    img = _IE.Sharpness(img).enhance(1.25)
                    img = _IE.Contrast(img).enhance(1.05)
                except Exception:
                    pass
                if circular:
                    # Orb framing: inscribed circle so the drawing
                    # sits as a round portrait on the dark console
                    # (the paper corners are background, not face).
                    # The full orb (glow/pulse states) is separate
                    # queued work; this is only the shape.
                    try:
                        from PIL import ImageDraw as _ID
                        mask = Image.new("L", img.size, 0)
                        _d = _ID.Draw(mask)
                        _d.ellipse((2, 2, img.size[0] - 2,
                                    img.size[1] - 2), fill=255)
                        img.putalpha(mask)
                    except Exception:
                        pass
                self.avatar_w, self.avatar_h = size
                self._avatar_profile = profile
                self._avatar_pil = img
                self.avatar_photo = ImageTk.PhotoImage(img)
                print(f"Avatar: loaded {rel} ({profile}, "
                      f"{self.avatar_w}x{self.avatar_h})")
                return
            except Exception as e:
                print(f"Avatar: could not load {rel} ({e}), trying next.")
        print("Avatar: no avatar image found, using drawn head fallback.")

    @staticmethod
    def _rot(x, y, cx, cy, deg):
        """Rotate point (x, y) around (cx, cy) by deg degrees — used
        to tilt the fallback vector head's features with the head tilt."""
        r = math.radians(deg)
        dx, dy = x - cx, y - cy
        return (cx + dx * math.cos(r) - dy * math.sin(r),
                cy + dx * math.sin(r) + dy * math.cos(r))

    def _draw_lips(self, c, cx, cy, half_w, smile=0.0, tags=None):
        """Real lips (lips.py) — ONLY for the drawn fallback vector
        head, whose mouth IS a real shape of the drawing. NEVER call
        this over the avatar image: drawing lips on top of the frozen
        image is the banned overlay (Lorenza, 2026-11-24 22:31 EST).
        level/shape come from the eased speech state; when not
        speaking the lips are closed (thin line, no dark hole)."""
        if lips_mod is None:
            return
        level = self.lip_level if self.mode == "speaking" else 0.0
        shape = self._lip_shape if self.mode == "speaking" else "closed"
        try:
            for op in lips_mod.lip_ops(half_w, level, shape, smile=smile):
                if op[0] == "poly":
                    pts = [(cx + x, cy + y) for (x, y) in op[1]]
                    kw = {"smooth": True, "fill": op[2], "outline": ""}
                    if tags is not None:
                        kw["tags"] = tags
                    c.create_polygon(pts, **kw)
                elif op[0] == "line":
                    pts = [(cx + x, cy + y) for (x, y) in op[1]]
                    kw = {"fill": op[2], "width": op[3], "smooth": True}
                    if tags is not None:
                        kw["tags"] = tags
                    c.create_line(pts, **kw)
        except Exception:
            pass

    def _draw_avatar(self, c, hx, hy, look_x, look_y, anim=None):
        """Draw the avatar image at (hx, hy) — the IMAGE itself is
        animated, never an overlay on top of it (Lorenza, 2026-11-24
        22:31 EST: a blink/mouth layer drawn over the frozen image
        looked fake and is banned). avatar_deform.deform_avatar
        warps the image's own mouth/eyes and rotates the whole head;
        bob/sway/look move the image as one piece via its canvas
        position. ``anim`` is the avatar_anim frame dict (or None):
        blink is a 0..1 eyelid closure at human timing (never a fixed
        metronome), tilt turns the whole head, smile lifts the lip
        corners of the image itself.
        """
        tilt = (anim or {}).get("tilt_deg", 0.0)
        smile = (anim or {}).get("smile", 0.0)
        blink = (anim or {}).get("blink", 0.0)
        if (avatar_deform_mod is not None
                and getattr(self, "_avatar_pil", None) is not None):
            try:
                # mouth_closed (pencil only): while speaking, a low
                # level compresses the drawn grin into a thin smile
                # and a high level stretches it open — the visible
                # close/open cycle (v1.0.10 fix, item 2). At rest
                # the portrait is untouched (closed = 0).
                frame = avatar_deform_mod.deform_avatar(
                    self._avatar_pil,
                    mouth_open=self.lip_level if self.mode == "speaking" else 0.0,
                    mouth_shape=self._lip_shape if self.mode == "speaking" else "closed",
                    mouth_closed=(1.0 - self.lip_level) if self.mode == "speaking" else 0.0,
                    blink=blink, look_x=look_x,
                    tilt_deg=tilt, smile=smile,
                    profile=getattr(self, "_avatar_profile", "anime"))
                photo = ImageTk.PhotoImage(frame)
                # Keep a reference: tkinter drops images with no ref.
                self._avatar_deformed_photo = photo
                c.create_image(hx + look_x, hy + look_y, image=photo)
                return
            except Exception:
                pass
        # Fallback (deformer unavailable): the plain image, still
        # moving as one piece — never a drawn-on mouth or blink.
        c.create_image(hx + look_x, hy + look_y, image=self.avatar_photo)


    # ------------------------------------------------------------ chat
    def append(self, who, msg):
        self.text.configure(state="normal")
        prefix = {"oracle": f"{AGENT_NAME}: ", "user": "You: ", "system": ""}[who]
        self.text.insert("end", prefix + msg + "\n\n", who)
        self.text.configure(state="disabled")
        self.text.see("end")

    # ------------------------------------------------------------ animation
    def animate(self):
        self.phase += 0.12
        # Ease the mouth towards the live speech level (v1.0.6):
        # fast attack, gentle release, so it tracks speech smoothly
        # and settles back to closed instead of snapping shut.
        target = self._lip_target_level if self.mode == "speaking" else 0.0
        self.lip_level += (target - self.lip_level) * (0.45 if target > self.lip_level else 0.25)
        if abs(target - self.lip_level) < 0.01:
            self.lip_level = target
        t = self.t
        c = self.canvas
        try:
            w = c.winfo_width() or 800
            h = 480
        except Exception:
            w, h = 800, 300
        cx, cy = w // 2, 210
        c.delete("all")

        # Starfield
        for sx, sy, s in self.stars:
            x = (sx * w + self.phase * 0.4) % w
            y = sy * h
            c.create_oval(x, y, x + s, y + s, fill=t["muted"], outline="")

        # Scanning line
        scan_y = (self.phase * 6) % h
        c.create_line(0, scan_y, w, scan_y, fill=_darken(t["accent"], 0.35), width=1)

        # --- Animated AI head, Gideon-inspired, original vector art ---
        # No ring anymore: the head IS the face. It breathes, bobs,
        # blinks at human timing, looks around, nods, tilts, and the
        # avatar IMAGE itself deforms while speaking (v1.0.9 fix:
        # the old mouth/blink overlay drawn over the frozen image is
        # banned — Lorenza, 2026-11-24 22:31 EST). The motion comes
        # from avatar_anim.AvatarAnimator — reproduced observable
        # behaviour, not copied Muse source (there is none to copy).
        now = time.time()
        dt = max(0.0, min(0.1, now - getattr(self, "_anim_last_t", now)))
        self._anim_last_t = now
        anim = None
        if getattr(self, "_animator", None) is not None:
            try:
                self._animator.set_mode(self.mode)
                anim = self._animator.frame(now, lip_level=self.lip_level)
            except Exception:
                anim = None
        if anim is not None:
            bob = anim["bob_y"]
            sway = anim["sway_x"]
            look_x = anim["look_x"]
            look_y = anim["look_y"]
            lean = anim["lean"]
            shrug = anim.get("shrug", 0.0)
            wave = anim.get("wave", 0.0)
            tilt = anim["tilt_deg"]
            smile = anim["smile"]
            blink = anim["blink"]
            brow_l = anim["brow_l"]
            brow_r = anim["brow_r"]
            eye_wide = anim["eye_wide"]
        else:  # fallback if the animator module is missing
            bob = math.sin(self.phase * 0.6) * 3
            sway, look_x, lean, tilt, smile = 0.0, math.sin(self.phase * 0.35) * 6, 0.0, 0.0, 0.0
            shrug = wave = 0.0
            look_y = -5 if self.mode == "thinking" else 0
            # No metronome blink here: without the animator there is
            # no human-timing blink source, and a fixed-rhythm blink
            # is worse than eyes open.
            blink = 0.0
            brow_l = brow_r = -6 if self.mode == "thinking" else 0.0
            eye_wide = 0.0
        # Shrug lifts the whole image a few px (shoulders rise);
        # a wave sways it gently side to side. Both move the image
        # as one piece — nothing is drawn over it. A literal hand
        # wave is impossible on a bust image with no visible hand,
        # so the greeting is this warm sway + smile instead.
        wave_sway = wave * math.sin(self.phase * 2.0) * 10.0
        hx, hy = cx + sway + wave_sway, cy - 12 + bob + lean * 3 - shrug * 6

        # Soft aura behind the head (glow, not a ring)
        for r, col in [(178, _darken(t["accent"], 0.18)), (142, _darken(t["accent"], 0.28)),
                       (113, _darken(t["accent2"], 0.35))]:
            c.create_oval(hx - r, hy - r * 0.9, hx + r, hy + r * 0.9, fill=col, outline="")

        # --- The face: Muse avatar image if loaded, else vector head ---
        if self.avatar_photo is not None:
            self._draw_avatar(c, hx, hy, look_x, look_y, anim=anim)
        else:
            # Neck and shoulders
            c.create_polygon(hx - 30, hy + 92, hx + 30, hy + 92,
                             hx + 48, hy + 128, hx - 48, hy + 128,
                             fill=t["panel2"], outline=t["accent"], width=1)
            c.create_line(hx - 48, hy + 128, hx + 48, hy + 128, fill=t["accent"], width=2)

            # Head silhouette: forehead wide, jaw narrowing to a chin
            head_pts = [
                (hx - 62, hy - 55), (hx - 48, hy - 88), (hx, hy - 98), (hx + 48, hy - 88),
                (hx + 62, hy - 55), (hx + 58, hy + 10), (hx + 42, hy + 62),
                (hx + 16, hy + 90), (hx - 16, hy + 90), (hx - 42, hy + 62),
                (hx - 58, hy + 10),
            ]
            c.create_polygon(head_pts, smooth=True, fill=t["panel2"],
                             outline=t["accent"], width=2)
            # Forehead circuit detail
            c.create_line(hx - 22, hy - 68, hx + 22, hy - 68, fill=_darken(t["accent"], 0.6), width=1)
            c.create_oval(hx - 3, hy - 71, hx + 3, hy - 65, fill=t["accent2"], outline="")

            # Side nodes (ears / sensors)
            for sx in (-70, 70):
                c.create_oval(hx + sx - 7, hy + 5, hx + sx + 7, hy + 19,
                              fill=t["panel"], outline=t["accent"], width=1)

            # Eyes: blink closure from the animator (human timing),
            # pupils follow the wandering gaze, brows lift per state
            # (thinking: left brow up; surprise: both up; laugh: squint).
            eye_h = max(2, int(20 * (1.0 - blink) + eye_wide * 5))
            for ex, brow in ((-34, brow_l), (34, brow_r)):
                eye_cx, eye_cy = self._rot(hx + ex, hy - 18 + look_y,
                                           hx, hy, tilt)
                c.create_oval(eye_cx - 19, eye_cy - eye_h, eye_cx + 19, eye_cy + eye_h,
                              fill=t["accent"], outline="")
                if blink < 0.6:
                    c.create_oval(eye_cx - 7 + look_x * 0.4, eye_cy - 7,
                                  eye_cx + 7 + look_x * 0.4, eye_cy + 7,
                                  fill="#04121a", outline="")
                    c.create_oval(eye_cx - 2 + look_x * 0.4, eye_cy - 4,
                                  eye_cx + 2 + look_x * 0.4, eye_cy, fill="#ffffff", outline="")
                # Eyebrow (tilts with the head, lifts per expression)
                bx1, by1 = self._rot(eye_cx - 20, eye_cy - 28 + brow,
                                     hx, hy, tilt)
                bx2, by2 = self._rot(eye_cx + 20, eye_cy - 28 + brow,
                                     hx, hy, tilt)
                c.create_line(bx1, by1, bx2, by2,
                              fill=t["accent2"], width=2)

            # Mouth: the fallback head is vector art, so its mouth IS
            # a real shape of the drawing (a permitted approach —
            # no image here, nothing is overlaid on anything).
            # Thinking: a straight lip line. Idle: a smile arc
            # when happy, else the usual slight smile.
            mouth_cx, mouth_cy = self._rot(hx, hy + 48, hx, hy, tilt)
            if self.mode == "speaking":
                self._draw_lips(c, mouth_cx, mouth_cy, 16, smile=smile)
            elif self.mode == "thinking":
                c.create_line(mouth_cx - 18, mouth_cy, mouth_cx + 18, mouth_cy, fill=t["accent"], width=3)
            elif smile > 0.3:
                c.create_arc(mouth_cx - 26, mouth_cy - 12, mouth_cx + 26, mouth_cy + 14,
                             start=200, extent=140, outline=t["accent"], width=3, style="arc")
            else:
                c.create_arc(mouth_cx - 26, mouth_cy - 12, mouth_cx + 26, mouth_cy + 14,
                             start=200, extent=140, outline=t["accent"], width=2, style="arc")

        # Waveform — bars follow the real speech level while speaking
        bars = 52
        for i in range(bars):
            x = cx - 260 + i * 10
            falloff = 1 - abs(i - 26) / 32
            if self.mode == "speaking":
                bh = (10 + self.lip_level * 55 + random.uniform(0, 6)) * falloff
            elif self.mode == "thinking":
                bh = 14 + abs(math.sin(self.phase + i * 0.4)) * 26 * falloff
            else:
                bh = 8 + abs(math.sin(self.phase * 0.5 + i * 0.3)) * 12 * falloff
            col = t["accent"] if i % 2 == 0 else t["accent2"]
            c.create_line(x, cy + 210, x, cy + 210 - bh, fill=col, width=4)

        # Mode text on canvas
        label = {"idle": "IDLE  •  AWAITING INPUT",
                 "listening": "LISTENING  •  HEARING YOU",
                 "thinking": "THINKING  •  PROCESSING",
                 "speaking": "SPEAKING  •  RESPONDING"}.get(self.mode, "IDLE")
        try:
            self.mode_label.config(text=f"—  {label}  —",
                                   fg=t["warn"] if self.mode == "thinking" else t["accent"])
        except Exception:
            pass
        self.root.after(33, self.animate)  # ~30 fps for smooth lip-sync

    # ------------------------------------------------------------ speech / lip-sync
    def _react_to_reply(self, kind, confused):
        """Main thread: start a laugh / surprise / happy / shrug /
        wave reaction, and set or clear the standing 'confused'
        expression."""
        if getattr(self, "_animator", None) is not None:
            try:
                if kind:
                    self._animator.react(kind)
                self._animator.set_confused(confused)
            except Exception:
                pass

    def _on_speech_level(self, level, shape):
        """Called from voice.py's playback thread. NEVER touch
        tkinter here — just store the target; animate() (main
        thread) eases towards it."""
        self._lip_target_level = max(0.0, min(1.0, float(level)))
        self._lip_shape = shape if shape in ("closed", "slight", "open", "wide", "round", "fv") else "open"

    def _on_speech_done(self):
        """Called on the main thread when the spoken reply ends."""
        self._speech_done = True
        self._lip_target_level = 0.0
        self._lip_shape = "closed"
        self._maybe_finish_speaking()

    def interrupt_speaking(self, source="button"):
        """Stop Oracle mid-reply, NOW — from the Stop button, the Esc
        key, or a spoken "stop" / "shut up" / "be quiet" (item 3,
        2026-11-25, Lorenza: she must be able to cut it off when it
        is long-winded). Must run on the main thread (button / key
        callbacks already do; the listen loop routes here via
        _post_ui). Does three things at once:
          1. TTS playback stops: voice.stop_speaking() sets the stop
             event the playback loop checks every ~23 ms chunk, and
             stops SAPI too — audio is gone within a fraction of a
             second, and no queued speech resumes (speak() checks
             the event before every chunk and every sentence pause).
          2. The reply stops generating/typing: the token bump makes
             _ask discard a reply still being generated and makes
             _typewriter abort its chain, so nothing more is typed
             or spoken from that reply.
          3. The GUI goes back to idle at once, mouth closed.
        Safe to call when nothing is speaking (a stray Esc / "stop"
        while idle just stays idle)."""
        self._reply_token += 1
        try:
            if voice_mod is not None:
                voice_mod.stop_speaking()
        except Exception:
            pass
        # Blackout the mic for 3 s after the stop (see __init__):
        # the stopped TTS tail is still in the air, and anything
        # the listener picks up in that window is echo, not Lorenza.
        try:
            self._interrupt_until = time.monotonic() + 3.0
        except Exception:
            pass
        self._lip_target_level = 0.0
        self._lip_shape = "closed"
        self.lip_level = 0.0
        self._typing_done = True
        self._speech_done = True
        was_busy = self.busy
        self.busy = False
        self.mode = "idle"
        self._ask_started = None
        try:
            self.status.config(text="● ONLINE", fg=self.t["good"])
        except Exception:
            pass
        if was_busy:
            try:
                self._log_listening(f"INTERRUPTED ({source}): speech stopped, reply discarded")
            except Exception:
                pass
            self.append("system", "Stopped.")

    def _maybe_finish_speaking(self):
        """Only go back to IDLE (and clear busy) once BOTH the reply
        has finished typing AND the voice has finished speaking — the
        old code went idle as soon as typing finished, while the
        voice was still talking."""
        if self._typing_done and self._speech_done and self.busy:
            self.mode = "idle"
            self.busy = False
            self._ask_started = None
            try:
                self.status.config(text="● ONLINE", fg=self.t["good"])
            except Exception:
                pass

    # ------------------------------------------------------------ API keys (v1.0.6 OpenAI; 2026-11-24 +ElevenLabs, +spare)
    # Three rows, same rules for all: masked, validated BEFORE saving
    # (a bad key never overwrites a good one), saved on this PC only
    # (Windows User env vars), active at once, no reinstall. The key
    # value is never shown or logged — only SET / NOT SET + last 4.
    _KEY_SERVICES = {
        "openai": {"env": "OPENAI_API_KEY", "name": "OpenAI"},
        "elevenlabs": {"env": "ELEVENLABS_API_KEY", "name": "ElevenLabs"},
        "extra": {"env": "ORACLE_EXTRA_API_KEY", "name": "extra"},
    }

    @staticmethod
    def _key_status_text_for(key):
        """Masked status for one key value: never shows the key."""
        if not key:
            return "NOT SET"
        return f"SET  •  ****…{key[-4:]}"

    def _api_key_status_text(self):
        """OpenAI row, with the 'Key: ' prefix the dialog expects."""
        return "Key: " + self._key_status_text_for(
            os.environ.get("OPENAI_API_KEY", ""))

    def _refresh_key_labels(self):
        """Refresh all three key rows (and the spare row's name)."""
        try:
            for service, cfg in self._KEY_SERVICES.items():
                self._key_labels[service].config(
                    text=self._key_status_text_for(
                        os.environ.get(cfg["env"], "")))
            if self._extra_name_label is not None:
                self._extra_name_label.config(text=self._extra_key_label())
        except Exception:
            pass

    def _refresh_api_key_label(self):
        try:
            self.api_key_label.config(text=self._api_key_status_text())
        except Exception:
            pass

    def _extra_key_label(self):
        """Editable plain label for the spare slot (default 'Extra key')."""
        try:
            from oracle_paths import get_setting
            label = (get_setting("extra_key_label", "") or "").strip()
        except Exception:
            label = ""
        return label or "Extra key"

    def _rename_extra_key(self):
        """Rename the spare slot (the label, not the key)."""
        import tkinter.simpledialog as sd
        new_label = sd.askstring(
            "Rename extra key",
            "What should this spare key slot be called?\n(e.g. the name of the service it is for)",
            initialvalue=self._extra_key_label())
        if new_label is None:
            return
        new_label = (new_label or "").strip()
        if not new_label:
            self.append("system", "The extra key slot still needs a name — keeping the old one.")
            return
        try:
            from oracle_paths import set_setting
            set_setting("extra_key_label", new_label)
        except Exception as e:
            self.append("system", f"Could not save that name: {e}")
            return
        self._refresh_key_labels()
        self.append("system", f"Spare key slot renamed to {new_label!r}.")

    def _voice_engine_display(self):
        """Display label for the saved voice engine."""
        if voice_mod is None:
            return "OpenAI (nova)"
        try:
            return voice_mod.VOICE_ENGINE_LABELS.get(
                voice_mod.get_voice_engine(), "OpenAI (nova)")
        except Exception:
            return "OpenAI (nova)"

    def _on_voice_engine_change(self, display):
        """VOICE-card engine picker. ElevenLabs without its key is
        refused with a plain message and the engine stays put."""
        if voice_mod is None:
            return
        engine = None
        for eng, label in voice_mod.VOICE_ENGINE_LABELS.items():
            if label == display:
                engine = eng
                break
        if engine is None:
            return
        if engine == "elevenlabs" and not os.environ.get("ELEVENLABS_API_KEY", ""):
            self.append("system", "ElevenLabs needs its key first — add it in the API KEYS card (ElevenLabs row), then pick ElevenLabs here. Staying on the current voice for now.")
            try:
                self.voice_engine_var.set(self._voice_engine_display())
            except Exception:
                pass
            return
        try:
            voice_mod.set_voice_engine(engine)
        except Exception as e:
            self.append("system", f"Could not save the voice choice: {e}")
            try:
                self.voice_engine_var.set(self._voice_engine_display())
            except Exception:
                pass
            return
        self.append("system", f"Voice engine: {voice_mod.VOICE_ENGINE_LABELS[engine]}. It speaks with the next reply.")

    def _keys_log_line(self):
        """SET / NOT SET for all three keys — values never included."""
        parts = []
        for service, cfg in self._KEY_SERVICES.items():
            state = "SET" if os.environ.get(cfg["env"], "") else "NOT SET"
            parts.append(f"{cfg['name'] if service != 'extra' else self._extra_key_label()} {state}")
        return "KEYS: " + ", ".join(parts)

    # ------------------------------------------------------------ memory (v1.0.7)
    # Muse conversation memory: import files Lorenza provides, keep
    # them in memory.json next to Oracle.exe, and feed them to the
    # brain in every reply. Local only — nothing here ever leaves
    # this PC (see MEMORY_SHARING.md).
    def _refresh_memory_label(self):
        try:
            if memory_import is None:
                text = "Remembered: unavailable"
            else:
                text = f"Remembered: {memory_import.memory_count(APP_DIR)} facts"
            self.memory_label.config(text=text)
        except Exception:
            pass

    def _memory_startup(self):
        """Auto-import any Muse exports dropped in memory_import/,
        then one short chat line about what Oracle remembers.
        Runs on the main thread at startup; the files are small."""
        if memory_import is None:
            self.append("system", "Memory import is unavailable (memory_import.py missing) — I only know what is in this chat.")
            return
        try:
            new_count, files = memory_import.auto_import(APP_DIR)
            total = memory_import.memory_count(APP_DIR)
        except Exception as e:
            self.append("system", f"Memory auto-import failed: {e}")
            return
        self._refresh_memory_label()
        if new_count:
            self.append("system", f"Memory: {new_count} new fact(s) remembered from Muse conversations ({len(files)} file(s): {', '.join(files)}). {total} facts remembered in total. Use Memory > Import to add more.")
        elif total:
            self.append("system", f"Memory: {total} facts remembered from Muse conversations and my own memory. Use Memory > Import to add more.")
        else:
            self.append("system", "Memory: nothing remembered yet. Drop a Muse chat export (.md / .json / .txt) in the memory_import folder next to Oracle.exe, or use Memory > Import Muse memory… — I will remember it from then on.")

    def _import_memory_file(self):
        """File dialog -> import in a worker thread -> label + chat line."""
        if memory_import is None:
            self.append("system", "Memory import is unavailable (memory_import.py missing).")
            return
        import tkinter.filedialog as fd
        path = fd.askopenfilename(
            title="Import Muse memory — pick a chat export",
            filetypes=[("Muse exports", "*.md *.json *.txt"),
                       ("Markdown", "*.md"), ("JSON", "*.json"),
                       ("Text", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        self.append("system", f"Importing {Path(path).name}…")
        def _run():
            try:
                new_count = memory_import.import_file(path, APP_DIR)
                total = memory_import.memory_count(APP_DIR)
            except Exception as e:
                self._post_ui(lambda err=e: self.append("system", f"Import failed: {err}"))
                return
            def _done():
                self._refresh_memory_label()
                name = Path(path).name
                if new_count:
                    self.append("system", f"Imported {new_count} new fact(s) from {name} — {total} facts remembered in total.")
                else:
                    self.append("system", f"No new facts from {name} — it was already imported, or everything in it I already knew. To add more, drop Muse chat exports (.md / .json / .txt) in the memory_import folder next to Oracle.exe and restart me, or use this Import button again with another export.")
            self._post_ui(_done)
        threading.Thread(target=_run, daemon=True).start()

    def _show_memory_summary(self):
        """Post a short grouped summary of the stored facts in chat."""
        if memory_import is None:
            self.append("system", "Memory import is unavailable (memory_import.py missing).")
            return
        try:
            lines = memory_import.memory_summary_lines(APP_DIR, max_lines=40)
        except Exception as e:
            self.append("system", f"Could not read memory: {e}")
            return
        self.append("system", "What I remember about Lorenza:\n" + "\n".join(lines))

    def _forget_memory_gui(self):
        """'Forget that' control: remove stored facts containing
        the words she types. Local only, immediate, and the memory
        label refreshes to the new count."""
        if continuous_memory is None and memory_import is None:
            self.append("system", "Memory is unavailable (memory_import.py missing).")
            return
        import tkinter.simpledialog as sd
        what = sd.askstring("Forget that",
                            "What should I forget? (any words from the memory)")
        if not what:
            return
        try:
            n = (continuous_memory.forget_matching(APP_DIR, what)
                 if continuous_memory is not None else 0)
        except Exception as e:
            self.append("system", f"Could not forget that: {e}")
            return
        self._refresh_memory_label()
        if n:
            self.append("system",
                        f"Forgot {n} {'memory' if n == 1 else 'memories'} "
                        f"matching {what!r}.")
        else:
            self.append("system", f"Nothing in memory matched {what!r}.")

    def _set_data_drive_gui(self):
        """Point Oracle at a dedicated data drive (2026-11-24):
        pick a folder on the new drive (e.g. D:\\OracleData) and
        memory.json, memory_import/, alerts/, logs, face profiles
        and get-to-know-you profiles live there instead of next to
        Oracle.exe. The choice is saved in oracle_settings.json
        next to the exe and takes effect on the NEXT restart —
        this session keeps using the current data dir. Picking the
        folder next to the exe again removes the dedicated drive.
        Nothing is moved automatically: existing memory stays where
        it is until it is copied over (the worker does that step
        on the PC)."""
        try:
            from oracle_paths import set_data_dir as _set_data_dir
            from oracle_paths import exe_dir as _exe_dir
        except Exception:
            self.append("system", "Data-drive setting is unavailable (oracle_paths.py missing).")
            return
        import tkinter.filedialog as fd
        # Default folder: J:\Oracle-Memory — Lorenza's dedicated
        # Oracle AI memory drive (2026-11-24 decision: J: is being
        # emptied — its old contents moved to H:\From-J\ — and
        # becomes the memory drive; NOT a new drive purchase). Only
        # offered as the starting folder when it actually exists on
        # this PC; the worker must not point anything at J: until
        # the move worker confirms J: is empty.
        _default_dir = str(APP_DIR)
        try:
            if os.path.isdir(r"J:\Oracle-Memory"):
                _default_dir = r"J:\Oracle-Memory"
        except Exception:
            pass
        chosen = fd.askdirectory(
            title="Choose the Oracle data folder (on the dedicated drive)",
            initialdir=_default_dir)
        if not chosen:
            return
        try:
            new_dir = _set_data_dir(chosen)
        except Exception as e:
            self.append("system", f"Could not use that folder as the data drive: {e}")
            return
        try:
            self._data_dir_label.config(text=f"Data: {new_dir} (after restart)")
        except Exception:
            pass
        if str(new_dir) == str(_exe_dir()):
            self.append("system",
                        "Data drive cleared — Oracle will keep its data next "
                        "to Oracle.exe after a restart.")
        else:
            self.append("system",
                        f"Data drive set to {new_dir}. Restart Oracle to use "
                        f"it — memory, alerts, logs and profiles will live "
                        f"there from then on. BEFORE restarting, carry the "
                        f"memory over so nothing is lost: copy memory.json "
                        f"AND the memory_import/ folder to {new_dir} (the "
                        f"728 imported Muse facts travel with it — the "
                        f"source build should still report 729 remembered "
                        f"facts after the move, the installed build 728). "
                        f"Do not start from zero on the new drive.")

    @staticmethod
    def _strip_key_prefix(text):
        """Accept a pasted `NAME=key` line as well as a bare key.
        Strips a known env-var prefix and surrounding quotes."""
        s = (text or "").strip()
        if "=" in s:
            name, _, rest = s.partition("=")
            if name.strip().upper() in ("OPENAI_API_KEY", "OPENAI_KEY",
                                        "ELEVENLABS_API_KEY",
                                        "ORACLE_EXTRA_API_KEY", "API_KEY"):
                s = rest.strip()
        return s.strip('"').strip("'").strip()

    @staticmethod
    def _validate_extra_key_format(key):
        """Format-only check for the spare slot, used when voice.py
        is unavailable. Same rule as voice.validate_extra_key."""
        k = (key or "").strip()
        if not k:
            return False, "no key entered."
        if any(c.isspace() for c in k):
            return False, "the key has whitespace in it — paste the bare key."
        if len(k) < 16:
            return False, "that looks too short for an API key (under 16 characters)."
        return True, "ok (format only — this slot has no service to check against yet)"

    def _show_api_key_dialog(self):
        """Backwards-compatible wrapper: the old 'Change API Key'
        button now opens the OpenAI row's dialog."""
        self._show_key_dialog("openai")

    def _show_key_dialog(self, service):
        """Change one API key (2026-11-24: three rows). Masked entry,
        validated BEFORE saving — a bad key never overwrites a good
        one — then saved as a Windows User env var on this PC only
        and used at once, no reinstall. The key value is never shown
        or logged."""
        service = service if service in self._KEY_SERVICES else "openai"
        cfg = self._KEY_SERVICES[service]
        env_name = cfg["env"]
        friendly = (self._extra_key_label() if service == "extra"
                    else cfg["name"])
        _help = {
            "openai": ("It is checked with a quick test call, then saved as a Windows\n"
                       "User environment variable on this PC only — never in source\n"
                       "code, logs, email, or GitHub. The running agent uses it at once."),
            "elevenlabs": ("It is checked live with ElevenLabs, then saved as a Windows\n"
                           "User environment variable on this PC only — never in source\n"
                           "code, logs, email, or GitHub. Pick ElevenLabs in the VOICE\n"
                           "card to speak with it. The running agent uses it at once."),
            "extra": ("A spare slot for any other service you name later. It is\n"
                      "checked for format only (there is no service to check\n"
                      "against yet), then saved as a Windows User environment\n"
                      "variable on this PC only. Rename it with 'Rename extra\n"
                      "key…' under the rows."),
        }[service]
        dlg = tk.Toplevel(self.root)
        dlg.title(f"Change {friendly} API Key")
        dlg.geometry("460x300" if service == "elevenlabs" else "460x260")
        dlg.transient(self.root)
        dlg.grab_set()
        tk.Label(dlg, text=f"Paste your new {friendly} API key below.",
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=16, pady=(14, 4))
        tk.Label(dlg, text=_help,
                 font=("Segoe UI", 9), justify="left").pack(anchor="w", padx=16, pady=(0, 8))
        entry = tk.Entry(dlg, font=("Segoe UI", 11), show="*", width=42)
        entry.pack(padx=16, fill="x")
        entry.focus_set()
        voice_entry = None
        if service == "elevenlabs":
            tk.Label(dlg, text="ElevenLabs voice ID (optional — blank uses Rachel):",
                     font=("Segoe UI", 9)).pack(anchor="w", padx=16, pady=(8, 2))
            voice_entry = tk.Entry(dlg, font=("Segoe UI", 10), width=42)
            try:
                current_vid = (voice_mod.get_elevenlabs_voice_id()
                               if voice_mod is not None else "")
            except Exception:
                current_vid = ""
            voice_entry.insert(0, current_vid)
            voice_entry.pack(padx=16, fill="x")
        status = tk.Label(dlg, text="Key: " + self._key_status_text_for(
            os.environ.get(env_name, "")),
            font=("Segoe UI", 9, "bold"))
        status.pack(anchor="w", padx=16, pady=(10, 4))
        btns = tk.Frame(dlg)
        btns.pack(padx=16, pady=8, fill="x")
        save_btn = tk.Button(btns, text="Save key", font=("Segoe UI", 10, "bold"))
        save_btn.pack(side="left", padx=(0, 8))
        tk.Button(btns, text="Cancel", font=("Segoe UI", 10),
                  command=dlg.destroy).pack(side="left")

        def _validate(new_key):
            if service == "elevenlabs":
                if voice_mod is None:
                    return False, "voice module unavailable — cannot check the key, so it was not saved."
                return voice_mod.validate_elevenlabs_key(new_key)
            if service == "extra":
                if voice_mod is not None:
                    return voice_mod.validate_extra_key(new_key)
                return self._validate_extra_key_format(new_key)
            return self._validate_api_key(new_key)

        def _do_save():
            new_key = self._strip_key_prefix(entry.get())
            if not new_key:
                status.config(text="Paste a key first.", fg="red")
                return
            save_btn.config(state="disabled")
            status.config(text="Validating the key…", fg="black")
            voice_id = (voice_entry.get().strip()
                        if voice_entry is not None else None)

            def _run():
                ok, msg = _validate(new_key)
                if not ok:
                    self._post_ui(lambda: self._key_failed(status, save_btn, msg))
                    return
                self._set_user_env_var(env_name, new_key)
                os.environ[env_name] = new_key
                if service == "elevenlabs" and voice_mod is not None and voice_id is not None:
                    try:
                        voice_mod.set_elevenlabs_voice_id(voice_id)
                    except Exception:
                        pass
                self._post_ui(lambda: self._key_saved(dlg, status, service, friendly))
            threading.Thread(target=_run, daemon=True).start()
        save_btn.config(command=_do_save)
        dlg.bind("<Return>", lambda _e: _do_save())

    def _key_saved(self, dlg, status, service, friendly):
        status.config(text="Key updated — the new key is active now.", fg="green")
        self._refresh_key_labels()
        self.append("system", f"{friendly} API key updated — the new key is active now. (The key itself is never shown here.)")
        self._log_listening(f"API KEY: {service} updated via GUI (key value not logged)")
        dlg.after(1200, dlg.destroy)

    def _key_failed(self, status, save_btn, msg):
        status.config(text=f"Key invalid — {msg}", fg="red")
        save_btn.config(state="normal")

    def _api_key_saved(self, dlg, status):
        self._key_saved(dlg, status, "openai", "OpenAI")

    def _api_key_failed(self, status, save_btn, msg):
        self._key_failed(status, save_btn, msg)

    @staticmethod
    def _validate_api_key(key):
        """Quick OpenAI test call. Returns (ok, message). The key
        value is never logged — only the HTTP outcome."""
        import json as _json
        import urllib.request as _url
        try:
            req = _url.Request(
                "https://api.openai.com/v1/chat/completions",
                data=_json.dumps({
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": "Reply with the single word Pineapple."}],
                    "max_tokens": 5,
                }).encode(),
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
            with _url.urlopen(req, timeout=25) as resp:
                data = _json.loads(resp.read())
            text = data["choices"][0]["message"]["content"].strip()
            if "pineapple" in text.lower():
                return True, "ok"
            return True, "ok (key accepted)"
        except Exception as e:
            return False, f"OpenAI rejected it ({e}). Check the key and try again."

    @staticmethod
    def _set_user_env_var(name, value):
        """Persist a User environment variable on Windows (HKCU\\
        Environment) and broadcast the change, so new processes see
        it. Falls back to process-only on other platforms."""
        if sys.platform.startswith("win"):
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment",
                                    0, winreg.KEY_SET_VALUE) as k:
                    winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
                try:
                    import ctypes
                    ctypes.windll.user32.SendMessageTimeoutW(
                        0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, None)
                except Exception:
                    pass
            except Exception as e:
                print(f"[gui] Could not persist {name} in registry: {e}")
        # Process-level, always:
        os.environ[name] = value

    # ------------------------------------------------------------ avatar-only mode (v1.0.6)
    def _on_unmap(self, event):
        """Minimise button -> avatar-only mode. Unmap also fires for
        other hides; only act when the window is actually iconic."""
        try:
            if event.widget is self.root and self.root.state() == "iconic" and not self._avatar_mode:
                self._enter_avatar_only()
        except Exception:
            pass

    def _enter_avatar_only(self):
        if self._avatar_mode:
            return
        self._avatar_mode = True
        try:
            self.root.withdraw()
        except Exception:
            pass
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-transparentcolor", "#000001")
        except Exception:
            pass
        win.geometry("440x450+200+200")
        self.avatar_win = win
        canvas = tk.Canvas(win, width=440, height=420, bg="#000001",
                           highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        self._avatar_canvas = canvas
        if self.avatar_photo is not None:
            self._avatar_only_img_id = canvas.create_image(
                220, 210, image=self.avatar_photo, tags="avatar")
        else:
            self._avatar_only_img_id = None
            canvas.create_oval(90, 48, 350, 370, fill=self.t["panel2"],
                               outline=self.t["accent"], width=2)
        restore = tk.Button(win, text="⤢  Restore full window",
                            font=("Segoe UI", 9, "bold"),
                            command=self._restore_from_avatar)
        restore.pack(fill="x")
        # Drag the avatar anywhere on the desktop; a plain click
        # (no drag) restores the full GUI.
        def _press(e):
            self._avatar_drag = (e.x_root, e.y_root, win.winfo_x(), win.winfo_y(), False)
        def _drag(e):
            if self._avatar_drag is None:
                return
            x0, y0, wx, wy, _moved = self._avatar_drag
            if abs(e.x_root - x0) > 5 or abs(e.y_root - y0) > 5:
                self._avatar_drag = (x0, y0, wx, wy, True)
            win.geometry(f"+{wx + e.x_root - x0}+{wy + e.y_root - y0}")
        def _release(_e):
            if self._avatar_drag is not None and not self._avatar_drag[4]:
                self._restore_from_avatar()
            self._avatar_drag = None
        canvas.bind("<Button-1>", _press)
        canvas.bind("<B1-Motion>", _drag)
        canvas.bind("<ButtonRelease-1>", _release)
        win.bind("<Button-3>", lambda _e: self._restore_from_avatar())
        # Esc stops Oracle mid-sentence here too (item 3).
        win.bind("<Escape>", lambda _e: self.interrupt_speaking("keyboard"))
        self._avatar_only_animate()

    def _avatar_only_animate(self):
        """Avatar-only mode: the avatar IMAGE itself animates — its
        own mouth opens/closes with speech, its own eyes blink, the
        whole image bobs as one piece. No overlay is ever drawn over
        it (Lorenza, 2026-11-24 22:31 EST — the overlay is banned)."""
        if not self._avatar_mode or self.avatar_win is None:
            return
        try:
            target = self._lip_target_level if self.mode == "speaking" else 0.0
            self.lip_level += (target - self.lip_level) * (0.45 if target > self.lip_level else 0.25)
            c = self._avatar_canvas
            anim = None
            if getattr(self, "_animator", None) is not None:
                try:
                    self._animator.set_mode(self.mode)
                    anim = self._animator.frame(time.time(),
                                                lip_level=self.lip_level)
                except Exception:
                    anim = None
            if (avatar_deform_mod is not None
                    and getattr(self, "_avatar_pil", None) is not None
                    and getattr(self, "_avatar_only_img_id", None) is not None):
                try:
                    frame = avatar_deform_mod.deform_avatar(
                        self._avatar_pil,
                        mouth_open=self.lip_level if self.mode == "speaking" else 0.0,
                        mouth_shape=self._lip_shape if self.mode == "speaking" else "closed",
                        mouth_closed=(1.0 - self.lip_level) if self.mode == "speaking" else 0.0,
                        blink=(anim or {}).get("blink", 0.0),
                        look_x=(anim or {}).get("look_x", 0.0),
                        tilt_deg=(anim or {}).get("tilt_deg", 0.0),
                        smile=(anim or {}).get("smile", 0.0),
                        profile=getattr(self, "_avatar_profile", "anime"))
                    photo = ImageTk.PhotoImage(frame)
                    self._avatar_deformed_photo = photo
                    c.itemconfig(self._avatar_only_img_id, image=photo)
                    # Bob: the whole image moves as one piece.
                    c.coords(self._avatar_only_img_id, 220,
                             210 + (anim or {}).get("bob_y", 0.0))
                except Exception:
                    pass
            self.avatar_win.after(33, self._avatar_only_animate)
        except Exception:
            pass

    def _restore_from_avatar(self):
        if self.avatar_win is not None:
            try:
                self.avatar_win.destroy()
            except Exception:
                pass
            self.avatar_win = None
        self._avatar_mode = False
        try:
            self.root.deiconify()
            self.root.state("normal")
            self.root.focus_force()
        except Exception:
            pass

    # ------------------------------------------------------------ actions
    def toggle_speak(self):
        self.speak_replies = not self.speak_replies
        self.speak_btn.config(text=f"Speak replies: {'ON' if self.speak_replies else 'OFF'}")

    def _start_listening(self):
        """Turn always-listening ON: mic open, no wake word, listen
        thread running. Returns True when listening actually started."""
        if voice_mod is None:
            self.append("system", "Voice libraries are not installed. Run: pip install pyttsx3 SpeechRecognition PyAudio")
            self.always_listen = False
            self._log_listening("LISTENING FAILED: voice module not available")
            return False
        self.always_listen = True
        self.listen_btn.config(text="Always listen: ON", bg=self.t["danger"])
        self.listen_label.config(text="● LISTENING - mic is on")
        self.mic_pill.config(text="MIC: ON", fg=self.t["danger"])
        self.append("system", "Always listening is ON. I will respond to speech with no wake word. Tap the button again to pause it instantly.")
        self._log_listening("LISTENING STARTED: mic open, no wake word")
        if self.listen_thread is None or not self.listen_thread.is_alive():
            self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.listen_thread.start()
        return True

    def _stop_listening(self):
        self.always_listen = False
        self.listen_btn.config(text="Always listen: OFF", bg=self.t["panel2"])
        self.listen_label.config(text="")
        self.mic_pill.config(text="MIC: OFF", fg=self.t["muted"])
        self.append("system", "Always listening is OFF. Mic is no longer being transcribed.")
        self._log_listening("LISTENING STOPPED by user")

    def toggle_listen(self):
        if self.always_listen:
            self._stop_listening()
        else:
            self._start_listening()

    def _listen_loop(self):
        while self.always_listen:
            if self.busy:
                if voice_mod is None:
                    time.sleep(0.5)
                    continue
                # While a reply is speaking, the mic stays open ONLY
                # for interrupt phrases (item 3): the old code slept
                # through the whole reply, so "stop" / "shut up"
                # could never be heard mid-speech. Short listen
                # cycles (2 s wait, 4 s phrase) keep the ear open;
                # anything that is not a short interrupt phrase is
                # ignored, never answered. Honest limit: this is the
                # Whisper path, so a spoken interrupt lands a few
                # seconds after the words, not instantly — the Stop
                # button and the Esc key are the instant routes.
                # While only THINKING (generating, not yet speaking)
                # there is nothing to stop mid-audio, but the token
                # in _ask still discards the reply if she stops it.
                if self.mode == "speaking" or (
                        voice_mod is not None
                        and voice_mod.is_speaking()):
                    # Token guard: a listen cycle that started during
                    # this reply must not deliver the agent's own
                    # words as a "user" utterance if Lorenza stopped
                    # the reply while the cycle was in flight.
                    listen_token = self._reply_token
                    try:
                        heard = voice_mod.listen_once(
                            timeout=2, phrase_time_limit=4)
                    except Exception:
                        heard = ""
                    if heard:
                        try:
                            engine = voice_mod.last_stt_engine()
                        except Exception:
                            engine = ""
                        self._log_listening(
                            f"HEARD-WHILE-SPEAKING ({engine or 'stt'}): {heard}")
                    if listen_token != self._reply_token:
                        # Interrupted mid-listen: drop whatever this
                        # cycle caught — it is the stopped reply's
                        # own audio, not a new thing Lorenza said.
                        continue
                    if heard and voice_mod.contains_interrupt_command(heard):
                        self._log_listening(
                            f"INTERRUPT HEARD: {heard!r}")
                        self._post_ui(
                            lambda: self.interrupt_speaking("voice"))
                        continue
                    time.sleep(0.2)
                    continue
                time.sleep(0.5)
                continue
            if time.monotonic() < getattr(self, "_interrupt_until", 0.0):
                # Post-interrupt blackout (see interrupt_speaking):
                # still listen (the call blocks on audio), but drop
                # the result — it is the stopped reply's echo.
                _dropped = voice_mod.listen_once(timeout=2,
                                                 phrase_time_limit=4)
                if _dropped:
                    self._log_listening(
                        f"HEARD dropped (post-interrupt blackout): {_dropped!r}")
                continue
            heard = voice_mod.listen_once(timeout=10, phrase_time_limit=30)
            if heard and self.always_listen:
                try:
                    engine = voice_mod.last_stt_engine()
                except Exception:
                    engine = ""
                self._log_listening(f"HEARD ({engine or 'stt'}): {heard}")
                self._post_ui(lambda h=heard: self.handle_user_text(h, spoken=True))

    def check_improvements(self):
        self.append("system", "Checking the internet for possible improvements. Proposals only - nothing will change without your YES, by email or in this GUI.")
        def _run():
            if monitor_mod is None:
                self._post_ui(lambda: self.append("system", "monitor.py not found in this folder."))
                return
            try:
                monitor_mod.run_daily_check()
                self._post_ui(lambda: self.append("system", "Check done. See the proposals/ folder and any email sent. Reply YES to apply, NO to skip."))
            except Exception as e:
                self._post_ui(lambda: self.append("system", f"Improvement check failed: {e}"))
        threading.Thread(target=_run, daemon=True).start()

    def test_camera_gui(self):
        """Grab one real frame and show where it was saved (v1.0.6).
        This is the honest camera check — a saved frame, not a guess."""
        if camera_mod is None:
            self.append("system", "camera.py not found, or OpenCV is not installed. Run: pip install opencv-python")
            return
        self.append("system", "Testing camera — trying every camera index and backend (DirectShow / Media Foundation) until one returns a real frame…")
        def _run():
            try:
                if hasattr(camera_mod, "capture_test_frame"):
                    ok, result = camera_mod.capture_test_frame()
                else:
                    ok, result = False, "capture_test_frame() is not in this camera.py"
                if ok:
                    self._post_ui(lambda: self.append("system", f"Camera works — a real frame was grabbed and saved at: {result}"))
                else:
                    self._post_ui(lambda: self.append("system", f"Camera test failed: {result}"))
            except Exception as e:
                self._post_ui(lambda err=e: self.append("system", f"Camera test failed: {err}"))
        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------ camera watch: ALWAYS ON
    # Camera watch is ALWAYS ON from startup (2026-11-24, Lorenza).
    # Before this, watch was manual-only: watcher started as None,
    # cam_label "Camera: OFF", and nothing watched until the user
    # clicked "Start camera watch". Now the GUI starts watch itself
    # at launch, in a worker thread, and retries every 30 s if the
    # camera is busy / fails to open — it never silently stays off.
    # The user can still stop it (button / Privacy mode); that sets
    # _camera_watch_user_stopped, which stops the retry loop too.
    # Pan-and-describe reuses this same watcher/controller, so watch
    # stays on through a sweep (it only pauses auto-tracking).
    def _start_watch(self):
        """Create the controller + Watcher and start it. Returns the
        start message. Raises on failure, leaving watcher None.
        Callable from any thread; UI updates are separate."""
        if camera_mod is None:
            raise RuntimeError("camera.py not found, or OpenCV is not installed. Run: pip install opencv-python")
        controller = camera_mod.CameraController()
        watcher = camera_mod.Watcher(
            controller=controller,
            on_alert=lambda txt: self._post_ui(lambda: self._on_camera_alert(txt)),
            on_track=lambda info: self._post_ui(lambda: self._on_track_update(info)),
        )
        try:
            msg = watcher.start()
        except Exception:
            try:
                controller.close()
            except Exception:
                pass
            raise
        self.camera_controller = controller
        self.watcher = watcher
        return msg

    def _on_camera_alert(self, txt):
        """Motion alert from the Watcher: show it in chat, and leave
        one short memory note from the description line (throttled
        in continuous_memory, so repeated alerts do not spam
        memory)."""
        self.append("system", txt)
        if continuous_memory is not None and txt.startswith("Oracle camera alert"):
            try:
                lines = txt.splitlines()
                desc = lines[2] if len(lines) > 2 else txt
                continuous_memory.note_sighting(
                    APP_DIR, "Motion alert: " + str(desc)[:160],
                    key="motion-alert")
            except Exception:
                pass

    def _apply_watch_on(self, msg):
        """Main-thread UI for watch running."""
        if self.watcher is None:
            return  # user stopped it between start and this UI update
        # Auto-track defaults ON when the camera is on (item 7).
        try:
            self.watcher.set_auto_track(self.auto_track_enabled)
            self._refresh_track_button()
            self._on_track_update({})
        except Exception:
            pass
        self.watch_btn.config(text="Stop camera watch", bg=self.t["danger"])
        self.cam_label.config(text="Camera: WATCHING", fg=self.t["danger"])
        self.cam_pill.config(text="CAM: ON", fg=self.t["danger"])
        self.append("system", msg + " Motion alerts will be emailed if SMTP is set, otherwise they appear here and in alerts/.")

    def _apply_watch_off(self, msg="Watcher stopped."):
        """Main-thread UI for watch stopped by the user."""
        try:
            self.track_label.config(text="Tracking: —", fg=self.t["muted"])
        except Exception:
            pass
        self.watch_btn.config(text="Start camera watch", bg=self.t["panel2"])
        self.cam_label.config(text="Camera: OFF", fg=self.t["muted"])
        self.cam_pill.config(text="CAM: OFF", fg=self.t["muted"])
        self.append("system", msg)

    def _apply_watch_failed(self, short, attempt):
        """Main-thread UI for a failed auto-start attempt. Shows the
        failure plainly (never silently off) and that it retries."""
        self.watch_btn.config(text="Start camera watch", bg=self.t["panel2"])
        self.cam_label.config(text=f"Camera: OFF — retrying ({attempt})", fg=self.t["danger"])
        self.cam_pill.config(text="CAM: OFF", fg=self.t["muted"])
        if attempt == 1:
            self.append("system", f"Camera watch could not start: {short}. Retrying every 30 seconds — if it stays off, close EMEET Studio / Zoom / OBS, or unplug and replug the PIXY.")

    def _start_camera_watch_auto(self):
        """Start camera watch at launch, in a worker thread, so a
        slow camera probe never blocks the GUI from opening."""
        if camera_mod is None:
            self.cam_label.config(text="Camera: OFF — camera.py missing", fg=self.t["danger"])
            self.cam_pill.config(text="CAM: OFF", fg=self.t["muted"])
            self.append("system", "Camera watch is off: camera.py not found, or OpenCV is not installed. Run: pip install opencv-python")
            self._log_listening("CAMERA WATCH AUTO-START FAILED: camera module not available")
            return
        self._camera_watch_user_stopped = False
        self.cam_label.config(text="Camera: STARTING…", fg=self.t["accent"])
        self.cam_pill.config(text="CAM: …", fg=self.t["muted"])
        threading.Thread(target=self._camera_watch_auto_loop, daemon=True).start()

    def _camera_watch_auto_loop(self):
        """Retry loop: start watch, retry every 30 s on failure until
        it opens, the user stops it, or Privacy mode is used."""
        attempt = 0
        while not self._camera_watch_user_stopped:
            if self.watcher is not None:
                return
            attempt += 1
            try:
                msg = self._start_watch()
                self._log_listening(f"CAMERA WATCH AUTO-STARTED: {msg}")
                self._post_ui(lambda m=msg: self._apply_watch_on(m))
                return
            except Exception as e:
                err = " ".join(str(e).split())
                self._log_listening(f"CAMERA WATCH AUTO-START FAILED (attempt {attempt}): {err}")
                short = err if len(err) <= 120 else err[:117] + "…"
                self._post_ui(lambda s=short, a=attempt: self._apply_watch_failed(s, a))
                for _ in range(60):  # 30 s, checked every 0.5 s so Stop/Privacy stops it promptly
                    if self._camera_watch_user_stopped or self.watcher is not None:
                        return
                    time.sleep(0.5)

    def toggle_watch(self):
        if camera_mod is None:
            self.append("system", "camera.py not found, or OpenCV is not installed. Run: pip install opencv-python")
            return
        if self.watcher is None:
            self._camera_watch_user_stopped = False
            try:
                msg = self._start_watch()
                self._apply_watch_on(msg)
                self._log_listening(f"CAMERA WATCH STARTED (button): {msg}")
            except Exception as e:
                self._log_listening(f"CAMERA WATCH START FAILED (button): {e}")
                self.append("system", f"Could not start camera: {e}")
                self.watcher = None
                self.camera_controller = None
        else:
            self._camera_watch_user_stopped = True
            msg = self.watcher.stop()
            self.watcher = None
            self._apply_watch_off(msg)
            self._log_listening("CAMERA WATCH STOPPED by user")

    # ------------------------------------------------ camera window
    # Separate preview window (2026-11-24 layout change, supersedes
    # the lower-right box: "Open the camera preview in a SEPARATE
    # window, and REMOVE it from the lower-right corner of the main
    # GUI"). Toplevel "Oracle Camera", resizable, default 640x360,
    # movable anywhere. Same feed watch is using
    # (camera.latest_frame, updated by the Watcher loop) — no second
    # camera open. Closing it HIDES it only — camera watch keeps
    # running — and it reopens from the main GUI ("Show camera"
    # button) or by voice ("show camera" / "hide camera"). The
    # status line shows the Harmony tracking state and who is in
    # frame. Shows a plain message when there is no frame yet /
    # the camera is off / it cannot open.
    def _build_camera_window(self):
        win = tk.Toplevel(self.root)
        win.title("Oracle Camera")
        win.geometry("640x390")
        win.minsize(320, 200)
        win.configure(bg="#000000")
        self._cam_window = win
        self._cam_window_visible = True
        self._cam_window_status = tk.Label(
            win, text="Harmony — PIXY leads  •  Camera starting…",
            font=("Segoe UI", 9, "bold"), fg="#ffffff", bg="#000000",
            anchor="w")
        self._cam_window_status.pack(fill="x", padx=6, pady=(4, 2))
        self._cam_window_label = tk.Label(
            win, text="Camera starting…", font=("Segoe UI", 10),
            fg="#bbbbbb", bg="#000000")
        self._cam_window_label.pack(fill="both", expand=True)
        win.protocol("WM_DELETE_WINDOW", self._hide_camera_window)
        # Preview fluidity (v1.0.9): render counter / fps window, and
        # the id of the last frame drawn, so unchanged frames are
        # skipped instead of re-rendered.
        self._cam_preview_last_id = None
        self._cam_preview_frames = 0
        self._cam_preview_fps_t0 = time.time()
        self._update_camera_window()

    def _show_camera_window(self):
        """Reopen the camera window (button or 'show camera')."""
        try:
            if self._cam_window is None:
                self._build_camera_window()
                return
            self._cam_window.deiconify()
            self._cam_window.lift()
            self._cam_window_visible = True
        except Exception:
            pass

    def _hide_camera_window(self):
        """Hide the camera window only — watch keeps running, and
        the preview loop keeps its timer (cheap when hidden)."""
        try:
            if self._cam_window is not None:
                self._cam_window.withdraw()
            self._cam_window_visible = False
        except Exception:
            pass

    def _update_camera_window(self):
        # Fluid preview (v1.0.9): 33 ms timer (~30 fps); resize with
        # OpenCV instead of Pillow LANCZOS on the GUI thread; skip
        # re-render when the Watcher has produced no new frame.
        # NO face overlays are drawn on the video (Lorenza,
        # 2026-11-24 22:02: "remove the identifying boxes on
        # faces" — recognition stays invisible: the agent still
        # enrols, identifies and remembers people locally and can
        # say who is on camera, it just draws nothing on the
        # picture). Render size follows the window's current size
        # (default 640x360) so the window is resizable.
        try:
            label = self._cam_window_label
            if label is not None and self._cam_window_visible:
                try:
                    tw = label.winfo_width()
                    th = label.winfo_height()
                except Exception:
                    tw, th = 0, 0
                if tw < 50 or th < 50:
                    tw, th = 640, 360
                frame = None
                frame_id = None
                if camera_mod is not None:
                    frame = getattr(camera_mod, "latest_frame", None)
                    frame_id = getattr(camera_mod, "latest_frame_id", None)
                if frame is not None and Image is not None:
                    if frame_id is not None and frame_id == getattr(self, "_cam_preview_last_id", None):
                        pass  # no new frame since last draw: skip the work
                    else:
                        self._cam_preview_last_id = frame_id
                        try:
                            import cv2 as _cv2
                            small = _cv2.resize(frame, (tw, th),
                                                interpolation=_cv2.INTER_AREA)
                            rgb = _cv2.cvtColor(small, _cv2.COLOR_BGR2RGB)
                            img = Image.fromarray(rgb)
                        except Exception:
                            # Fallback if OpenCV is unavailable in the GUI.
                            rgb = frame[:, :, ::-1].copy()
                            img = Image.fromarray(rgb)
                            img = img.resize((tw, th), Image.LANCZOS)
                        photo = ImageTk.PhotoImage(img)
                        self._cam_window_photo = photo
                        label.config(image=photo, text="")
                        self._cam_preview_frames = getattr(self, "_cam_preview_frames", 0) + 1
                elif label is not None:
                    if self.watcher is None:
                        msg = "Camera off" if self._camera_watch_user_stopped else "Camera starting…"
                    else:
                        msg = "Camera on — waiting for frames…"
                    label.config(image="", text=msg)
                # Status line: Harmony state + who is in frame.
                try:
                    if self.watcher is not None:
                        status = self.watcher.track_status_text()
                    else:
                        status = "Camera starting…"
                    self._cam_window_status.config(
                        text=f"Harmony — PIXY leads  •  {status}")
                except Exception:
                    pass
        except Exception as e:
            try:
                if self._cam_window_label is not None:
                    self._cam_window_label.config(image="", text=f"Camera preview error: {e}")
            except Exception:
                pass
        try:
            now = time.time()
            t0 = getattr(self, "_cam_preview_fps_t0", None)
            if t0 is None:
                self._cam_preview_fps_t0 = now
                self._cam_preview_frames = 0
            elif now - t0 >= 10.0:
                n = getattr(self, "_cam_preview_frames", 0)
                fps = n / max(now - t0, 0.001)
                self._cam_preview_frames = 0
                self._cam_preview_fps_t0 = now
                if n > 0:
                    self._log_listening(
                        f"PREVIEW FPS: {fps:.1f} (renders in last {now - t0:.0f}s)")
        except Exception:
            pass
        try:
            self.root.after(33, self._update_camera_window)
        except Exception:
            pass

    def camera_ptz(self, pan, tilt, zoom):
        if self.camera_controller is None:
            self.append("system", "Start camera watch first, then use PTZ. Note: PIXY motor control is officially via EMEET Studio - OpenCV PTZ may be ignored, in which case Oracle uses digital framing and the camera's own AI tracking.")
            return
        result = self.camera_controller.ptz(pan_delta=pan, tilt_delta=tilt, zoom_delta=zoom)
        # NOTE (2026-11-24 22:12): a deliberate PTZ move is temporary
        # and must NOT update home — home is fixed directly forward,
        # facing the chair. It only changes by explicit calibration
        # ("set this as home").
        self.append("system", f"PTZ: pan {result['pan']}°, tilt {result['tilt']}°, zoom {result['zoom']}x. UVC pan/tilt/zoom worked: {result['uvc_pan_ok']}/{result['uvc_tilt_ok']}/{result['uvc_zoom_ok']}. {result['note']}")

    def camera_privacy(self):
        # Privacy also stops the auto-start retry loop, so watch does
        # not come back on by itself after the user chose privacy.
        self._camera_watch_user_stopped = True
        if self.watcher is not None:
            self.toggle_watch()
        if self.camera_controller is not None:
            self.append("system", self.camera_controller.privacy_mode())
        else:
            self.append("system", "Privacy mode: camera watch is off. Tilt the PIXY down manually, or unplug it, for guaranteed privacy.")
        self.cam_label.config(text="Camera: PRIVACY", fg=self.t["good"])
        self.cam_pill.config(text="CAM: PRIVACY", fg=self.t["good"])

    # ------------------------------------------------ Harmony tracking
    # Harmony is the ONLY tracking mode (2026-11-24 decision): the
    # PIXY leads, Oracle watches. The button below is a hold-still
    # PAUSE inside Harmony — it freezes movement instantly and
    # stays still until she says track again.
    def _refresh_track_button(self):
        try:
            self.track_btn.config(
                text=("Resume tracking" if not self.auto_track_enabled
                      else "Hold still"))
        except Exception:
            pass

    def toggle_hold_still(self):
        self.auto_track_enabled = not self.auto_track_enabled
        if self.watcher is not None:
            self.append("system", self.watcher.set_auto_track(self.auto_track_enabled))
        else:
            self.append("system", f"Harmony tracking will be {'ON' if self.auto_track_enabled else 'PAUSED — hold still'} when you start camera watch.")
        self._refresh_track_button()
        self._on_track_update({})

    def _on_track_update(self, _info):
        """Watcher thread -> main thread: show who is tracked/identified."""
        try:
            if self.watcher is not None:
                text = self.watcher.track_status_text()
                # Continuous memory: a newly identified face leaves
                # one short note (throttled in continuous_memory).
                name = getattr(self.watcher, "last_identified_name", None)
                if name and name != getattr(self, "_last_noted_name", None):
                    self._last_noted_name = name
                    if continuous_memory is not None:
                        try:
                            continuous_memory.note_sighting(
                                APP_DIR, f"Saw {name} on camera",
                                key=f"face:{name}")
                        except Exception:
                            pass
                elif not name:
                    self._last_noted_name = None
            else:
                text = "Tracking: —"
            self.track_label.config(text=text)
        except Exception:
            pass

    def enroll_face_gui(self):
        """Enrol the face currently on camera (local only, item 9)."""
        if self.watcher is None:
            self.append("system", "Start camera watch first, then enrol the face in view.")
            return
        import tkinter.simpledialog as sd
        name = sd.askstring("Enroll face", "Whose face is on camera? Enter their name:")
        if not name:
            return
        self.append("system", self.watcher.enrol_current(name))

    def enroll_voice_gui(self):
        if identity_mod is None:
            self.append("system", "identity.py not found.")
            return
        import tkinter.simpledialog as sd
        name = sd.askstring("Enroll voice", "Whose voice is this? Enter their name:")
        if not name:
            return
        # Home mode, per your instruction: naming the person is enrollment.
        def _run():
            result = identity_mod.enroll_voice(name, consent=True)
            self._post_ui(lambda: self.append("system", result))
        threading.Thread(target=_run, daemon=True).start()

    def delete_identity_gui(self):
        if identity_mod is None:
            return
        import tkinter.simpledialog as sd
        name = sd.askstring("Delete identity", "Whose local identity should be deleted?")
        if name:
            self.append("system", identity_mod.delete_identity(name))

    # ------------------------------------------------ Get to know me
    # Optional mode (Lorenza, 2026-11-24): Oracle asks 18 questions,
    # one at a time, to learn about a person. Trigger phrases:
    # "get to know me" / "learn about me" / "get to know you" /
    # "let's get to know each other". Say "skip" on any question,
    # "stop" to end at any time; it never asks again unless the
    # trigger is said again. Answers live in identities/<name>/
    # get_to_know.json on this PC only — never sent anywhere.
    def get_to_know_gui(self):
        if get_to_know_mod is None:
            self.append("system", "Get to know me is not available (get_to_know.py missing).")
            return
        if self._gtk_session is not None and self._gtk_session.active:
            self.append("system", "We're already in the middle of getting to know each other — say 'skip' to pass a question or 'stop' to end.")
            return
        person = None
        if self.watcher is not None:
            person = getattr(self.watcher, "last_identified_name", None)
        self._gtk_session = get_to_know_mod.Session(person=person)
        self.append("system", self._gtk_session.start_text())

    def _review_get_to_know(self):
        if get_to_know_mod is None:
            return "Get to know me is not available (get_to_know.py missing)."
        person = None
        if self._gtk_session is not None:
            person = self._gtk_session.person
        if not person and self.watcher is not None:
            person = getattr(self.watcher, "last_identified_name", None)
        if not person:
            return "I don't know who to look up — start 'Get to know me' first, or enrol a face so I know who I'm talking to."
        return get_to_know_mod.summary_text(person)

    def forget_get_to_know_gui(self):
        if get_to_know_mod is None:
            return
        import tkinter.simpledialog as sd
        name = sd.askstring("Forget what you told me",
                            "Whose Get to know me answers should I forget?")
        if name:
            self.append("system", get_to_know_mod.delete_answers(name))

    def _route_get_to_know(self, user_text):
        """Route a message through a Get-to-know-me session, or start
        one on the trigger phrase. Returns the reply string when
        handled, else None (fall through to the normal reply path).
        Runs on the _ask worker thread; session logic is pure."""
        if get_to_know_mod is None:
            return None
        if self._gtk_session is not None and self._gtk_session.active:
            session = self._gtk_session
            before = set(session.answers)
            reply = session.answer(user_text)
            # Continuous memory: a just-answered Get-to-know-me
            # answer is a durable fact about that person — save it
            # into memory.json as well as get_to_know.json.
            if continuous_memory is not None:
                try:
                    person = session.person or "Someone"
                    qmap = {k: q for (_g, k, q) in get_to_know_mod.QUESTIONS}
                    for key in set(session.answers) - before:
                        continuous_memory.remember_fact(
                            APP_DIR,
                            f"{person} — {qmap.get(key, key)} "
                            f"{session.answers[key]}",
                            topic="get-to-know", source="heard")
                except Exception:
                    pass
            if not self._gtk_session.active:
                self._gtk_session = None
            return reply
        if get_to_know_mod.is_trigger(user_text):
            person = None
            if self.watcher is not None:
                person = getattr(self.watcher, "last_identified_name", None)
            self._gtk_session = get_to_know_mod.Session(person=person)
            return self._gtk_session.start_text()
        return None

    def start_repair_gui(self):
        self.append("system", "Repair mode: Apollo Twin USB, won't turn on. Safety first: unplug it from wall and unit, do not open the power brick. Manual checks first: barrel fully inserted then twist to lock, power switch ON, wall socket confirmed with another device. PSU spec: 12VDC, 1.5A, center positive, 5.5/2.1 mm barrel.")
        self.append("system", "Next questions to answer in chat, one at a time: 1) Is the PSU original or replacement, and is the barrel locked? 2) Any LEDs at all when switched ON? Tell me those two, and I will follow with the next step for your exact result. Full step-by-step flow is in repair.py (python repair.py).")
        if repair_mod is not None:
            self.append("system", "Tip: point the PIXY camera at the board and tap 'Look at board' and I will describe what I see - burnt marks, swollen caps, loose connectors.")

    def look_at_board_gui(self):
        if repair_mod is None:
            self.append("system", "repair.py not found.")
            return
        def _run():
            s = repair_mod.RepairSession("Apollo Twin USB", "won't turn on")
            try:
                s.look_at_board()
                self._post_ui(lambda: self.append("system", "Board look done - check the transcript above and the repairs/ snapshot. Tell me if that matches what you see, and point closer to any area you want re-checked."))
            except Exception as e:
                self._post_ui(lambda: self.append("system", f"Board look failed: {e}"))
        threading.Thread(target=_run, daemon=True).start()

    def _answer_where_left(self, user_text):
        """'Where did I leave my X?' — answer from the visual-memory
        log (sighting facts in memory.json + the Watcher's minute
        sweep log), or say plainly it was never seen. Runs on the
        _ask worker thread; never guesses, never invents a place."""
        thing = None
        try:
            thing = continuous_memory.extract_left_behind_thing(user_text)
        except Exception:
            thing = None
        if not thing:
            return ("I didn't catch what you're looking for — what did "
                    "you leave, and where did you last have it?")
        found = None
        try:
            found = continuous_memory.find_last_seen(APP_DIR, thing)
        except Exception:
            found = None
        sweep_hit = None
        try:
            if self.watcher is not None:
                sweep_hit = self.watcher.find_in_visual_log(thing)
        except Exception:
            sweep_hit = None
        if found:
            reply = f"Last I saw your {thing}: {found}"
            if sweep_hit and sweep_hit not in found:
                reply += f" Latest camera sweep also notes: {sweep_hit}"
            return reply
        if sweep_hit:
            return f"Latest camera sweep notes: {sweep_hit}"
        return (f"I haven't seen your {thing} on camera — not in any "
                "sweep, sighting or motion alert I have logged. "
                "Want me to pan around and look for it now?")

    def _run_pan_describe(self):
        """Run the pan-and-describe sweep synchronously; call from a
        worker thread. Returns the spoken description (or a plain
        explanation when it could not be done). Progress lines are
        posted to the chat as the sweep runs."""
        if camera_mod is None:
            return "I can't use the camera — camera.py is not available, or OpenCV is not installed."
        # Reuse the watcher's controller when camera watch is on, so we
        # do not fight a second open of the same camera.
        controller = self.camera_controller
        own = False
        if controller is None:
            controller = camera_mod.CameraController()
            own = True

        def _pause_tracking():
            # Pause auto-tracking during the sweep so it does not fight
            # the commanded pan; resume afterwards. The Watcher has
            # set_auto_track (auto-track defaults ON when watching).
            watcher = self.watcher
            if watcher is not None and hasattr(watcher, "set_auto_track"):
                try:
                    was_on = bool(getattr(watcher, "auto_track", False))
                    watcher.set_auto_track(False)

                    def _resume():
                        if was_on:
                            watcher.set_auto_track(True)
                    return _resume
                except Exception:
                    return None
            return None

        try:
            result = camera_mod.pan_and_describe(
                controller=controller,
                progress=lambda m: self._post_ui(
                    lambda msg=m: self.append("system", msg)),
                pause_tracking=_pause_tracking)
            # The sweep restores the camera to its start position;
            # then return to the FIXED home (directly forward, facing
            # the chair — 2026-11-24 22:12), never left at an extreme.
            try:
                controller.go_home()
            except Exception:
                pass
            # Continuous memory: the sweep's sighting lands in
            # memory as one short note (who/what was seen).
            if continuous_memory is not None:
                try:
                    continuous_memory.note_sighting(
                        APP_DIR,
                        "Pan-and-describe: " + str(result["description"])[:180],
                        key="pan-describe")
                except Exception:
                    pass
            return result["description"]
        except Exception as e:
            return f"The pan-and-describe sweep failed: {e}."
        finally:
            if own:
                try:
                    controller.close()
                except Exception:
                    pass

    def pan_describe_gui(self):
        """'Pan & describe what you see' button: sweep in a thread,
        then speak/show the full description."""
        if self.busy:
            self.append("system", "Hold on — I am still answering. Ask me to look around again in a moment.")
            return
        self.append("system", "Panning the camera left to right, then right to left, and describing everything I see...")
        def _run():
            desc = self._run_pan_describe()
            self._post_ui(lambda: self._typewriter(desc))
        threading.Thread(target=_run, daemon=True).start()

    def _handle_camera_command(self, user_text, spoken=False):
        """Local camera commands: 'track me', 'stop tracking', 'who is
        that', 'enrol this person as <name>'. Returns True if handled
        (no LLM call), False to fall through to the normal reply path.
        Matching is case-insensitive; names keep the user's casing.
        Pan-and-describe phrases are NOT handled here — they fall
        through to _ask, which runs the sweep (verified live 2026-11-24).
        """
        low = user_text.strip().lower()
        if not low:
            return False
        watcher = self.watcher

        def _need_watcher():
            if watcher is None:
                self.append("user", user_text + ("  [spoken]" if spoken else ""))
                self.append("system", "Start camera watch first, then I can do that.")
                return False
            return True

        if low in ("track me", "track this person", "start tracking", "follow me"):
            self.append("user", user_text + ("  [spoken]" if spoken else ""))
            if not _need_watcher():
                return True
            self.auto_track_enabled = True
            self._refresh_track_button()
            self.append("system", watcher.track_me())
            return True
        if low.startswith("track ") and len(low) > 6:
            # Ambiguous without a running camera ("track my package"):
            # only treat it as a camera command when the watcher is on.
            if watcher is None:
                return False
            self.append("user", user_text + ("  [spoken]" if spoken else ""))
            name = user_text.strip()[6:].strip()
            self.auto_track_enabled = True
            self._refresh_track_button()
            self.append("system", watcher.track_me(name))
            return True
        if low in ("stop tracking", "stop following", "stop following me",
                   "hold still", "freeze"):
            self.append("user", user_text + ("  [spoken]" if spoken else ""))
            if not _need_watcher():
                return True
            self.auto_track_enabled = False
            self._refresh_track_button()
            self.append("system", watcher.stop_tracking())
            self._on_track_update({})
            return True
        if low in ("resume tracking", "track again", "start tracking again",
                   "harmony mode", "resume"):
            self.append("user", user_text + ("  [spoken]" if spoken else ""))
            if not _need_watcher():
                return True
            self.auto_track_enabled = True
            self._refresh_track_button()
            self.append("system", watcher.set_auto_track(True))
            self._on_track_update({})
            return True
        if low in ("set this as home", "this is home", "calibrate home",
                   "save this as home"):
            # Explicit home calibration ONLY (2026-11-24 22:12): with
            # Lorenza sitting in the chair, this saves the current
            # forward position as the fixed home. Nothing else ever
            # writes home — not moves, not sweeps, not tracking.
            self.append("user", user_text + ("  [spoken]" if spoken else ""))
            if not _need_watcher():
                return True
            saved = (self.camera_controller.save_home()
                     if self.camera_controller is not None else None)
            if saved:
                self.append("system", f"Home set — this spot, facing you in the chair (pan {saved['pan']}°, tilt {saved['tilt']}°). I'll come back here every time.")
            else:
                self.append("system", "I couldn't save home — try again in a moment.")
            return True
        if low in ("go home", "return home", "face forward", "face me"):
            self.append("user", user_text + ("  [spoken]" if spoken else ""))
            if not _need_watcher():
                return True
            pos, _cal = (self.camera_controller.go_home()
                         if self.camera_controller is not None else ({}, False))
            self.append("system", f"Back home, facing forward (pan {pos.get('pan', 0)}°, tilt {pos.get('tilt', 0)}°).")
            return True
        if low in ("show camera", "show the camera", "open camera"):
            self.append("user", user_text + ("  [spoken]" if spoken else ""))
            self._show_camera_window()
            self.append("system", "Camera window open.")
            return True
        if low in ("hide camera", "close camera", "hide the camera"):
            self.append("user", user_text + ("  [spoken]" if spoken else ""))
            self._hide_camera_window()
            self.append("system", "Camera window hidden — watch keeps running.")
            return True
        if low in ("who is this", "who is that", "who is that person",
                   "who do you see", "who is on camera"):
            self.append("user", user_text + ("  [spoken]" if spoken else ""))
            if watcher is None:
                self.append("system", "The camera isn't on — start camera watch and I'll tell you who I see.")
            else:
                self.append("system", watcher.track_status_text())
            return True
        for prefix in ("enrol this person as ", "enroll this person as "):
            if low.startswith(prefix):
                self.append("user", user_text + ("  [spoken]" if spoken else ""))
                if not _need_watcher():
                    return True
                name = user_text.strip()[len(prefix):].strip()
                self.append("system", watcher.enrol_current(name))
                return True
        return False

    def on_send(self):
        user_text = self.entry.get().strip()
        if not user_text:
            return
        self.entry.delete(0, "end")
        self.handle_user_text(user_text)

    def handle_user_text(self, user_text, spoken=False):
        # Interrupt first (item 3): "stop" / "shut up" / "be quiet"
        # while a reply is going must cut it off, not be dropped by
        # the busy-guard below and not be answered as a question.
        if (voice_mod is not None
                and voice_mod.is_interrupt_phrase(user_text)
                and (self.busy or self.mode == "speaking")):
            self.interrupt_speaking("voice" if spoken else "typed")
            return
        # Camera tracking / face commands are handled locally, without
        # calling the LLM (v1.0.8, items 7 + 9).
        if self._handle_camera_command(user_text, spoken=spoken):
            return
        # "What do you remember?" is a memory question, not a chat
        # question: answer from memory.json directly, no LLM call.
        if user_text.strip().lower() in (
                "what do you remember", "what do you remember about me",
                "what do you remember about lorenza"):
            self.append("user", user_text + ("  [spoken]" if spoken else ""))
            self._show_memory_summary()
            return
        if self.busy:
            return
        self.busy = True
        self._typing_done = False
        self._speech_done = False
        self._ask_started = datetime.now()
        self.append("user", user_text + ("  [spoken]" if spoken else ""))
        self.history.append({"role": "user", "content": user_text})
        if spoken:
            # Listening beat (v1.0.9): the avatar looks at her and
            # leans in while the words land, then thinking takes
            # over. True live "hearing you right now" needs a
            # speech-start callback in voice.py's listen loop — the
            # listen thread only reports finished phrases today, so
            # this beat is the honest version until that exists.
            self.mode = "listening"
            self.status.config(text="● LISTENING", fg=self.t["accent"])
            self.root.after(600, self._promote_listening_to_thinking)
        else:
            self.mode = "thinking"
            self.status.config(text="● THINKING", fg=self.t["warn"])
        threading.Thread(target=self._ask, args=(user_text,), daemon=True).start()

    def _promote_listening_to_thinking(self):
        """Listening beat over: thinking, unless the reply already
        moved the avatar on (speaking / idle)."""
        if self.mode == "listening" and self.busy:
            self.mode = "thinking"
            try:
                self.status.config(text="● THINKING", fg=self.t["warn"])
            except Exception:
                pass

    def _ask(self, user_text):
        # Runs on a worker thread: never touch tkinter directly.
        # try/finally guarantees busy always clears, and every
        # outcome is logged, so a dead reply thread can no longer
        # leave the GUI stuck on THINKING forever.
        # Interrupt token (item 3): captured now; if Lorenza stops
        # this reply while it is still generating, the token goes
        # stale and the reply is discarded below, never typed or
        # spoken. The LLM HTTP call itself cannot be cancelled
        # mid-flight (no cancel API), but its output is dropped.
        token = self._reply_token
        try:
            # "Get to know me" is a local conversation mode, not a chat
            # question: one question at a time, skip/stop any time.
            gtk_reply = self._route_get_to_know(user_text)
            if gtk_reply is not None:
                reply = gtk_reply
            # "What do you see?" is a camera command, not a chat question:
            # pan left->right then right->left and describe everything,
            # instead of asking the LLM to guess without looking.
            elif (camera_mod is not None
                    and hasattr(camera_mod, "is_pan_describe_request")
                    and camera_mod.is_pan_describe_request(user_text)):
                self._post_ui(lambda: self.append(
                    "system", "Panning the camera left to right, then right "
                    "to left, and describing everything I see..."))
                reply = self._run_pan_describe()
            # "Where did I leave my X?" is answered from the visual
            # memory log (sighting facts + minute sweeps), not
            # guessed by the LLM — or plainly "never seen".
            elif (continuous_memory is not None
                    and hasattr(continuous_memory,
                                "extract_left_behind_thing")
                    and continuous_memory.extract_left_behind_thing(
                        user_text)):
                reply = self._answer_where_left(user_text)
            elif call_llm is None:
                reply = "I could not load my brain (agent.py). Make sure agent.py is in the same folder as gui.py."
            else:
                # Memory (v1.0.7): what Oracle knows about Lorenza,
                # from Muse conversations and its own memory.json.
                # Read fresh on the worker thread each time so a
                # just-imported file is used in the very next reply.
                # query=user_text boosts facts matching this
                # question (2026-11-25 recall fix); the key facts
                # (kids, cars) are always included regardless.
                memory_text = ""
                if memory_import is not None:
                    try:
                        memory_text = memory_import.load_memory_text(
                            APP_DIR, query=user_text)
                    except Exception:
                        memory_text = ""
                system = PERSONALITY
                # Chat-window honesty (2026-11-25, item 4): this GUI
                # reply path has no tool execution, unlike agent.py's
                # CLI loop — so the model must never claim it opened
                # a program, wrote a file, or found a file when it
                # has not. It still attempts, in the way it can here:
                # exact steps, the exact command, or the exact file
                # content, briefly — never a refusal, never a false
                # "done". (A GUI tool loop is the remaining work if
                # Lorenza wants the chat window itself to execute.)
                system += ("\n\nYou are answering in the chat window: you "
                           "cannot run programs, open files, or write files "
                           "from here, so never claim such a task is already "
                           "done. Instead attempt it in the way you can: "
                           "give the exact steps, the exact command, or the "
                           "exact file content, briefly.")
                if memory_text:
                    system += ("\n\nWHAT YOU KNOW ABOUT LORENZA (from Muse conversations "
                               "and your own memory — use it, refer to it naturally, "
                               "and continue these open threads):\n" + memory_text)
                messages = [{"role": "system", "content": system}] + self.history
                try:
                    reply = call_llm(messages)
                except Exception as e:
                    reply = (f"I hit a problem reaching OpenAI: {e}. "
                             "Check that OPENAI_API_KEY is set on this PC and that you have internet, then try again.")
            self.history.append({"role": "assistant", "content": reply})
            self._log_listening(f"ASK OK: {user_text[:80]!r} -> reply {len(reply)} chars")
            # Avatar reactions (v1.0.9): the avatar laughs / looks
            # surprised / smiles when the reply itself is funny,
            # surprising or good news — and looks unsure when it
            # says it does not know. Pure reply-text markers.
            if avatar_anim_mod is not None:
                try:
                    kind = avatar_anim_mod.reaction_for_reply(reply)
                    confused = any(p in reply.lower() for p in (
                        "i'm not sure", "i don't know", "not certain",
                        "uncertain", "i'm not certain"))
                    self._post_ui(
                        lambda k=kind, cf=confused: self._react_to_reply(k, cf))
                except Exception:
                    pass
            # Continuous learning memory (v1.0.9): durable facts /
            # preferences from this exchange are auto-saved into
            # memory.json, so the next conversation already knows
            # them. Most chat stores nothing — only durable facts.
            if continuous_memory is not None:
                try:
                    continuous_memory.remember_exchange(APP_DIR, user_text, reply)
                    self._post_ui(self._refresh_memory_label)
                except Exception:
                    pass
            if token != self._reply_token:
                # Interrupted while generating: drop this reply
                # entirely — do not type it, do not speak it.
                self._log_listening("ASK DISCARDED: reply interrupted during generation")
                return
            self._post_ui(lambda r=reply, t=token: self._typewriter(r, token=t))
        except Exception as e:
            self._log_listening(f"ASK FAILED: {e}")
            self._post_ui(lambda err=e, t=token: self._typewriter(
                f"I hit a problem answering that: {err}. Please try again.",
                token=t))
        finally:
            # busy is cleared by _typewriter when the reply finishes
            # typing; the watchdog in _tick_clock clears it if the
            # reply never reaches the screen.
            pass

    def _typewriter(self, full_text, idx=0, token=None):
        # Runs on the main thread only (via _post_ui). Any exception
        # here must still clear busy, or the GUI sticks on THINKING.
        # Interrupt (item 3): a stale token means Lorenza stopped
        # this reply — abort the chain at once, typing and speaking
        # nothing more from it. A caller that passes no token gets the
        # CURRENT token captured at chain start, so every reply — the
        # _ask path and direct callers such as pan-and-describe — is
        # interruptible. (2026-11-25: a typed-stop test caught the
        # pan-describe path typing through a stop because token=None
        # used to bypass the check entirely.)
        if token is None:
            token = self._reply_token
        if token != self._reply_token:
            return
        try:
            if idx == 0:
                self.mode = "speaking"
                self.status.config(text="● SPEAKING", fg=self.t["accent"])
                if self.speak_replies and voice_mod is not None:
                    # Fluid lip-sync (v1.0.6): voice.py reports the
                    # real audio level + phoneme shape as it speaks.
                    voice_mod.speak_async(
                        full_text,
                        on_level=self._on_speech_level,
                        on_done=lambda: self._post_ui(self._on_speech_done),
                    )
                else:
                    self._speech_done = True
                self.text.configure(state="normal")
                self.text.insert("end", f"{AGENT_NAME}: ", "oracle")
                self.text.configure(state="disabled")
            if idx < len(full_text):
                chunk = full_text[idx:idx + 3]
                self.text.configure(state="normal")
                self.text.insert("end", chunk, "oracle")
                self.text.configure(state="disabled")
                self.text.see("end")
                self.root.after(18, lambda: self._typewriter(full_text, idx + 3, token=token))
            else:
                self.text.configure(state="normal")
                self.text.insert("end", "\n\n")
                self.text.configure(state="disabled")
                self._typing_done = True
                self._maybe_finish_speaking()
        except Exception as e:
            self._log_listening(f"TYPEWRITER FAILED: {e}")
            self.mode = "idle"
            self.busy = False
            self._typing_done = True
            self._speech_done = True
            self._ask_started = None
            try:
                self.status.config(text="● ONLINE", fg=self.t["good"])
            except Exception:
                pass


def _write_crash_log(exc_text):
    """Write the full traceback next to Oracle.exe (or the .py file).

    The windowed build hides tracebacks behind PyInstaller's generic
    "Failed to execute script 'gui'" dialog, which is why v1.0.0 was
    undiagnosable on Lorenza's PC. From v1.0.1 the real traceback is
    always in Oracle-crash.log next to the .exe.
    """
    try:
        try:
            from oracle_paths import exe_dir as _exe_dir
            log_path = _exe_dir() / "Oracle-crash.log"
        except Exception:
            log_path = Path(__file__).resolve().parent / "Oracle-crash.log"
        log_path.write_text(
            f"Oracle crash — {datetime.now():%Y-%m-%d %H:%M:%S}\n{exc_text}\n",
            encoding="utf-8",
        )
        print(f"Crash traceback written to {log_path}")
    except Exception:
        pass


def _run_gui():
    # Headless smoke test (used by the GitHub debug build):
    # ORACLE_SMOKE_TEST=1 just proves tkinter can start — i.e. that
    # init.tcl was bundled — without opening the full GUI loop.
    if os.environ.get("ORACLE_SMOKE_TEST") == "1":
        _smoke_root = tk.Tk()
        _smoke_root.withdraw()
        _smoke_root.update()
        _smoke_root.destroy()
        print("SMOKE OK: tkinter started (init.tcl found), Tk created and destroyed cleanly.")
        return
    root = tk.Tk()
    OracleGUI(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        _run_gui()
    except Exception:
        import traceback

        _exc = traceback.format_exc()
        _write_crash_log(_exc)
        # Also print it (visible in the console debug build) and then
        # re-raise so the windowed build still shows its usual dialog
        # — but now with Oracle-crash.log next to the .exe to read.
        print(_exc)
        raise
