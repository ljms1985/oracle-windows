"""Real lip rendering for Oracle (Windows) — visemes, not an oval.

Lorenza, 2026-11-24: "the animation for speech is still horrible.
When the agent is speaking, it's still just a hole where mouth
should be. Opening and closing. We need actual animation to where
his lips are actually moving." She was right: gui.py drew the
speaking mouth as a create_oval() whose height scaled with the
audio level, and voice.py's _lip_shape only changed that oval's
width/height. That is exactly a hole opening and closing.

This module draws an actual mouth: an upper lip and a lower lip
as filled shapes with a visible lip line, lip corners that move,
and teeth / tongue visible on open shapes. It is pure geometry
(stdlib only, no tkinter import) so it can be verified headlessly:
``lip_ops(half_w, level, shape)`` returns draw ops centred on
(0, 0); the caller offsets them to the mouth position and executes
them on a tkinter canvas (gui.py _draw_lips) or a PIL image (tests).

Visemes (shapes come from voice.py _shape_for_word, blended by the
live eased audio level, so the mouth moves continuously and closes
fully between words):
  * "closed" — lips together: upper + lower lip bands meeting at a
    thin dark lip line. NO dark interior at all — a still frame of
    this must never look like a hole.
  * "slight" — small opening: a thin dark slit, lips around it.
  * "open"   — medium opening, teeth band at the top.
  * "wide"   — a/e/i: wide opening, upper teeth clearly visible,
    tongue at the bottom when wide open.
  * "round"  — o/u/oo: pursed lips, narrower, small round opening,
    no teeth.
  * "fv"     — f/v: upper teeth resting on the lower lip, small
    dark slit below the teeth.

Ops are ("poly", [(x, y), ...], fill) — draw with smooth=True —
or ("line", [(x, y), ...], fill, width). All coordinates are
relative to the mouth centre; x is half-width units, y is vertical
(opening) units. Colours are chosen to read as lips both on the
anime avatar's skin and on the dark drawn fallback head.
"""

# Lip colours — muted rose-brown, not cartoon red, so they read as
# lips on skin and on the dark console alike.
LIP_UPPER = "#9c4636"
LIP_LOWER = "#b25a44"
LIP_LINE = "#33100a"
MOUTH_DARK = "#2a0a08"
TEETH = "#f5efe2"
TONGUE = "#8c3a3a"

SHAPES = ("closed", "slight", "open", "wide", "round", "fv")


def _upper_lip(w, oh):
    """Upper lip band: corners at (∓w, 0), cupid's bow dipping to
    (0, -oh - 5). Bottom edge follows the top of the opening."""
    return [(-w, 0), (-w * 0.55, -oh - 4.5), (-w * 0.18, -oh - 3.0),
            (0, -oh - 5.0), (w * 0.18, -oh - 3.0), (w * 0.55, -oh - 4.5),
            (w, 0), (w * 0.6, -oh * 0.45), (0, -oh * 0.6),
            (-w * 0.6, -oh * 0.45)]


def _lower_lip(w, oh):
    """Lower lip band: fuller than the upper lip, bottom edge
    dipping to (0, oh + 5)."""
    return [(-w, 0), (-w * 0.6, oh * 0.5), (0, oh * 0.65),
            (w * 0.6, oh * 0.5), (w, 0), (w * 0.55, oh + 4.5),
            (w * 0.18, oh + 3.5), (0, oh + 5.0), (-w * 0.18, oh + 3.5),
            (-w * 0.55, oh + 4.5)]


def _interior(w, oh):
    """Dark mouth cavity: corners at (∓w, 0), top (0, -oh),
    bottom (0, oh * 0.9)."""
    return [(-w, 0), (-w * 0.55, -oh * 0.75), (0, -oh),
            (w * 0.55, -oh * 0.75), (w, 0), (w * 0.55, oh * 0.65),
            (0, oh * 0.9), (-w * 0.55, oh * 0.65)]


def _teeth_band(w, oh):
    """Upper teeth: a band across the top of the opening, hanging
    BELOW the upper lip's lower edge (teeth emerge from under the
    lip — the old band sat behind the lip and was invisible).
    Top at -0.4*oh, bottom just above the centre line, narrower
    than the opening so the lip corners stay visible."""
    top = -oh * 0.4
    bottom = -oh * 0.05
    band = [(-w * 0.62, top), (w * 0.62, top),
            (w * 0.55, bottom), (-w * 0.55, bottom)]
    separators = []
    for fx in (-0.3, 0.0, 0.3):
        x = w * fx
        separators.append(("line", [(x, top + 1), (x, bottom - 1)],
                           "#c9bfa8", 1))
    return ("poly", band, TEETH), separators


