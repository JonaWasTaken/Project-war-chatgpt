# Source-preserving surface detail placement

Use `scripts/place_surface_details.py` for an actual inspected master mesh and **explicit authored or reference-backed placements**. It repeats bolts, fasteners, vents or similar mesh details on explicitly named static target surfaces. It does not detect features from photographs, recover hidden dimensions, invent missing fasteners, or establish a copying/fidelity percentage.

## Prepare the input

1. Inspect the actual master mesh, UVs and material-slot ownership in Blender. This helper cannot authenticate that review. Record authored intent or the reference identifier/view/region supporting **each** feature. Do not label inferred locations as independently measured reference truth.
2. Work from a trusted, Object-mode source in a disposable process. Preserve the original file at its original location. Complex/linked/animated targets must first be prepared as a **separate static source**, not destructively applied in the original.
3. The master is a modifier-free local mesh with applied identity rotation and scale. Its shelf/world translation is ignored. Specify its **local attachment origin**. Local **+Z** is the attachment normal and **+X** is its orientation tangent; these axis strings are mandatory, not arbitrary choices. Coordinates/UVs are copied, not recentered, generated or remeshed. An attachment origin need not lie on a verified contact footprint: choose it by inspecting the real master.
4. Author each world-space ray origin, nonzero direction and positive maximum distance in the same Blender-unit world frame as the source. Direction is normalized in double precision before conversion to Blender vectors; range is world distance, independent of its accepted input magnitude (including small directions such as `[0,0,-1e-18]`). The first intersection is sought on **only the explicitly named target**, not all scene objects. Other objects can occlude or intersect the result without being tested.
5. Provide a nonzero world-space tangent. It is likewise normalized before Blender-vector conversion, then its normal component is projected away; positive rescaling of an accepted tangent does not change the frame. Local +X aligns with this projected tangent, then rotates by `rotation_degrees` about the winding-derived hit normal using the right-hand rule. Local +Y is normal cross +X. The normal is not flipped to face the ray. Use consistent target winding.
6. `offset` is a signed world-distance displacement along the hit normal; zero is allowed. `scale` is three strictly positive **master-local** scale factors. Attachment origin is scaled/rotated with the mesh, then translated to `hit + normal * offset`. No randomness, feature-spacing guessing or automatic tolerance widening occurs.

The shipped `assets/surface-details.json` is deliberately **incomplete** and rejected until filled. It is an authoring template, not evidence and not a JSON Schema document. Exact schema version 1 (unknown keys rejected):

```json
{
  "schema_version": 1,
  "collection": "PanelFasteners_v001",
  "master": {
    "object": "InspectedHexBoltMaster",
    "attachment_origin": [0, 0, 0],
    "normal_axis": "+Z",
    "tangent_axis": "+X"
  },
  "placements": [
    {
      "feature_id": "left-panel-fastener-01",
      "object_name": "LeftPanelFastener01_v001",
      "target": "LeftPanel",
      "ray": {
        "origin": [0.3, -0.2, 5],
        "direction": [0, 0, -1],
        "max_distance": 10
      },
      "tangent": [1, 0, 0],
      "offset": 0.001,
      "rotation_degrees": 30,
      "scale": [1, 1, 1],
      "support": {
        "kind": "authored",
        "description": "Approved authored panel layout; coordinates must be adapted to the actual source."
      }
    }
  ]
}
```

`support.kind` is `authored` or `reference`. The nonempty description (at most 4096 characters) should identify the design decision or reference and explain the supported position; it is a supplied assertion, not automatic provenance validation. Every other name is nonempty and at most 63 UTF-8 bytes. Feature IDs and output names must be unique. Existing feature IDs, object/mesh output names or output collection names are refused; rerun with a genuinely new scope/names rather than overwriting. Repeated targets are allowed.

## CLI and API

Use an existing Blender installation, or an already available official `bpy` environment. Do not install software merely because an example names it.

```sh
blender --background --disable-autoexec --python "$SKILL/scripts/place_surface_details.py" -- \
  --source /absolute/source.blend --spec /absolute/filled-surface-details.json \
  --output /absolute/NEW.blend --report /absolute/NEW.json
```

In the verified offline runtime:

```sh
uv run --offline --python 3.13 --with bpy --with pillow python \
  "$SKILL/scripts/place_surface_details.py" \
  --source /absolute/source.blend --spec /absolute/filled-surface-details.json \
  --output /absolute/NEW.blend --report /absolute/NEW.json
```

All four paths must be distinct; source/spec must already exist, output/report must not exist (including dangling symlinks), and destination directories must already exist. Hardlink source/spec aliases are rejected. CLI exit code is **0** on publication, **2** on invalid/unsupported input or an operational failure. No failure diagnostic is written to the requested report path.

Importable API:

```python
validate(spec)  # strict data validation; no bpy import/scene edits
report = place(spec)  # current real bpy scene; all placements preflight first
```

`place` returns JSON-serializable per-feature hit positions, winding-derived world normals, projected tangents, world distances, evaluated triangle/polygon indices, attachment positions and actual row-major `matrix_world` values. The polygon index refers to the evaluated target mesh, not necessarily its base topology. It includes explicit copy/material ownership, source-scoped base-state preservation fingerprints and contact/collision limitations. The CLI wraps this in status/schema/command and source/spec/output hashes. Importing or using the API does not save files. Run it in a disposable process; unexpected post-preflight construction exceptions remove newly created IDs, but the API is not a general scene transaction or recovery system.

## Supported geometry and refusals

