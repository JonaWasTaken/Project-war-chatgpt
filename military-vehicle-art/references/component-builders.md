# Profile and routed-round component builders

Use `scripts/build_components.py` for deliberate rotational forms and explicitly sampled round supports, pipes or cables. These complement, not replace, the convex-section loft in `reconstruct_vehicle.py`: a hollow shade, bottle wall, lathed foot, curved handle or cable is not another convex body loft. Inputs are authored/measured samples in Blender units, **not automatically extracted from photographs or curves**. The helper does no aesthetic review or engineering certification.

## Execution and publication

```sh
# Already-available official bpy Python; no install required by this helper.
python "$SKILL/scripts/build_components.py" \
  --source /actual/original.blend --spec /actual/filled-components.json \
  --output /actual/NEW-components.blend --report /actual/NEW-components.json

# Equivalent Blender invocation:
blender --background --disable-autoexec --python "$SKILL/scripts/build_components.py" -- \
  --source /actual/original.blend --spec /actual/filled-components.json \
  --output /actual/NEW-components.blend --report /actual/NEW-components.json
```

Use a disposable process; opening the source replaces the current in-memory scene. CLI exit 0 means built/published mechanics; exit 2 means refused/error. Both output parents must already exist. Existing outputs, symlinks (including dangling ones), input/output aliases, hardlinked source/spec and duplicate JSON keys are refused. Source and spec hashes are checked after validation, source-open, construction, actual Blender save, and publication. The saved results are privately staged before exclusive hard-link/exclusive-create publication. This is accidental-change detection, not a transactional lock against an adversary continuously replacing files or parent directories. No source saves, `.blend1` sidecars or overwrites. If report publication fails, this operation's new snapshot is removed; a competing owner's file is retained.

The helper reuses `reconstruct_vehicle.check_paths`, `digest`, `save_snapshot` and strict numeric/schema helpers. Blender opens the **original at its original location**, then `make_paths_absolute()` preserves source-relative texture/library targets before saving the new snapshot. Files are not packed or redistributed: original external dependencies must remain available. Real tests save/reopen both relative PNGs and linked `.blend` libraries. Source bytes and existing mesh/selection/active-object data remain unchanged; adding objects can naturally change scene-level ray/render/Collection Info results, so no universal evaluated-scene-invariance claim is made.

Python API: `validate(spec)` returns the supplied dictionary unchanged or raises `ValueError`; it has no Blender side effects and can run without bpy. `build(spec)` validates again, rejects existing datablock names and non-Object mode, prepares all component geometry, measures real meshes, then links new local objects into one new scene-root collection. On construction failure it removes its own temporary mesh/object/collection datablocks. It returns a JSON-safe mechanics report, not Blender objects. It does not save; use the CLI for lineage/publication. Selection and active object are not reassigned.

## Schema 1 — every field explicit

[assets/component-builders.json](../assets/component-builders.json) is intentionally incomplete and rejected until filled. Remove unused rows; do not pass nulls or add annotations/extra keys to the strict runtime spec.

Root: `schema_version: 1`, `collection: "NewUniqueCollection"`, `components: [ ... ]`.

Common row keys:

- `kind`: `lathe` or `tube`.
- `object_name`, `mesh_name`: explicit, nonempty, new, unique within their respective Blender ID namespaces; at most 63 UTF-8 bytes, no NUL. Collection name must also be new, including scene-root collection names. No automatic `.001` name acceptance.
- `origin`: three finite translation values, each in `[-10000,10000]`. Only translation is supported; no implicit scale, parenting, axis fitting or rotations. Lathe axis is local **+Z**; tube samples are local XYZ. Generated vertices must remain distinct at Blender float32 local and translated world precision. Distinct vertices alone do not establish a valid surface: actual transformed triangle areas and closed-component world volumes are also checked before any objects are linked.
- `segments`: integer `8..128` (not a Boolean), explicit circumferential tessellation. No automatic subdivisions/smoothing of the supplied samples.

Global limits: `1..32` components, `2..512` samples per profile/path, at most `250000` combined `sample_count * segments`, and runtime JSON at most `2000000` bytes. Numbers must be finite numeric JSON values, not Booleans/strings. Coordinates are bounded; profile/tube radius is at most `1000`, nonzero radius at least `0.0001`. These are implementation safety bounds, not a production polygon budget or quality score.

### Lathe

Additional keys: `mode`, `profile`, `smooth_angle_degrees`.

`profile` is an ordered list of `[radius,z]` vertices. Edges are straight between samples; artist-authored extra samples produce deliberate contour curvature. `smooth_angle_degrees` is finite `1..180`, marking sharp edges above that angle; it does not add bevel geometry. Useful modes:

1. **`open_surface`**: positive radii, strictly increasing Z with each step at least `0.0001` before and after float32 conversion. Produces a single thin open sheet, with exactly `2 * segments` boundary edges and outward-facing winding. **No wall thickness or cap** is invented. Example: `[[0.65,0],[0.24,0.65]]`. This is an intentional render surface, not a watertight lampshade.
2. **`closed_solid`**: a simple counterclockwise polygon in the `(radius,z)` plane. The final-to-first edge is automatic; **do not repeat the first point**. Every profile edge must be at least `0.0001`; reversals, nonadjacent touches/crossings, negligible area and clockwise winding are refused. Radii can all be positive for a solid wall around an open air space: `[[0.61,0],[0.65,0],[0.24,0.65],[0.21,0.65]]` includes outer/inner surfaces and annular rim faces. A closed *wall mesh* does not mean its central opening is filled. For a filled cylinder/cone/foot, **only first and last** samples may be on the axis, first below last: `[[0,0],[0.4,0],[0.4,0.15],[0,0.15]]`. Axis vertices become single poles with triangle fans; the axis-to-axis edge sweeps no face. Other axis-touching arrangements are unsupported, not welded heuristically.

