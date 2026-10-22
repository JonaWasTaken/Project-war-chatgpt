# Reference features connected to actual scene geometry

Use `audit_feature_inventory.py` when a reconstruction needs traceable visible details: a particular bolt, hinge, vent, panel, marking or support must have an identified evidence region and a corresponding implementation. It complements, rather than replaces, the existing image feature ledger and registered comparisons. The new check reads actual evaluated mesh anchors; the earlier image ledger records visual assessments. Neither automatically discovers every detail.

## Start with evidence, not a target score

Inventory the whole object's regions before choosing easy features. Record broad forms, connections and conspicuous details as well as small fasteners. For every declared feature, identify its actual reference crop, uncertain identity/visibility, implementation and outstanding visual checks. Look at the images yourself. A count of listed fasteners cannot establish an exhaustive count on the real object.

Do not advertise “95% accurate” from feature counts, a silhouette score, object count or a manually filled spreadsheet. Counts here apply only to this supplied inventory. Unknown/occluded surfaces remain unknown. Do not convert them to observed facts because a plausible proxy was modelled.

## Invocation

```sh
python "$SKILL/scripts/audit_feature_inventory.py" --source "$JOB/current.blend" --spec "$JOB/feature-inventory.json" --report "$JOB/inventory-NEW.json"
```

Run in a disposable official bpy Python process or Blender background with scripts disabled. It opens the specified source read-only and creates only a NEW report. Exit 0 means computed, **not accepted**; exit 2 means invalid/unsupported/stale input or publication failure. A missing feature is a reported finding, not a crash or a pass.

## Exact schema

The top level contains exactly:

- `schema_version`: integer 1.
- `scene`, `view_layer`: exact saved Blender names.
- `evaluation_frame`: integer -1000000..1000000.
- `subject`: subject/version/configuration or authored design identity.
- `scope_note`: actual inventory scope and important omissions.
- `evidence`: 1..64 `{id, path, sha256}` records. Paths are relative to the spec directory, confined beneath it, without symlinks. Copy permitted evidence into that job directory; do not bypass file-access boundaries. Use actual lower-case SHA-256 of the image bytes.
- `regions`: 1..256 `{id, coverage_note}` records. State which surfaces/features have and have not been inventoried. An empty region's count remains zero; do not delete it to improve coverage.
- `features`: 1..4096 records described below. IDs must be unique.

Each feature has exactly:

```json
{
  "id": "front-cover-fastener-01",
  "region": "front-cover",
  "description": "Specific observed fastener, not a generic decoration",
  "epistemic": "observed",
  "uncertainty": "State ambiguity and any unverified size/orientation",
  "observations": [{"evidence": "front-detail", "region_px": [120, 90, 146, 116]}],
  "model": {
    "object": "FrontFastener01",
    "anchor": "bounds_center",
    "vertex_index": null,
    "target_world": [0.2, -0.1, 0.3],
    "tolerance": 0.001,
    "position_basis": "Explain the measured/authored 3D target and uncertainty, not merely this photograph's pixels"
  }
}
```

The numbers above illustrate syntax; they are not default positions or tolerances. `epistemic` is `observed`, `authored`, `inferred` or `unknown`; it is supplied context, not recognized automatically. Observed/authored features require at least one evidence crop. Crops are raw-image `[left,top,right,bottom]` integer pixels, right/bottom exclusive, with positive area inside the real image. EXIF orientation is not automatically applied; prepare a separate explicit oriented image when necessary and preserve its original.

`model: null` records an outstanding implementation or unresolved unknown. Otherwise it selects an exact mesh and either `bounds_center` with `vertex_index: null`, or `evaluated_vertex` with its nonnegative integer index. Evaluated indices can change after modifiers; use them only for the bound saved source. Two IDs cannot reuse the same object/anchor/index to manufacture coverage. An object containing several details requires distinct meaningful anchors or separately named components.

For an unchecked position, set **all three** of `target_world`, `tolerance`, `position_basis` to null. Do not invent a 3D point from an unregistered photo. Targets are three finite coordinates within ±1e8 Blender world units; tolerance is a finite positive number in 1e-12..1e6 with a nonempty basis. These are numerical bounds, not accuracy recommendations. Scene-unit conversion is **not** performed by this helper.

## Results and scope

States are `not_modelled`, `unresolved`, `missing_geometry`, `geometry_present_position_unchecked`, `position_within_tolerance` or `position_outside_tolerance`. The source/spec/image/tool hashes and requested frame are recorded. Observed/authored/inferred/unknown counts remain separate; no whole-object accuracy or acceptance score exists.

The helper evaluates explicit scene/layer/frame, world transforms and supported modifiers. It refuses hidden/excluded/non-mesh/empty/degenerate meshes, unsupported instances/Geometry Nodes, nonfinite coordinates, more than 2 million combined evaluated vertices or more than 4 million triangles on one evaluated mesh. Both local and world-transformed geometry must contain usable area (>1e-20); this is a numerical support floor, not a physical feature-size recommendation. References are static PNG/JPEG, at most 4,194,304 pixels each and 128 MiB combined encoded bytes; spec limit is 1 MiB. These workload limits do not cap production texture resolution—prepare explicitly derived inspection references when needed.

A correct anchor does **not** validate feature shape, physical dimensions, orientation, repeated count, attachment, normals, UVs, material, photographic authenticity or completeness. Use the geometry probes, matched-camera crops and actual visual review for those questions. Render-time displacement and external Blender-dependency fingerprinting are outside this helper's scope. Re-run after source changes; do not refresh old report hashes and call the changed geometry reviewed.
