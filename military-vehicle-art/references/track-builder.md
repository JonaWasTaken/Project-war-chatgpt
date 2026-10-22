# Static shared-mesh track builder

`scripts/build_track.py` constructs a complete, closed **static repeated-geometry belt** from an **existing, prepared, approved mesh master**. It creates actual Blender objects sharing that master's actual mesh datablock; it does not manufacture fallback cubes, simplify the link, apply modifiers, merge links, or alter the master. Detailed close-up military-simulation source geometry is supported: mesh material slots, UV layers, attributes, smoothing and custom normals remain shared, not replaced. There is no universal low-poly/triangle limit. A distant LOD or animated texture belt is a separate optional representation, not a substitute for the close-up source.

This helper does **not** create a rig, animated track, suspension, wheels, hinge mechanism, physical collision certification, or an export-ready asset. Its numeric report is not visual approval. Inspect close-up tread/grouser/guide details, winding/direction, seams, contact, wheel and skirt clearance, and intended views after construction.

## Prepare the source master

1. Work in a new approved source snapshot; retain the original artwork. The builder opens that source at its original location and never saves over it. Run the CLI in a disposable Blender/Python process, not an unsaved interactive working scene.
2. Prepare one mesh object with **local +X across link width, +Y along belt travel, +Z outward from the loop**. Origin must be at the actual local vertex bounding-box center, not necessarily the vertex centroid or hinge pivot. Translation in the source scene is allowed and ignored for distribution. Check actual tread direction and outward-facing art yourself; an axis declaration cannot infer them from arbitrary mesh topology.
3. Require unit positive object scale, identity rotation, zero delta location/rotation and unit delta scale (numeric tolerance `1e-6`). No parent, modifiers (even disabled), constraints, object/mesh animation data, shape keys, vertex groups, instancing, rigid body state, linked-library/override master, or edit-mode state. DATA-linked mesh slots remain shared; any OBJECT-linked material overrides are copied explicitly to each new link without changing the master's mesh slots or other mesh users. Prepare/applied results on a separately approved source yourself; the builder refuses rather than applying or silently dropping unsupported state.
4. The actual mesh must contain finite vertices and polygons, nonzero extents in all three local axes (smallest extent greater than `1e-8` of largest), and a centered origin (bounds-center tolerance `1e-6` of largest extent). Measured local +Y extent is the diagnostic link length. Thickness must not be zero. Manifoldness, material quality, correct custom normals, watertightness and artistic detail are not certified.
5. Fill `master.object`, set `master.approved` to literal `true` only after inspection, and replace `approval_note` with the actual approval/preparation basis. That note is user-supplied evidence, not authenticated approval. The shipped [track-spec.json](../assets/track-spec.json) is **deliberately unapproved**. Its generic fictional loop—including illustrative sag—is not a historical vehicle measurement or approved design.

Fresh objects inherit the shared mesh, DATA-linked materials and explicitly copied OBJECT-linked material overrides, including those produced by `build_pbr.py`. They do not inherit arbitrary object-level custom properties, visibility settings, display overrides or animation. Existing objects—including the master—remain present at their original transforms. Newly created links are ordinary visible static mesh objects in the active scene's new collection.

## Spec contract (schema 1)

Required top-level fields: `schema_version`, `master`, `collection`, `prefix`, `path`, `count`, `phase`. Unknown fields are rejected. Master fields are exactly `object`, `approved`, `approval_note`. Path fields are exactly `x`, `yz`.

- Vehicle/world axes: **X width, Y length, Z up**. `path.x` is a constant world X for this one belt. `path.yz` contains ordered `[Y, Z]` world-coordinate pairs in the source scene's Blender units. At least 4 and at most 1024 vertices; the final-to-first segment is implicit—**do not repeat the first vertex**.
- Convex and concave simple closed paths are supported, including restrained sag. All coordinates must be finite numeric values, not booleans. No zero/duplicate edges, self-crossings, nonadjacent touches/overlaps, reversing adjacent edges or degenerate area. Forward-collinear edges are allowed. Scale-relative geometric tolerance is `1e-10`; extremely thin or poorly separated features can be refused conservatively.
- Coordinates are converted to Blender float32 and revalidated **before** building. Reported `effective_path` is the converted path; path length and pitch are measured on it. Center duplicates and catastrophic world float32 loss of the three transformed local extent-axis probes are refused. This is a precision guard, not proof that every tiny bevel survives large scene coordinates. Keep the vehicle near the origin and at a suitable unit scale.
- `count`: literal integer `4..10000`. This is a resource/object-count cap, not a polygon budget or fidelity recommendation. Each object shares the one source mesh even when that mesh is high detail.
- `phase`: finite number in `[0,1)`, a **fraction of one pitch**, not of the whole loop. Link `i` has arclength `((i + phase) * path_length / count) mod path_length`. Count is fixed; there is no hidden rounding of a desired link count.
- Optional **paired** fields `requested_pitch` (positive) and `max_pitch_error` (nonnegative absolute length tolerance, in the same units). Build refuses if `abs(actual_pitch - requested_pitch) > max_pitch_error`. They never stretch links or claim hinge closure. With both omitted, fixed count plus measured actual pitch is sufficient.
- New collection and every generated object name must be unowned. Names are `prefix_00000`, `prefix_00001`, etc.; prefix plus suffix must fit 63 UTF-8 bytes. All conflicts are checked before creating anything. Run a second version with new names and output paths; rerunning never updates/deletes an existing belt.

## Deterministic locally smoothed orientation

