"""Deform the avatar IMAGE itself (2026-11-24, Lorenza 22:31 EST).

RULE (her words, after seeing the v1.0.9 animation live): never draw
an animated mouth/blink layer ON TOP of the frozen avatar image.
That overlay is banned — it looked fake because the mouth was not
part of the face. Every motion must happen to the actual avatar
image: this module warps/deforms the image's own pixels.

Approach picked: regional mesh warp of the rendered avatar image
(PIL MESH, stdlib + Pillow only, no tkinter — headless-testable).
Why this one:
* The avatar is a single painted image — there are no separate
  mouth/eye layers to cut out, and cutting the mouth out of the
  painting would show seams.
* Redrawing the whole character as vector art would not be the
  same character.
* A mesh warp moves the painted pixels themselves: the mouth IN the
  image opens/closes, the eyes IN the image close, the whole head
  turns as one piece. Nothing floats over the face.

Two profiles (``deform_avatar(..., profile=...)``):
* ``"anime"`` — the red-and-black anime avatar (Mac/sale builds and
  the fallback). Render space 420x386, head-and-shoulders crop
  (430, 0, 1170, 680) of the 1600x1600 original, face centre
  (210, 193). Eyes (162, 212) and (262, 212); eye band y 196-228.
  Mouth (210, 250); mouth band y 238-272, mouth half-width 26.
  (Lip line measured at y 249-251 in the render.)
* ``"pencil"`` — Lorenza's PERSONAL Windows avatar (2026-11-24
  23:00 EST): the pencil sketch of her adult daughter, childhood
  portrait, signed ELM 2024. Render space 410x409 (the orb crop,
  native size — no resize distortion). Geometry re-measured
  2026-11-24 23:12 EST by visual grounding on the orb file itself
  plus a pixel-darkness profile of the file (not the phone
  screenshot): eyes (178, 156) and (241, 158); eye band y 144-170
  (brows sit at y 136-142 and stay OUT of the band); mouth centre
  (209, 209), corners (178, 207) and (240, 205), opening spans
  y ~194-220, mouth band y 192-226, mouth half-width 31.
  NOTE: the task's earlier "lip line y ~232" does NOT match this
  file — darkness drops off after y 220 and 232 is chin shading,
  so the warp pivots at the measured opening centre (209, 209).
  The pencil warp is GENTLER than the anime's (mouth_stretch 0.35
  vs 0.75, wide_stretch 0.12 vs 0.25): the sketch's smile is
  already open, so a full anime-strength stretch turns it into a
  cavern and smears the nose bottom down into the mouth. The blink
  collapses toward the upper-lid skin line (lid_y 146), NOT the
  eye line: the pencil eye line passes through the tall dark
  pupils, so sampling it stretches the pupils into staring
  vertical capsules — the opposite of a blink. Sampling lid skin
  closes the eye.

Honest limits:
* Anime: the painted image has a CLOSED mouth — there are no teeth
  or tongue painted in it to reveal. The warp opens and closes her
  own painted lips (the dark lip line stretches into an opening),
  and visemes differ in width/height, but it cannot conjure teeth
  that were never painted. Say so plainly; do not claim teeth appear.
* Pencil: the sketch's mouth is ALREADY an open smile with teeth
  drawn — that is the resting face, so "closed" is the drawn smile
  itself (the warp is identity at rest). Visemes modulate that
  smile (wide stretches it taller/wider, round pulls the corners
  in, fv barely opens) and the drawn teeth stretch with it. The
  warp cannot close the smile into a thin lip line the way a real
  mouth closes — say so plainly; the resting smile is the character.
  LIVE FINDING 2026-11-25 (screenshot proof on Lorenza's PC): the
  deform IS applied while speaking — the mouth region changes ~5x
  more than a static control region — but the stretch alone is
  perceptually invisible: the grin never closes, so there is no
  open/closed cycle for a viewer to see, and Lorenza rightly
  reports the mouth "stays closed". Fix (same deform, no overlay):
  while speaking, a low speech level now COMPRESSES the grin
  (``mouth_closed``) into a thin smile line, and a high level
  stretches it open — a real visible close/open cycle of the
  image's own pixels. At rest (not speaking) the portrait is
  untouched: the drawn grin is the idle face.

The warp is an inverse map: for each destination grid corner
(x, y) the source sample is (x - dx, y - dy), where (dx, dy) is
the forward displacement field at that point. Displacements are
small (<= ~14 px) and smooth, so no mesh cell inverts.
"""

from PIL import Image

