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
        self.mode = "idle"  # idle, thinking, speaking
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
        self._lip_shape = "closed"  # closed/slight/open/wide/round
        self._typing_done = False
        self._speech_done = True
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
        # Auto-track defaults ON when the camera is on (v1.0.8, item 7).
        self.auto_track_enabled = True
        self.stars = [(random.random(), random.random(), random.choice([1, 1, 2]))
                      for _ in range(90)]
        # --- Muse avatar (Lorenza's chosen red-and-black anime avatar) ---
        # Loaded from assets/avatar.png (copy at avatar.png). If Pillow or
        # the file is missing, avatar_photo stays None and animate() falls
        # back to the drawn vector head. Never crashes on a missing image.
        self.avatar_photo = None
        self.avatar_w, self.avatar_h = 420, 386  # hi-res render (was 260x239)
        self._load_avatar()

        self._build_top()
        self._build_main()
        self._refresh_api_key_label()
        # Minimise -> avatar-only mode (v1.0.6): clicking the minimise
        # button hides the main box and leaves just the avatar.
        try:
            self.root.bind("<Unmap>", self._on_unmap)
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
        # camera is busy / fails to open. _build_cam_preview() adds
        # the small live preview box in the lower right corner, on
        # the same feed watch is using.
        self._camera_watch_user_stopped = False
        self._cam_preview_photo = None
        self._cam_preview_label = None
        self._build_cam_preview()
        self._start_camera_watch_auto()

    def _log_listening(self, line):
        """Append one timestamped line to voice-listening.log next to
        the .exe / .py file, so always-listening can be verified from
        outside the GUI (process + log, not just the on-screen label)."""
        try:
            try:
                from oracle_paths import exe_dir as _exe_dir
                log_path = _exe_dir() / "voice-listening.log"
            except Exception:
                log_path = Path(__file__).resolve().parent / "voice-listening.log"
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

        # API KEY card — first in the left deck, visible on first open
        # (v1.0.6). The key itself is NEVER shown; only SET / NOT SET
        # and the last 4 characters.
        key_card = self._card(deck, "🔑  API KEY")
        self.api_key_label = tk.Label(key_card, text="Key: …", font=("Segoe UI", 9, "bold"),
                                      fg=t["muted"], bg=t["panel"])
        self.api_key_label.pack(anchor="w", pady=(2, 4))
        self._btn(key_card, "Change API Key", self._show_api_key_dialog).pack(fill="x", pady=2)
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
        tk.Label(mem_card, text="Drop Muse chat exports (.md / .json / .txt) in the memory_import folder next to Oracle.exe — I pick them up at startup. Local only, never uploaded.",
                 font=("Segoe UI", 8), fg=t["muted"], bg=t["panel"],
                 wraplength=200, justify="left").pack(anchor="w", pady=(2, 0))

        voice_card = self._card(deck, "◇  VOICE")
        self.listen_btn = self._btn(voice_card, "Always listen: OFF", self.toggle_listen)
        self.listen_btn.pack(fill="x", pady=2)
        self.speak_btn = self._btn(voice_card, "Speak replies: ON", self.toggle_speak)
        self.speak_btn.pack(fill="x", pady=2)
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
        # Auto-track toggle (v1.0.8, item 7) — default ON.
        self.track_btn = self._btn(cam_card, "Auto-Track: ON", self.toggle_autotrack)
        self.track_btn.pack(fill="x", pady=2)
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

        sys_card = self._card(deck, "⚙  SYSTEM")
        self._btn(sys_card, "Check for improvements", self.check_improvements).pack(fill="x", pady=2)
        self._btn(sys_card, "Avatar only  ◐", self._enter_avatar_only).pack(fill="x", pady=2)
        self._btn(sys_card, "Switch theme  ◐", self.switch_theme).pack(fill="x", pady=2)
        tk.Label(sys_card, text="Proposals never apply without a clear YES, by email or in this GUI.",
                 font=("Segoe UI", 8), fg=t["muted"], bg=t["panel"],
                 wraplength=200, justify="left").pack(anchor="w", pady=(2, 0))

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
    # Lorenza's chosen Muse avatar: muscular anime male, long spiky black
    # hair, blue eyes, light stubble, red gi with black trim, black
    # undershirt, blue sash. Source: workspace/avatars/
    # avatar-1795504357733091975-0.webp, converted to assets/avatar.png.
    # The source is a full-body figure on white, so we crop to the head
    # and shoulders for the GUI face: crop box (430, 0, 1170, 680) in the
    # 1600x1600 original. In that crop, the eyes sit at about
    # (-48, +19) and (+52, +19) from the face centre and the mouth at
    # (0, +61) at the 420x386 display size - those offsets drive the
    # blink and speaking-mouth overlays in _draw_avatar(). Eye/mouth
    # positions were checked by sampling the source pixels and by
    # measuring the live GUI screenshots (eyes ~y375, mouth ~y445
    # in the 1600x1600 original).
    def _load_avatar(self):
        if Image is None or ImageTk is None:
            print("Avatar: Pillow not available, using drawn head fallback.")
            return
        for rel in ("assets/avatar.png", "avatar.png", "assets/avatar.webp"):
            path = RESOURCE_DIR / rel
            if path.exists():
                try:
                    img = Image.open(path).convert("RGBA")
                    # Crop to head + shoulders, then scale to GUI size.
                    # The PNG already has its white background made
                    # transparent (flood-fill from the edges, so interior
                    # whites like the eyes stay opaque), so it sits cleanly
                    # on the dark console instead of a white box.
                    img = img.crop((430, 0, 1170, 680))
                    img = img.resize((self.avatar_w, self.avatar_h), Image.LANCZOS)
                    try:
                        from PIL import ImageEnhance as _IE
                        img = _IE.Sharpness(img).enhance(1.25)
                        img = _IE.Contrast(img).enhance(1.05)
                    except Exception:
                        pass
                    self._avatar_pil = img
                    self.avatar_photo = ImageTk.PhotoImage(img)
                    print(f"Avatar: loaded {rel} ({self.avatar_w}x{self.avatar_h})")
                    return
                except Exception as e:
                    print(f"Avatar: could not load {rel} ({e}), trying next.")
        print("Avatar: no avatar image found, using drawn head fallback.")

    def _draw_avatar(self, c, hx, hy, look_x, look_y):
        """Draw the avatar image at (hx, hy) with blink + mouth overlays.

        hx/hy is the face centre (already includes bob/nod/look). The
        image is placed centred there; the eye/mouth overlays use the
        same centre so they track the bob/look/nod exactly.
        """
        c.create_image(hx + look_x, hy + look_y, image=self.avatar_photo)
        # Blink: skin-coloured bar + eyelid line over each eye, briefly.
        blinking = (self.phase % 62) < 2.5
        if blinking:
            for ex in (-48, 52):
                exx, eyy = hx + look_x + ex, hy + look_y + 19
                c.create_rectangle(exx - 24, eyy - 8, exx + 24, eyy + 8,
                                   fill="#fbe0c0", outline="")
                c.create_line(exx - 24, eyy + 3, exx + 24, eyy + 3,
                              fill="#1a1a1a", width=2)
        # Mouth (v1.0.6): fluid lip-sync, NOT a binary open/closed
        # toggle. animate() eases self.lip_level towards the real
        # speech-audio RMS level from voice.py every frame, and the
        # shape comes from the word being spoken (round for O/U,
        # wide for A/E). When speech ends the level eases back to
        # closed — it never snaps shut.
        if self.mode == "speaking":
            mw, mh = self._mouth_dims()
            mw, mh = int(mw * 1.615), int(mh * 1.615)  # avatar is 1.615x larger now
            # A mouth is wider than it is tall — clamp the height so the
            # overlay reads as an open mouth, not a round hole.
            if self._lip_shape in ("wide", "open"):
                mh = min(mh, int(mw * 0.7))
            elif self._lip_shape == "slight":
                mh = min(mh, int(mw * 0.5))
            mx, my = hx + look_x, hy + look_y + 61
            c.create_oval(mx - mw, my - mh, mx + mw, my + mh,
                          fill="#40160f", outline="")

    def _mouth_dims(self):
        """(half-width, half-height) for the mouth, from the eased
        lip level and the current phoneme shape. Returns a closed
        mouth (near-zero height) when not speaking."""
        level = self.lip_level if self.mode == "speaking" else 0.0
        shape = self._lip_shape if self.mode == "speaking" else "closed"
        if shape == "closed" or level < 0.04:
            return (7, 1)
        if shape == "slight":
            return (10, 2 + level * 4)
        if shape == "wide":
            return (16, 4 + level * 13)
        if shape == "round":
            return (8, 5 + level * 11)
        return (12, 3 + level * 9)  # "open"


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
        # No ring anymore: the head IS the face. It blinks, looks around,
        # nods, and its mouth actually moves while Oracle is speaking.
        # This is an original stylised head drawn in code, not a show asset.
        bob = math.sin(self.phase * 0.6) * 3
        nod = math.sin(self.phase * 2.2) * 2 if self.mode == "speaking" else 0
        look_x = math.sin(self.phase * 0.35) * 6
        look_y = -5 if self.mode == "thinking" else 0
        hx, hy = cx, cy - 12 + bob + nod

        # Soft aura behind the head (glow, not a ring)
        for r, col in [(178, _darken(t["accent"], 0.18)), (142, _darken(t["accent"], 0.28)),
                       (113, _darken(t["accent2"], 0.35))]:
            c.create_oval(hx - r, hy - r * 0.9, hx + r, hy + r * 0.9, fill=col, outline="")

        # --- The face: Muse avatar image if loaded, else vector head ---
        if self.avatar_photo is not None:
            self._draw_avatar(c, hx, hy, look_x, look_y)
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

            # Eyes: blink every few seconds, glow, pupils follow look_x
            blinking = (self.phase % 62) < 2.5
            eye_h = 3 if blinking else 20
            brow_lift = -6 if self.mode == "thinking" else (2 if self.mode == "speaking" else 0)
            for ex in (-34, 34):
                eye_cx, eye_cy = hx + ex, hy - 18 + look_y
                c.create_oval(eye_cx - 19, eye_cy - eye_h, eye_cx + 19, eye_cy + eye_h,
                              fill=t["accent"], outline="")
                if not blinking:
                    c.create_oval(eye_cx - 7 + look_x * 0.4, eye_cy - 7,
                                  eye_cx + 7 + look_x * 0.4, eye_cy + 7,
                                  fill="#04121a", outline="")
                    c.create_oval(eye_cx - 2 + look_x * 0.4, eye_cy - 4,
                                  eye_cx + 2 + look_x * 0.4, eye_cy, fill="#ffffff", outline="")
                # Eyebrow
                c.create_line(eye_cx - 20, eye_cy - 28 + brow_lift,
                              eye_cx + 20, eye_cy - 28 + brow_lift,
                              fill=t["accent2"], width=2)

            # Mouth: fluid lip-sync (v1.0.6) — same eased level and
            # phoneme shape as the avatar image, not a sine toggle.
            mouth_cy = hy + 48
            if self.mode == "speaking":
                mouth_w, mouth_h = self._mouth_dims()
                c.create_oval(hx - mouth_w, mouth_cy - mouth_h, hx + mouth_w, mouth_cy + mouth_h,
                              fill="#08101f", outline=t["accent2"], width=2)
                c.create_oval(hx - mouth_w * 0.55, mouth_cy + mouth_h * 0.25,
                              hx + mouth_w * 0.55, mouth_cy + mouth_h * 0.9,
                              fill=_darken(t["accent2"], 0.6), outline="")
            elif self.mode == "thinking":
                c.create_line(hx - 18, mouth_cy, hx + 18, mouth_cy, fill=t["accent"], width=3)
            else:
                c.create_arc(hx - 26, mouth_cy - 12, hx + 26, mouth_cy + 14,
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
        label = {"idle": "IDLE  •  AWAITING INPUT", "thinking": "THINKING  •  PROCESSING",
                 "speaking": "SPEAKING  •  RESPONDING"}.get(self.mode, "IDLE")
        try:
            self.mode_label.config(text=f"—  {label}  —",
                                   fg=t["warn"] if self.mode == "thinking" else t["accent"])
        except Exception:
            pass
        self.root.after(33, self.animate)  # ~30 fps for smooth lip-sync

    # ------------------------------------------------------------ speech / lip-sync
    def _on_speech_level(self, level, shape):
        """Called from voice.py's playback thread. NEVER touch
        tkinter here — just store the target; animate() (main
        thread) eases towards it."""
        self._lip_target_level = max(0.0, min(1.0, float(level)))
        self._lip_shape = shape if shape in ("closed", "slight", "open", "wide", "round") else "open"

    def _on_speech_done(self):
        """Called on the main thread when the spoken reply ends."""
        self._speech_done = True
        self._lip_target_level = 0.0
        self._lip_shape = "closed"
        self._maybe_finish_speaking()

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

    # ------------------------------------------------------------ API key (v1.0.6)
    def _api_key_status_text(self):
        """Never shows the key — only SET / NOT SET + last 4 chars."""
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            return "Key: NOT SET"
        return f"Key: SET  •  ****…{key[-4:]}"

    def _refresh_api_key_label(self):
        try:
            self.api_key_label.config(text=self._api_key_status_text())
        except Exception:
            pass

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

    def _show_api_key_dialog(self):
        import tkinter.simpledialog as _sd  # noqa: F401  (kept for symmetry)
        dlg = tk.Toplevel(self.root)
        dlg.title("Change API Key")
        dlg.geometry("460x240")
        dlg.transient(self.root)
        dlg.grab_set()
        tk.Label(dlg, text="Paste your new OpenAI API key below.",
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=16, pady=(14, 4))
        tk.Label(dlg, text="It is checked with a quick test call, then saved as a Windows\n"
                 "User environment variable on this PC only — never in source\ncode, logs, email, or GitHub. The running agent uses it at once.",
                 font=("Segoe UI", 9), justify="left").pack(anchor="w", padx=16, pady=(0, 8))
        entry = tk.Entry(dlg, font=("Segoe UI", 11), show="*", width=42)
        entry.pack(padx=16, fill="x")
        entry.focus_set()
        status = tk.Label(dlg, text=self._api_key_status_text(),
                          font=("Segoe UI", 9, "bold"))
        status.pack(anchor="w", padx=16, pady=(10, 4))
        btns = tk.Frame(dlg)
        btns.pack(padx=16, pady=8, fill="x")
        save_btn = tk.Button(btns, text="Save key", font=("Segoe UI", 10, "bold"))
        save_btn.pack(side="left", padx=(0, 8))
        tk.Button(btns, text="Cancel", font=("Segoe UI", 10),
                  command=dlg.destroy).pack(side="left")

        def _do_save():
            new_key = entry.get().strip()
            if not new_key:
                status.config(text="Paste a key first.", fg="red")
                return
            save_btn.config(state="disabled")
            status.config(text="Validating the key with OpenAI…", fg="black")
            def _run():
                ok, msg = self._validate_api_key(new_key)
                if ok:
                    self._set_user_env_var("OPENAI_API_KEY", new_key)
                    os.environ["OPENAI_API_KEY"] = new_key
                    self._post_ui(lambda: self._api_key_saved(dlg, status))
                else:
                    self._post_ui(lambda: self._api_key_failed(status, save_btn, msg))
            threading.Thread(target=_run, daemon=True).start()
        save_btn.config(command=_do_save)
        dlg.bind("<Return>", lambda _e: _do_save())

    def _api_key_saved(self, dlg, status):
        status.config(text="Key updated — the new key is active now.", fg="green")
        self._refresh_api_key_label()
        self.append("system", "API key updated — the new key is active now. (The key itself is never shown here.)")
        self._log_listening("API KEY: updated via GUI (key value not logged)")
        dlg.after(1200, dlg.destroy)

    def _api_key_failed(self, status, save_btn, msg):
        status.config(text=f"Key invalid — {msg}", fg="red")
        save_btn.config(state="normal")

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
        win.geometry("440x430+200+200")
        self.avatar_win = win
        canvas = tk.Canvas(win, width=440, height=400, bg="#000001",
                           highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        self._avatar_canvas = canvas
        if self.avatar_photo is not None:
            canvas.create_image(220, 200, image=self.avatar_photo, tags="avatar")
        else:
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
        self._avatar_only_animate()

    def _avatar_only_animate(self):
        """Keep the avatar's mouth moving in avatar-only mode."""
        if not self._avatar_mode or self.avatar_win is None:
            return
        try:
            target = self._lip_target_level if self.mode == "speaking" else 0.0
            self.lip_level += (target - self.lip_level) * (0.45 if target > self.lip_level else 0.25)
            c = self._avatar_canvas
            c.delete("mouth")
            if self.mode == "speaking":
                mw, mh = self._mouth_dims()
                mw, mh = int(mw * 1.615), int(mh * 1.615)
                c.create_oval(220 - mw, 261 - mh, 220 + mw, 261 + mh,
                              fill="#40160f", outline="", tags="mouth")
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
                import time as _time
                _time.sleep(0.5)
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
            on_alert=lambda txt: self._post_ui(lambda: self.append("system", txt)),
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

    # ------------------------------------------------ camera preview box
    # Small live preview in the lower right corner (2026-11-24,
    # Lorenza: "add like a small box in the lower right hand corner
    # of the GUI that shows what the camera's seeing"). Same feed
    # watch is using (camera.latest_frame, updated by the Watcher
    # loop) — no second camera open. place() overlay, anchored to
    # the window's lower right, just above the input bar so it never
    # covers SEND. Shows a plain message in the box when there is
    # no frame yet / the camera is off / it cannot open.
    def _build_cam_preview(self):
        frame = tk.Frame(self.root, bg=self.t["panel"], padx=1, pady=1)
        frame.place(relx=1.0, rely=1.0, x=-12, y=-62, anchor="se", width=232, height=152)
        tk.Label(frame, text="CAMERA", font=("Segoe UI", 8, "bold"),
                 fg=self.t["accent"], bg=self.t["panel"]).pack(anchor="w", padx=4)
        self._cam_preview_label = tk.Label(
            frame, text="Camera starting…", font=("Segoe UI", 9),
            fg=self.t["muted"], bg="#000000", width=28, height=7)
        self._cam_preview_label.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self._update_cam_preview()

    def _update_cam_preview(self):
        try:
            frame = None
            if camera_mod is not None:
                frame = getattr(camera_mod, "latest_frame", None)
            if frame is not None and Image is not None and self._cam_preview_label is not None:
                # OpenCV frames are BGR; convert to RGB for Pillow.
                rgb = frame[:, :, ::-1].copy()
                img = Image.fromarray(rgb)
                img = img.resize((224, 126), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self._cam_preview_photo = photo
                self._cam_preview_label.config(image=photo, text="")
            elif self._cam_preview_label is not None:
                if self.watcher is None:
                    msg = "Camera off" if self._camera_watch_user_stopped else "Camera starting…"
                else:
                    msg = "Camera on — waiting for frames…"
                self._cam_preview_label.config(image="", text=msg)
        except Exception as e:
            try:
                if self._cam_preview_label is not None:
                    self._cam_preview_label.config(image="", text=f"Camera preview error: {e}")
            except Exception:
                pass
        try:
            self.root.after(200, self._update_cam_preview)
        except Exception:
            pass

    def camera_ptz(self, pan, tilt, zoom):
        if self.camera_controller is None:
            self.append("system", "Start camera watch first, then use PTZ. Note: PIXY motor control is officially via EMEET Studio - OpenCV PTZ may be ignored, in which case Oracle uses digital framing and the camera's own AI tracking.")
            return
        result = self.camera_controller.ptz(pan_delta=pan, tilt_delta=tilt, zoom_delta=zoom)
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

    # ------------------------------------------------ auto-track (v1.0.8, item 7)
    def _refresh_track_button(self):
        try:
            self.track_btn.config(
                text=f"Auto-Track: {'ON' if self.auto_track_enabled else 'OFF'}")
        except Exception:
            pass

    def toggle_autotrack(self):
        self.auto_track_enabled = not self.auto_track_enabled
        if self.watcher is not None:
            self.append("system", self.watcher.set_auto_track(self.auto_track_enabled))
        else:
            self.append("system", f"Auto-Track will be {'ON' if self.auto_track_enabled else 'OFF'} when you start camera watch.")
        self._refresh_track_button()
        self._on_track_update({})

    def _on_track_update(self, _info):
        """Watcher thread -> main thread: show who is tracked/identified."""
        try:
            if self.watcher is not None:
                text = self.watcher.track_status_text()
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
        if low in ("stop tracking", "stop following", "stop following me"):
            self.append("user", user_text + ("  [spoken]" if spoken else ""))
            if not _need_watcher():
                return True
            self.auto_track_enabled = False
            self._refresh_track_button()
            self.append("system", watcher.stop_tracking())
            self._on_track_update({})
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
        # Camera tracking / face commands are handled locally, without
        # calling the LLM (v1.0.8, items 7 + 9).
        if self._handle_camera_command(user_text, spoken=spoken):
            return
        if self.busy:
            return
        self.busy = True
        self._typing_done = False
        self._speech_done = False
        self._ask_started = datetime.now()
        self.append("user", user_text + ("  [spoken]" if spoken else ""))
        self.history.append({"role": "user", "content": user_text})
        self.mode = "thinking"
        self.status.config(text="● THINKING", fg=self.t["warn"])
        threading.Thread(target=self._ask, args=(user_text,), daemon=True).start()

    def _ask(self, user_text):
        # Runs on a worker thread: never touch tkinter directly.
        # try/finally guarantees busy always clears, and every
        # outcome is logged, so a dead reply thread can no longer
        # leave the GUI stuck on THINKING forever.
        try:
            # "What do you see?" is a camera command, not a chat question:
            # pan left->right then right->left and describe everything,
            # instead of asking the LLM to guess without looking.
            if (camera_mod is not None
                    and hasattr(camera_mod, "is_pan_describe_request")
                    and camera_mod.is_pan_describe_request(user_text)):
                self._post_ui(lambda: self.append(
                    "system", "Panning the camera left to right, then right "
                    "to left, and describing everything I see..."))
                reply = self._run_pan_describe()
            elif call_llm is None:
                reply = "I could not load my brain (agent.py). Make sure agent.py is in the same folder as gui.py."
            else:
                # Memory (v1.0.7): what Oracle knows about Lorenza,
                # from Muse conversations and its own memory.json.
                # Read fresh on the worker thread each time so a
                # just-imported file is used in the very next reply.
                memory_text = ""
                if memory_import is not None:
                    try:
                        memory_text = memory_import.load_memory_text(APP_DIR)
                    except Exception:
                        memory_text = ""
                system = PERSONALITY
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
            self._post_ui(lambda r=reply: self._typewriter(r))
        except Exception as e:
            self._log_listening(f"ASK FAILED: {e}")
            self._post_ui(lambda err=e: self._typewriter(
                f"I hit a problem answering that: {err}. Please try again."))
        finally:
            # busy is cleared by _typewriter when the reply finishes
            # typing; the watchdog in _tick_clock clears it if the
            # reply never reaches the screen.
            pass

    def _typewriter(self, full_text, idx=0):
        # Runs on the main thread only (via _post_ui). Any exception
        # here must still clear busy, or the GUI sticks on THINKING.
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
                self.root.after(18, lambda: self._typewriter(full_text, idx + 3))
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
