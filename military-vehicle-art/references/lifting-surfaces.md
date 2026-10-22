# Construct lifting surfaces: wings, fins and tails

`build_lifting_surface.py` **builds a new editable mesh**, not a quality checklist and not a wrapper around the convex `reconstruct_vehicle.loft` operation. It constructs paired chordwise upper/lower skins from a shared airfoil sampling grid, triangulates them, joins leading/trailing edges, and triangulates closed root/tip caps. Nonconvex airfoil sections are supported. It never modifies an existing mesh or reuses an owned output name.

## Run

Use an already available official bpy environment in a disposable process. Inspect the actual Blender/Python environment; do not install merely because an example names one:

```sh
python "$SKILL/scripts/build_lifting_surface.py" \
  --source /absolute/existing.blend --spec /absolute/filled.json \
  --output /absolute/NEW.blend --report /absolute/NEW.json
```

Blender form:

```sh
blender --background --disable-autoexec --python scripts/build_lifting_surface.py -- \
  --source existing.blend --spec filled.json --output NEW.blend --report NEW.json
```

Output/report must not exist, including dangling symlinks. Their parent directories must already exist. Exit 0 means built/published; exit 2 emits a JSON error on stderr and no new snapshot/report. CLI opens the source with scripts disabled. The API operates on the current scene and adds one object/mesh/new collection:

```python
validation_report = validate(spec)  # JSON-serializable; no bpy scene mutation
construction_report = build(spec)  # JSON-serializable; validates again
```

`validate` checks schema, finite numbers, float32 coordinates, workload bounds, projected ordering, triangle conditioning, full between-station skin separation and conservative placement precision. `build` additionally requires Object mode, unowned names, real positive signed Blender volume, oriented manifold edges, usable float32 UV triangles and native Blender face normals agreeing with the stored triangle geometry. Passing `validate` alone does not establish usable native normals. A build-time failure removes its newly created datablocks. Use CLI in a disposable process for disk publication; calling it replaces the process's currently open scene.

## Coordinate convention

All lengths are **source Blender units**, not automatically metres. Reports record `scene_system` and `scene_scale_length`; the helper does not change either. Fractions in profiles are normalized by each station's chord. No unit normalization or guessed aircraft orientation occurs.

* Local **+X** points from leading edge to trailing edge (aft).
* Local **+Y** points root to tip. `span` is the Y coordinate and must strictly increase.
* Local **+Z** is upper-surface height. This is a right-handed local basis.
* `leading_edge: [x,z]` sets the leading-edge X/Z offsets at a station. Sweep and dihedral are controlled by offsets, not an additional ambiguous rotation. Segment reports give `atan2(delta_x,delta_span)` sweep and `atan2(delta_z,delta_span)` dihedral in degrees.
* `twist_degrees` rotates each XZ airfoil about its **leading edge**, around local **+Y**. Positive twist moves an aft chord point toward **−Z**. It does **not** rotate the station plane away from constant Y. This restricted definition keeps the construction well-defined.
* `placement.origin` and XYZ `placement.rotation_degrees` apply a rigid object transform after construction, no scale/mirror. For a vertical fin whose local span points world +Z, use `[90,0,0]`. For the opposite half-wing, a proper `[180,0,0]` rotation points span toward −Y and flips the local upper side; explicitly reflect camber/dihedral if required. Do not infer a symmetric opposite surface from an asymmetric section.

For normalized point `(u,h)`, station chord `c`, leading edge `(a,b)` and twist `t`, the mesh-local vertex is:

```text
X = a + c * (u*cos(t) + h*sin(t))
Y = span
Z = b + c * (-u*sin(t) + h*cos(t))
```

Add stations to model changes in sweep, taper, dihedral, thickness/camber or twist; station-to-station skins are **triangulated, piecewise planar**, not aerodynamic interpolation or a smooth NURBS wing.

## Filled generated schema

`assets/lifting-surface.json` is a complete runnable example. Every displayed field is required; unknown keys, booleans masquerading as numbers, NaN/Infinity, duplicate JSON keys, invalid UTF-8 names and extra fields are refused.