Targets may have translation, rotation and positive nonuniform scale. World-space BVHs are constructed from **actual dependency-graph-evaluated triangles transformed to world coordinates**, so nonuniform-scale normals are obtained from the world triangle winding rather than the incorrect direct linear transform of a local normal. Smooth shading normals, shader displacement and renderer-only geometry are not contact geometry here.

Supported target modifiers are at most four of BEVEL, SUBSURF, SOLIDIFY, TRIANGULATE and WEIGHTED_NORMAL. They must be enabled in viewport and render. Subdivision is Catmull-Clark at matching viewport/render levels 0..2; bevel has at most eight segments. Vertex-group-controlled bevel/solidify is refused. These are intentionally narrow static support rules, not instructions to strip valuable rigs or source modifiers.

Refused: missing/ambiguous/nonmesh targets, master-as-target, hidden objects/collections or hidden base mesh elements, unselectable objects, linked/overridden input data, non-Object mode, parents/children/constraints, animation/drivers, shape keys, vertex groups, particles/physics/instances, unsupported modifiers, delta transforms, mirrored/singular/ill-conditioned/sheared transforms and an unapplied master rotation/scale. Dependent object users, collection consumers and collection instances involving input ancestors or the destination scene root are rejected to prevent collection/Object Info/instance leakage. Static sources outside this support envelope must be prepared separately and reviewed.

Each placement gets a **new object and independent copied mesh** retaining the master's mesh data/UVs/material indices. OBJECT-versus-DATA material slot links and OBJECT overrides, including null overrides, are preserved explicitly. Material datablocks/textures are intentionally **shared and unchanged**; the report says so. This is not a material-localization or shader-baking tool. No master object parenting/modifiers/constraints/animation are copied. Target and master geometry/frame/UV/slot fingerprints are checked unchanged; this is not a whole-scene or shader-state preservation certificate.

## Numeric and workload boundaries

- 1..256 placement requests, spec file at most 1048576 bytes.
- Finite numeric inputs only, not booleans. All scalar/vector component magnitudes are bounded to 10000000; nonzero values underflowing float32 are rejected. Rotation is in [-360, 360] degrees.
- Base mesh: faces required, at most 100000 vertices, 200000 edges and 200000 loops per involved mesh. Conservative modifier expansion must fit 600000 loops before target evaluation.
- Evaluated target: at most 200000 vertices, 600000 loops and 200000 triangles each; combined targets at most 500000 vertices and 500000 triangles.
- Independent copies: at most 1000000 total vertices and 2000000 loops. These are helper safety limits, not universal asset/poly budgets.
- Target transform scale must be at least 1e-6 per axis and its condition ratio at most 1e6; shear dot tolerance is 1e-5. Near-parallel tangent rejection uses projected/input length ratio 1e-7, evaluated after normalizing the input to unit length so the test is magnitude-independent. Ray/tangent normalization uses `math.hypot` on the supplied double-precision components, avoiding mathutils' small-length normalization cutoff; the existing component-range/float32-underflow refusals still apply. Triangles reject zero/collapsed edges and relative cross-product magnitude at or below 1e-7.
- Float32-collapsed ray endpoints, offsets, placement triangles and attachment transforms are refused. Attachment reconstruction error must not exceed max(1e-6, attachment world magnitude * 5e-7). These are implementation precision gates, **not accuracy/engineering tolerances**. They do not make poorly scaled data trustworthy.

All requested hits, tangents, names, dependencies, geometry workloads and transforms preflight before any output collection/object/mesh creation. Ray misses and invalid tangents abort the entire batch. Source/spec hashes are rechecked before and after saving and immediately before publication. The source is opened with autoexec disabled and never saved. Relative dependency paths are made absolute from the source origin in the new snapshot, following `reconstruct_vehicle.py`'s lineage/save pattern; dependencies are not packaged or guaranteed available.

The `.blend` and report are completely staged, then exclusively hard-linked into their destination directories; ordinary report-publication failure rolls back the newly published snapshot without deleting a competitor's file. Existing/race-created files are not overwritten. This is **not a crash-atomic two-file transaction**, filesystem adversary sandbox, or protection against unrelated handlers in an already running Blender process. Never use this helper to open untrusted `.blend` files as a security boundary.

## Verification and contact limitations

Real-bpy regressions:

```sh
uv run --offline --python 3.13 --with bpy --with pillow python -m unittest discover \
  -s "$SKILL/scripts" -p test_place_surface_details.py -v
```

Tests exercise an evaluated solidified rotated/nonuniformly-scaled panel, a curved faceted transformed surface, world normals/tangent twist/nonzero attachment origin, ray/tangent magnitude invariance (unit, 1e-18, 1e-40 and 1e5 inputs), independent copies and DATA/OBJECT/null material slots, whole-batch rejection, float32 collapse, source-byte preservation, save/reopen and real save-handler-induced publication/input-change races. Fixtures are synthetic mechanics evidence, not real-subject reconstruction or visual/artistic approval.

A successful ray establishes **one target-triangle hit** and an oriented **single local attachment anchor** at an explicit offset. It does **not** establish whole-footprint contact, correct bolt insertion depth, vent cutting, watertightness, clearance from other parts, visibility from a reference camera, absence of intersections between copies, hidden contacts, collision-free articulation or mechanical validity. Curved surfaces can leave a finite bolt/vent footprint floating or penetrating despite a correct anchor. Inspect the actual placed geometry under useful views and record unresolved contacts separately. Photographs are not automatically independent 3D measurements.