Closed cross-section tests use scale-aware conservative tolerances and are repeated after float32 conversion. This input-profile check is not advertised as a general 3D mesh intersection certificate.

### Tube / cable / round support

Additional keys: `radius`, `path`, `frame_up`, `caps`.

- Constant `radius`; taper, elliptic sections, branching, multiple splines and closed loops are unsupported. `path` is `2..512` explicitly sampled XYZ points; no hidden Bézier interpolation, physical sag or adaptive resampling occurs.
- Each step length is at least `max(0.0001,4*radius)`. Adjacent direction changes are at most **45 degrees**. Reversals, coincident points, overly dense paths relative to the radius and sharper kinks are refused before frame construction. Author a gentle sampled bend, reduce radius, or use another modelling method—not a bypass switch.
- Nonadjacent finite centerline segments must be farther than `2.2*radius`. A bounded segment-distance filter catches close return arms/crossed routes, including nearly parallel interior crossings. It is an **input rejection filter**, not a full swept-mesh self-intersection or external-scene collision solver. No collision/clearance certification follows from passing it.
- `frame_up` is an explicit seed vector: length at least `0.0001`, perpendicular component to the initial direction at least 10% of vector length. A parallel/near-parallel seed is refused instead of silently changing orientation. End tangents use segment directions; interior tangents are normalized adjacent-direction bisectors. Minimal-rotation **parallel transport**, followed by orthogonal reprojection, supplies stable frames even through straight/inflection samples. There is no arbitrary world-up reset at each station. UV seam orientation follows this frame; it is not a physically engineered cable torsion solution.
- `caps`: **`none`** preserves two open rings; **`flat`** adds planar triangulated disk fans aligned to end tangents, flat shaded and sharply separated from the smooth side. No rounded plugs or wall/inner bore is invented. A tube here is a constant-radius swept **solid round section**, not hollow plumbing.

## Normals, seams, UVs and measured claims

Topology has consistent authored winding. Closed components must have positive signed BMesh volume `>1e-12` in **both local and actual float32-transformed world coordinates**; open surfaces report both volumes `null`, never an invented solid volume. Volume evaluation subtracts a reference vertex after transformation to avoid translation cancellation without masking world-coordinate collapse. Generated real meshes must have the expected boundary count, no edge fans/loose edges, contiguous manifold-edge winding, finite local normals and geometric triangle area `>1e-16` in both coordinate spaces. Report `signed_volume` and `minimum_triangle_area` retain their local meanings; `world_signed_volume` and `minimum_world_triangle_area` explicitly measure the transformed result. A world-area/volume failure rejects the whole batch and removes all temporary meshes, without publishing either CLI output. Recenter the component or increase dimensions rather than bypassing a precision refusal. Tests inspect outward outer normals, inward hollow-wall normals, cap normals and volumes, not only the return dictionary.

Each new mesh gets `ComponentUV`. Sides map U to circumference fraction `[0,1]`, V to cumulative profile/path arc length `[0,1]`. The circumference is geometrically welded but per-loop U jumps across its honest marked seam. Closed profiles also have a V seam where the polygon closes. Pole fans have nonzero-area per-triangle UVs and pole UV splits; they are not falsely presented as an undistorted polar unwrap. Tube disk caps use separate planar UV islands centered at `(1.5,0.5)` and `(2.5,0.5)` with UV radius `0.4`, deliberately **outside 0–1** and separate from side UVs. Boundary edges and actual per-loop UV discontinuities are marked seams. Every generated Blender-triangulated UV face must have area `>1e-12`.

These are parameterizations, **not packed texture-ready UVs**: no common texel density, angle preservation, global overlap certificate, padding guarantee or bake. Pole distortion, profile circumference changes and nonplanar routed quads require actual surface inspection. Use the existing finishing/surface-audit workflow for destination-specific UV work. A smooth-shaded tube still has a piecewise straight sampled centreline: if its silhouette is too angular, supply suitable path samples within the documented radius/step support limits or choose another method. Do not call higher circumferential tessellation a repair of sparse bend sampling. No Boolean union, fillet at joins, curve fitting, scene collision checks, mesh-triangle self-intersection certification, minimum cable bend-radius engineering, loads, fatigue, fabrication or physical suitability is claimed. Report `self_intersection_tested` is explicitly false.

## Tests and runnable example

```sh
uv run --offline --python 3.13 --with bpy --with pillow python -m unittest discover \
  -s "$SKILL/scripts" -p test_build_components.py -v
```

The tests run actual Blender meshes, signed volumes, winding/normals, UV triangles/seams, boundary topology, save/reopen, external dependency preservation, strict schema/numeric/refusal cases, source/spec change detection and exclusive-publication races. World-precision regressions cover all-distinct vertices with collapsed cap triangles, and nondegenerate but coplanar closed faces with zero world volume; both must roll back the whole batch. They are synthetic mechanics tests, not visual approval.

For a useful integration check, construct a hollow closed-wall shade, a base with welded axis poles and a sampled bent support in a new job. Reopen the saved result and inspect actual mesh boundaries, volume, UV/shading and endpoint relationships. Add deliberate sockets or collars at joins where the design requires them: independently valid solids can still form an ambiguous or disconnected assembly. Run the actual downstream material builder, surface audit and fixed-camera renderer, then inspect the images. This demonstrates the exercised construction pipeline, not a finished electrical product, physical safety or artistic acceptance.
