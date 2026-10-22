# Numerical helpers: precision without false certainty

## What they do
`scripts/measure_vehicle.py` is standard-library Python and does not require Blender. It checks supplied actual measurements, not meshes or image content. Obtain measurements from the current Blender scene/reference first; never fabricate a plausible measurement report to satisfy a gate. A passing number is not a good-looking model or calibrated reference.

Commands (substitute actual paths):
- `python <skill>/scripts/measure_vehicle.py landmarks <job>/landmarks.json`
- `python <skill>/scripts/measure_vehicle.py assemblies <job>/assembly-measurements.json`

Both print JSON to stdout, make no source edits, and return 0 within chosen numerical tolerances, 1 needs correction, or 2 invalid/incomplete input. Save stdout to a versioned report with the actual execution facility. Preserve invalid-input reports instead of mislabelling them aesthetic failures. Numeric roundoff handling is relative at tolerance boundaries only; zero tolerances stay exact. Numerical schema 1 is independent of review-record schema 2.

## Landmarks
Copy `assets/landmark-measurements.json`. Fill model/reference versions, view, alignment_note, image sizes, justified tolerance_px/tolerance_basis, and landmarks. Each correspondence has a unique ID, reference_px, model_px, and optionally a per-point tolerance_px. Coordinates are continuous pixels from the upper-left image corner; points outside their frames are rejected. Tolerances are reference-image pixels, not world dimensions.

Only set alignment_confirmed after verifying compatible viewpoint/projection, orientation, subject framing, crop, and aspect ratio. The tool rescales image resolution to reference pixel space; it does NOT fit translation/rotation, warp images, align cameras, or normalize away shape errors. Different aspect ratios are rejected. Same aspect ratio does not prove alignment. Avoid unreliable occluded landmarks and record ambiguity rather than pretending subpixel precision.

Use landmarks that constrain actual shape: body ends, wheel centres, turret position, wing tips, rotor hubs. A few cherry-picked matching points do not certify the rest of the vehicle. Inspect alternate views, silhouette, and shaded forms separately.

To obtain model projections in Blender, use the actual scene camera and current world-space landmark locations. The established `bpy_extras.object_utils.world_to_camera_view` returns normalized camera coordinates: convert x by rendered width and y with `(1-y) * rendered_height` for upper-left coordinates. Check visibility/depth, render percentage, pixel aspect, and border/crop settings before using those coordinates. Discover the installed Blender API rather than assuming a copied snippet covers all render setups. Do not treat a generated perspective reference as an exact orthographic drawing.

## Assemblies
Copy `assets/assembly-measurements.json`. Supply model_version, units, coordinate_frame, tolerance_basis, and nonempty assemblies. Each assembly has unique id and measured_dimensions [axis0,axis1,axis2] in the declared measurement frame. Add target_dimensions and dimension_tolerance arrays only where targets are supported. Unknown targets may be omitted, but no numerical checks at all is rejected rather than passing vacuously.

Optional attachments each have id, from_assembly, to_assembly, from_position, to_position, expected_gap, tolerance. All positions must already be in the SAME declared frame and units. The helper compares actual endpoint separation with the intended gap; it does not validate socket rotation, mesh contact, collision, or motion. Inspect those separately. Record intended gaps explicitly; do not assume every overlap/contact target is zero.

Optional ratios each have id, numerator {assembly, axis}, denominator {assembly, axis}, target_ratio, relative_tolerance. A relative tolerance of 0.01 means one percent of the target ratio; it is an example of notation, not a recommended design tolerance. Axes are 0/1/2 in the declared frame. Use ratios where exact real-world scale is unsupported.

Extract actual dimensions from evaluated geometry in the APPROVED measurement frame. For an assembly comprising several objects, aggregate transformed evaluated bounding-box corners into that frame, or actual evaluated vertices when tighter bounds matter. Include source modifiers; exclude explicitly out-of-scope helpers/colliders. A world AABB of a rotated part is not its local design dimensions. Document bounds approximations, scene unit scale, non-uniform parent transforms, and exclusions. Transform attachment points to the common frame before comparison. Never compare two raw local coordinate vectors from different parents.

## Read results as diagnostics
A mismatch tells you where to investigate, not automatically which vertices to move. Check camera/reference/measurement-frame causes before geometry. If the measurement is unreliable, correct or declare it; don't tune tolerances just to make a report green. Keep the original target and rationale in the design lock.