def _tongue(w, oh):
    """Tongue: a rounded shape filling the bottom of a wide opening."""
    return ("poly", [(-w * 0.62, oh * 0.25), (0, oh * 0.95),
                     (w * 0.62, oh * 0.25), (w * 0.3, oh * 0.55),
                     (0, oh * 0.4), (-w * 0.3, oh * 0.55)], TONGUE)


def _lift_corners(ops, w, smile):
    """Smile: lift the outer points of the lip bands (corners rise,
    centre stays) so a smile reads in the lips, not just the eyes.
    Only lip-coloured polys are lifted, never teeth or tongue."""
    if smile <= 0:
        return ops
    lifted = []
    for op in ops:
        if op[0] == "poly" and op[2] in (LIP_UPPER, LIP_LOWER):
            pts = [(x, y - smile * 3.0 * (abs(x) / w) ** 2)
                   for (x, y) in op[1]]
            lifted.append(("poly", pts, op[2]))
        else:
            lifted.append(op)
    return lifted


def lip_ops(half_w, level, shape, smile=0.0):
    """Draw ops for one mouth frame, centred on (0, 0).

    half_w: mouth half-width in pixels (26 on the avatar image,
    16 on the drawn fallback head). level: eased audio level 0..1.
    shape: one of SHAPES. smile: 0..1, lifts the lip corners.
    Unknown shapes fall back to "open".
    The opening height grows with level and never snaps: at level 0
    every shape is (near-)closed, at level 1 fully open.
    """
    if shape not in SHAPES:
        shape = "open"
    level = max(0.0, min(1.0, float(level or 0.0)))
    smile = max(0.0, min(1.0, float(smile or 0.0)))
    w = float(half_w)

    if shape == "round":
        # Pursed lips: narrower, rounder opening.
        w = w * 0.62
        oh = 4.0 + level * 10.0
        ops = [("poly", _interior(w, oh), MOUTH_DARK),
               ("poly", _upper_lip(w, oh), LIP_UPPER),
               ("poly", _lower_lip(w, oh), LIP_LOWER)]
        return _lift_corners(ops, w, smile)

    if shape == "closed" or level < 0.04:
        # Lips together. No dark interior — this must never read
        # as a hole, even in a still frame. A smile turns the lip
        # line into an upward arc (corners up, centre down).
        w = w * 0.85
        line_y = (lambda x: -smile * 3.0 * (abs(x) / w) ** 2
                  + (1.0 - smile) * 0.8 * (1.0 - abs(x) / w))
        ops = [("poly", _upper_lip(w, 0.0), LIP_UPPER),
               ("poly", _lower_lip(w, 0.0), LIP_LOWER),
               ("line", [(-w, line_y(-w)), (-w * 0.4, line_y(-w * 0.4)),
                         (0, line_y(0.0)), (w * 0.4, line_y(w * 0.4)),
                         (w, line_y(w))], LIP_LINE, 2)]
        return _lift_corners(ops, w, smile)

    if shape == "fv":
        # Upper teeth resting on the lower lip: a teeth band
        # straddling the lip line (top above it, bottom below it),
        # small dark slit underneath, lower lip below that.
        w = w * 0.85
        oh = 2.0 + level * 3.0
        band = [(-w * 0.8, -4.0), (w * 0.8, -4.0),
                (w * 0.7, 2.5), (-w * 0.7, 2.5)]
        ops = [("poly", _interior(w * 0.9, oh), MOUTH_DARK),
               ("poly", band, TEETH)]
        for fx in (-0.35, 0.0, 0.35):
            x = w * fx
            ops.append(("line", [(x, -3.5), (x, 2.0)], "#c9bfa8", 1))
        ops.append(("poly", _lower_lip(w, oh), LIP_LOWER))
        return _lift_corners(ops, w, smile)

    # slight / open / wide: same construction, different opening.
    if shape == "slight":
        w = w * 0.8
        oh = 1.5 + level * 3.5
    elif shape == "wide":
        oh = 4.0 + level * 12.0
    else:  # "open"
        oh = 3.0 + level * 9.0
    ops = [("poly", _interior(w, oh), MOUTH_DARK)]
    if oh > 4.5:
        teeth, seps = _teeth_band(w, oh)
        ops.append(teeth)
        ops.extend(seps)
    if shape == "wide" and oh > 7.0:
        ops.append(_tongue(w, oh))
    ops.append(("poly", _upper_lip(w, oh), LIP_UPPER))
    ops.append(("poly", _lower_lip(w, oh), LIP_LOWER))
    return _lift_corners(ops, w, smile)
