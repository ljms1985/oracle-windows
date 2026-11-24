"""
3D design for Oracle - create print-ready STL files from a specification,
and suggest improvements, asking before applying them.

No external libraries required for the core shapes. This uses only
Python's standard library + math, so it runs on Windows with plain
Python. For complex CAD (fillets, booleans, threads), the next step
is to add CadQuery / Build123d - see 3D_KNOWLEDGE.md - but the
primitives here already cover most everyday prints accurately.

How Oracle should use this:
  1. You give a specification in plain language or as a dict, e.g.:
       {"shape": "box", "width_mm": 60, "depth_mm": 40, "height_mm": 20,
        "wall_mm": 2, "hole_diameter_mm": 5}
     or {"shape": "cylinder", "diameter_mm": 30, "height_mm": 15}
     or {"shape": "phone_stand", "phone_width_mm": 75, "angle_deg": 65}
  2. Oracle validates it for printing (see validate_spec()).
  3. Oracle runs suggest_improvements(spec) and ASKS you, one by one:
       "I notice this overhang is over 45°, so it will need supports.
        Would you like me to add a chamfer / split it / orient it
        differently instead?"
     Nothing in that list is applied unless you say yes.
  4. Only then does it write the STL, in millimetres, to prints/.

Units: ALWAYS millimetres. STL files themselves have no unit - slicers
assume mm for most FDM printers, so Oracle must confirm mm with you
if a spec is ambiguous.

Print-ready checks (validate_spec):
  * Size fits a typical bed (default 220 x 220 x 250 mm, configurable)
  * Wall / feature thickness >= 0.8 mm (a 0.4 mm nozzle can barely do
    less, and it will be fragile)
  * Overhangs > 45° from vertical will need supports - flagged, not hidden
  * Holes: a printed hole usually comes out ~0.2-0.4 mm smaller than
    designed, so Oracle adds that clearance for bolts / screws unless
    you say the hole is decorative
  * Moving parts: 0.2-0.3 mm clearance per side; press-fit: 0.1-0.2 mm

Run a test:
  python design3d.py
  -> creates prints/test-box.stl and prints/test-cylinder.stl
"""

import json
import math
import os
from pathlib import Path

# Frozen (.exe) builds: writable data (memory, workspace, credentials,
# prints, alerts, ...) must live NEXT TO Oracle.exe, not in PyInstaller's
# temp _MEIPASS folder (deleted on exit). oracle_paths.app_dir() returns
# exactly that when frozen, and the source folder when running from source.
try:
    from oracle_paths import app_dir as _oracle_app_dir
    BASE_DIR = _oracle_app_dir()
except Exception:
    BASE_DIR = Path(__file__).resolve().parent
PRINTS_DIR = BASE_DIR / "prints"
BED_X, BED_Y, BED_Z = 220, 220, 250
MIN_WALL_MM = 0.8
MM_PER_INCH = 25.4


# ---------------------------------------------------------------- units: mm and inches

def inches_to_mm(inches):
    return float(inches) * MM_PER_INCH


def mm_to_inches(mm):
    return float(mm) / MM_PER_INCH


def format_both(mm_value):
    """Show a dimension in both units, e.g. '127.0 mm (5.00 in)'."""
    return f"{float(mm_value):.1f} mm ({mm_to_inches(mm_value):.2f} in)"


def parse_length(value, default_unit="mm"):
    """
    Parse a dimension given as a number, or as a string like
    '5 in', '5"', '5 inch', '127 mm', '127'.
    Returns mm as a float. This is how Oracle works in both units:
    you can say inches or millimetres, and it converts accurately.
    """
    if isinstance(value, (int, float)):
        return float(value) * MM_PER_INCH if default_unit in ("in", "inch", "inches", '"') else float(value)
    text = str(value).strip().lower().replace("inches", "in").replace("inch", "in")
    # Handle 5" notation
    is_inch = text.endswith('"') or text.endswith("in") or text.endswith("in.")
    is_mm = text.endswith("mm")
    num_text = text.replace('"', "").replace("in.", "").replace("in", "").replace("mm", "").strip()
    try:
        num = float(num_text)
    except Exception:
        raise ValueError(f"Could not parse dimension: {value!r}")
    if is_inch:
        return num * MM_PER_INCH
    if is_mm:
        return num
    # No unit in the string - use the spec's default unit
    return num * MM_PER_INCH if default_unit in ("in", "inch", "inches") else num


