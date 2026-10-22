# Evaluated geometry probes

## Contents

- [Run and preservation](#run-and-preservation)
- [Exact input schema](#exact-input-schema)
- [Frames, units and evaluated data](#frames-units-and-evaluated-data)
- [Dimensions](#dimensions)
- [Datum and axis](#datum-and-axis)
- [Sampled clearance](#sampled-clearance)
- [Directional thickness](#directional-thickness)
- [Four illustrative records](#four-illustrative-records)
- [Report and interpretation](#report-and-interpretation)
- [Limits and tests](#limits-and-tests)

These are **four independent measured-geometry systems**, not the supplied-coordinate checks in `measure_vehicle.py`. They extract actual evaluated vertices, object transforms and triangle intersections from the named source. Use measurements to diagnose a specific reconstruction/design defect; passing them does not establish artistic likeness, authentic references, photorealism or engineering function.

## Run and preservation

Use a disposable Blender Python process with `bpy` available, from any working directory:

```sh
python "$SKILL/scripts/probe_geometry.py" \
  --source "/original/location/real.blend" \
  --spec "/job/filled-geometry-probes.json" \
  --report "/job/NEW-geometry-report.json"
```

In the tested cached environment, the equivalent invocation is `uv run --offline --python 3.13 --with bpy --with pillow python "$SKILL/scripts/probe_geometry.py"` followed by those flags. Pillow is not required by this helper itself. Do not install packages without authorization. For Blender's bundled Python, `blender --background --factory-startup --disable-autoexec --python "$SKILL/scripts/probe_geometry.py" -- --source ... --spec ... --report ...` supplies the same script arguments.

The script opens **the original source location**, disables embedded-script execution, evaluates only in memory and never saves a `.blend` or preferences. Do not relocate a byte-identical archive and assume its `//` dependencies still refer to the original files. Source/spec SHA-256 values are checked again before publication. External linked libraries, caches, drivers and other dependencies are not independently fingerprinted by this helper; use trusted, prepared sources, not an adversarial-file sandbox.

The report must have a new filename in an existing directory. Existing files, directories, symlinks, hard-link destinations and source/spec aliases are never overwritten. Symlink components in any input/output path and `..` traversal are refused. JSON is fully written and flushed in a temporary sibling, then published with an exclusive hard link; unsupported hard-link filesystems fail rather than falling back to overwrite. Temporary siblings are removed on normal exceptions. Avoid concurrent editing/moving of inputs or their directories while measuring.

[The distributed template](../assets/geometry-probes.json) is deliberately **unfilled and rejected**. Copy it outside the skill, retain only needed checks and fill actual names, frames and samples. Optional `target` must be omitted for measurement-only use, not set to `null`. Never fill unknown target values with made-up dimensions or inherited universal tolerances.

## Exact input schema

All object schemas are closed: **unknown fields and duplicate JSON keys are rejected**, including nested records. No coercion of numeric strings, booleans, NaN or infinity. Length vectors contain exactly three finite numbers. Text is nonempty, has no NUL and is at most 4096 characters. Names are exact, case-sensitive Blender datablock names; there is no prefix, collection expansion or fuzzy fallback.

Top level has exactly:

| Field | Value |
|---|---|
| `schema_version` | integer `1`, not boolean |
| `scene` | exact scene name |
| `view_layer` | exact view-layer name within that scene |
| `evaluation_frame` | integer in `-1000000..1000000`; subframe is zero |
| `units` | exactly `"m"` |
| `checks` | nonempty list, at most 128 records; unique nonempty `id` strings |

Every check requires `id`, `type`, `frame` and the type-specific fields below. Only `target` is optional. Each check type may be used alone; no ceremony requires executing the other three.

`frame` is exactly one of:

- `{"kind":"world"}`: world origin and world axes.
- `{"kind":"object","object":"ExactDatumName"}`: evaluated object origin and rigid orientation at the requested frame. Scale, shear and reflection are rejected, not silently stripped.

Every supplied `target` requires exactly the numerical fields listed for its check type and `basis`. `basis` is exactly `kind`, `note`, `sha256`:

- `kind`: `"reference"` or `"design_brief"`.
- `note`: identify the actual reference/version/feature or original authored design requirement, what the target measures, and why the tolerance is justified, including uncertainty. A made-up human approval is not a basis.
- `sha256`: 64 lowercase hexadecimal characters fingerprinting the actual cited reference artifact or original brief. The tool validates its format and preserves the declaration; it **does not authenticate the evidence or read an evidence file**.

All comparisons use the caller's explicit thresholds; no universal asset-accuracy constants are applied. Zero tolerances are allowed and compare exactly. The rigid-frame `1e-6` guard addresses Blender matrix roundoff only; it is not a dimensional or artistic acceptance tolerance.

## Frames, units and evaluated data

The source scene must explicitly use `METRIC` or `IMPERIAL`, with positive finite `scale_length`. `NONE` is refused. All spec/output lengths are metres regardless of UI display units. The reported `metres_per_blender_unit` is the source's `scale_length`; no implicit millimetre interpretation or automatic rescaling occurs.

For an evaluated object matrix `M`, rigid measurement frame `F`, evaluated local vertex `v` and source unit scale `s`, the measured point is:

`p_m = s * (F^-1 * M * v)`.

Positions use the affine transformation; directions use only its linear part and are normalized. Object nonuniform scales and rotation are therefore included in geometry, unlike multiplying an already-world-aligned object bounding box. The report records evaluated world matrices in **Blender units** (`matrix_world_bu`) and the frame matrix for every check; measured coordinates themselves are in metres.

Objects must be uniquely named across all loaded local/linked objects, present and visible in the selected viewport view layer. Hidden/excluded objects are refused rather than evaluated stale. Mesh checks require actual nonempty `MESH` data. Ordinary mesh modifiers and animation at the requested frame are evaluated. Collection/vertex/face/particle instancers, children of instancers, and Geometry Nodes modifiers are conservatively unsupported. For these cases, explicitly prepare a separate realized mesh snapshot outside this read-only tool; do not imply it measured omitted instances. Origin/axis datums and frames can be Empty objects.

This is **viewport dependency-graph geometry**, not render-time shader displacement, bump, adaptive subdivision, render-only modifier geometry or every possible simulation state. Triangle winding supplies probe normals; mirrored/inverted/inconsistently wound geometry can invalidate orientation interpretation.

## Dimensions

`type: "dimensions"` additionally requires `objects`: 1..128 unique exact mesh names. All evaluated vertices from those objects are transformed into the specified frame. For each frame axis, report `bounds_min_m`, `bounds_max_m`, and their difference `dimensions_m`. This is a frame-aligned envelope over actual vertices, **not** object `dimensions`, a transformed world AABB, a best-fit oriented box or a semantic length measurement of a curved part.

Optional `target` has exactly:

| Field | Meaning |
|---|---|
| `dimensions_m` | three strictly positive desired envelope dimensions |
| `tolerance_m` | three nonnegative absolute per-axis error allowances |
| `basis` | evidence/brief declaration above |

Comparison is componentwise `abs(actual_i - desired_i) <= tolerance_i`; all three must hold. Flat/curved shapes may need another measurement frame or another method rather than treating the envelope as their physical local thickness.

## Datum and axis

`type: "datum"` additionally requires:

- `landmark`: exactly `{"object":"Name","point":"origin"}`, or `{"object":"Name","point":"vertex","index":0}` with a nonnegative integer evaluated-mesh index. The vertex index must exist in the evaluated array; it is not an original-topology semantic guarantee after modifiers.
- `axis`: `"X"`, `"Y"` or `"Z"`, meaning that object's **positive local axis** transformed by its evaluated world matrix and normalized. This is not a supplied/invented model position or a fitted alignment.

Report actual `position_m` and normalized `direction` in the measurement frame. Object-origin/axis semantics must genuinely identify the intended datum; a named Empty can be authored at an arbitrary location, so naming alone does not validate its real-world placement.

Optional `target` has exactly `position_m` (three numbers), `position_tolerance_m` (nonnegative), `direction` (three finite numbers with nonzero length), `angle_tolerance_deg` (0..180 inclusive), and `basis`. Both position and signed axis direction are compared. Position error is Euclidean distance. Angular error is `atan2(length(cross(a,b)), dot(a,b))` in degrees for normalized axes; opposite axes differ by 180 degrees. Both thresholds must hold. There is no best-fit transform or supplied-coordinate substitution.

## Sampled clearance

`type: "clearance"` additionally requires `from_object`, `to_object` (distinct exact mesh names), `samples`, `max_distance_m` and `epsilon_m`.

Every sample is exactly `id`, `origin_m`, `direction`. Sample IDs are unique within a check. Origin and direction are expressed in the check's measurement frame. Direction must be nonzero and is normalized. `max_distance_m` is positive and bounds the **entire ray from its original origin**. `epsilon_m` must be positive and less than that maximum. Both are supplied explicitly, with no hidden scene-space offsets. Origins/ranges overflowing Blender's float representation and epsilons underflowing to zero are refused; passing this representation guard does not establish useful scene-scale precision.

For each sample:

1. Find the first two-sided triangle hit on `from_object` along the ray.
2. Advance by `epsilon_m` in the same direction, then find the first `to_object` hit within the remaining original range.
3. Also check for a `from_object` re-hit before that target; report `source-obstructed` if encountered.
4. For an interpretable outward-to-inward gap, require the first hit's normal dot direction to be positive and the target hit's to be negative. Otherwise report `orientation-inconsistent`, never a tolerance pass.

Choose seeds inside the intended source solid near its outward surface, not blindly outside its back face or inside a hollow cavity. Report the actual hits, normals, evaluated triangle indices, original-seed distances, re-hit when tested, and directional `gap_m = dot(target_hit - source_hit, direction)`. Intersections with other scene objects are not searched. Misses are `from-miss` or `to-miss`, with null missing hits/gap; they are **not zero distance, guaranteed free space or infinite clearance**.

Optional `target` is exactly `gap_m` (nonnegative), `tolerance_m` (nonnegative), and `basis`. It applies to each interpretable sample using absolute scalar error; use separate checks for different target gaps. Report raw separation even for an orientation/obstruction diagnostic, but do not compare it as an accepted clearance.

## Directional thickness

`type: "thickness"` requires `object` (one exact mesh), and the same `samples`, `max_distance_m` and `epsilon_m` schema as clearance.

Find the first hit, advance by epsilon, then find the next hit on the **same evaluated mesh** along the same ray and remaining range. Report `entry_hit`, `exit_hit`, and `thickness_m = dot(exit - entry, direction)`. Require entry normal dot direction < 0 and exit > 0 for an interpretable pair. Absent hits produce `entry-miss` or `exit-miss`; winding-inconsistent pairs produce `orientation-inconsistent`. A lone open plane has no measured thickness, not zero thickness.

For a consistently wound hollow shell and a seed outside the material, the first entry/exit pair can measure the local wall before the cavity, not the whole object's outer span or the cavity width. Along an oblique ray it measures a **chord**, generally longer than normal thickness. To request normal thickness, explicitly select a seed/direction justified by the intended surface normal. The tool reports hit normals but does not optimize ray direction, prove watertightness, classify all solids, find minimum walls, or certify manufacturability.

Optional `target` is exactly `thickness_m` (nonnegative), `tolerance_m` (nonnegative), and `basis`, applying separately to each interpretable sample with absolute scalar error.

## Four illustrative records

This exact measurement-only example assumes an **authored synthetic** scene `AuthoredDemo`: visible mesh `Body` is a hollow box at datum origin, envelope `(1,0.5,0.25)` metres; `Other` begins at datum-local X=1.75 m; positive X exits Body at X=0.5 m. Datum has rigid orientation. These are illustrative authored conditions, **not real-object evidence or ready-made acceptance thresholds**. Origins, directions, range and epsilon below are specific to this toy layout. Retain only the records justified for the actual asset.

```json
{
  "schema_version": 1,
  "scene": "AuthoredDemo",
  "view_layer": "ViewLayer",
  "evaluation_frame": 1,
  "units": "m",
  "checks": [
    {
      "id": "envelope", "type": "dimensions", "objects": ["Body"],
      "frame": {"kind": "object", "object": "Datum"}
    },
    {
      "id": "corner", "type": "datum",
      "landmark": {"object": "Body", "point": "vertex", "index": 0}, "axis": "X",
      "frame": {"kind": "object", "object": "Datum"}
    },
    {
      "id": "opening", "type": "clearance", "from_object": "Body", "to_object": "Other",
      "frame": {"kind": "object", "object": "Datum"}, "max_distance_m": 3, "epsilon_m": 0.000001,
      "samples": [{"id": "outward", "origin_m": [0.45,0,0], "direction": [1,0,0]}]
    },
    {
      "id": "shell-wall", "type": "thickness", "object": "Body",
      "frame": {"kind": "object", "object": "Datum"}, "max_distance_m": 3, "epsilon_m": 0.000001,
      "samples": [{"id": "entry", "origin_m": [-1,0,0], "direction": [1,0,0]}]
    }
  ]
}
```

## Report and interpretation

The output JSON has top-level `schema_version: 1`, `command: "probe-geometry"`, actual input `source` / `source_sha256`, `spec` / `spec_sha256`, `evaluation` (scene, view layer, frame, geometry kind, Blender version), `units`, `scene_unit_system`, `metres_per_blender_unit`, `evaluated_objects` (name/type/world matrix), `checks`, `status` and declared `limitations`. This is diagnostic material for source-hash-aware design review, not an approval record or a reconstructed image.

Each check retains its ID/type/scope/frame and evaluated frame matrix. Supplied target/basis declarations are preserved when present. Numeric residuals and `within_tolerance` are reported only for interpretable comparisons. A measurement-only check is `measured`, **not** `within-tolerances`. Target disagreement is `needs-correction`. A ray miss, inconsistent orientation or obstructed source sample makes that check `incomplete`, even if other samples pass. The top-level status is `incomplete` before `needs-correction`, else `complete`; inspect all rows because a top-level incomplete result can coexist with other target failures.

Exit code `0` means the requested diagnostics completed without target disagreement (possibly no targets at all). Code `1` means a published diagnostic has disagreement or incomplete samples. Code `2` means invalid/unsupported input or publication failure; no new diagnostic is published on ordinary validation/evaluation failures. Existing files remain untouched. Do not interpret exit zero as real-object accuracy, collision clearance or artistic acceptance.

## Limits and tests

Workload guards, not quality recommendations: JSON <=1 MiB, <=128 checks, <=128 names per dimensions check, <=4096 ray samples across all checks, <=2,000,000 evaluated vertices and <=4,000,000 evaluated triangles cumulatively over mesh reads. Reusing a mesh in another check counts another read. These guards cannot prevent Blender itself spending time/memory evaluating a pathological source before the mesh can be inspected; use a trusted disposable process with an external execution timeout when needed.

Rays sample specified directions only, are two-sided and use floating-point BVHs. Coincident/grazing surfaces, triangle-edge hits, extreme coordinate scales and near-zero separations need special inspection. Epsilon advancement can skip features thinner than epsilon or fail to move representably at large scales. Neither valid normal signs nor two intersections prove the mesh encloses material. A separation between selected surfaces does not rule out collisions elsewhere or with another object. No automatic minimum-wall, collision, all-pose articulation, engineering, authenticity or aesthetic claim is made.

Real-bpy regression tests include rotated/nonuniformly scaled meshes, nonunit scene scale, evaluated modifiers/animation, rigid datum frames, actual evaluated vertex extraction, true gaps, hollow normal/oblique wall measurements, misses, open surfaces, obstruction, unsupported instances/GN, ambiguous linked names, schema/numeric rejection, exclusive publication races, input preservation and CLI use from an unrelated working directory:

```sh
PYTHONDONTWRITEBYTECODE=1 uv run --offline --python 3.13 --with bpy --with pillow \
  python -m unittest discover -s "$SKILL/scripts" -p test_probe_geometry.py -v
```