Positions remain **on the straight segments**. A polyline has no unique derivative at a corner; the frame is an explicit visual convention, not a mechanical hinge solver:

1. Sample all link centers at the specified equal arclength pitch and phase.
2. At link `i`, normalize the vector from the previous sampled center to the following sampled center. The report names this `orientation_method: centered_neighbor_chord`. Undefined/degenerate tangents are refused before construction.
3. Away from corners, neighbors on a straight run produce exactly the segment tangent. Near corners the frame blends only over neighboring links, rather than spreading an end-corner rotation over an entire long run. Frames vary continuously with phase where that chord remains nondegenerate. Coarse samples around several tight/concave corners can still give a poor visual approximation; refine the path/count and inspect. The report keeps both this frame `tangent` and the exact containing `segment_tangent`, which may differ.
4. Let `s = +1` for CCW in the ordered `(Y,Z)` plane and `-1` for CW, and `T = (0, ty, tz)`. Frame columns are `W = (-s,0,0)`, `T`, `N = (0,s*tz,-s*ty)`. Local +Z maps to the winding-defined outward-side normal field of the sampled tangent. Local +Y follows traversal. Local +X maps to **world -X for CCW** and **world +X for CW**. This width-axis reversal is necessary to retain outward +Z and a right-handed frame for both windings—it is a rotation, not mirrored mesh geometry. Choose winding deliberately for asymmetric side details; a second belt is not generated automatically.

Frames are unit-scale, right-handed with positive determinant (approximately +1 at Blender precision). No negative scaling, mirrored geometry or mesh copying occurs. At concave sections, "outward" is the winding-defined local side, not a radial vector from a guessed global center.

## Run

From the skill directory, with a Blender-compatible Python environment containing `bpy` (no additional third-party dependencies are required):

```sh
python scripts/build_track.py \
  --source /project/source/prepared.blend \
  --spec /project/track-filled.json \
  --output /project/candidates/track-v001.blend \
  --report /project/candidates/track-v001.json
```

Or with Blender:

```sh
blender --background --disable-autoexec --python scripts/build_track.py -- \
  --source /project/source/prepared.blend \
  --spec /project/track-filled.json \
  --output /project/candidates/track-v001.blend \
  --report /project/candidates/track-v001.json
```

Both output parents must already exist. Source, spec, output and report must resolve to distinct paths. Existing outputs, dangling output symlinks and same-source aliases are refused. The CLI disables source autoexecution, opens the original `.blend`, and calls `make_paths_absolute` **while that original is loaded**, preserving relative external image/library targets when saving elsewhere. It reuses `reconstruct_vehicle.check_paths`, `digest` and `save_snapshot`: staged same-filesystem save, exclusive hard-link publication of the new `.blend`, exclusive creation of report, rollback of that new snapshot if report creation fails. Filesystems without hard-link support are a blocker, not an overwrite fallback. Source/spec SHA-256 are checked again before publication; source, spec and output hashes are recorded. No dependency files are copied or rewritten; the result retains absolute dependencies and is not a portable asset package. Existing filepath metadata is remapped in the **new** snapshot; the source bytes remain unchanged.

Success exits `0` and prints output/report paths, link count, actual pitch and warnings. Validation/file/Blender runtime errors exit `2` without publishing a successful candidate. Output and report both remain required; consumers should verify output hash. CLI work changes only the disposable process scene. Unexpected process termination or storage failure is not a transactional filesystem guarantee.

## Read the diagnostic report honestly

The report includes measured mesh-local bounds/extents and tangent length, effective path, winding, count/phase, path length, actual arclength pitch, optional requested-pitch error, and each object's world position, tangent, outward normal, width vector, 4×4 row-major frame, arclength, segment and segment fraction.

`neighbor_chord_distances[i]` is the **actual Euclidean center distance** from link `i` to `(i+1) mod count` after float32 placement. The final entry is `closure_center_spacing`; `closure_arclength_spacing` is always one pitch. These describe center distribution only: no duplicated closure link, no mechanical hinge matching. Sharp bends can make chord distances shorter than arclength pitch. Diagnostics include minimum **neighbor** chord divided by actual local tangent length, pitch/length, and every signed corner turn. The minimum is not an all-pairs clearance search.

Long links are **warned about, not automatically refused or resized**: a +Y bounding-box extent is not an exact collision shape and can include intentionally overlapping grousers or connectors. Warnings flag length exceeding minimum neighboring chord or pitch and absolute corner turns over 15 degrees. The 15-degree threshold is a fixed review cue, **not** an engineering acceptance criterion. Ratios above 1 do not establish safety; ratios below 1 do not prove collision. Finite thickness, local detail, nonadjacent links on concave runs, wheel/skirt geometry and hinge offsets need separate real geometry/visual checks. No `collision_pass` result is emitted.

## Verified runtime and tests

Tested with official `bpy` **5.2.2 LTS**, Python 3.13. Use the installed matching Blender/bpy rather than assuming another Blender major is verified. In the task runtime, the cached environment command was:

```sh
PYTHONDONTWRITEBYTECODE=1 uv run --python 3.13 --with bpy python scripts/test_build_track.py
```

Tests use real Blender data, a synthetic explicitly approved profile-link fixture, both windings, continuous seam frames, a concave loop, malformed paths, count/phase/pitch guards, source preparation refusal, name conflicts, float32 collapse, and actual CLI save/reload. The relocated snapshot test verifies source bytes/hashes, existing objects, shared mesh, UVs/material slots/custom normals and actual relative external image/library targets. These are helper correctness checks—not a rendered close-up vehicle review, animated-track test, physical simulation or target-engine export verification.
