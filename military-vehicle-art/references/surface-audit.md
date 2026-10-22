# Evaluated surface audit

## Contents
- [Run and fill a spec](#run-and-fill-a-spec)
- [Exact input schema](#exact-input-schema)
- [Four separate measurements](#four-separate-measurements)
- [Report contract](#report-contract)
- [Safety, scope and tests](#safety-scope-and-tests)

Read-only diagnostics of an existing `.blend`, an explicit UV layer and declared source texture files. These are four new measurements, not the finishing helper's UV-area/island inventory or the PBR builder's map-binding checks. They do not automatically score photorealism, establish subject fidelity, approve an asset or verify that the shader graph actually uses the declared map.

## Run and fill a spec

Use a dedicated process: opening the source replaces that process's current in-memory scene. Requires real `bpy` and Pillow; no other packages, downloads or network are used.

```sh
python "$SKILL/scripts/audit_surface.py" \
  --source /actual/finished.blend --spec /actual/filled.json --report /actual/NEW.json
```

With the already-cached environment used by the mechanics tests:

```sh
uv run --offline --python 3.13 --with bpy --with pillow python \
  "$SKILL/scripts/audit_surface.py" \
  --source /actual/finished.blend --spec /actual/filled.json --report /actual/NEW.json
```

Blender's bundled Python must also have Pillow when using:

```sh
blender --background --disable-autoexec --python "$SKILL/scripts/audit_surface.py" -- \
  --source /actual/finished.blend --spec /actual/filled.json --report /actual/NEW.json
```

`assets/surface-audit.json` is deliberately **unfilled and rejected**: names, scale, map path/hash/dimensions must be supplied. This executable example creates an exact filled spec from a real PNG/JPEG, without an invented hash. Replace the actual path, exact source names and supported physical scale first; run in Python with Pillow:

```python
import hashlib, json
from pathlib import Path
from PIL import Image
texture = Path('/actual/basecolor.png').absolute()
with Image.open(texture) as image:
    size = list(image.size)
spec = {
    'schema_version': 1,
    'meters_per_blender_unit': 1,
    'limits': {'triangles': 1000, 'overlap_pairs': 100000, 'seam_samples': 100000},
    'overlap': {'scope': 'within_object_material_region', 'area_epsilon': 1e-12},
    'seams': {'samples_per_edge': 16, 'inset_fraction': 0.001,
              'discontinuity_threshold': 0.1},
    'targets': [{'object': 'Panel', 'uv_map': 'ProducedUV', 'regions': [
        {'material': 'Paint', 'uv_policy': 'single_1001', 'texture': {
            'path': str(texture), 'sha256': hashlib.sha256(texture.read_bytes()).hexdigest(),
            'size': size, 'role': 'color', 'color_space': 'srgb', 'wrap': 'clamp'}}]}]
}
with Path('/actual/filled.json').open('x') as stream:
    json.dump(spec, stream, indent=2, allow_nan=False)
```

The map declaration identifies what to audit, **not a discovered shader binding**. Run separate specs to inspect different maps on the same material region; do not duplicate a region in one spec. `finish_asset.py` can produce the named UV layer in a new snapshot before auditing that snapshot. No producer schema changes are required.

## Exact input schema

Every listed field is required, with **no extra fields** at any level. Duplicate JSON keys, duplicate objects/regions, booleans masquerading as numbers, nonfinite numbers, null placeholders and empty scopes are rejected. JSON file limit: 1 MiB. Names are exact, nonempty strings, at most 63 UTF-8 bytes, no NUL; they are never normalized.

| Object | Required fields and bounds |
|---|---|
| root | `schema_version`: integer `1`; `meters_per_blender_unit`: number `1e-9..1e6`; `limits`; `overlap`; `seams`; `targets` |
| `limits` | `triangles`: integer `1..20000`; `overlap_pairs`: integer `1..2000000`; `seam_samples`: integer `1..1000000` |
| `overlap` | `scope`: exactly `"within_object_material_region"`; `area_epsilon`: number `0..1e-6`, in squared normalized-UV units |
| `seams` | `samples_per_edge`: integer `1..128`; `inset_fraction`: number `0..0.01`; `discontinuity_threshold`: number `0..1` |
| `targets` | array of `1..16` objects, unique exact object names |
| target | `object`; `uv_map`; `regions`: array of `1..16` regions, at most 64 across the entire spec |
| region | `material`: exact actual material datablock name; `uv_policy`: `"single_1001"` or `"repeat_unwrapped"`; `texture` |
| texture | `path`; `sha256`: 64 lowercase hexadecimal characters; `size`: `[width,height]`, integers `1..16384`, product at most 16777216; `role`; `color_space`; `wrap` |
| texture policy | `role`: `"color"`, `"scalar"` or `"tangent_normal"`; color uses `color_space`: `"srgb"` or `"linear"`; scalar/normal require `"data"`; `wrap`: `"clamp"` or `"repeat"` |

Texture paths are absolute or relative to the spec's directory, at most 4096 characters, no NUL or `..` components. File suffix and decoder format must agree: PNG `.png` or JPEG `.jpg`/`.jpeg`, decoded 8-bit `L`, `RGB` or `RGBA`. Palette, 16-bit, float, animated-sequence/UDIM specifications and other formats are unsupported. At most 67108864 decoded pixels across unique map files. Stored image orientation is used; no EXIF rotation, ICC transform or embedded gamma inference. Alpha is ignored. A scalar map explicitly means **red channel**, not inferred grayscale or packed-channel selection.

Workload limits are implementation safety bounds, **not universal art budgets**. `triangles` counts the whole evaluated mesh of every named target, even undeclared material faces. Pair and seam-sample budgets are cumulative across all measured regions/objects. Pair budget counts all unordered triangle pairs, even AABB-pruned pairs. A sample is one two-sided comparison (up to eight source pixel taps), not one pixel read. Unsupported systems consume no pair/sample work.

### UV domain / tiling / UDIM

- `single_1001`: all audited triangle UVs must be in the **closed** `[0,1]²` tile. Outside coordinates do **not** cause a generic geometry error: the region's four systems report `unsupported_outside_1001`, with bounds/reason and no measurements. An incomplete object's aggregate density is explicitly unsupported.
- `repeat_unwrapped`: requires `wrap:"repeat"` and explicitly declares one repeated image, **not UDIM**. Density/stretch and seam sampling work for negative or multi-tile coordinates. If any audited UV is outside `[0,1]²`, overlap reports `unsupported_periodic_domain`; it does not silently test the unwrapped plane and pretend to exclude periodically folded overlaps. For in-tile coordinates the geometric test covers that tile only.
- No multi-file UDIM resolution, tile splitting, periodic intersection, inter-object or inter-material overlap is claimed. Different material regions are intentionally independent, even if they declare the same map. Cross-region atlas conflicts require another diagnostic.

## Four separate measurements

### 1. Actual texel density

Use evaluated triangle vertices, evaluated `matrix_world` (including parents, scale, shear and live modifiers), then the explicit `meters_per_blender_unit`. Scene unit scale is reported **informationally**, not multiplied a second time. The physical scale must be independently supported by the caller; the audit does not discover true object dimensions.

World edge vectors are transformed in Python double precision; translation cancels analytically before transformation, avoiding float32 loss from subtracting large translated world positions. Blender's stored/evaluated coordinates retain their original precision limitations.

For each triangle:

`pixel_area = abs(UV_triangle_area) * actual_width * actual_height`

`texels_per_meter = sqrt(pixel_area / evaluated_world_area_m2)`

Region and object effective density is `sqrt(sum(pixel_area)/sum(world_area_m2))`, i.e. the area-weighted RMS of local density, **not** an arithmetic average or unique occupied texture area. Overlapping/repeated UV coverage is counted with multiplicity; this is not a packing-efficiency measure. Object aggregates cover declared material regions only; `audited_triangles` versus `evaluated_triangles` discloses scope.

### 2. Actual triangle mapping / stretch

An orthonormal basis in each world-space triangle yields its affine world-plane→UV Jacobian and world-plane→pixel Jacobian. Report both pairs of singular values (descending, per meter), both dimensionless max/min anisotropy ratios, and signed UV winding (`uv_mirrored`, relative to ordered mesh-triangle orientation). Non-square image aspect therefore affects texel anisotropy without changing normalized-UV anisotropy. There is no subjective quality score or universal preferred stretch/density threshold.

Inspect the worst local triangles, especially modifier-generated bevel corners, not only effective object density. Healthy aggregate density can coexist with nearly collapsed local mapping. If base-mesh UV interpolation creates the defect, author the actual corner UVs in a scoped workflow or a separately saved evaluated-mesh derivative; preserve the editable source, evaluated shape and material-slot ownership. Re-audit and inspect the fixed-camera result. Applying a modifier alone is not a UV repair, and a low anisotropy ratio does not establish good grain direction, end grain, seam placement or bake readiness.

### 3. Actual positive-area UV intersection

Every unordered pair **within one object's declared material region** is considered; AABB separation only prunes impossible positive-area intersections. Remaining triangles are intersected by convex geometric clipping with Python float64 arithmetic. Shared edges/vertices alone have zero area and are not overlaps. Reversed winding and containment are handled.

`positive_area_pairs` counts intersection areas **strictly greater** than `area_epsilon`. `pairwise_intersection_area_sum_uv2` is a pairwise sum, **not a union area**; triple coverage counts multiple times. Intersection records stop at 256 but totals do not; omission counts are exact. No raster, UV-area sum or island-packing proxy certifies no overlap. Zero pairs above the chosen epsilon means only that scoped, finite-precision result, not mathematically exact absence at arbitrary tolerances. One triangle reports `not_applicable_single_triangle`, not a vacuous pass.

### 4. Actual hashed source-pixel seam sampling

Only evaluated mesh edges with exactly two incident polygons **in the same declared material region** are compared, with UV endpoints aligned by actual shared vertex identity. Endpoints differing by more than `1e-7` UV units select a split edge; no reliance on the seam flag. Open, nonmanifold and different-material edges are counted/excluded. Unwelded coincident edges are not discovered. Nonmanifold exclusions produce an explicit partial/unsupported status rather than a clean result.

For `N=samples_per_edge`, sample edge parameters `t=(k+0.5)/N`, **not endpoints**. On each side blend the edge UV toward the centroid of its actual incident loop-triangle by `inset_fraction`; this stays within that triangle even for triangulated concave polygons. Density/UV degeneracy is rejected before sampling. Insets and finite resolution can include real texture variation, not just a mathematical seam jump.

Bilinear coordinates are `x=u*W-0.5`, `y=(1-v)*H-0.5` (bottom-left UV / top-left stored pixels). Each pixel tap is clamped or repeated explicitly. `srgb` is decoded with the standard piecewise transfer function **before** interpolation; `linear`/`data` is used unchanged after division by 255. No shader graph, node transforms, mipmaps, filtering derivatives, alpha blending, lighting or normal strength are simulated.

Color delta is maximum absolute linear-RGB channel difference; scalar delta is absolute raw-red difference. Report per-edge/global maximum and mean delta; flag a sampled edge only when its maximum exceeds the declared threshold. This is a measured source-pixel difference, **not proof an artistic seam is wrong or visible**. Tangent normals report `unsupported_tangent_normal`, zero comparisons and null deltas: raw RGB can legitimately differ across tangent frames. No naive RGB normal-seam verdict is made.

Record `sample_count`, `samples_per_edge`, inset, threshold, omitted edge count, and world/pixel spacing on reported edge sample tracks. Maximum world spacing covers all sampled edges. With inset `f`, world spacing is `(1-f)*edge_length_m/N`; pixel spacing is `(1-f)*pixel_edge_length/N` per side. Features narrower than this spacing, unsampled endpoints and missing/unwelded/omitted topology can escape detection. At most 256 edge records; aggregates still include every sampled edge. No split edges gives `not_applicable_no_uv_split_edges` with null deltas, not an all-clear.

## Report contract

Success publishes one exclusive JSON report and returns `0`; this means diagnostics were recorded, **including unsupported/not-applicable statuses**. Validation/workload/decode/publication failure returns `2`, prints `audit-surface: ...` to stderr and publishes no new report. An existing/competing report is never altered.

Top-level fields are exactly: `schema_version:1`, `command:"audit-surface"`, `status:"diagnostic"`, `source`, **`source_sha256` of the actual opened source**, `spec_sha256` of parsed bytes, `meters_per_blender_unit`, `blender_version`, `scene_frame`, `scene_unit_scale_informational`, `units_policy:"explicit_spec_scale_after_evaluated_world_transform"`, `shader_graph_equivalence_verified:false`, `input_files_rehashed:true`, `workload`, `limits`, `targets`.

- `workload`/`limits`: exactly `triangles`, `overlap_pairs`, `seam_samples`.
- target: exactly `object`, `uv_map`, `evaluated_triangles`, `audited_triangles`, `density`, `regions`.
- region: exactly `material`, `uv_policy`, `uv_bounds` (`[[min_u,min_v],[max_u,max_v]]`), `outside_1001`, `triangle_count`, `texture`, `density`, `stretch`, `overlap`, `seams`.
- report texture: exactly resolved `path`, verified `sha256`, decoded `actual_size`, declared `role`, `color_space`, `wrap`.
- measured density: `status`, `world_area_m2`, `pixel_triangle_area_sum`, `effective_texels_per_meter`, `triangles`. Each triangle: `triangle`, `polygon`, `world_area_m2`, `uv_area`, `pixel_area`, `texels_per_meter`. Indices identify the evaluated mesh, not persistent base-mesh IDs.
- measured stretch: `status`, `triangles`. Each: `triangle`, `polygon`, `uv_singular_values_per_meter`, `texel_singular_values_per_meter`, `uv_anisotropy`, `texel_anisotropy`, `uv_mirrored`.
- geometric overlap (including one-triangle status): `status`, `method:"convex_triangle_clipping_float64"`, `scope`, `area_epsilon_uv2`, `triangle_pairs`, `aabb_candidates`, `positive_area_pairs`, `pairwise_intersection_area_sum_uv2`, `intersections`, `intersections_omitted`, `record_limit:256`. Each intersection: `triangles` (two indices), `intersection_area_uv2`.
- seam result: `status`, `uv_split_edges`, `sample_count`, `samples_per_edge`, `inset_fraction`, `uv_endpoint_tolerance:1e-7`, `sampling:"edge_midpoint_strata_bilinear"`, `endpoints_sampled:false`, `alpha_compared:false`, `comparison_space` (`linear_rgb`, `data_red`, `unsupported`), `excluded_material_boundaries`, `excluded_open_edges`, `excluded_nonmanifold_edges`, `discontinuity_threshold`, `discontinuous_edges`, `max_delta`, `mean_delta`, `max_world_sample_spacing_m`, `edges`, `edges_omitted`, `record_limit:256`. Edge: `edge`, `max_delta`, `mean_delta`, `world_sample_spacing_m`, `pixel_sample_spacing` (two side spacings).
- single-tile unsupported system: exactly `status:"unsupported_outside_1001"`, `reason`. Incomplete object density: exactly `status:"unsupported_incomplete_regions"`.
- out-of-tile repeat overlap: exactly `status:"unsupported_periodic_domain"`, `reason`, `periodic_overlap_tested:false`.

Seam statuses: `sampled`, `not_applicable_no_uv_split_edges`, `unsupported_tangent_normal`, `partial_nonmanifold_edges` (some actual samples plus excluded nonmanifold edges), `unsupported_nonmanifold_edges` (none sampled). No comparisons means delta/threshold-count/spacing fields are null, except `sample_count:0`. Region unsupported-domain results use their shorter tagged shape above. All arrays are bounded by the declared workload, object/region limits or 256-record caps; there is no unbounded per-sample output.

## Safety, scope and tests

Source and spec must be distinct regular `.blend`/`.json` files. Report must be a NEW `.json` in an existing directory. Symlink files/components, hardlink aliases among distinct inputs, report/input aliases and `..` paths are rejected before source opening. Reusing the exact same real texture path across regions is allowed with consistent hash/dimensions; distinct hardlinked aliases are not. Source/spec/maps are rehashed after loading/measurement and immediately before exclusive publication. A complete fsynced temporary report is hard-linked exclusively into place, then the temporary name removed; filesystems without hard-link support fail safely. No source snapshot, mesh, UV, material, modifier or source texture is saved or mutated.

Only the named objects' evaluated **mesh components in the active view layer at the saved current frame** are measured. Not dependency-graph instances, motion ranges, all scenes/view layers, linked dependency provenance, shader-displacement silhouettes, padding, bake quality, semantic grain direction, normal tangent correctness, export/runtime readiness or the real object's physical truth. Blender evaluates modifiers in this process's dependency-graph context, not an invented final-render mesh. Loading trusted sources and depsgraph evaluation themselves are not bounded by the Python diagnostic limits; use separate processes/OS resource controls for hostile or enormous files. Input rehashing is not a hostile-filesystem race-proof attestation.

Empty target meshes/material regions, missing names/UVs, nonfinite UVs/transforms, and audited world/UV triangle areas `<=1e-20` are rejected, not silently dropped. All evaluated UV loops must be finite with coordinate magnitude `<=1e6`; transformed edge-vector coordinates must be finite with magnitude `<=1e15` Blender units. These are numerical implementation limits, not artistic budgets.

```sh
uv run --offline --python 3.13 --with bpy --with pillow python \
  -m unittest discover -s "$SKILL/scripts" -p test_audit_surface.py -v
```

Tests use actual bpy/Pillow scenes/images: analytic and non-square density, evaluated parents/shear/modifiers, translation precision, distorted mapping, exact overlapping/adjacent/reversed triangles, bounded detailed records, actual continuous/discontinuous pixels, intended material boundaries, nonmanifold exclusions, sRGB/scalar/wrap policy, tangent-normal refusal, tiling statuses, schemas, aliases/symlinks, changed-input refusal, exclusive competing publication and unchanged source hashes. A real `finish_asset → audit_surface` subprocess test consumes the producer's actual new UV layer/snapshot. Synthetic mechanics only; no real-subject or photorealism certification.
