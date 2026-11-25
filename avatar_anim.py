"""Avatar animation director for Oracle — full parity with Muse's
phone avatar animation, reproduced from observable behaviour.

HONEST LIMIT: there is no Muse avatar source code to copy — nobody
on this project has it, and this module does not claim to copy it.
It reproduces what can be SEEN on the phone: idle breathing and
bob, natural blinking, a wandering gaze, nods, head tilt, state-
tied expressions, and laugh / surprise reactions — all eased at
~30 fps, never snapping. Pure stdlib (time / math / random): no
tkinter, so it is headless-testable. gui.py animate() calls
``frame()`` every tick and applies the returned parameters to the
canvas; the painted avatar image itself limits some expression
(the image's brows and eyes are painted on, so brow/eye reshaping
shows fully only on the drawn fallback head — on the image the
personality comes from head motion, gaze, lips and timing).

Behaviour, all continuous:
  * Idle life — breathing (slow ~4.5 s cycle), gentle bob layered
    on it, slow sway. Never a frozen still image.
  * Eyes — blinking at human timing: intervals randomised 2.2–6 s
    (never a fixed metronome), fast close / slower open, occasional
    double-blink. Gaze wanders to a new target every 1.2–3.5 s and
    eases there; while listening the gaze narrows and centres on the
    speaker; while thinking it drifts up / aside.
  * Head — nods while speaking (amplitude follows the speech
    level), slight tilt when thinking or curious, small wobble
    while laughing, lean-in while listening, lean BACK while
    thinking, a small shrug when unsure, a warm side-to-side
    greeting wave on hello / goodbye. (A literal hand-wave is
    impossible on a bust/shoulders image with no visible hand,
    so the wave is a head-and-shoulders greeting sway + smile,
    not a drawn hand.)
  * Expressions (eased weights, 0..1) — thinking, listening,
    happy/smile, confused (one brow up + tilt), laugh, surprise
    (both brows up, eyes wide). Reactions are triggered by the
    reply text (see reaction_for_reply) and decay on their own.
  * Smoothness — every parameter approaches its target
    exponentially per frame; nothing jumps between frames.
"""

import math
import random
import re
import time

# Reaction durations (seconds).
LAUGH_SECONDS = 2.5
SURPRISE_SECONDS = 1.5
HAPPY_SECONDS = 3.0
SHRUG_SECONDS = 1.2
WAVE_SECONDS = 2.0

_GREETING_WORDS = ("hello", "hi there", "hey there", "good morning",
                   "good afternoon", "good evening", "goodbye",
                   "bye for now", "see you")
_UNSURE_WORDS = ("i'm not sure", "i don't know", "i dont know",
                 "not sure", "no idea", "i'm afraid i don't know")

_LAUGH_WORDS = ("haha", "hehe", "lol", "😂", "🤣", "that's funny",
                "thats funny", "hilarious", "too funny")
_SURPRISE_WORDS = ("wow", "really?!", "oh!", "no way", "seriously?",
                   "you're kidding", "unbelievable")
_HAPPY_WORDS = ("congratulations", "that's wonderful", "thats wonderful",
                "awesome", "love that", "great news", "brilliant")


def reaction_for_reply(reply):
    """What the avatar should do on this reply: 'laugh', 'surprise',
    'happy', 'shrug' (unsure), 'wave' (greeting / goodbye) or None.
    Pure text markers — a laugh is only shown when the reply itself
    is funny / surprising / good news; a wave only when the reply
    opens with a greeting or closes with a goodbye; a shrug only
    when the reply itself says it does not know."""
    low = " " + (reply or "").lower() + " "
    stripped = (reply or "").strip().lower()
    if any(stripped.startswith(w) for w in _GREETING_WORDS) \
            or any(w in low for w in ("goodbye", "bye for now", "see you")):
        return "wave"
    if any(w in low for w in _LAUGH_WORDS):
        return "laugh"
    if any(w in low for w in _SURPRISE_WORDS):
        return "surprise"
    if any(w in low for w in _HAPPY_WORDS):
        return "happy"
    if any(w in low for w in _UNSURE_WORDS):
        return "shrug"
    return None


def _approach(current, target, rate, dt):
    """Exponential approach: rate ~ how fast (per second)."""
    if dt <= 0:
        return target
    a = 1.0 - math.exp(-rate * dt)
    return current + (target - current) * a


