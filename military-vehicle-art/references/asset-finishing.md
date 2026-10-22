# Generic hard-surface finishing

- [Run safely](#run-safely)
- [Exact schema](#exact-schema-version-1)
- [Supported scope and refusals](#supported-scope-and-deliberate-refusals)
- [Report interpretation](#what-the-report-provesand-does-not)
- [Materials and review integration](#chain-to-real-materials-and-review)
- [Regression tests](#verification-and-regression-tests)

Use `scripts/finish_asset.py` for a bounded, reusable pass on explicit local mesh objects: props, furniture, product housings, static architectural components, or vehicle parts. It actually smart-projects a **new named UV layer**, adds an **unapplied editable Bevel modifier**, and/or prepares polygon/edge shading. It does not model missing forms or judge the result.

## Run safely

Use a disposable Blender process, not an unsaved interactive modelling session. Supply an existing `.blend`, a filled JSON specification, and two **new, distinct** output paths. Parent directories must already exist. There is no overwrite flag.

```sh
python /path/to/skill/scripts/finish_asset.py --help
python /path/to/skill/scripts/finish_asset.py \
  --source /project/cabinet-v03.blend \
  --spec /project/finish-filled.json \
  --output /project/cabinet-v04.blend \
  --report /project/cabinet-v04-finish.json
```

Here `python` must already have official `bpy` available. Alternatively, use an installed Blender executable:

```sh
blender --background --disable-autoexec \
  --python /path/to/skill/scripts/finish_asset.py -- \
  --source /project/cabinet-v03.blend \
  --spec /project/finish-filled.json \
  --output /project/cabinet-v04.blend \
  --report /project/cabinet-v04-finish.json
```

The script imports its neighbours relative to its own location, not the working directory. With official bpy Python, exit status is `0` for publication and `2` for a handled error. Blender executable launches can retain their own exit-code behaviour; also require the new report's `status: "finished"` and matching output SHA-256. A console `Saved as` line can refer to a temporary staging file and is not proof of publication.

The helper reuses `reconstruct_vehicle.check_paths`, `save_snapshot`, and `digest`. It never saves over the source: it stages a new snapshot, makes dependency paths absolute **from the opened source's origin**, exclusively publishes the `.blend`, then exclusively creates the report. Existing files, symlinks (including dangling ones), path aliases, and source/spec hardlink aliases are rejected. Publication races do not overwrite the winner; failure to publish the report removes this operation's new snapshot. Source and spec hashes are checked again before publication. Dependency paths are preserved, not bundled or certified available. Treat `.blend` files as trusted inputs; disabled script autoexecution is not a sandbox for untrusted files/plugins.

## Exact schema, version 1

All shown keys are required. No unknown or duplicate JSON keys are accepted at any level. Numbers must be finite JSON numbers, never strings or booleans. Integers must be actual integers (`3`, not `3.0` or `true`). Names are exact, nonblank strings without NUL, at most 63 UTF-8 bytes; the helper never strips, repairs, or automatically renames conflicting names.

Root:

| Key | Value |
|---|---|
| `schema_version` | Integer `1` |
| `targets` | Array of 1..128 target records; distinct `object` names |

Every target has exactly these five keys:

| Key | Value |
|---|---|
| `object` | Exact, unambiguous existing mesh object name |
| `shared_mesh` | `"reject"` or `"copy_for_target"` |
| `uv` | `null` to leave UV layers untouched, or the UV record below |
| `bevel` | `null` to add no modifier, or the Bevel record below |
| `shading` | `null` to preserve shading, or one of the shading records below |

At least one of `uv`, `bevel`, `shading` must be non-null. Selection is not scope: only explicitly named targets are changed, even if other objects are selected.

UV record, exactly:

```json
{
  "name": "CabinetSurfaceUV",
  "method": "smart_project",
  "angle_limit_degrees": 66,
  "island_margin": 0.02
}
```

- `name`: NEW UV layer/mesh-attribute name. Existing UV or other attribute names are conflicts, not invitations to overwrite them. A mesh with 8 UV layers cannot receive another.
- `method`: only `"smart_project"`.
- `angle_limit_degrees`: finite number in `[1, 89]`.
- `island_margin`: finite number in `[0, 0.1]`. This is Blender's **SCALED** margin parameter, not pixels and not a certified final gap.
- Projection uses base-mesh local coordinates, before modifier evaluation. Fixed operator controls: `margin_method="SCALED"`, `rotate_method="AXIS_ALIGNED"`, `area_weight=0`, `correct_aspect=false`, `scale_to_bounds=false`. It does not follow texture resolution or manufacture intentional seams.
- It temporarily enters Edit mode on only the target, including temporarily unhidden/unselected mesh elements, then restores Object mode, object selection/active object and mesh hide/select flags. Existing UV coordinates, pins, and active/render UV choices are preserved. If there were no UV layers, the new layer becomes active. A new UV layer is not automatically made the render default when an older map exists; use its explicit name in shaders.

Bevel record, exactly:

```json
{
  "name": "CabinetEdgeFinish",
  "width": 0.012,
  "segments": 3,
  "angle_degrees": 35,
  "clamp_overlap": true
}
```

- `name`: NEW modifier name on this object; existing modifier names fail.
- `width`: finite positive number, still positive at Blender float32 precision, no greater than `1000000`, in **Blender units**, not automatic metres/millimetres. Scene unit-display settings do not change the literal width. Object, delta, and world scale must be unit within `1e-6`; negative or unapplied scales are rejected, not applied silently.
- `segments`: integer `1..32`.
- `angle_degrees`: finite number in `[0, 180]`; Bevel uses the `ANGLE` limit, `OFFSET` width type, and edges, not vertices.
- `clamp_overlap`: literal boolean; choose explicitly. Clamping may reduce achieved width on tight geometry. Unclamped bevels can self-intersect. Neither choice is a universal quality setting.
- The modifier is appended to the existing stack and **never applied**. Base vertices, edges, faces and coordinates stay unchanged; evaluated geometry, face count, outline, and potentially UV interpolation change. Existing modifiers are not reordered or tuned. Inspect stack order, corner treatment, width and shading at the intended distance. No weighted-normal modifier or arbitrary node graph is generated.

Shading is exactly one of:

```json
{"mode": "flat"}
```

```json
{"mode": "smooth"}
```

```json
{"mode": "smooth_by_angle", "angle_degrees": 45}
```

- `flat`: clears polygon smooth flags; retains existing sharp-edge marks.
- `smooth`: sets polygon smooth flags; retains existing sharp-edge marks, so it does not erase intentional hard edges.
- `smooth_by_angle`: sets polygon smooth flags and **replaces sharp-edge marks** using Blender's `Mesh.set_sharp_from_angle`. `angle_degrees` must be finite and in `(0, 180]`. Boundary/nonmanifold edge handling is Blender's own. It does not generate a geometry-node modifier.
- There is no `"preserve"` mode: use `shading: null`. Targets with custom split normals reject non-null shading to avoid silently replacing an existing normal workflow.

The numbers above illustrate schema only, not an approved material/edge recipe. Choose widths, angles, segmentation, and margins from actual scale, construction, lighting, camera distance and delivery requirements. The distributed [finish-spec.json](../assets/finish-spec.json) is deliberately **unfilled and invalid**: names/numeric controls/boolean policy are `null`. Fill each operation completely or replace that whole operation with `null`. Keep at least one real operation; do not use the template as a quality preset.

## Supported scope and deliberate refusals

Preflight resolves the **entire** target list before editing anything. This static-mesh profile rejects:

- Missing, ambiguous local/linked duplicate names, non-mesh, linked, library-overridden, or noneditable object/mesh data.
- Any current Edit/sculpt/paint mode or mesh left in Edit mode. Targets must be visible and selectable in the current view layer.
- Target parents or children, constraints, animation/drivers on object/mesh, shape keys, vertex groups, rigid-body physics, and target instancing.
- Existing target modifiers other than `BEVEL` or `WEIGHTED_NORMAL`. Prepare a separate static mesh source for armatures, Geometry Nodes, booleans, mirrors, subdivision, simulations or other complex stacks; this helper will not evaluate/apply arbitrary reconstruction logic for you.
- Nonunit scale, nonfinite transforms/coordinates, empty surfaces, or no usable geometric area (at least one base face area must exceed `1e-20`). Limits: 100000 base faces, 400000 vertices, 400000 edges (including loose geometry), and 400000 loops per target, 1000000 loops across targets. These are execution bounds, not art or engine budgets.
- UV projection on an edge with more than two incident faces; open boundaries and disconnected surfaces are allowed. This refusal also bounds island-adjacency work; it is not a complete manifold/mesh validity certification.
- Target object ID dependencies outside ordinary scene/collection membership (for example another object's Boolean/Object Info/texture-coordinate/driver reference), or collection consumers. Preflight follows containing collections through all parent collections and rejects non-membership ID users such as Geometry Nodes Collection Info and collection instances; checking direct object users alone would miss these indirect changes. These can change other evaluated objects even when no unselected datablock is directly edited; isolate a static source first.

Shared meshes require an explicit policy. `reject` refuses when Blender's mesh user count is not exactly one, including extra/fake users. `copy_for_target` duplicates a shared mesh **for this target only**, preserving its existing attributes/material references before adding the finish. Other mesh users keep the original mesh and UV/shading data. No material is created, changed, or rebound; source material slots and polygon material indices are retained. Linked/overridden data remain unsupported even with the copy policy.

Failed preflight makes no finishing edits. A later Blender/operator/validation failure may leave disposable in-memory data changed; it publishes neither requested output. Do not call the library functions as an interactive undo/transaction system. Work from a new named version, never the only original.

## What the report proves—and does not

Report version 1 has `command: "finish-asset"`, `status: "finished"`, source/spec/output paths and SHA-256 lineage, Blender version, and one `targets` entry per explicit target:

- Object name, actual old/new mesh names, copy policy and `mesh_copied`.
- `base_geometry.unchanged` plus before/after hashes of base coordinates and connectivity. This explicitly excludes intended UV/shading/modifier edits, and makes **no claim that evaluated bevel geometry is unchanged**.
- `bevel`: actual read-back width/segments/angle/clamp/offset settings and `applied: false`, or `null`; `shading`: requested explicit operation or `null`.
- `uv`: actual named layer, loop count, bounds `[[min_u,min_v],[max_u,max_v]]`, sum of absolute triangle UV areas, count of triangles with area `<=1e-12`, operator controls, and UV-connected island diagnostics, or `null`.

A new UV layer must have nonempty finite coordinates and finite total triangle area **greater than `1e-12`**; otherwise publication fails. Some triangles can still be tiny/degenerate and are reported. Bounds are measured, not silently clamped to `[0,1]`. Area is a sum, **not nonoverlapping coverage or packing efficiency**.

Islands are connected base faces sharing the same mesh edge and matching UV endpoints within `1e-6`. This approximate connectivity is not geometric overlap detection; disconnected coincident islands remain separate. The exact computed `island_count` is reported, with bounds/face counts/area for the 256 largest islands, `islands_omitted`, and `island_report_limit: 256`. `overlap_tested: false` and `texel_density_tested: false` are intentional. No seam placement, distortion, orientation, final padding, texel density, no-overlap, baking readiness, or artistic/export approval is established by success.

## Chain to real materials and review

Audit the output's **evaluated** UVs with [surface-audit](surface-audit.md) before calling it close-up-ready. The base UV inventory does not inspect new bevel corners: interpolation can create severe local stretch even when aggregate density looks sufficient. Correct the owning UV/chart workflow in a new scoped version, or author a separately evaluated UV derivative while retaining the editable original; preserve shape/material ownership and re-render under the same saved camera/light plan. Do not silently bake away the only editable source or lower a diagnostic threshold to accept the defect.

Use the finished `.blend` as `build_pbr.py --source`, and set the material's explicit `uv_map` to the new name (for example `"CabinetSurfaceUV"`). The PBR builder still requires actual declared texture files/hashes/sizes and explicit bindings; finishing does not create textures, retopologize, bake or optimize assets. See [PBR builder](pbr-builder.md).

For a scene with a known camera and suitable collection, feed the shaded snapshot to `render_registered.py`; see [registered rendering](registered-rendering.md). It renders the existing camera without refitting. Inspect UV/checker layout and neutral/grazing-light surfaces at intended framing before approving the edge/shading recipe. A synthetic test camera is not photographic registration.

## Verification and regression tests

Tested with official bpy **5.2.2 LTS** and Pillow, using only labelled synthetic mechanics fixtures. The tests create temporary sources, reopen real outputs, check source preservation/UVs/base geometry/shared users/materials/context, exercise strict schema and conflicts, test output races and dependency relocation, and pass a produced snapshot through explicit-UV PBR binding and registered **Cycles CPU** rendering. They also run `--help` and Blender-style `runpy` launches from an unrelated working directory. No external assets or network are needed.

With those packages already available:

```sh
python -m unittest discover -s /path/to/skill/scripts -p test_finish_asset.py -v
```

Where cached offline `uv` environments are already supported, the tested invocation is:

```sh
uv run --offline --python 3.13 --with bpy --with pillow python \
  -m unittest discover -s /path/to/skill/scripts -p test_finish_asset.py -v
```

Do not install packages without authorization. Missing bpy skips real-Blender tests rather than validating the helper; missing Pillow blocks the image/render-chain tests. A skipped suite is not a successful integration run. The synthetic render proves executable mechanics, not attractive furniture, product accuracy, architectural correctness or final art quality.
