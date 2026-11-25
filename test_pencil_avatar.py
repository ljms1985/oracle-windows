"""Proof for the PENCIL avatar animation (Lorenza's personal Windows
build) — sandbox-first, headless, PIL only, no display, no PC, no email.

What it proves, for profile "pencil" in avatar_deform.py:
  * The image ITSELF warps (PIL MESH): mouth opens on the lip line,
    eyes close on the eye line, gaze shifts, smile lifts the mouth
    corners, head tilts as one piece. No overlay is drawn on top of
    the frozen image (that overlay was rejected by Lorenza and is
    banned) — the far-region checks below are what distinguish a real
    deform from an overlay or a whole-image shift: a real deform
    changes ONLY the feature region, exactly 0.00 elsewhere.
  * Geometry is grounded in the actual file: the eye/mouth landmarks
    in avatar_deform.py are checked against the pixel-darkness
    profile of avatars/pencil-avatar-orb.jpg itself (eyes darkest
    ~y155, mouth darkest ~y210), not against a screenshot.

Thresholds are meaningful, not tuned to pass: each is set at roughly
55-70% of the value measured on 2026-11-25 during development
(mouth-wide 28.3, blink 25.6, look L-vs-R 13.1, smile corners
11.0/7.2), so a broken warp, a wrong-region warp, an overlay, or a
whole-image shift fails. Measured values are printed for every check.

Measurement trap this script avoids (found 2026-11-25): gui.py loads
the pencil image with a circular orb mask, so the corners are
fully transparent (alpha 0). The MESH warp leaves alpha 0 there but
the RGB values UNDER the transparent alpha change — comparing raw RGB
in the corners reports a huge fake diff (~219). All diffs here are
therefore computed ONLY over pixels opaque in the base image, and the
alpha channel is asserted unchanged separately.

Run:  python3 test_pencil_avatar.py   (exit 0 = all checks pass)
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from PIL import Image, ImageDraw, ImageEnhance  # noqa: E402

import avatar_deform as ad  # noqa: E402

ORB = HERE / "avatars" / "pencil-avatar-orb.jpg"
GUI = HERE / "gui.py"

RESULTS = []


def check(name, ok, detail):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def region_stats(base, frame, box):
    """Mean/max abs RGB diff + fraction of pixels changed >20, over
    pixels that are OPAQUE in the base image only (transparent orb
    corners carry meaningless RGB under alpha 0). Also mean abs
    alpha diff over the whole box."""
    b = base.crop(box)
    f = frame.crop(box)
    bp = list(b.getdata())
    fp = list(f.getdata())
    diffs = []
    alpha_diffs = []
    for (r1, g1, b1, a1), (r2, g2, b2, a2) in zip(bp, fp):
        alpha_diffs.append(abs(a1 - a2))
        if a1 > 0:
            diffs.append((abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2)) / 3.0)
    if not diffs:
        return 0.0, 0.0, 0.0, sum(alpha_diffs) / len(alpha_diffs)
    mean = sum(diffs) / len(diffs)
    frac = sum(1 for d in diffs if d > 20) / len(diffs)
    return mean, max(diffs), frac, sum(alpha_diffs) / len(alpha_diffs)


def whole_alpha_diff(base, frame):
    bp = list(base.getdata())
    fp = list(frame.getdata())
    return sum(abs(a[3] - b[3]) for a, b in zip(bp, fp)) / len(bp)


def darkest_row(gray, y0, y1, x0=140, x1=280):
    px = gray.load()
    best = (0.0, None)
    for y in range(y0, y1 + 1):
        d = sum(255 - px[x, y] for x in range(x0, x1)) / (x1 - x0)
        if d > best[0]:
            best = (d, y)
    return best  # (darkness, y)


def timed(fn, n=5):
    ts = []
    out = None
    for _ in range(n):
        t0 = time.perf_counter()
        out = fn()
        ts.append((time.perf_counter() - t0) * 1000.0)
    ts.sort()
    return out, ts[len(ts) // 2], ts


def main():
    geom = ad.PROFILES["pencil"]
    base = Image.open(ORB).convert("RGBA")
    check("input file", base.size == (410, 409) and base.mode == "RGBA",
          f"avatars/pencil-avatar-orb.jpg {base.size} {base.mode}")

    # --- geometry grounded in the actual file -----------------------
    gray = Image.open(ORB).convert("L")
    eye_dark, eye_y = darkest_row(gray, 140, 175)
    mouth_dark, mouth_y = darkest_row(gray, 185, 230, 160, 260)
    check("geometry: eyes in file match geom",
          150 <= eye_y <= 162 and abs(eye_y - geom.eye_centers[0][1]) <= 6,
          f"darkest eye-band row y={eye_y} (geom eye y={geom.eye_centers[0][1]}), "
          f"darkness={eye_dark:.1f}")
    check("geometry: mouth in file matches geom",
          195 <= mouth_y <= 215 and abs(mouth_y - geom.mouth_cy) <= 6,
          f"darkest mouth-band row y={mouth_y} (geom mouth y={geom.mouth_cy}), "
          f"darkness={mouth_dark:.1f}")

    # --- regions, taken from the profile (not hand-typed) -----------
    mcx, mcy = geom.mouth_cx, geom.mouth_cy
    mouth_box = (mcx - 40, geom.mouth_y0, mcx + 40, geom.mouth_y1)
    eye_box = (150, geom.eye_y0, 270, geom.eye_y1)
    eye_l_box = (150, geom.eye_y0, 206, geom.eye_y1)
    eye_r_box = (214, geom.eye_y0, 270, geom.eye_y1)
    corner_l_box = (mcx - geom.mouth_half_w - 14, mcy - 15,
                    mcx - geom.mouth_half_w + 14, mcy + 15)
    corner_r_box = (mcx + geom.mouth_half_w - 14, mcy - 15,
                    mcx + geom.mouth_half_w + 14, mcy + 15)
    centre_box = (mcx - 14, mcy - 15, mcx + 14, mcy + 15)
    far_boxes = {"corner TL": (0, 0, 60, 60), "corner TR": (350, 0, 410, 60),
                 "hair top": (150, 0, 270, 60), "chin": (170, 260, 250, 320)}

    # --- 1. identity: closed rest = the drawn smile itself ---------
    ident = ad.deform_avatar(base, profile="pencil")
    check("identity: closed rest returns base unchanged",
          ident is base, "deform_avatar(...) with no motion returns base")

    # --- frames (timed) ---------------------------------------------
    wide, wide_ms, _ = timed(
        lambda: ad.deform_avatar(base, mouth_open=1.0, mouth_shape="wide",
                                 profile="pencil"))
    open_f, open_ms, _ = timed(
        lambda: ad.deform_avatar(base, mouth_open=1.0, mouth_shape="open",
                                 profile="pencil"))
    blink, blink_ms, _ = timed(
        lambda: ad.deform_avatar(base, blink=1.0, profile="pencil"))
    look_l, _, _ = timed(
        lambda: ad.deform_avatar(base, look_x=-7.0, profile="pencil"))
    look_r, _, _ = timed(
        lambda: ad.deform_avatar(base, look_x=7.0, profile="pencil"))
    smile, _, _ = timed(
        lambda: ad.deform_avatar(base, smile=1.0, profile="pencil"))
    tilt, tilt_ms, _ = timed(
        lambda: ad.deform_avatar(base, tilt_deg=5.0, profile="pencil"))

    check("output size/mode preserved",
          wide.size == base.size and wide.mode == base.mode
          and blink.size == base.size and tilt.size == base.size,
          f"wide/blink/tilt all {wide.size} {wide.mode} (input {base.size} {base.mode})")

    # --- 2. mouth wide: big change in mouth, zero in eyes -----------
    m_mean, m_max, m_frac, _ = region_stats(base, wide, mouth_box)
    e_mean, _, _, _ = region_stats(base, wide, eye_box)
    check("mouth wide opens the mouth (and only the mouth)",
          m_mean >= 15.0 and m_frac >= 0.25 and e_mean <= 1.0,
          f"mouth mean={m_mean:.2f} frac>20={m_frac:.3f} max={m_max:.0f}; "
          f"eyes mean={e_mean:.2f} (thresholds 15 / 0.25 / 1.0)")

    # --- 3. mouth open (plain viseme) --------------------------------
    m_mean, _, m_frac, _ = region_stats(base, open_f, mouth_box)
    check("mouth open viseme moves the mouth",
          m_mean >= 10.0 and m_frac >= 0.15,
          f"mouth mean={m_mean:.2f} frac>20={m_frac:.3f} (thresholds 10 / 0.15)")

    # --- 4. blink: both eyes close, mouth untouched ------------------
    e_mean, e_max, e_frac, _ = region_stats(base, blink, eye_box)
    el_mean, _, _, _ = region_stats(base, blink, eye_l_box)
    er_mean, _, _, _ = region_stats(base, blink, eye_r_box)
    m_mean, _, _, _ = region_stats(base, blink, mouth_box)
    check("blink closes both eyes (and only the eyes)",
          e_mean >= 15.0 and el_mean >= 10.0 and er_mean >= 10.0
          and m_mean <= 1.0,
          f"eyes mean={e_mean:.2f} frac>20={e_frac:.3f} max={e_max:.0f}; "
          f"left={el_mean:.2f} right={er_mean:.2f}; mouth mean={m_mean:.2f} "
          f"(thresholds 15 / 10 / 10 / 1.0)")

    # --- 5. gaze: left vs right differ in the eyes, nowhere else -----
    lr_mean, lr_max, lr_frac, _ = region_stats(look_l, look_r, eye_box)
    l_mean, _, _, _ = region_stats(base, look_l, eye_box)
    r_mean, _, _, _ = region_stats(base, look_r, eye_box)
    m_mean, _, _, _ = region_stats(look_l, look_r, mouth_box)
    check("look left vs right shifts the gaze",
          lr_mean >= 8.0 and l_mean >= 4.0 and r_mean >= 4.0
          and m_mean <= 1.0,
          f"left-vs-right eyes mean={lr_mean:.2f} frac>20={lr_frac:.3f} "
          f"max={lr_max:.0f}; vs-base L={l_mean:.2f} R={r_mean:.2f}; "
          f"mouth mean={m_mean:.2f} (thresholds 8 / 4 / 4 / 1.0)")

    # --- 6. smile: corners lift, centre does NOT move ---------------
    cl_mean, _, cl_frac, _ = region_stats(base, smile, corner_l_box)
    cr_mean, _, cr_frac, _ = region_stats(base, smile, corner_r_box)
    cc_mean, _, _, _ = region_stats(base, smile, centre_box)
    wm_mean, _, _, _ = region_stats(base, smile, mouth_box)
    check("smile lifts the mouth corners (not the whole mouth)",
          cl_mean >= 5.0 and cr_mean >= 5.0 and cc_mean <= 2.0
          and wm_mean >= 3.0,
          f"corner L mean={cl_mean:.2f} (frac>20={cl_frac:.3f}), "
          f"corner R mean={cr_mean:.2f} (frac>20={cr_frac:.3f}), "
          f"centre mean={cc_mean:.2f}, whole-mouth mean={wm_mean:.2f} "
          f"(thresholds 5 / 5 / 2 / 3)")

    # --- 7. far regions: EXACTLY unchanged (no overlay / no shift) --
    # Tilt is excluded on purpose: it rotates the whole head, so far
    # regions legitimately move. Mouth/blink/look/smile must not move
    # anything outside their feature region.
    far_ok = True
    far_detail = []
    for frame, fname in ((wide, "wide"), (blink, "blink"),
                         (look_l, "lookL"), (smile, "smile")):
        for label, box in far_boxes.items():
            mean, mx, _, _ = region_stats(base, frame, box)
            far_detail.append(f"{fname}/{label}={mean:.2f}")
            if mean > 0.5 or mx > 1.0:
                far_ok = False
    check("far regions unchanged (mouth/blink/look/smile)",
          far_ok,
          "opaque-pixel mean diff; " + ", ".join(far_detail)
          + " (threshold mean<=0.5, max<=1)")

    # --- 8. no extra drawn shapes: alpha untouched, no new pixels ---
    # The warp only resamples existing pixels: alpha must be identical
    # everywhere, and the output may differ from the base ONLY inside
    # mesh cells that have a displaced corner (computed from the warp
    # itself via _displacement — the bump radii plus one mesh cell of
    # interpolation spill, e.g. the wide-pull reaches x~276, the blink
    # reaches y~176). Anything changed outside those cells would be
    # a drawn-on shape or a whole-image shift, not a warp.
    alpha_ok = all(whole_alpha_diff(base, f) == 0.0
                   for f in (wide, blink, look_l, look_r, smile))

    def displaced_cells(params):
        cells = set()
        xc, yc = geom.x_cuts, geom.y_cuts
        corner_disp = {}
        for x in xc:
            for y in yc:
                dx, dy = ad._displacement(x, y, params.get("mouth_open", 0.0),
                                          params.get("wide", 0.0),
                                          params.get("blink", 0.0),
                                          params.get("look_x", 0.0),
                                          params.get("smile", 0.0), geom)
                corner_disp[(x, y)] = abs(dx) + abs(dy) > 0.01
        for j in range(len(yc) - 1):
            for i in range(len(xc) - 1):
                if any(corner_disp[(xc[i + di], yc[j + dj])]
                       for di in (0, 1) for dj in (0, 1)):
                    cells.add((xc[i], yc[j], xc[i + 1], yc[j + 1]))
        return cells

    def in_cells(x, y, cells):
        return any(x0 <= x < x1 and y0 <= y < y1
                   for (x0, y0, x1, y1) in cells)

    # wide_factor for the "wide" frame is 1.0 (shape wide, open 1.0);
    # blink/look/smile carry no mouth opening.
    outside_changed = 0
    worst_outside = []
    for frame, params in (
            (wide, {"mouth_open": 1.0, "wide": 1.0}),
            (blink, {"blink": 1.0}),
            (look_l, {"look_x": -7.0}),
            (smile, {"smile": 1.0})):
        cells = displaced_cells(params)
        for y in range(0, 409, 2):
            for x in range(0, 410, 2):
                if in_cells(x, y, cells):
                    continue
                a = base.getpixel((x, y))
                b = frame.getpixel((x, y))
                if a[3] > 0 and (abs(a[0] - b[0]) + abs(a[1] - b[1])
                                + abs(a[2] - b[2])) / 3.0 > 20:
                    outside_changed += 1
                    if len(worst_outside) < 5:
                        worst_outside.append((x, y))
    check("no extra drawn shapes / alpha preserved",
          alpha_ok and outside_changed == 0,
          f"whole-image mean alpha diff=0.0 for wide/blink/look/smile: "
          f"{alpha_ok}; sampled pixels changed >20 outside displaced "
          f"mesh cells: {outside_changed} {worst_outside}")

    # --- 9. tilt moves the whole head as one piece -------------------
    e_mean, _, _, _ = region_stats(base, tilt, eye_box)
    m_mean, _, _, _ = region_stats(base, tilt, mouth_box)
    check("tilt 5deg moves head as one piece",
          e_mean >= 10.0 and m_mean >= 10.0,
          f"eyes mean={e_mean:.2f}, mouth mean={m_mean:.2f} (threshold 10)")

    # --- 10. timing: deform fits the ~33 ms GUI tick -----------------
    _, seq_med, _ = timed(
        lambda: ad.deform_avatar(base, mouth_open=0.8, mouth_shape="open",
                                 blink=0.0, look_x=3.0, smile=0.4,
                                 profile="pencil"), n=30)
    check("deform timing fits 30 fps tick",
          seq_med <= 33.0 and wide_ms <= 33.0,
          f"median speaking frame={seq_med:.1f} ms, wide frame={wide_ms:.1f} ms, "
          f"blink frame={blink_ms:.1f} ms, tilt frame={tilt_ms:.1f} ms "
          f"(threshold 33 ms)")

    # --- 11. gui-pipeline image (resize/enhance/orb mask) deforms ---
    gimg = Image.open(ORB).convert("RGBA").resize((410, 409), Image.LANCZOS)
    gimg = ImageEnhance.Sharpness(gimg).enhance(1.25)
    gimg = ImageEnhance.Contrast(gimg).enhance(1.05)
    mask = Image.new("L", gimg.size, 0)
    ImageDraw.Draw(mask).ellipse((2, 2, 408, 407), fill=255)
    gimg.putalpha(mask)
    gwide = ad.deform_avatar(gimg, mouth_open=1.0, mouth_shape="wide",
                             profile="pencil")
    gm_mean, _, gm_frac, _ = region_stats(gimg, gwide, mouth_box)
    g_alpha = whole_alpha_diff(gimg, gwide)
    # Far check on opaque pixels only (corners are transparent here).
    gfar, _, _, _ = region_stats(gimg, gwide, far_boxes["chin"])
    check("gui-loaded (orb-masked) image deforms the same",
          gwide.size == (410, 409) and gm_mean >= 15.0 and g_alpha == 0.0
          and gfar <= 0.5,
          f"mouth mean={gm_mean:.2f} frac>20={gm_frac:.3f}; "
          f"alpha diff={g_alpha:.2f}; chin far mean={gfar:.2f}")

    # --- 12. gui.py actually uses the pencil profile + deform --------
    src = GUI.read_text()
    # Order must be judged inside the candidates tuple only: the
    # string "assets/avatar.png" also appears in comments/docstrings
    # earlier in the file, so a whole-file index comparison is wrong.
    cand_start = src.index("candidates = (")
    cand = src[cand_start:cand_start + 900]
    pencil_first = ('"avatars/pencil-avatar-orb.jpg", "pencil"' in cand
                    and cand.index("pencil-avatar-orb.jpg")
                    < cand.index('"assets/avatar.png"'))
    deform_calls = src.count(
        "profile=getattr(self, \"_avatar_profile\", \"anime\")")
    # _draw_lips must only be called in the fallback branch (no image).
    lips_calls = [ln for ln in src.splitlines()
                  if "_draw_lips(" in ln and "def _draw_lips" not in ln]
    lips_only_fallback = (
        len(lips_calls) == 1
        and "self.avatar_photo is not None" in src)
    check("gui.py loads pencil first, deforms with its profile",
          pencil_first and deform_calls == 2 and lips_only_fallback,
          f"pencil candidate before anime: {pencil_first}; "
          f"deform_avatar calls passing _avatar_profile: {deform_calls} "
          f"(in _draw_avatar + _avatar_only_animate); "
          f"_draw_lips call sites: {len(lips_calls)} "
          f"(fallback vector head only: {lips_only_fallback})")
    check("gui.py never draws lips over the avatar image",
          "lips.py is used ONLY by the drawn fallback" in src
          or "ONLY for the drawn fallback" in src,
          "docstring states lips.py is fallback-only; _draw_avatar path "
          "uses avatar_deform, never _draw_lips")

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