class AvatarAnimator:
    """Per-frame animation state. Call set_mode() when the GUI mode
    changes, react() on a reaction, and frame() every ~33 ms."""

    def __init__(self, rng=None):
        self.rng = rng if rng is not None else random.Random()
        self.mode = "idle"
        self.t0 = time.monotonic()
        self._last_t = self.t0
        # Blink state machine.
        self._next_blink_in = self.rng.uniform(2.0, 4.0)
        self._blink_t0 = None
        self._blink_duration = 0.16
        self._blink_double = False
        # Gaze.
        self._gaze_target = (0.0, 0.0)
        self._gaze = [0.0, 0.0]
        self._next_gaze_in = 1.0
        # Eased expression weights.
        self._tilt = 0.0
        self._smile = 0.0
        self._brow_l = 0.0
        self._brow_r = 0.0
        self._eye_wide = 0.0
        self._lean = 0.0
        self._shrug = 0.0
        self._wave = 0.0
        # Reaction: (kind, ends_at_monotonic) or None.
        self._reaction = None
        self._reaction_t0 = 0.0
        self._reaction_until = 0.0

    # ------------------------------------------------------------ inputs

    def set_mode(self, mode):
        if mode in ("idle", "listening", "thinking", "speaking"):
            self.mode = mode

    def react(self, kind, now=None):
        """Start a laugh / surprise / happy / shrug / wave reaction."""
        if kind not in ("laugh", "surprise", "happy", "shrug", "wave"):
            return
        now = time.monotonic() if now is None else now
        seconds = {"laugh": LAUGH_SECONDS, "surprise": SURPRISE_SECONDS,
                   "happy": HAPPY_SECONDS, "shrug": SHRUG_SECONDS,
                   "wave": WAVE_SECONDS}[kind]
        self._reaction = kind
        self._reaction_t0 = now
        self._reaction_until = now + seconds

    # ------------------------------------------------------------ frame

    def frame(self, now=None, lip_level=0.0):
        """One frame of animation parameters. ``now`` is monotonic
        seconds (defaults to time.monotonic()); lip_level 0..1 is
        the eased speech level, which drives speaking nods."""
        now = time.monotonic() if now is None else now
        dt = max(0.0, min(0.1, now - self._last_t))
        self._last_t = now
        t = now - self.t0
        reaction = self._reaction
        if reaction is not None and now >= self._reaction_until:
            reaction = None
            self._reaction = None

        # --- breathing + bob + sway (idle life, always on) ---
        breathe = math.sin(2.0 * math.pi * t / 4.5) * 2.2
        bob = math.sin(2.0 * math.pi * t / 1.8) * 1.4
        sway = math.sin(2.0 * math.pi * t / 7.0) * 3.0
        # Speaking nod: amplitude follows the live speech level.
        nod = 0.0
        if self.mode == "speaking":
            nod = math.sin(2.0 * math.pi * t / 0.9) * 2.0 * lip_level
        bob_y = breathe + bob + nod
        if reaction == "laugh":
            # Laugh bounce: quick extra bob on top of everything.
            bob_y += abs(math.sin(2.0 * math.pi * t / 0.35)) * 3.0

        # --- blink: human timing, never a metronome ---
        blink = self._blink_closure(now, dt)

        # --- gaze: random WALK (small steps from where the eyes
        # already are, never a teleport), eased to the target.
        # Listening narrows the range onto the speaker; thinking
        # drifts the eyes up / aside.
        self._next_gaze_in -= dt
        if self._next_gaze_in <= 0:
            self._next_gaze_in = self.rng.uniform(1.2, 3.5)
            if self.mode == "listening":
                gx = max(-3.0, min(3.0, self._gaze[0] + self.rng.uniform(-3.0, 3.0)))
                gy = max(-2.0, min(2.0, self._gaze[1] + self.rng.uniform(-2.0, 2.0)))
            elif self.mode == "thinking":
                gx = max(-7.0, min(7.0, self._gaze[0] + self.rng.uniform(-4.0, 4.0)))
                gy = max(-8.0, min(0.0, self._gaze[1] + self.rng.uniform(-4.0, 0.0)))
            else:
                gx = max(-7.0, min(7.0, self._gaze[0] + self.rng.uniform(-4.0, 4.0)))
                gy = max(-4.0, min(4.0, self._gaze[1] + self.rng.uniform(-3.0, 3.0)))
            self._gaze_target = (gx, gy)
        self._gaze[0] = _approach(self._gaze[0], self._gaze_target[0], 4.0, dt)
        self._gaze[1] = _approach(self._gaze[1], self._gaze_target[1], 4.0, dt)

        # --- expression targets by mode / reaction ---
        tilt_t = 0.0
        smile_t = 0.0
        brow_l_t = 0.0
        brow_r_t = 0.0
        eye_wide_t = 0.0
        lean_t = 0.0
        if self.mode == "thinking":
            tilt_t = 6.0
            brow_l_t = 4.0  # one brow up: curious, thinking
            lean_t = -0.8  # lean BACK while thinking
        elif self.mode == "listening":
            lean_t = 1.0  # lean in, attentive
            eye_wide_t = 0.4
        # Shrug / wave envelopes (0..1): a shrug rises and falls
        # once; a wave stays up while the GUI sways it side to
        # side, then fades. Both decay with the timed reaction.
        shrug_t = 0.0
        wave_t = 0.0
        if reaction in ("shrug", "wave"):
            dur = max(0.01, self._reaction_until - self._reaction_t0)
            frac = max(0.0, min(1.0, (now - self._reaction_t0) / dur))
            if reaction == "shrug":
                shrug_t = math.sin(math.pi * frac)
            else:
                wave_t = 1.0 - frac
                smile_t = 1.0  # a greeting wave is a warm smile too
        if reaction == "laugh":
            smile_t = 1.0
            tilt_t = 3.0 * math.sin(2.0 * math.pi * t / 0.7)
            brow_l_t = -2.0
            brow_r_t = -2.0
            eye_wide_t = -0.5  # laughing squint
        elif reaction == "surprise":
            brow_l_t = 7.0
            brow_r_t = 7.0
            eye_wide_t = 1.0
        elif reaction == "happy":
            smile_t = 1.0
        # Confused is set by the GUI via set_confused() below; it is
        # a standing expression, not a timed reaction.
        if getattr(self, "_confused", False):
            brow_l_t = 6.0
            brow_r_t = 1.0
            tilt_t = -5.0
        self._tilt = _approach(self._tilt, tilt_t, 5.0, dt)
        self._smile = _approach(self._smile, smile_t, 4.0, dt)
        self._brow_l = _approach(self._brow_l, brow_l_t, 6.0, dt)
        self._brow_r = _approach(self._brow_r, brow_r_t, 6.0, dt)
        self._eye_wide = _approach(self._eye_wide, eye_wide_t, 6.0, dt)
        self._lean = _approach(self._lean, lean_t, 3.0, dt)
        self._shrug = _approach(self._shrug, shrug_t, 8.0, dt)
        self._wave = _approach(self._wave, wave_t, 6.0, dt)

        return {
            "bob_y": bob_y,
            "sway_x": sway,
            "lean": self._lean,
            "shrug": self._shrug,  # 0..1, shoulders lift
            "wave": self._wave,    # 0..1, greeting sway envelope
            "blink": blink,          # 0 open .. 1 fully closed
            "look_x": self._gaze[0],
            "look_y": self._gaze[1],
            "tilt_deg": self._tilt,
            "smile": self._smile,    # 0 .. 1, lifts lip corners
            "brow_l": self._brow_l,  # px brow lift, left
            "brow_r": self._brow_r,  # px brow lift, right
            "eye_wide": self._eye_wide,  # -0.5 squint .. 1 wide
        }

    def set_confused(self, confused):
        """Standing 'confused / unsure' expression (one brow up,
        tilt). The GUI sets it when the reply says it is unsure."""
        self._confused = bool(confused)

    # ------------------------------------------------------------ blink

    def _blink_closure(self, now, dt):
        """Eyelid closure 0..1. Blinks are scheduled at randomised
        human intervals; the lid closes fast and opens slower."""
        if self._blink_t0 is None:
            self._next_blink_in -= dt
            if self._next_blink_in <= 0:
                self._blink_t0 = now
                self._blink_duration = self.rng.uniform(0.13, 0.19)
                self._blink_double = self.rng.random() < 0.10
            return 0.0
        elapsed = now - self._blink_t0
        if elapsed >= self._blink_duration:
            self._blink_t0 = None
            if self._blink_double:
                # Second blink of a double-blink, sooner.
                self._blink_double = False
                self._next_blink_in = self.rng.uniform(0.12, 0.25)
            else:
                self._next_blink_in = self.rng.uniform(2.2, 6.0)
            return 0.0
        frac = elapsed / self._blink_duration
        if frac < 0.4:
            return frac / 0.4  # fast close
        return 1.0 - (frac - 0.4) / 0.6  # slower open
