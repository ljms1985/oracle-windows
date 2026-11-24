# Oracle 3D Design Knowledge — Print-Ready STLs

## Units and accuracy

- STL files have no unit. Oracle always works in millimetres and tells
  the slicer / user that, because most FDM slicers assume mm.
- Accuracy comes from the specification, not from guessing: width,
  depth, height, hole diameters, wall thickness, and tolerances must
  be in the spec. If a dimension is missing, Oracle asks, it does not
  invent a size that matters for fit.
- For tight fits, print a small test piece first (e.g. a hole gauge
  or a tolerance test) before printing the full part.

## FDM design rules Oracle uses

- **Nozzle / layer:** 0.4 mm nozzle, 0.2 mm layer height is a good
  default. 0.12 mm for detail, 0.28 mm for fast, strong parts.
- **Wall thickness:** at least 0.8 mm, ideally 1.2-2.4 mm (3-6 perimeters).
- **Overhangs:** up to 45° from vertical usually prints without supports.
  Over that, use supports, a chamfer, or re-orient the part.
- **Bridging:** short bridges (under ~20 mm) can print in air; longer
  ones sag — add support or split the part.
- **Holes:** printed holes come out 0.2-0.4 mm smaller. Add clearance:
  bolt hole +0.3 mm, press-fit +0.1-0.2 mm, moving / sliding parts
  +0.2-0.3 mm per side.
- **Orientation and strength:** parts are weakest between layers.
  Put the load across layers, not pulling layers apart. Print flat
  for a flat part, on its side for a bracket that will bend.
- **Supports:** use them only where needed, with a support interface
  distance (0.2 mm) so they remove cleanly. Tree supports for organic shapes.
- **Infill:** 15-20% for decorative, 40-60% for functional, 100% only
  for small, high-load parts. More walls usually help strength more
  than more infill.
- **Shrinkage:** PLA shrinks little (~0.2-0.5%), ABS/ASA more (~1-2%).
  For precise ABS parts, scale up slightly and print in an enclosure.
- **Fillets and chamfers:** fillets reduce stress concentration and
  warping at corners; chamfers replace overhangs and make parts
  easier to remove from the bed.

## Resin (SLA/MSLA) — different rules

- Much finer detail, but supports, orientation, washing, and curing
  matter more. Hollow parts need drain holes. Do not use FDM rules
  blindly for resin.

## How Oracle suggests improvements

Oracle runs `suggest_improvements()` on every spec and asks you,
one by one, before applying anything:
- "I notice X — would you like me to do Y instead?"
- If you say no, the original spec stands, warnings and all.
- If you say yes, the change is recorded in the spec and the STL
  is built from the updated spec, so you can see exactly what changed.

Examples of good suggestions:
- Rounded corners instead of sharp 90° corners
- Ribs / thicker walls for tall, thin parts
- 45° chamfer instead of a support-heavy overhang
- A lip / cable slot on a phone stand
- Re-orientation for layer strength
- Splitting a part that is too large for the bed, with alignment pins

## Next steps for complex CAD

The built-in primitives in `design3d.py` cover boxes, cylinders,
spheres, extrusions, and simple stands with no extra libraries.
For threads, gears, booleans (holes through a shape, unions), and
parametric assemblies, add one of:
- **CadQuery** (`pip install cadquery`) — scripted CAD, good for
  precise engineering parts
- **Build123d** — a newer, Pythonic CAD library, also good for parts
- **OpenSCAD** via command line — simple, scriptable, widely used

Oracle's `design3d.py` is written so those can be added as a new
`build_from_spec()` shape without breaking the existing validation
and suggestion flow.