```json
{
  "schema_version": 1,
  "object_name": "NewWing",
  "collection": "NewSurfaces",
  "airfoil": {"kind": "naca4_vertical", "samples": 17},
  "placement": {"origin": [0,0,0], "rotation_degrees": [0,0,0]},
  "stations": [
    {"span": 0, "leading_edge": [0,0], "chord": 2, "twist_degrees": 0,
     "profile": {"thickness": 0.12, "camber": 0.02, "camber_position": 0.4}},
    {"span": 4, "leading_edge": [1,0.3], "chord": 0.8, "twist_degrees": -2,
     "profile": {"thickness": 0.09, "camber": 0.01, "camber_position": 0.4}}
  ]
}
```

`naca4_vertical` uses cosine-spaced normalized X, a NACA-four-digit-style mean line and the closed-trailing-edge thickness polynomial
`5*t*(.2969*sqrt(x) - .126*x - .3516*x^2 + .2843*x^3 - .1036*x^4)`.
Thickness is added/subtracted **vertically** to/from the mean line, not along its normal. Both endpoint heights are set to exactly zero. Therefore this is a useful construction family, **not an assertion that cambered results reproduce canonical published NACA ordinates or aerodynamic performance**. Use explicit profiles to preserve measured/published coordinates.

## Explicit corresponding profiles, including actual reference ordinates

Replace `airfoil` and each station's `profile` as follows; all other fields above remain unchanged:

```json
"airfoil": {"kind":"explicit", "x":[0,0.2,0.5,0.8,1], "trailing_edge":"sharp"}
"profile": {"upper":[0,0.08,0.02,0.015,0], "lower":[0,-0.03,-0.01,-0.01,0]}
```

* Shared `airfoil.x` must increase strictly from exactly **0 to 1**; upper/lower ordinates correspond by index at **every station**. It is not an arbitrary cyclic ring, point cloud, or independently resampled profile.
* Upper minus lower must be at least `1e-5` at every interior sample. LE upper/lower must both be exactly zero. Concave portions are allowed; crossings, touching interiors, unmatched counts and collapsed samples are not.
* `trailing_edge` is optional and defaults to `sharp`: both TE ordinates must be exactly zero, a shared TE vertex. Do not silently alter public blunt-edge coordinates to fit sharp mode.
* `trailing_edge: "blunt"` keeps separate last upper/lower vertices with gap at least `1e-5`, closes them with a trailing-edge strip and adds a fifth UV island. **Every station must have zero twist in blunt mode**; sweep, taper, dihedral and global rigid fin/tail rotation remain supported.
* Published upper/lower X coordinates must already correspond. Resampling, smoothing, removing duplicate points or closing an open profile is an external explicit modelling decision, not something this helper silently performs. Preserve source data/provenance separately; inline ordinates are authoritative for this operation.

### Using public section coordinates