# --- Geometry profiles -------------------------------------------------
# A profile is everything the warp needs to know about one face, in
# that face's own render space. The anime constants below it are kept
# as module-level names for back-compat (old tests import them).


class _Geom(object):
    __slots__ = ("w", "h", "face_cx", "face_cy", "mouth_cx", "mouth_cy",
                 "eye_centers", "eye_y0", "eye_y1", "mouth_y0",
                 "mouth_y1", "mouth_half_w", "eye_half", "x_cuts",
                 "y_cuts", "mouth_stretch", "wide_stretch", "lid_y",
                 "close_strength")

    def __init__(self, w, h, face_cx, face_cy, mouth_cx, mouth_cy,
                 eye_centers, eye_y0, eye_y1, mouth_y0, mouth_y1,
                 mouth_half_w, eye_half, x_cuts, y_cuts,
                 mouth_stretch=0.75, wide_stretch=0.25, lid_y=None,
                 close_strength=0.0):
        self.w, self.h = w, h
        self.face_cx, self.face_cy = face_cx, face_cy
        self.mouth_cx, self.mouth_cy = mouth_cx, mouth_cy
        self.eye_centers = eye_centers
        self.eye_y0, self.eye_y1 = eye_y0, eye_y1
        self.mouth_y0, self.mouth_y1 = mouth_y0, mouth_y1
        self.mouth_half_w = mouth_half_w
        self.eye_half = eye_half
        self.x_cuts, self.y_cuts = x_cuts, y_cuts
        # mouth_stretch: how hard the mouth opens (1 - k). The
        # anime needs 0.75 (closed line -> open); the pencil smile
        # is already open, so 0.35 modulates it without a cavern.
        # wide_stretch: how far the corners pull out/in (anime
        # 0.25, pencil 0.12). lid_y: the row the eye band collapses
        # toward on a blink (None = the eye line itself, which is
        # right for the anime's lash line but wrong for the pencil
        # — its eye line runs through the tall dark pupils).
        # close_strength: how hard a low speech level COMPRESSES
        # the mouth toward the lip line (k > 1). The anime's mouth
        # is already a closed line, so 0.0 (no compression). The
        # pencil's resting mouth is a wide open grin, so without
        # compression it can never visibly close: 0.45 squeezes
        # the 34 px mouth band to ~19 px — a thin smile line —
        # while a high level still stretches it open. This is the
        # same mesh warp, not an overlay: the image's own pixels.
        self.mouth_stretch = mouth_stretch
        self.wide_stretch = wide_stretch
        self.lid_y = lid_y
        self.close_strength = close_strength


PROFILES = {
    "anime": _Geom(
        420, 386, 210, 193, 210, 250,
        ((162, 212), (262, 212)), 196, 228, 238, 272, 26, 32,
        (0, 120, 138, 162, 184, 210, 236, 262, 286, 320, 420),
        (0, 170, 196, 212, 228, 238, 254, 272, 300, 386)),
    "pencil": _Geom(
        410, 409, 209, 170, 209, 209,
        ((178, 156), (241, 158)), 144, 170, 192, 226, 31, 28,
        (0, 120, 148, 178, 196, 209, 224, 241, 262, 300, 410),
        (0, 120, 144, 157, 170, 192, 209, 226, 260, 300, 409),
        mouth_stretch=0.35, wide_stretch=0.12, lid_y=146,
        close_strength=0.45),
}

# Render-space geometry for the default (anime) profile.
_ANIME = PROFILES["anime"]
IMG_W, IMG_H = _ANIME.w, _ANIME.h
FACE_CX, FACE_CY = _ANIME.face_cx, _ANIME.face_cy
MOUTH_CX, MOUTH_CY = _ANIME.mouth_cx, _ANIME.mouth_cy
EYE_CENTERS = _ANIME.eye_centers

# Mesh grid cuts (anime). Dense around the eyes and mouth so the warp
# follows the features; coarse elsewhere (hair, shoulders, bg).
_X_CUTS = _ANIME.x_cuts
_Y_CUTS = _ANIME.y_cuts

# Viseme -> (vertical open factor, horizontal wide factor).
# wide pulls the mouth corners out; round pulls them in and opens
# taller than wide; fv barely opens (upper teeth on lower lip);
# closed/slight are near-shut.
_SHAPE_PARAMS = {
    "closed": (0.0, 0.0),
    "slight": (0.35, 0.0),
    "open": (0.8, 0.25),
    "wide": (1.0, 1.0),
    "round": (0.85, -1.0),
    "fv": (0.30, 0.0),
}