def normalize_spec(spec):
    """
    Convert any spec to mm internally, whatever unit it was given in.
    Accepts:
      * {"length_mm": 127, "unit": "mm"}
      * {"length_mm": 5, "unit": "in"}  -> length_mm becomes 127
      * {"length": "5 in", "width": "3 in"}
      * {"length_in": 5, "width_in": 3, "base_height_in": 2}
      * {"length_mm": "5 in"}  -> string with its own unit wins
    Returns a new spec dict with all dimensions in mm, plus
    "unit": "mm" and "original_unit" preserved for display.
    STL files themselves have no unit, so the STL is always written
    in mm (what slicers expect) - but Oracle always shows you both
    mm and inches, so you can check it in whichever unit you think in.
    """
    spec = dict(spec)
    original_unit = spec.get("unit", "mm")
    out = {}
    # First, handle *_in keys
    for key, value in spec.items():
        if key.endswith("_in"):
            out[key[:-3] + "_mm"] = parse_length(value, default_unit="in")
        elif key.endswith("_mm"):
            # If the spec unit is inches and the value is a plain number,
            # it is actually inches - convert it. Strings with their own
            # unit win over the spec unit.
            if isinstance(value, str):
                out[key] = parse_length(value, default_unit=original_unit)
            elif original_unit in ("in", "inch", "inches"):
                out[key] = float(value) * MM_PER_INCH
            else:
                out[key] = float(value)
        elif key in ("length", "width", "depth", "height", "diameter", "base_height", "wall"):
            out[key + "_mm"] = parse_length(value, default_unit=original_unit)
        else:
            out[key] = value
    out["unit"] = "mm"
    out["original_unit"] = original_unit
    return out


def describe_spec(spec_mm):
    """Human-readable dimensions in both units."""
    parts = []
    for key in ("length_mm", "width_mm", "depth_mm", "height_mm", "base_height_mm", "diameter_mm", "wall_mm"):
        if key in spec_mm:
            parts.append(f"{key.replace('_mm', '')}: {format_both(spec_mm[key])}")
    return ", ".join(parts) if parts else "No dimensions in spec."


# ---------------------------------------------------------------- STL core

def _normal(p1, p2, p3):
    ux, uy, uz = p2[0]-p1[0], p2[1]-p1[1], p2[2]-p1[2]
    vx, vy, vz = p3[0]-p1[0], p3[1]-p1[1], p3[2]-p1[2]
    nx, ny, nz = uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
    length = math.sqrt(nx*nx + ny*ny + nz*nz) or 1
    return (nx/length, ny/length, nz/length)