Preserve the original coordinate file and its actual hash, identify upper/lower ordering and shared X samples, and retain a real finite trailing-edge gap using blunt mode. The [UIUC coordinate database](https://m-selig.ae.illinois.edu/ads/coord_database.html) includes public section data; its [NACA0012 file](https://m-selig.ae.illinois.edu/ads/coord/n0012.dat) uses separate upper/lower LE→TE lists with a count header. Parse the actual format instead of treating the header as a point. A section file does not establish permission for unrelated aircraft assets or prove a complete real aircraft's planform, twist or installed section. Keep those authorship/evidence questions separate.

## Supported domain and refusal boundaries

* 2..64 increasing span stations, span 0..100000, separation at least `1e-4` and distinct in float32.
* Generated: 5..65 X samples. Explicit: 5..129 X samples, normalized spacing at least `1e-5`. At most 16448 vertices / 32892 triangles in explicit blunt mode; no unbounded subdivision or scene-wide geometry operation.
* Chord `1e-4`..10000; no zero-chord/pointed tip. Leading-edge offsets and placement origins within ±100000. XYZ placement angles within ±360°.
* Generated thickness fraction .01...4; camber −.1...1; camber position .1...9. Explicit heights within ±.5 chord. Sharp-mode twist −20..20° **and** both transformed skin chains must remain strictly increasing in projected X. Even a numerically in-range twist may be refused at a densely sampled/thick nose; reduce twist, reduce samples or use another modelling method. Blunt mode requires zero twist.
* Ordered projected chord chains make each triangulated skin a graph over XY. The helper clips **every overlapping upper/lower triangle pair in each Y slab** and bounds affine height differences on the convex overlay vertices, rather than only sampling endpoint rings or a few mid-stations. Upper/lower separation below numerical guard is refused. This supports nonconvex airfoils without reusing the convex-ring loft restriction.
* Mesh is built from float32 coordinates, checked for triangle collapse/conditioning and actual positive-volume manifold topology. Native Blender face normals must agree with independently normalized double-precision cross products of the stored coordinates (dot product at least `.99999`). Blender can substitute an incorrect normal for very small triangles even when relative conditioning and topology pass; such builds are refused with rollback. Numeric chord/span bounds are necessary, not sufficient: support depends on the actual triangles and native Blender result, not a larger blanket minimum chord. Enlarge the surface or simplify its sampling if native normals fail. Conservative placement rounding guard rejects excessively small/far-origin geometry. Float32 UV collapse is also rejected. These are bounded numerical construction checks, not an exact arithmetic proof for arbitrary geometric inputs.
* Root and tip are planar caps at the first/last station. Leading edge is sharp at the sampled LE, not automatically rounded beyond the sampled profile. No wing/body fillets, intersecting fairings, Boolean union, rounded/elliptical tip, control-surface hinge/cut/gap, sweep-folded or overhanging profiles, variable station-plane orientation, aerodynamic meshing, collision clearance against the rest of the scene or engineering certification.

## UVs, shading and editability

`LiftingSurfaceUV` contains non-overlapping atlas **regions**: upper and lower chord/span grids, root/tip XZ planar islands, and the optional blunt TE strip. UV triangles are checked after float32 storage. Chordwise UVs use normalized X; spanwise UVs use station span, so taper is intentionally not area-preserving. **Uniform texel density and artistic paintability are not certified**. Region padding is fixed, not a bake-resolution promise. Seams and sharp edges separate those regions. Skins are smooth-shaded, caps/TE flat; no modifiers or normals on existing objects are touched. New object custom properties retain the exact construction spec for rebuilding with a new name.

## Non-destructive publication and dependencies

CLI reuses `reconstruct_vehicle.check_paths`, `digest` and `save_snapshot`, the same new-snapshot path as `finish_asset.py`: distinct inputs/outputs, no overwrite, staged same-filesystem save, hard-link publication, exclusive report creation, rollback if report creation/write/close fails, no `.blend1`, and absolute dependency paths before moving the snapshot. A failed write/close removes the report created by that invocation; a report already owned by another writer when exclusive creation is attempted is preserved. The source `.blend` is never saved. Source/spec are rehashed before publication. Existing raw source mesh geometry and transforms are left editable; adding a new scene object can still affect scene-wide consumers such as Geometry Nodes that query collections.

Existing unpacked static files exposed by `bpy.utils.blend_paths(absolute=True, packed=False)` are hashed before/after construction: ≤256 files, ≤512 MiB/file and ≤2 GiB total. Missing files, UDIM/sequence templates and directory cache paths are refused rather than guessed. Linked library and nested image paths are tested. Packed data remains in the snapshot. Dependencies are **not copied, locked, bundled or made portable**; arbitrary scripts, plugins, procedural caches and undiscoverable external resources are outside this scope. A hash check cannot prevent another process changing a file immediately afterward.

## Tests

```sh
python "$SKILL/scripts/test_build_lifting_surface.py" -v
```

Tests cover generated/cambered sections, nonconvex explicit sections, blunt TE preservation, sweep/taper/dihedral/twist and fin rotation, manifold positive volume/caps, full slab crossing regression, UVs/seams, numeric/schema/workload/refusal cases, Object mode, owned names, rollback, real subprocess CLI, autoexec off, new-path publication, source/spec/dependency hashes, changed-input refusal, publication races and linked nested textures. The tiny nonconvex native-normal regression requires rollback and retains a 100× scale control with correct native face/flat-cap corner normals. Shared `test_reconstruct_vehicle.py` additionally exercises a real POSIX `RLIMIT_FSIZE` report short write, read-only source/spec/dependency preservation and late publication races. Workload boundaries exercise generated 64×65 and explicit-blunt 64×129 samples. These are construction-mechanics tests, not aesthetic/aerodynamic evidence; inspect the actual output before claiming artwork quality.
