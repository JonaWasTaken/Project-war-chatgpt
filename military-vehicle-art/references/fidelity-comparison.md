# Reference-fidelity diagnostics

## Contents
- [Three systems and evidence limits](#three-systems-and-evidence-limits)
- [Compare: exact schema and command](#compare-exact-schema-and-command)
- [Contour convention](#contour-convention)
- [Appearance mathematics and image handling](#appearance-mathematics-and-image-handling)
- [Aggregate: exact schema and command](#aggregate-exact-schema-and-command)
- [Output, safety and workload](#output-safety-and-workload)
- [Integration and tests](#integration-and-tests)

## Three systems and evidence limits

`scripts/compare_fidelity.py` adds **bidirectional boundary-distance distributions**, **explicit-region appearance differences**, and **source-bound required-view/worst-case aggregation**. These are not the existing silhouette IoU, registration connector, camera fitting or rig A/B comparison. Requires Pillow + NumPy, not SciPy or a colour-science package. It reads existing files; it neither opens/saves Blender sources nor registers, segments, resizes, warps or exposure-matches images.

A real comparison needs the actual aligned reference image, its independently prepared mask, actual reference/configuration/permission/uncertainty notes, and confirmed projection/crop/occlusion registration. `independent_photo` means an independently supplied photograph, NOT a model render or generated concept. `authorized_design` means an actual separately supplied authorized design, NOT proof of a real object's construction. `synthetic_test` explicitly labels tool mechanics, including model self-mask fixtures; it is never photographic evidence. These declarations are retained, **not authenticated**. Alias/hardlink checks and hash checks cannot discover all copied or falsely labelled imagery.

For real/design evidence, the reference image/mask may not alias either renderer artifact; the reference image may not be a byte-copy of the detail render. Independently drawn masks can legitimately have identical pixel contents. Their independent provenance remains a supplied declaration, not a conclusion from equal or different hashes. Synthetic self-tests are allowed only when labelled as such.

Appearance changes in uncontrolled photographs can be caused by lighting, exposure, camera processing and calibration. Even controlled/calibrated declarations do not establish physical material properties. There is no automatic photographic registration, image authenticity verification, artistic acceptance or whole-model fidelity percentage. Hidden geometry, texture correctness and BRDF realism require separate evidence.

## Compare: exact schema and command

Copy [fidelity-comparison.json](../assets/fidelity-comparison.json) into the job and fill it truthfully. The shipped empty template is **deliberately invalid**. Every listed key is required; extra keys are rejected at every owned object level. Objects below are exact; no implicit defaults:

| Object | Required fields / types |
|---|---|
| comparison spec | `schema_version: 1` (integer, not boolean), `view`, `reference`, `evidence`, `registration`, `appearance`, `regions` |
| `view` | `id: string`, `role: "fit" \| "check" \| "held_out"` |
| `reference` | `path`, `sha256`, `mask_path`, `mask_sha256`, `foreground: "light" \| "dark"`, `source_note` — same field names/conventions as the existing registered-reference spec |
| `evidence` | `kind: "independent_photo" \| "authorized_design" \| "synthetic_test"`, `independent: boolean`; non-synthetic evidence requires `true` |
| `registration` | `confirmed: true` (literal boolean), `note: string` |
| `appearance` | `color_encoding: "srgb"`, `controlled_lighting: boolean`, `calibrated: boolean`, `note: string` |
| each `regions` entry | `id: string`, `mask_path: string`, `mask_sha256: string` |

IDs match `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`; region IDs and decoded mask pixel sets must be unique. Notes require 20–4096 characters and must not start with TODO/REPLACE/`<`. Paths are job-relative strings, hashes exactly 64 lowercase hexadecimal characters. Region masks are explicitly supplied **common pixel masks**, not independent model/reference crops, and must lie inside both foreground masks. At least one nonempty region is required. This prevents background pixels quietly dominating a nominal surface region; it does not prove semantic correspondence.

```sh
python "$SKILL/scripts/compare_fidelity.py" compare \
  --root "$JOB" \
  --manifest "$JOB/registered-side/render-manifest.json" \
  --spec "$JOB/fidelity-side.json" \
  --output "$JOB/fidelity-side-v001"
```

Use the real `render_registered.py` **schema-1 `registered_camera_render`** manifest, not a studio rig or controlled-light material stress manifest. Source path/hash and model detail/mask paths/hashes are consumed directly; **do not add or transcribe a `model` object**. Manifest artifacts stay relative to the render-manifest directory. Actual dimensions must equal the manifest. Named PERSP/ORTHO camera metadata and its finite affine 4×4 matrix are retained; known optional projection fields are checked. Existing renderer metadata beyond the consumed core is preserved by the manifest fingerprint, not interpreted as calibration proof.

The existing reference block can be reused from `registered-reference-spec.json`; omit its `features` ledger here and add the exact comparison fields above. The existing `reference_match.py` IoU report is not silently converted into distance/appearance evidence.

## Contour convention

Foreground is the supplied binary mask, light = 255 and dark = 0; the renderer model mask is light foreground. A boundary sample is a **foreground pixel centre with at least one background 4-neighbour**. Pixels outside the image are background. Hole boundaries and image-edge foreground boundaries count. A full-frame mask has a perimeter boundary; a single foreground pixel has one boundary sample. No half-pixel segment offsets, diagonal erosion, contour subsampling or hidden exterior clipping is used.

For every model boundary centre, compute the nearest reference boundary-centre **Euclidean pixel distance**, then reverse the direction. Integer squared distances are enumerated exactly in bounded blocks and square-rooted as float64; there is no approximate distance transform or sampling error (ordinary floating-point rounding still applies). Reject excessive work rather than silently approximate.

`metrics.contour` contains:
- `boundary_counts: [model_count, reference_count]`.
- `model_to_reference`, `reference_to_model`, `pooled`: each has `mean_px`, `p95_px`, `max_px`.
- `pooled` concatenates all directional samples, weighted by sample count, NOT a mean of directional means. Its maximum is the discrete sampled symmetric Hausdorff distance, not the Hausdorff distance between continuous curves.
- p95 uses sorted-sample linear interpolation at index `0.95 × (N−1)` (NumPy `method="linear"`).

Report both directions: an extra thin protrusion can affect few samples. Aggregate policy checks the **larger directional p95**, plus the symmetric maximum, so even a small failing view is not averaged away. Empty foregrounds and incompatible sizes are errors, not zero-distance matches.

## Appearance mathematics and image handling

All actual decoded images must be aligned, opaque, 8-bit RGB/RGBA PNG or RGB JPEG. Masks must be strictly binary opaque PNG: mode 1 or 8-bit L/RGB/RGBA with equal channels and only 0/255. No thresholding of antialiasing occurs. Paletted, grayscale appearance, floating-point/16-bit and animated images are rejected. A known PNG 16-bit RGB decode must not silently truncate to 8-bit. EXIF orientation other than 1 is rejected; explicitly bake orientation before registration.

**Transparency is rejected anywhere**, not just within selected regions; explicitly precompose to a documented background outside this tool if appropriate. Embedded nonempty ICC profiles are rejected rather than silently ignored/converted. Convert permitted originals to documented sRGB derivatives externally and record that step in `source_note`. A PNG gamma declaration, when present, must be approximately 0.45455 (absolute tolerance 0.00005). No automatic white-balance, ICC conversion, chromatic adaptation, histogram, gain, exposure or contrast normalization occurs. Other metadata does not override the explicit sRGB declaration; that declaration must be correct.

For each common region, `metrics.regions[region_id]` contains `pixels`, `encoded_srgb`, `linear_srgb`, `delta_e76`:

1. `encoded_srgb` uses channel values divided by 255, without exposure changes.
2. `linear_srgb` uses the standard sRGB inverse transfer function: `c/12.92` if `c <= 0.04045`, otherwise `((c+0.055)/1.055)^2.4`.
3. Both encoded/linear objects contain RGB-ordered `signed_mean`, `mae`, `rmse` vectors. Signed errors are **model minus reference**. MAE is mean absolute channel difference; RMSE is square-root mean squared channel difference.
4. `delta_e76` contains scalar `mean`, `p95`, `max` of Euclidean **CIELAB D65 DeltaE76**, not CIEDE2000. Transform linear RGB to XYZ using rows `[.4124564,.3575761,.1804375]`, `[.2126729,.7151522,.0721750]`, `[.0193339,.1191920,.9503041]`; divide by D65 white `[.95047,1,1.08883]`. Let `f(t)=cuberoot(t)` for `t>(6/29)^3`, otherwise `t/(3*(6/29)^2)+4/29`; then `L*=116f(Y)-16`, `a*=500(f(X)-f(Y))`, `b*=200(f(Y)-f(Z))`. p95 uses the same sample interpolation convention.

These precisely named image metrics do not separate albedo from illumination, demonstrate faithful texture provenance or certify physical reflectance. Retain lighting/calibration flags even when differences are small.

## Aggregate: exact schema and command

Create an actual job-local JSON object with exactly these fields (placeholders below are **not runnable defaults**):

```json
{
  "schema_version": 1,
  "purpose": "reference_review",
  "required_views": [
    {"id": "side", "role": "fit"},
    {"id": "rear", "role": "held_out"}
  ],
  "reports": [
    {"path": "fidelity-side-v001/report.json", "sha256": "ACTUAL_REPORT_SHA256"},
    {"path": "fidelity-rear-v001/report.json", "sha256": "ACTUAL_REPORT_SHA256"}
  ],
  "limits": {
    "contour_p95_px": null,
    "contour_max_px": null,
    "region_delta_e76_mean": null,
    "region_delta_e76_max": null
  }
}
```

All four limits require actual project-authored finite nonnegative numbers, **not booleans/null**. No universal artistic threshold is supplied. Each nested object is exact. `purpose` is `reference_review` or explicitly `synthetic_test`; reference review refuses synthetic reports. Required view IDs must be unique and roles must match the compare spec. Fit views were used during adjustment; check views are additional checks; held-out views must truly have been withheld from fitting. Role names do not establish independence by themselves.

```sh
python "$SKILL/scripts/compare_fidelity.py" aggregate \
  --root "$JOB" --spec "$JOB/fidelity-aggregate.json" \
  --output "$JOB/fidelity-multiview-v001"
```

Aggregate accepts only exact comparison outputs: it verifies report/spec/manifest/image/source fingerprints, **recomputes the actual comparison from bound files**, and requires the entire report to equal that result. Hand-entered metric summaries or edited reports with refreshed hashes are rejected. This is reproducibility checking, not cryptographic authorship/authentication: someone able to fabricate an entire matching input history is outside its claims.

It rejects missing/extra/duplicate required views, role substitutions, repeated render manifests, numerically identical camera projection/pose metadata apart from camera name (including signed-zero and integer/float spelling equivalence), mixed source path/hash pairs, and stale/missing bound inputs. Re-render all views for the same immutable saved source before aggregating; do not refresh fingerprints on a changed model and preserve an old review claim.

`threshold_status` is `exceeded` if **any** directional-p95/max contour or **any** regional mean/max DeltaE76 exceeds its authored limit in **any** required view. Equality does not exceed a limit. No averaging across views or regions is performed. Full per-view metrics/failures, evidence declarations and lighting/calibration flags remain in `views`; `worst` retains the worst value/view/role/region for each policy metric; `roles` retains fit/check/held-out results, with `not_present` if a role was not required. `not_exceeded` means only those declared diagnostic limits were not exceeded, never model acceptance.

## Output, safety and workload

Both modes write only a NEW output directory containing `report.json`. Exclusive atomic directory publication reuses the registered renderer's publication primitive; a racing existing directory is not replaced or removed. Input fingerprints are checked before computation and all bound files rehashed after computation immediately before publication. Absolute CLI/manifest source paths are allowed only inside the job root. JSON/reference/region paths are relative. Traversal, empty path segments, symlinks, nonregular/missing/empty inputs, malformed/duplicate-key/nonfinite JSON, bool-as-number fields and unsupported sizes are refused. Paths are a conservative job-scope guard, not a hostile-filesystem security sandbox.

Operational caps, not asset-quality budgets:
- 4,194,304 pixels per image and at most 16,384 pixels per side.
- 32,000,000 model-boundary × reference-boundary pairs per comparison; temporary distance blocks are at most 256×256.
- 32 nonempty distinct region masks; 16 required views.
- 2 MiB per JSON, 64 MiB per encoded image, 512 MiB per saved source; 2 GiB total bytes actually read per invocation, including final rehashes. Source bytes are streamed, not retained in the image/JSON cache. Aggregate recomputation uses the same bounded snapshot cache.
- JSON nesting at most 32 levels.

Use deliberately prepared compatible diagnostic derivatives if necessary, retaining originals and documenting the changed pixel scale. Never silently lower resolution, sample contours or substitute unsupported estimates to escape a cap.

Exit 0 = computed diagnostic (including threshold failures); exit 2 = invalid/stale/unsupported inputs or failure. CLI success/error results are JSON; argument-parser usage errors use standard argparse stderr. No pass/fail return code represents artistic approval.

## Integration and tests

Reports contain `schema_version: 1`, `command: "compare-fidelity"` / `"aggregate-fidelity"`, `source_sha256` at top level, canonical job-relative `source`, and input path/hash bindings. Compare additionally retains `render_camera` and `renderer_registration_note`; aggregate retains the actual source-bound outputs. A current authorized-design comparison may be cited as the job controller's design-review diagnostic metrics JSON, but accepted-design authorization, actual inspected-render design checks and current approval/delegation remain separately required. This tool creates none of them.

Exact parent integration sequence: produce `registered-side/render-manifest.json` and `registered-rear/render-manifest.json` from the **same saved source**, truthfully fill `fidelity-side.json` and `fidelity-rear.json`, run the compare command above once for each actual manifest/spec/new output, then fingerprint those two `report.json` files into the aggregate spec and run aggregate. Only reference/region paths are authored manually; model paths/source hashes come directly from renderer manifests.

```sh
python -m unittest discover -s "$SKILL/scripts" -p test_compare_fidelity.py -v
```

With the already provisioned offline Blender/Pillow environment:

```sh
uv run --offline --python 3.13 --with bpy --with pillow python \
  -m unittest discover -s "$SKILL/scripts" -p test_compare_fidelity.py -v
```

Tests use openly synthetic files, independently implemented brute-force boundary oracles (full-frame/single-pixel/diagonal/hole/shifted cases), scalar sRGB/Lab math, known colour differences, real Pillow files, CLI execution, source tampering, worst held-out failures, edited-report rejection, unfilled-template refusal and publication races. Synthetic fixture `.blend` bytes in consumer unit tests are lineage tokens, not executable scenes or photographic quality evidence. Producer integration must use actual `render_registered.py` outputs; no unit-test metric is evidence that an asset resembles a real subject.