def write_stl(path, triangles, name="oracle"):
    """triangles: list of (p1, p2, p3), each point is (x, y, z) in mm."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"solid {name}\n")
        for p1, p2, p3 in triangles:
            n = _normal(p1, p2, p3)
            f.write(f"  facet normal {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}\n    outer loop\n")
            for p in (p1, p2, p3):
                f.write(f"      vertex {p[0]:.4f} {p[1]:.4f} {p[2]:.4f}\n")
            f.write("    endloop\n  endfacet\n")
        f.write(f"endsolid {name}\n")
    return str(path)


def box_triangles(w, d, h, cx=0, cy=0, cz=0):
    x0, x1 = cx - w/2, cx + w/2
    y0, y1 = cy - d/2, cy + d/2
    z0, z1 = cz, cz + h
    v = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
             (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    tris = []
    for a, b, c, dd in quads:
        tris.append((v[a], v[b], v[c]))
        tris.append((v[a], v[c], v[dd]))
    return tris


def cylinder_triangles(diameter, height, segments=48, cx=0, cy=0, cz=0):
    r = diameter / 2
    tris = []
    bottom, top = [], []
    for i in range(segments):
        a1 = 2 * math.pi * i / segments
        a2 = 2 * math.pi * (i + 1) / segments
        p1 = (cx + r*math.cos(a1), cy + r*math.sin(a1), cz)
        p2 = (cx + r*math.cos(a2), cy + r*math.sin(a2), cz)
        p3 = (cx + r*math.cos(a2), cy + r*math.sin(a2), cz + height)
        p4 = (cx + r*math.cos(a1), cy + r*math.sin(a1), cz + height)
        tris.append((p1, p2, p3))
        tris.append((p1, p3, p4))
        bottom.append(p1)
        top.append(p4)
    centre_b = (cx, cy, cz)
    centre_t = (cx, cy, cz + height)
    for i in range(segments):
        tris.append((centre_b, bottom[(i+1) % segments], bottom[i]))
        tris.append((centre_t, top[i], top[(i+1) % segments]))
    return tris


def sphere_triangles(diameter, segments=32, rings=16, cx=0, cy=0, cz=0):
    r = diameter / 2
    tris = []
    def pt(i, j):
        theta = 2 * math.pi * i / segments
        phi = math.pi * j / rings
        return (cx + r*math.sin(phi)*math.cos(theta),
                cy + r*math.sin(phi)*math.sin(theta),
                cz + r*math.cos(phi))
    for j in range(rings):
        for i in range(segments):
            p1 = pt(i, j); p2 = pt((i+1) % segments, j)
            p3 = pt((i+1) % segments, j+1); p4 = pt(i, j+1)
            if j != 0:
                tris.append((p1, p2, p3))
            if j != rings - 1:
                tris.append((p1, p3, p4))
    return tris


def extrude_polygon_triangles(points_2d, height):
    """Extrude a 2D polygon (list of (x, y)) straight up by height mm."""
    if len(points_2d) < 3:
        raise ValueError("Extrusion needs at least 3 points.")
    tris = []
    bottom = [(x, y, 0) for x, y in points_2d]
    top = [(x, y, height) for x, y in points_2d]
    n = len(points_2d)
    for i in range(n):
        j = (i + 1) % n
        tris.append((bottom[i], bottom[j], top[j]))
        tris.append((bottom[i], top[j], top[i]))
    # Fan caps - works for convex polygons; for concave shapes, use a
    # proper triangulation library (e.g. triangulate / shapely) in v2.
    for i in range(1, n - 1):
        tris.append((bottom[0], bottom[i+1], bottom[i]))
        tris.append((top[0], top[i], top[i+1]))
    return tris


# ---------------------------------------------------------------- validation + suggestions

def validate_spec(spec):
    """Return a list of warnings - empty means print-ready on first pass."""
    warnings = []
    w = spec.get("width_mm", spec.get("diameter_mm", 0))
    d = spec.get("depth_mm", spec.get("diameter_mm", 0))
    h = spec.get("height_mm", 0)
    if w > BED_X or d > BED_Y or h > BED_Z:
        warnings.append(f"Too large for a {BED_X}x{BED_Y}x{BED_Z} mm bed: {w}x{d}x{h} mm. Split it, scale it, or use a larger printer.")
    wall = spec.get("wall_mm")
    if wall is not None and wall < MIN_WALL_MM:
        warnings.append(f"Wall {wall} mm is below the {MIN_WALL_MM} mm minimum for a 0.4 mm nozzle - it will be fragile or may not slice. Increase to at least 1.2 mm for strength.")
    if spec.get("overhang_deg", 0) > 45:
        warnings.append(f"Overhang {spec['overhang_deg']}° is over 45° - it will need supports, or a chamfer / re-orientation would avoid them.")
    if spec.get("hole_diameter_mm") and spec["hole_diameter_mm"] < 3:
        warnings.append("Small holes print 0.2-0.4 mm smaller than designed. For a bolt hole, add 0.3 mm clearance, or drill it out after printing.")
    return warnings


def suggest_improvements(spec):
    """
    Return improvement ideas. Oracle must ASK about each one before
    applying it - see apply_suggestions_with_approval().
    Each suggestion is (title, explanation, apply_function_name).
    """
    suggestions = []
    if spec.get("shape") in ("box", "bracket", "phone_stand", "chest"):
        suggestions.append((
            "Add fillets / rounded corners",
            "Sharp 90° corners warp and crack more easily, and feel sharp in the hand. Rounding corners by 2-3 mm usually prints cleaner and is stronger.",
            "fillet",
        ))
    if spec.get("height_mm", 0) > 40 and spec.get("wall_mm", 2) < 2:
        suggestions.append((
            "Add ribs or thicken walls",
            "Tall, thin walls flex and can snap. Adding a rib or thickening to 2-3 mm makes it much stiffer for almost no extra print time.",
            "thicken",
        ))
    if spec.get("overhang_deg", 0) > 45:
        suggestions.append((
            "Replace the overhang with a 45° chamfer",
            "A 45° chamfer prints without supports, so you get a cleaner underside and a faster print than support material would give.",
            "chamfer",
        ))
    if spec.get("shape") == "phone_stand":
        suggestions.append((
            "Add a cable slot and a lip at the front",
            "A small slot for the charging cable and a 5 mm lip stop the phone sliding off when you tap it, without changing the look much.",
            "phone_lip",
        ))
    # Always offer orientation / strength as a check, not an automatic change.
    suggestions.append((
        "Check orientation for strength",
        "Parts are weakest between layers. If this will take load, printing it on its side (so the load is across layers, not pulling them apart) is often stronger. I can re-orient it if you want.",
        "orient",
    ))
    return suggestions


def apply_suggestions_with_approval(spec, ask):
    """
    ask(title, explanation) -> True/False, supplied by Oracle's chat loop.
    In the GUI / terminal, ask() is input(). In tests, it can be a lambda.
    Returns (new_spec, applied_titles).
    """
    applied = []
    for title, explanation, key in suggest_improvements(spec):
        if ask(title, explanation):
            applied.append(title)
            # Apply the idea in the spec, in a simple, reversible way.
            if key == "fillet":
                spec["corner_radius_mm"] = 3
            elif key == "thicken":
                spec["wall_mm"] = max(spec.get("wall_mm", 2), 3)
            elif key == "chamfer":
                spec["overhang_deg"] = 45
            elif key == "phone_lip":
                spec["lip_mm"] = 5
                spec["cable_slot"] = True
            elif key == "orient":
                spec["orientation_note"] = "Print on side for layer strength, if load-bearing."
    return spec, applied


# ---------------------------------------------------------------- chest

def _half_cylinder_lid(length, width, base_z, segments=32):
    """Half-cylinder treasure-chest lid, axis along X, flat side down."""
    r = width / 2
    tris = []
    # Side surface: angles 0..pi in the Y-Z plane
    for i in range(segments):
        a1 = math.pi * i / segments
        a2 = math.pi * (i + 1) / segments
        y1, z1 = r * math.cos(a1), base_z + r * math.sin(a1)
        y2, z2 = r * math.cos(a2), base_z + r * math.sin(a2)
        x0, x1 = -length / 2, length / 2
        tris.append(((x0, y1, z1), (x1, y1, z1), (x1, y2, z2)))
        tris.append(((x0, y1, z1), (x1, y2, z2), (x0, y2, z2)))
    # End caps (fan from centre of the semicircle)
    for x in (-length / 2, length / 2):
        centre = (x, 0, base_z)
        for i in range(segments):
            a1 = math.pi * i / segments
            a2 = math.pi * (i + 1) / segments
            p1 = (x, r * math.cos(a1), base_z + r * math.sin(a1))
            p2 = (x, r * math.cos(a2), base_z + r * math.sin(a2))
            tris.append((centre, p2, p1) if x < 0 else (centre, p1, p2))
    return tris


def chest_triangles(spec):
    """
    A chest: open-top base (bottom + 4 walls) + a lid on top.
    Spec keys (mm unless noted):
      length_mm (default 127 = 5 inch), width_mm (default 80),
      base_height_mm (default 50), wall_mm (default 2),
      lid_style: "flat" or "curved" (default "curved" - treasure chest),
      lid_height_mm: for flat lids, thickness; for curved, ignored (radius = width/2)
    For a functional, openable chest, print the base and lid as
    separate STLs - see create_chest_stls(). The single-STL version
    here is a closed chest model, good for display / sizing checks.
    """
    spec = normalize_spec(spec)
    length = spec.get("length_mm", 127)
    width = spec.get("width_mm", 80)
    base_h = spec.get("base_height_mm", 50)
    wall = spec.get("wall_mm", 2)
    lid_style = spec.get("lid_style", "curved")
    tris = []
    # Bottom
    tris += box_triangles(length, width, wall, cx=0, cy=0, cz=0)
    # Front / back walls
    tris += box_triangles(length, wall, base_h, cx=0, cy=width/2 - wall/2, cz=wall)
    tris += box_triangles(length, wall, base_h, cx=0, cy=-width/2 + wall/2, cz=wall)
    # Side walls
    tris += box_triangles(wall, width - 2*wall, base_h, cx=length/2 - wall/2, cy=0, cz=wall)
    tris += box_triangles(wall, width - 2*wall, base_h, cx=-length/2 + wall/2, cy=0, cz=wall)
    # Lid, sitting on top of the base
    lid_z = wall + base_h
    if lid_style == "curved":
        tris += box_triangles(length, width, wall, cx=0, cy=0, cz=lid_z)
        tris += _half_cylinder_lid(length, width, lid_z + wall)
    else:
        tris += box_triangles(length, width, wall, cx=0, cy=0, cz=lid_z)
    return tris


def chest_base_triangles(spec):
    """Base only, for separate printing."""
    spec = normalize_spec(spec)
    length = spec.get("length_mm", 127)
    width = spec.get("width_mm", 80)
    base_h = spec.get("base_height_mm", 50)
    wall = spec.get("wall_mm", 2)
    tris = []
    tris += box_triangles(length, width, wall, cx=0, cy=0, cz=0)
    tris += box_triangles(length, wall, base_h, cx=0, cy=width/2 - wall/2, cz=wall)
    tris += box_triangles(length, wall, base_h, cx=0, cy=-width/2 + wall/2, cz=wall)
    tris += box_triangles(wall, width - 2*wall, base_h, cx=length/2 - wall/2, cy=0, cz=wall)
    tris += box_triangles(wall, width - 2*wall, base_h, cx=-length/2 + wall/2, cy=0, cz=wall)
    return tris


def chest_lid_triangles(spec):
    spec = normalize_spec(spec)
    length = spec.get("length_mm", 127)
    width = spec.get("width_mm", 80)
    wall = spec.get("wall_mm", 2)
    if spec.get("lid_style", "curved") == "curved":
        return box_triangles(length, width, wall, cx=0, cy=0, cz=0) + _half_cylinder_lid(length, width, wall)
    return box_triangles(length, width, wall, cx=0, cy=0, cz=0)


def create_chest_stls(spec, base_name="chest"):
    """Write separate base + lid STLs, for a chest you can actually open."""
    base_path = write_stl(PRINTS_DIR / f"{base_name}-base.stl", chest_base_triangles(spec), name="chest_base")
    lid_path = write_stl(PRINTS_DIR / f"{base_name}-lid.stl", chest_lid_triangles(spec), name="chest_lid")
    return base_path, lid_path


def ask_chest_questions(input_fn=input):
    """
    The exact questioning flow Oracle should use for a vague request
    like 'make me an stl file of 5 inch hanged chest'.
    input_fn is input() in real use, or a test function.
    Returns a spec dict in mm. It does NOT guess dimensions that matter.
    """
    def q(prompt, default=""):
        answer = input_fn(prompt + (f" [{default}] " if default else " ")).strip()
        return answer or default

    print("Oracle: I want to get this chest right, so a few quick questions first - I won't guess on sizes that matter for fit.")
    print("Oracle: I work in both mm and inches - tell me sizes in either, and I will show you both (5 in = 127 mm).")
    kind = q("Did you mean a hinged chest (lid opens on a hinge), a hanging / wall-mounted chest, or a treasure chest with a curved lid?", "hinged treasure chest")
    size_raw = q("You said 5 inch - is that the length (longest side)? If not, what is 5 inch measuring? (length / width / height)", "length")
    # Convert: 5 inch = 127 mm, used for whichever dimension the user confirms.
    length_mm = 127.0
    width_mm = 80.0
    base_h_mm = 50.0
    if "width" in size_raw.lower():
        width_mm = 127.0
    elif "height" in size_raw.lower():
        base_h_mm = 127.0
    # Ask for the other dimensions, with defaults shown, not assumed silently.
    try:
        width_mm = float(q("Width in inches (front to back)?", "3.15"))
        width_mm = width_mm * 25.4 if width_mm < 20 else width_mm
    except Exception:
        pass
    try:
        base_h_mm = float(q("Base height in inches (not counting the lid)?", "2"))
        base_h_mm = base_h_mm * 25.4 if base_h_mm < 20 else base_h_mm
    except Exception:
        pass
    lid_style = q("Lid style - flat, or curved treasure-chest lid?", "curved")
    use = q("What will it hold / be used for? (jewelry, small items, display, etc.)", "small items")
    print_as = q("Print as: separate base + lid (so you can open it), or one closed model?", "separate")
    spec = {
        "shape": "chest",
        "kind": kind,
        "length_mm": length_mm,
        "width_mm": width_mm,
        "base_height_mm": base_h_mm,
        "wall_mm": 2,
        "lid_style": "curved" if "curv" in lid_style.lower() or "treasure" in lid_style.lower() else "flat",
        "use": use,
        "print_as": print_as,
    }
    return spec


# ---------------------------------------------------------------- building from a spec

def build_from_spec(spec):
    spec = normalize_spec(spec)
    shape = spec.get("shape", "box")
    if shape == "box":
        return box_triangles(spec.get("width_mm", 50), spec.get("depth_mm", 30), spec.get("height_mm", 20))
    if shape == "cylinder":
        return cylinder_triangles(spec.get("diameter_mm", 30), spec.get("height_mm", 20))
    if shape == "sphere":
        return sphere_triangles(spec.get("diameter_mm", 30))
    if shape == "chest":
        return chest_triangles(spec)
    if shape == "phone_stand":
        # Simple L-shaped stand: base + back, as two boxes in one STL.
        # A slicer treats this as one print with two solids touching.
        base = box_triangles(80, 60, 6, cx=0, cy=0, cz=0)
        back = box_triangles(80, 6, 90, cx=0, cy=-27, cz=6)
        return base + back
    if shape == "extrude" and "points" in spec:
        return extrude_polygon_triangles(spec["points"], spec.get("height_mm", 10))
    raise ValueError(f"Unknown shape: {shape}. Try box, cylinder, sphere, phone_stand, or extrude with points.")


def create_stl(spec, filename, ask=None):
    """
    Full flow: validate, suggest (asking if ask is given), then write STL.
    Returns (path, warnings, applied_suggestions).
    """
    spec = normalize_spec(spec)
    warnings = validate_spec(spec)
    applied = []
    if ask is not None:
        spec, applied = apply_suggestions_with_approval(spec, ask)
        spec = normalize_spec(spec)
        warnings = validate_spec(spec)
    triangles = build_from_spec(spec)
    path = write_stl(PRINTS_DIR / filename, triangles, name=spec.get("shape", "oracle"))
    return str(path), warnings, applied


if __name__ == "__main__":
    def _ask(title, explanation):
        print(f"\nSuggestion: {title}\n  {explanation}")
        return input("Apply this? (y/n): ").strip().lower() == "y"

    print("Test prints (no suggestions applied in test mode, ask=None):")
    for spec, name in [
        ({"shape": "box", "width_mm": 40, "depth_mm": 30, "height_mm": 20}, "test-box.stl"),
        ({"shape": "cylinder", "diameter_mm": 30, "height_mm": 15}, "test-cylinder.stl"),
    ]:
        path, warnings, _ = create_stl(spec, name, ask=None)
        print(f"  {path} - warnings: {warnings or 'none'}")
    print("\nTo try suggestions interactively, call create_stl(spec, 'my-print.stl', ask=_ask) from Python.")
