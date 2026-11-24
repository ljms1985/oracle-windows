# Oracle Avatar — Windows GUI

## What was added (2026-11-24, v3)

Lorenza asked for the Windows (and Mac) Oracle agents to have an avatar
exactly like Muse's avatar runs. The Windows GUI now shows her chosen
Muse avatar as its face, animated the same way.

**Avatar:** muscular anime male, long spiky black hair, blue eyes,
light facial stubble, red gi with black trim, black undershirt, blue
sash — the red-and-black one she picked for Muse on 2026-11-24.

**Source image:** `workspace/avatars/avatar-1795504357733091975-0.webp`
(1600×1600, full-body figure on a white background), converted to:

- `assets/avatar.png` (1600×1600, RGBA)
- `avatar.png` (same file, top-level copy — `gui.py` checks both)

The white background was removed by flood-fill from the image edges
(near-white pixels connected to the border made transparent), so
interior whites — the eyes, highlights — stay opaque and the figure
sits cleanly on the dark console instead of in a white box.

## How it is animated (gui.py)

Tkinter only, plus Pillow for the image. No video files, no heavy
dependencies — this is a still image animated with canvas overlays,
the way the drawn head was animated before.

- **Load:** `_load_avatar()` in `gui.py` opens `assets/avatar.png`
  (fallback `avatar.png`, then `assets/avatar.webp`), crops to head
  + shoulders — crop box (430, 0, 1170, 680) in the 1600×1600 original
  — and resizes to 260×239 with LANCZOS. Requires Pillow; the
  setup guide already lists `pip install pillow`.
- **Idle bob:** the whole image bobs ±3 px on a slow sine, same as
  the old head.
- **Look-around:** the image shifts ±6 px horizontally on a slow
  sine, and −5 px vertically while thinking.
- **Nod:** ±2 px vertical while speaking.
- **Blink:** every ~3 seconds (phase % 62 < 2.5) a skin-coloured bar
  (`#fbe0c0`, sampled from the face) plus a dark eyelid line is drawn
  over each eye. Eye centres are at (−30, +12) and (+32, +12) from
  the face centre at the 260×239 display size — measured from the
  source pixels (eyes ~y375 in the original) and checked against
  live GUI screenshots.
- **Mouth while speaking:** a small dark oval (`#40160f`, ±11 px wide,
  height 2–9 px, opening/closing on a sine) is drawn over the smile
  at (0, +38) from the face centre (mouth ~y445 in the original).
  It is deliberately small so it reads as an open mouth, not a patch.
  While idle the original smile shows; while thinking the mouth is
  left as drawn.
- **Fallback:** if Pillow is missing or no avatar file is found,
  `avatar_photo` stays `None` and `animate()` draws the original
  Gideon-inspired vector head in code instead. The GUI never crashes
  on a missing image.

All other features are untouched. `computer.py` was **not** changed
in this update — the job-hunting tools from v2 are exactly as they
were. Voice, camera, repair, 3D, monitor, identity and the rest are
unchanged.

## Testing done (Linux VM, 2026-11-24)

- `python3 -m py_compile` on all 12 `.py` files in
  `~/workspace/friend-agent/`: **all pass**.
- Live GUI run under Xvfb (`xvfb-run`): GUI opened, avatar loaded
  (`Avatar: loaded assets/avatar.png (260x239)`), animation frames
  ran in idle / thinking / speaking modes, blink + speaking frames
  ran, and the missing-image fallback drew the vector head correctly.
  Screenshots were taken and the eye/mouth overlay positions were
  corrected twice from them (first mouth oval was too big and sat
  on the chin; final oval sits on the smile).
- Screenshots: idle and speaking frames verified visually — avatar
  is clean on the dark background, no white box.

## Still needs testing on a real Windows PC

- First real run of `python gui.py` on Windows with the avatar:
  confirm Pillow installs (`pip install pillow` — already in the
  setup guide), the image loads, and the animation looks right at
  the real window size / DPI scaling (Windows display scaling may
  make the 260×239 avatar look smaller or larger than on Linux).
- Blink and mouth overlays at real size — the offsets were measured
  on Linux screenshots; if the avatar looks misaligned on Windows,
  adjust the eye/mouth offsets in `_draw_avatar()` in `gui.py`.
- This is a 2D still-image animation, not a rigged Live2D / video
  avatar: the mouth is an overlay oval and the blink is an overlay
  bar. It moves like Muse's avatar in the sense of bob / blink /
  look / nod / talk, but it is not frame-by-frame lip-sync — the
  mouth opens and closes on a sine while speaking, it does not track
  individual sounds.
- Replacing the avatar: drop a new PNG over `assets/avatar.png`
  (same head-and-shoulders framing works best) and restart the GUI.
  If the new image has a different face position, the eye/mouth
  offsets in `_draw_avatar()` will need re-measuring.