_SMILE_PX = 3.0          # max mouth-corner lift


def _bump(v, centre, half_width):
    """Triangular bump: 1 at centre, 0 beyond half_width. Never < 0."""
    d = abs(v - centre) / float(half_width)
    return max(0.0, 1.0 - d) if d < 1.0 else 0.0


def _displacement(x, y, mouth_k, wide_amount, blink, look_x, smile,
                  geom):
    """Forward displacement (dx, dy) of the source pixel at (x, y).

    The vertical mouth/blink motion is LINEAR in the distance from
    the feature line, so the PIL mesh (which interpolates linearly
    between grid corners) reproduces it exactly — a smooth bump
    peaked inside a mesh cell is averaged away by the interpolation
    and the eye never fully closes / the mouth never fully opens.
    * Mouth: dest rows show source rows squeezed toward the lip
      line (k < 1 stretches the mouth open; k > 1 compresses it
      toward the lip line — the pencil's close, since its resting
      mouth is an open grin); corners move out (wide_amount > 0)
      or in (wide_amount < 0, the pencil's close); smile lifts the
      corners.
    * Blink: dest rows show source rows squeezed toward the eye
      line (k = 1 - blink); at blink = 1 the whole eye band samples
      the eye line itself — the painted eye is shut.
    * Look: the eye band shifts a little with the gaze (small, so
      the bump form is fine here); smile's corner lift is small too.
    """
    dx = 0.0
    dy = 0.0
    # --- mouth (linear stretch/compress around the lip line) ---
    if mouth_k != 1.0 or wide_amount != 0.0 or smile > 0.0:
        wx = _bump(x, geom.mouth_cx, 60)  # local to the mouth width
        if wx > 0.0:
            if geom.mouth_y0 <= y <= geom.mouth_y1 and mouth_k != 1.0:
                dy += (y - geom.mouth_cy) * (1.0 - mouth_k) * wx
            if wide_amount != 0.0:
                kx = 1.0 - geom.wide_stretch * wide_amount
                dx += (x - geom.mouth_cx) * (1.0 - kx) * _bump(
                    y, geom.mouth_cy, 25)
            if smile > 0.0:
                corner = (_bump(x, geom.mouth_cx - geom.mouth_half_w, 14)
                          + _bump(x, geom.mouth_cx + geom.mouth_half_w, 14))
                dy -= _SMILE_PX * smile * corner * _bump(
                    y, geom.mouth_cy, 15)
    # --- blink (linear squeeze toward the lid line) + gaze ---
    # At blink = 1 the whole eye band samples the lid line itself —
    # the painted eye is shut. The lid line is the eye line for the
    # anime (its dark lash line closes the eye); for the pencil it
    # is the upper-lid skin row above the eye (sampling the eye
    # line there would stretch the tall dark pupils into capsules).
    if blink > 0.0 or look_x != 0.0:
        for (ex, ey) in geom.eye_centers:
            exb = _bump(x, ex, geom.eye_half)
            if exb <= 0.0:
                continue
            lid_y = geom.lid_y if geom.lid_y is not None else ey
            if blink > 0.0 and geom.eye_y0 <= y <= geom.eye_y1:
                dy += (y - lid_y) * blink * exb
            if look_x != 0.0:
                dx += look_x * 0.4 * _bump(y, ey, 18) * exb
    return dx, dy


def _mouth_params(geom, mouth_open, mouth_shape, mouth_closed):
    """(mouth_k, wide_amount) for one frame: the vertical mesh scale
    (k < 1 stretches the mouth open, k > 1 compresses it toward
    the lip line) and the signed horizontal corner pull (-1..1).
    Shared by deform_avatar() and the tests, so the warp the tests
    measure is the warp the GUI draws."""
    open_v, wide_f = _SHAPE_PARAMS.get(mouth_shape, (0.0, 0.0))
    open_eff = mouth_open * open_v
    mouth_k = 1.0 - geom.mouth_stretch * open_eff \
        + geom.close_strength * mouth_closed
    mouth_k = max(0.4, min(1.6, mouth_k))
    wide_amount = max(-1.0, min(1.0, wide_f * open_eff
                                 - 0.8 * mouth_closed
                                 * (1.0 if geom.close_strength else 0.0)))
    return mouth_k, wide_amount


def _mesh(mouth_k, wide_amount, blink, look_x, smile, geom):
    """PIL MESH list for the current frame's warp.

    Destination boxes tile the whole image; each box's quad is the
    source quadrilateral, from the inverse displacement at its four
    corners. Identity where the field is zero.

    Quad order matters (PIL reads it as upper-left, LOWER-left,
    lower-right, upper-right) — passing NW/NE/SE/SW twists the
    mapping and scrambles the image, so the corners are reordered
    explicitly here.
    """
    mesh = []
    for j in range(len(geom.y_cuts) - 1):
        y0, y1 = geom.y_cuts[j], geom.y_cuts[j + 1]
        for i in range(len(geom.x_cuts) - 1):
            x0, x1 = geom.x_cuts[i], geom.x_cuts[i + 1]
            corners = []
            for (cx, cy) in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                dx, dy = _displacement(cx, cy, mouth_k, wide_amount,
                                       blink, look_x, smile, geom)
                corners.append((cx - dx, cy - dy))
            nw, ne, se, sw = corners
            mesh.append(((x0, y0, x1, y1),
                         (nw[0], nw[1],
                          sw[0], sw[1],
                          se[0], se[1],
                          ne[0], ne[1])))
    return mesh


def deform_avatar(base, *, mouth_open=0.0, mouth_shape="closed",
                  blink=0.0, look_x=0.0, look_y=0.0, tilt_deg=0.0,
                  smile=0.0, profile="anime", mouth_closed=0.0):
    """Return a new RGBA image: ``base`` (the rendered avatar, in the
    profile's render space — 420x386 anime, 410x409 pencil) with its
    own mouth/eyes warped and the whole head tilted.

    * ``profile`` selects the face geometry: ``"anime"`` (default,
      the red-and-black anime avatar) or ``"pencil"`` (Lorenza's
      personal pencil-drawing avatar). Unknown profiles fall back to
      anime. The base image must already be in that profile's size;
      a wrong-size base is still warped (the mesh tiles the base's
      own size) but the features will not line up — callers must
      load the matching image (see gui._load_avatar).
    * ``mouth_open`` 0..1 is the eased live speech level; the viseme
      (``mouth_shape``: closed/slight/open/wide/round/fv) sets how
      tall vs wide the opening is. Closed + 0.0 returns ``base``
      unchanged (same object — callers must not mutate it). For the
      pencil profile, "closed" is the drawn open smile itself.
    * ``mouth_closed`` 0..1 is how firmly the mouth is shut WHILE
      SPEAKING (the GUI passes 1 - lip_level while speaking, 0
      otherwise). Only the pencil profile uses it: its resting
      mouth is a wide open grin, so a low speech level must
      COMPRESS that grin into a thin smile line (k > 1) or the
      mouth can never visibly close — the stretch-only warp was
      proven live on 2026-11-25 to move the mouth pixels without
      any visible open/close cycle. The anime profile ignores it
      (its resting mouth is already a closed line). Still the same
      mesh warp of the image's own pixels — never an overlay.
    * ``blink`` 0..1 closes the painted eyes themselves.
    * ``look_x``/``look_y`` shift the gaze (eye band only, subtle).
      look_y is accepted for API symmetry and currently unused —
      the painted eyes have no vertical gaze range worth faking.
    * ``tilt_deg`` rotates the WHOLE image around the face centre
      (the head turns as one piece); positive = tilt right.
    * ``smile`` 0..1 lifts the mouth corners of the image itself.

    The returned image is the same size as ``base``. Raises nothing
    for out-of-range inputs — values are clamped.
    """
    geom = PROFILES.get(profile, PROFILES["anime"])
    mouth_open = max(0.0, min(1.0, float(mouth_open)))
    mouth_closed = max(0.0, min(1.0, float(mouth_closed)))
    blink = max(0.0, min(1.0, float(blink)))
    smile = max(0.0, min(1.0, float(smile)))
    tilt_deg = max(-10.0, min(10.0, float(tilt_deg)))
    mouth_k, wide_amount = _mouth_params(geom, mouth_open, mouth_shape,
                                         mouth_closed)
    if abs(mouth_k - 1.0) < 0.01 and abs(wide_amount) < 0.02 \
            and blink < 0.02 and smile < 0.02 \
            and abs(tilt_deg) < 0.05 and abs(look_x) < 0.1:
        return base
    img = base.transform(base.size, Image.MESH,
                         _mesh(mouth_k, wide_amount, blink, look_x, smile,
                               geom),
                         Image.BILINEAR)
    if abs(tilt_deg) >= 0.05:
        img = img.rotate(-tilt_deg, resample=Image.BILINEAR,
                         center=(geom.face_cx, geom.face_cy),
                         fillcolor=(0, 0, 0, 0))
    return img
