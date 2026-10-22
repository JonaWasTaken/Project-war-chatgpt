# Local Blender asset-job controller

- [Start a job](#start-every-codex-production-job-here)
- [Action protocol](#codex-action-protocol)
- [Routes and locked intent](#routes-and-locked-intent)
- [References manifest](#references-manifest-referencesjson)
- [Concept/design authorization](#conceptdesign-authorization)
- [Review gates](#review-gates-existing-schema-2)
- [Registration and diagnostics](#blockout-registration-and-diagnostic-metrics)
- [Original-design review](#original-design-review-no-real-subject-photo-fit)
- [Integrity and recovery](#integrity-confinement-and-recovery)

## Start every Codex production job here

This is an executable **local workflow gate**, not an autonomous Codex wrapper. It refuses invalid transitions made through its CLI. It cannot force Codex or a human to use it, inspect aesthetics, establish image provenance, or authenticate the truth of observations or user authorization. A SHA-256 identifies bytes, not their origin or correctness. There is no `codex exec` integration, command execution from job records, network access, installer, or implicit image inspection.

Use standard-library Python 3 for the controller. Run the shell examples using Codex's available shell tool. Set `SKILL` to this installed skill directory and `JOB` to a **new**, explicitly chosen production directory. The only external input allowed to `init` is an explicitly selected, authorized, existing `.blend`; it is read, never modified. The job's parent directory must already exist. A new project still needs a real saved starter scene (which may be empty), not fabricated `.blend` bytes. Create/save that scene using an actual available Blender runtime before initialization; the controller does not create geometry or infer permission to discard any source.

```sh
python3 "$SKILL/scripts/vehicle_job.py" init --job "$JOB" --source "/provided/source.blend" --route existing
python3 "$SKILL/scripts/vehicle_job.py" status --job "$JOB"
python3 "$SKILL/scripts/vehicle_job.py" next --job "$JOB"
```

`init` exclusively creates the directory and saves a byte-identical read-only baseline and SHA-256 under `.vehicle-job/`. It deliberately does **not** byte-copy a scene into an editable location: Blender's `//` texture/library/cache paths would silently retarget. It checks file existence/extension/nonemptiness, not whether Blender can open it.

Before references can advance, run the real Blender preparation helper from the **original source path**, using an already available compatible bpy runtime:

```sh
python3 "$SKILL/scripts/reconstruct_vehicle.py" prepare-source --source "/provided/source.blend" --output "$JOB/work/source-v001.blend" --report "$JOB/source-preparation.json"
```

The Python above must have actual `bpy`; an installed Blender launcher is also supported as described in [reconstruction-tools.md](reconstruction-tools.md). `next` suggests a launcher but does not install one. Preparation opens the original with script execution disabled, makes dependency targets absolute, verifies unchanged geometry/transforms, and saves a NEW snapshot. The controller requires the preparation report's input hash to match its immutable baseline, its `lineage.source` to exactly match the recorded resolved original `source_origin`, and its output hash to match the first selected source. Preparing from the byte-identical archival baseline is refused because it can resolve `//` dependencies to the wrong directory. It snapshots that report at the references transition. It cannot authenticate the report's authorship.

The baseline is an archive, not a relocated working scene. Do not open it as a substitute original when preparing paths. External assets are not copied; missing assets remain missing, and absolute paths do not make the job portable to another machine. Never pass the user source as an output path.

The sequence for every route and intent is strictly:

**references → blockout → assemblies → materials → delivery → complete**

There is no separate synthetic `registered` or `concept` transition. Explicit concept authorization is consumed with references when required; registration/design-review evidence is consumed with blockout. The archived baseline is source lineage, **never** evidence that a concept was approved.

## Routes and locked intent

`--route` describes the production start, while `--intent` describes what the model must match. They are independent:

| Init selection | Required references evidence | Blockout registration |
|---|---|---|
| `--route existing`, intent omitted or explicitly `reconstruction` | Existing schema-1 image/feature/check ledger and real source preparation; optional authorization is validated if supplied | Existing reconstruction fit / measured camera fit / explicitly approved orthographic route |
| `--route new`, intent omitted or explicitly `reconstruction` | The same evidence **plus actual concept authorization**, governing brief, exact accepted images and baseline binding | Still real-subject reconstruction; creating a new T-90/Leopard project does not turn it into an original design |
| Either route with `--intent original_design` | The same evidence **plus actual original-design authorization**, original brief, originality statement, exact accepted design/inspiration images and baseline binding | `design_review`: current diagnostics, review against the accepted design and actual current approval/delegation; no mandatory real-object photo fit |

Use `original_design` for genuinely original fictional vehicles, furniture, props, products, architecture parts and similar authored assets. A model of a specific real chair, aircraft or tank remains reconstruction. Describing a failed reconstruction as “stylized,” changing only a registration mode, or supplying a camera fit as “design review” is not authorization to change objectives.

```sh
# Existing work, compatible default reconstruction intent:
python3 "$SKILL/scripts/vehicle_job.py" init --job "$JOB" --source "/provided/source.blend" --route existing
# New real-subject project; concept approval is required and photo registration remains required:
python3 "$SKILL/scripts/vehicle_job.py" init --job "$JOB" --source "/provided/starter.blend" --route new --intent reconstruction
# Genuinely original design; choose a DIFFERENT new JOB for each independent invocation:
python3 "$SKILL/scripts/vehicle_job.py" init --job "$JOB" --source "/provided/starter.blend" --route new --intent original_design
```

Intent is fixed at initialization and bound into the genesis digest when explicitly supplied. There is no later `--intent` override, migration, rewind, or history-edit command. References must agree with the locked job intent; optional review `intent` must also agree. New history manifests bind intent. Older schema-1 jobs and manifests with no intent retain **reconstruction** behavior and their original genesis digest; they need no migration. Existing unfinished `route: new` jobs can now supply legitimate concept evidence and proceed in their original reconstruction intent.

If the user actually commissions a different original asset after a failed reconstruction, preserve the failed job and its evidence. Obtain a real new original brief/authorization and initialize a separately named original-design job with an explicitly authorized source. Do not claim the old reconstruction passed, rewrite its history, or silently change the requested subject. The controller cannot semantically classify a brief/photo or authenticate consent; these records are integrity checks, not an authentication guarantee.

## Codex action protocol

1. Run `init` once for a new job, otherwise run `status` first. Do not claim a stage has passed merely because a Markdown checklist was filled.
2. Run `next`. Its JSON contains `stage`, `route`, effective `intent`, `history_verified`, `unmet_checks`, `instructions`, and shell-quoted `commands` for existing tools and the exact controller transition. These commands are **suggestions**, not executions. Resolve the reported prerequisites with actual tools. An installed Blender is only discovered from `PATH`, not installed, launched, or certified compatible by this controller. Original-design instructions use `design_review`, not landmark photo-fit suggestions.
3. Work only in the job after the original-location preparation step. Make new versioned source paths and evidence paths; do not overwrite accepted artifacts. Copy the last accepted `.blend` to the next version before editing. Preserve its absolute dependency paths; after adding new `//` assets, remap/package them in Blender at that version's current location before moving it again. Defaults suggest `work/source-v002.blend` after references, then `v003` etc.; other explicit version names are allowed.
4. Produce actual reference observations, measured data, and diagnostic renders. Inspect images with an actual image-capable facility. Preserve the governing brief, image provenance/roles (design, inspiration, measured subject), limitations and actual authorization evidence. If required tools/evidence/authorization are unavailable, remain blocked and report the limitation. Do not manufacture a report, inspection finding, camera fit, or approval to make the controller pass.
5. Fill the current-stage record, using the schemas below. Preview a specific candidate with `status` or `next`, then run `advance` (alias `record`) with the **explicit** current source and stage. Advancement validates and snapshots the record in one operation; there is no separate self-certified "done" flag.
6. Continue from the returned next stage. Existing schema-2 approval/delegation rules apply; no extra human approval is added for every modeling operation.

Examples after creating the real files:

```sh
python3 "$SKILL/scripts/vehicle_job.py" advance --job "$JOB" --stage references --source work/source-v001.blend --references references.json
python3 "$SKILL/scripts/vehicle_job.py" next --job "$JOB" --source work/source-v002.blend --review blockout-review.json
python3 "$SKILL/scripts/check_review.py" "$JOB/blockout-review.json" --root "$JOB"
python3 "$SKILL/scripts/vehicle_job.py" advance --job "$JOB" --stage blockout --source work/source-v002.blend --review blockout-review.json
```

The standalone `check_review.py` remains unchanged; it does **not** enforce this controller's sequence, references, registration, or history. Running it is useful but is not a substitute for `advance`.

CLI exit codes: `0` means the init/status/next/transition request completed; inspect `stage` and `unmet_checks` for readiness. An accepted transition often returns the **next** stage blocked on its missing evidence. `2` means invalid input, integrity failure, locking, or a refused transition. Status/next do not advance the job even when a candidate is ready.

## References manifest: `references.json`

Controller schema 1, independent of review schema 2. All file paths are job-relative POSIX paths. A fingerprint is `{ "path": "...", "sha256": "actual lowercase SHA-256" }`.

Required fields:

- `schema_version`: integer `1`.
- `intent`: optional for reconstruction (omission means reconstruction); **explicit `"original_design"` required** for original-design jobs. Must match init. A reference ledger cannot switch a reconstruction job into design.
- `authorization`: fingerprint of the JSON record below. Required for every `route: new` job and every `original_design` job, regardless of route. Optional existing-reconstruction authorization is fully checked when supplied.
- `images`: nonempty list of fingerprint objects, each also containing nonempty `view` and `description`. Paths must be unique. Supported image types are actual **PNG/JPEG**, structurally checked by bytes, not merely suffix. This is not a complete decoder, image-content inspection, or authenticity test. Convert other real raster formats using an available tool, preserving the original separately.
- `features`: nonempty explicit feature ledger. Each row has `id`, `description`, `basis` (`observed` or `inferred`), nonempty `uncertainty`, and nonempty `reference_paths` citing actual entries in `images`. Use "none identified" only if that is the actual uncertainty finding; never promote inference to observation just to pass.
- `checks`: nonempty list of `{ "name": "...", "status": "pass", "reason": "actual finding", "reference_paths": ["..."] }`. Every cited path must name a real image entry. Empty checks do not pass vacuously. Cover actual view/variant agreement, ambiguous geometry, and missing information rather than making up supported features.

For original designs, accepted images can be genuine concept sketches, approved generated designs, orthographic drawings or explicitly designated inspiration, not necessarily photographs of an existing object. Explain each role and provenance in its `description` and the governing brief. An `observed` feature describes what is visible **in that design image**, not proof that a physical object exists; inferred/unresolved surfaces remain marked accordingly. The controller checks image structure and citations, not this semantic distinction. Image-free briefs do not pass this image-based controller: obtain actual governing concept/reference images instead of manufacturing a blank placeholder to bypass coverage.

Illustrative **shape only**, not evidence or a ready record:

```json
{
  "schema_version": 1,
  "images": [{"path": "refs/side.png", "sha256": "REPLACE_WITH_ACTUAL_DIGEST", "view": "side", "description": "REPLACE_WITH_ACTUAL_SOURCE_DESCRIPTION"}],
  "features": [{"id": "hull-outline", "description": "REPLACE_WITH_ACTUAL_OBSERVATION", "basis": "observed", "uncertainty": "REPLACE_WITH_ACTUAL_UNCERTAINTY", "reference_paths": ["refs/side.png"]}],
  "checks": [{"name": "variant/view coverage", "status": "pass", "reason": "REPLACE_WITH_ACTUAL_CHECK", "reference_paths": ["refs/side.png"]}]
}
```

## Concept/design authorization

Copy `assets/design-authorization.json` into the job and fill it **only from actual authorization**. Its blank strings, empty image list and `pending` status are deliberately non-passing. A new project cannot advance simply because a baseline exists or someone filled generic passing checks.

Authorization schema 1 (a separate JSON artifact, not a schema-2 review):

- `schema_version`: integer `1`.
- `intent`: exactly the locked `reconstruction` or `original_design` intent.
- `objective`: exactly `reconstruct_real_subject` for reconstruction, or `create_original` for original design. A real-subject reconstruction brief is not an original-design brief.
- `baseline_sha256`: exact immutable baseline SHA-256 from `.vehicle-job/state.json`; it names the actual saved starter/existing scene, not an invented approved concept or the relocated preparation output.
- `brief`: fingerprint of the actual nonempty governing brief file copied into the job. Preserve its constraints, intended subject, dimensions/function, style, authorized deviations, image roles, agreed views and approval/delegation scope. The controller accepts nonempty regular file bytes; it does not read or understand a PDF, image, text or other brief format.
- `reference_images`: nonempty list of `{path, sha256}` fingerprints binding **all and only** the images in `references.images`. Paths must be unique and their actual hashes must match. Unauthorized additional images or omitted accepted images fail the exact binding.
- `originality_statement`: nonempty and required for `original_design`; record the actual original-design remit and why this is not a reconstruction/fit to a named existing subject. Optional/unused for reconstruction. A string alone does not prove that the statement is true.
- `approval`: object with `status` equal to `approved` or `delegated`, `gate` equal to `concept`, nonempty actual `reference` and `scope`, and `evidence` fingerprint of the real nonempty authorization artifact (for example an exported user decision or accepted brief with the explicit decision). A free-text “approved” label without that artifact does not pass. Do not record secrets or account credentials.

There is intentionally no concept `model_version`: this decision accepts the governing design/brief/images for the baseline-backed project, not a claim that an existing mesh is already approved. Current modeled output still needs schema-2 blockout review and its registration/design review.

Illustrative **shape only**; capitalized values below are placeholders, not actual consent or hashes:

```json
{
  "schema_version": 1,
  "intent": "original_design",
  "objective": "create_original",
  "baseline_sha256": "ACTUAL_BASELINE_SHA256",
  "originality_statement": "ACTUAL_AUTHORIZED_ORIGINAL_REMIT_NOT_A_REAL_SUBJECT_RECONSTRUCTION",
  "brief": {"path": "brief/design.md", "sha256": "ACTUAL_BRIEF_SHA256"},
  "reference_images": [{"path": "refs/accepted-concept.png", "sha256": "ACTUAL_CONCEPT_SHA256"}],
  "approval": {
    "status": "approved",
    "gate": "concept",
    "reference": "ACTUAL_DECISION_REFERENCE",
    "scope": "ACTUAL_DESIGN_IMAGES_BRIEF_AND_DELEGATION_SCOPE",
    "evidence": {"path": "decisions/concept.txt", "sha256": "ACTUAL_DECISION_SHA256"}
  }
}
```

The corresponding references JSON retains its normal images/features/checks, adding:

```json
{
  "intent": "original_design",
  "authorization": {"path": "design-authorization.json", "sha256": "ACTUAL_AUTHORIZATION_SHA256"}
}
```

For `route: new` reconstruction, use the same shape with `intent: reconstruction`, `objective: reconstruct_real_subject`, the actual reconstruction concept brief/approval, and actual subject images. No `originality_statement` is required. For any route, run real source preparation first, then the ordinary references command; authorization is discovered through the references record, **not** a CLI approval flag:

```sh
python3 "$SKILL/scripts/vehicle_job.py" next --job "$JOB" --source work/source-v001.blend --references references.json
python3 "$SKILL/scripts/vehicle_job.py" advance --job "$JOB" --stage references --source work/source-v001.blend --references references.json
```

The authorization, brief, decision artifact and exact reference images are all snapshotted at that transition. Their accepted live bytes remain immutable. This verifies documentary linkage, not who authored the decision, whether a concept image is licensed, or whether a brief is honest. Never generate an approval, use synthetic tests as consent, or relabel a failed camera fit to obtain passage.

## Review gates: existing schema 2

Use `assets/review.json`, not a new substitute format. `check_review.validate(record, job_root)` is imported from the same scripts directory and remains authoritative for required inspected views, coverage, defect severity/rechecks, source/evidence SHA-256, model versions, and approval readiness.

Controller additions:

- `review.gate` must equal the **current** stage. Gates cannot be skipped or repeated.
- An optional review `intent` must equal the locked job intent. Omission uses that job's intent, never changes it. Reviews stay schema 2; no edits to `check_review.py` are needed.
- `review.source.path` must exactly equal `--source`; all source/evidence paths must be confined real job files without symlinks. A `.blend` suffix is required for the source. Render evidence must also be a structurally supported image, not a text file renamed `.png`.
- `approval.gate` and `approval.model_version` must match the review even for `not_required`. That status additionally needs a nonempty `reference` and `scope` identifying the actual brief/policy/delegation basis. It is not a way around a required blockout approval.
- Blockout additionally needs the `registration` extension below. Later reviews need not repeat it; the accepted immutable history preserves its evidence.

## Blockout registration and diagnostic metrics

Add `registration` to the blockout schema-2 review. This is a documentary bridge to real evidence, **not** a camera fitter or generic aesthetic metric engine.

Common required fields:

- `mode`: for reconstruction, `reconstruction_fit_report` (preferred for the bundled fitter), `measured_camera_fit` (other measured producers), or `orthographic_approved`; for original designs, **only `design_review`**, described below.
- `model_version` and `source_sha256`: exactly match the review's current source.
- `reference_paths`: nonempty citations of real images accepted at the references stage. A `.blend`, a generated rig, or an unrelated render is not an approved modeling reference.
- `metrics_report`: fingerprint of a **nonempty machine-readable JSON object** from the actual current diagnostic run.
- `diagnostic_scope`: what that report measures, its omissions, and why it is diagnostic rather than an aesthetic judgment.
- `metrics_finding`: actual interpretation, including limitations/failures. A nonempty JSON report is **not** treated as a passing visual score.

The metrics producer owns its report schema. No unknown parent-tool schema is assumed. The wrapper declares which current source the fingerprinted report describes. It can point to an actual audit or reconstruction/metrics report; it cannot authenticate that declaration or prove the producer really ran. Original-design diagnostics additionally require explicit current-source binding inside the producer report, as detailed below. Never relabel a stale report as current. The chosen registration/design-review checks and the review's real coverage/defect rules must still pass.

### Bundled reconstruction camera fit (preferred)

Use `mode: "reconstruction_fit_report"` and `fit_report` with the real
`reconstruct_vehicle.py fit-camera` report fingerprint. Keep the common fields
above; the same report may serve as `metrics_report` if sparse reprojection is
its stated diagnostic scope. No separate `camera_report`/`landmarks` conversion
is required. The review's source must be the actual **fitted output** `.blend`:
its hash must equal the report's `lineage.output_sha256`, not `source_sha256`
(which names the pre-fit input). The photo hash must identify one of the cited
accepted images. The controller requires convergence, untouched other geometry,
unused holdouts, at least four fit/two held-out landmarks, and passing explicit
RMS policies; it recomputes per-point errors and both RMS values. This checks
report integrity/consistency, not proof the report was honestly produced or that
the whole model is accurate. Changing/resaving the output requires new evidence.

See [reconstruction-tools.md](reconstruction-tools.md) for actual preparation,
commands, supported solver, and limits. The helper's fixed-lens local perspective
fit does not replace silhouette/detail inspection or ordinary blockout approval.

### Other measured camera producers

Supply both:

- `camera_report`: fingerprint of a JSON object extracted from the actual fitted camera. The small controller documentary schema is:
  - current `model_version`, `source_sha256`;
  - `projection`: `ORTHO` or `PERSP`;
  - `matrix_world`: four rows of four finite numbers, final row `[0,0,0,1]`;
  - `image_size`: `[width,height]`, positive and identical to landmark `model_size`;
  - `ortho_scale` positive for ORTHO; or `lens_mm` and `sensor_width_mm` positive for PERSP.
  Preserve additional calibration/shift/crop fields whenever needed to reproduce the camera; the minimal structural checks do not certify a correct projection.
- `landmarks`: fingerprint of actual projected/reference correspondence JSON in `assets/landmark-measurements.json`'s existing schema. Model version must match. The controller calls the existing `measure_vehicle.landmarks` function and refuses invalid measurements or results outside their justified tolerances.

Standalone diagnostic invocation:

```sh
python3 "$SKILL/scripts/measure_vehicle.py" landmarks "$JOB/landmarks.json"
```

Measure actual camera projections; record compatibility of view, crop, framing, and image aspect. The numeric helper checks supplied projections, **does not fit a camera**, cannot authenticate measurements, and cannot establish a good model from cherry-picked correspondences. Use enough independent landmarks and views to constrain the relevant silhouette/assemblies. A single point may be a diagnostic, not a camera-calibration proof. The schema does not invent a universal landmark count or tolerance.

Common field shape, with no invented results:

```json
{
  "mode": "measured_camera_fit",
  "model_version": "YOUR_ACTUAL_VERSION",
  "source_sha256": "ACTUAL_SOURCE_SHA256",
  "reference_paths": ["refs/side.png"],
  "diagnostic_scope": "ACTUAL_METRIC_SCOPE_AND_LIMITATIONS",
  "metrics_finding": "ACTUAL_REPORT_INTERPRETATION",
  "metrics_report": {"path": "diagnostic-current.json", "sha256": "ACTUAL_REPORT_SHA256"},
  "camera_report": {"path": "camera-current.json", "sha256": "ACTUAL_CAMERA_SHA256"},
  "landmarks": {"path": "landmarks.json", "sha256": "ACTUAL_MEASUREMENTS_SHA256"}
}
```

### Explicitly approved orthographic reference

This legitimate alternative still requires the current metrics report and common fields. Use `mode: "orthographic_approved"`, nonempty `orthographic_reason`, and:

```json
{
  "approval": {
    "status": "approved",
    "gate": "registration",
    "model_version": "YOUR_ACTUAL_VERSION",
    "reference": "ACTUAL_EXPLICIT_AUTHORIZATION_REFERENCE",
    "scope": "EXACT_REFERENCE_IMAGES_AND_ORTHOGRAPHIC_USE_AUTHORIZED"
  }
}
```

This must be actual explicit authorization of the modeling references/projection, not merely the ordinary blockout approval. `pending`, absent approval, or an orthographic inspection rig does not qualify. The program checks record consistency, not who really authorized it. The measured route does not add this extra human gate.

## Original-design review: no real-subject photo fit

This path is available **only** to jobs initialized with `--intent original_design` and their accepted explicit original-design authorization. It is not an alternate registration for reconstruction, including new real-subject projects. A reconstruction job cannot replace failed fit evidence with `design_review`; an original-design job cannot substitute a reconstruction-fit/orthographic mode for actual review of its approved design.

Copy `assets/design-review-registration.json` as the blockout review's `registration` object, not as a standalone review. The template is unfilled, pending and non-passing. The enclosing record remains `assets/review.json` schema 2, with current source/renders, inspected views, full coverage, defects/rechecks and actual blockout approval/delegation. “Fit” coverage means fit to the **authorized original brief, dimensions, function, interfaces and design constraints**, not invented matching to a real-world photograph. Do not mark required coverage `na` merely because the asset is fictional.

Keep all common registration fields and add:

- `mode`: exactly `design_review`.
- `accepted_design`: the **exact fingerprint object** from accepted `references.authorization`, not a new unaccepted design, a brief alone, a render or a camera report. That accepted authorization already binds the governing brief, all design/inspiration images and the actual baseline.
- `metrics_report`: the actual diagnostic JSON must internally identify the current review source. At least one of top-level `source_sha256` (native `blender_vehicle_tools.py audit`/render manifest) or `lineage.output_sha256` (a producer that saved the exact inspected output) is required. If both fields are present, **both** must equal the current review source hash. A pre-edit input `lineage.source_sha256`, old model version label, generic `{ "pass": true }`, or stale hash is insufficient. No producer format conversion is needed for the native audit. This verifies source-byte linkage, not that the producer honestly ran or diagnosed all relevant geometry.
- `design_checks`: nonempty list of `{ "requirement": "actual governing-brief requirement", "status": "pass", "finding": "actual inspection result and limitations", "evidence_paths": ["current inspected render path"] }`. Every cited path must name an inspected render in the current schema-2 review. Cover the actual approved silhouette/proportions, functional/assembly fit, dimensions and important design decisions; do not substitute an aesthetic score, generic “looks good,” or unrelated reference image for current render evidence. The program cannot parse brief semantics or prove complete requirement coverage.
- `approval`: actual design review decision with `status` `approved` or `delegated`, `gate` `design_review`, current `model_version`, current `source_sha256`, `accepted_design_sha256` matching the accepted authorization, nonempty actual `reference`/`scope`, and an `evidence` fingerprint of the real nonempty decision/delegation artifact. Pending, stale-source or unrelated-design decisions fail. The ordinary schema-2 blockout approval remains required too. Both records may cite the **same actual decision/delegation event and artifact** when its real scope covers both; this is not a demand for another artificial approval ceremony.

To prevent mechanical relabeling, `design_review` refuses reconstruction-only registration keys `fit_report`, `camera_report`, `landmarks`, and `orthographic_reason` (even empty), and refuses a metrics report whose `command` is `fit-camera`. A fitted photo report is reconstruction evidence, not original design acceptance. These checks cannot detect someone rewriting an entire false brief/report; do not describe them as provenance or authentication guarantees.

Shape only, **not** an approved record:

```json
{
  "mode": "design_review",
  "model_version": "ACTUAL_VERSION",
  "source_sha256": "ACTUAL_SOURCE_SHA256",
  "reference_paths": ["refs/accepted-concept.png"],
  "diagnostic_scope": "ACTUAL_DIAGNOSTIC_SCOPE_OMISSIONS_NOT_AN_AESTHETIC_SCORE",
  "metrics_finding": "ACTUAL_REPORT_FINDINGS_AND_LIMITATIONS",
  "metrics_report": {"path": "audit-v002.json", "sha256": "ACTUAL_AUDIT_SHA256"},
  "accepted_design": {"path": "design-authorization.json", "sha256": "ACTUAL_ACCEPTED_AUTHORIZATION_SHA256"},
  "design_checks": [{
    "requirement": "ACTUAL_BRIEF_REQUIREMENT_OR_SECTION",
    "status": "pass",
    "finding": "ACTUAL_INSPECTION_FINDING",
    "evidence_paths": ["render-blockout/side-clay.png"]
  }],
  "approval": {
    "status": "approved",
    "gate": "design_review",
    "model_version": "ACTUAL_VERSION",
    "source_sha256": "ACTUAL_SOURCE_SHA256",
    "accepted_design_sha256": "ACTUAL_ACCEPTED_AUTHORIZATION_SHA256",
    "reference": "ACTUAL_CURRENT_DESIGN_DECISION_REFERENCE",
    "scope": "ACTUAL_REVIEWED_DESIGN_SOURCE_AND_DELEGATION_SCOPE",
    "evidence": {"path": "decisions/blockout.txt", "sha256": "ACTUAL_DECISION_SHA256"}
  }
}
```

For an already supported real bpy Python runtime, obtain actual native evidence without photo-camera fitting (fill `review-rig.json` with the exact asset collection and agreed views):

```sh
python3 "$SKILL/scripts/blender_vehicle_tools.py" audit --blend "$JOB/work/source-v002.blend" --collection "ACTUAL_COLLECTION" --output "$JOB/audit-v002.json"
python3 "$SKILL/scripts/blender_vehicle_tools.py" render --blend "$JOB/work/source-v002.blend" --config "$JOB/review-rig.json" --output "$JOB/render-blockout"
# Inspect the actual renders with an image-capable tool; fill schema-2 review and its design registration from real evidence.
python3 "$SKILL/scripts/vehicle_job.py" next --job "$JOB" --source work/source-v002.blend --review blockout-review.json
python3 "$SKILL/scripts/vehicle_job.py" advance --job "$JOB" --stage blockout --source work/source-v002.blend --review blockout-review.json
```

The current design-approval artifact and diagnostic JSON are snapshotted with blockout. Later assemblies/materials/delivery gates use the unchanged schema-2 review rules and immutable accepted original-design history. New design changes outside the accepted remit require actual authorization and a separate job; do not alter accepted reference bytes or their fingerprints in place.

## Integrity, confinement, and recovery

Each accepted transition copies the selected source, review/config, and all referenced evidence files into a read-only history snapshot. A manifest contains each original path, SHA-256, snapshot path, source/stage, locked intent, and previous-manifest digest. The chain starts from route, baseline digest and explicitly supplied intent (legacy omission keeps the original route/baseline genesis). State stores the ordered manifest fingerprints rather than a mutable stage counter. `status`, `next`, and `advance` verify the baseline, complete chain, intent consistency, snapshot bytes, and **live earlier evidence bytes** every time. Missing, changed, stale, or replaced earlier evidence blocks the workflow. Use new paths for later changes, including source revisions. Do not move or edit accepted files inside the job.

Paths are relative to the chosen job root, reject lexical `..`, absolute/Windows-drive paths, and every symlink component, and cannot refer into reserved `.vehicle-job/` as user artifacts. The explicit initial source is the sole external source input; copy authorized references into the job rather than pointing outside it. Source-file hashes and read-only permissions are not authenticity, a malicious-owner security boundary, or protection against deliberate rewriting of all records and hashes. Avoid untrusted concurrent filesystem modification; Blender itself is not sandboxed by this controller.

State JSON is written to a same-directory temporary file, flushed/fsynced, and atomically replaced. Operations obtain an exclusive lock file; concurrent writers/read-status operations are refused rather than racing. Snapshots are completed before state publication. A caught publication failure leaves old state intact, or retains any history already referenced by an atomic commit. Abrupt process death can leave a lock or an uncommitted history directory; the controller fails closed, never silently adopts the partial work.

Recovery is deliberately explicit, not an automatic bypass:

1. Confirm no controller process is running before removing a stale `.vehicle-job/lock`.
2. Preserve the failed job/outputs. If an unreferenced history directory exists after a crash, inspect `state.json` and move only that uncommitted directory **outside** the job for diagnosis before retrying. Never remove a state-referenced snapshot or edit the chain to manufacture passage.
3. For changed accepted artifacts, restore the exact accepted bytes from their verified snapshot or start a new job from a separately selected authorized source. Do not update old fingerprints to bless new bytes. There is no rewind/edit-history command in this revision.
4. If init was interrupted before a valid state was published, preserve that directory and initialize a different new job root. Existing directories are never adopted or overwritten.

Run the real-file tests without Blender:

```sh
python3 -m unittest discover -s "$SKILL/scripts" -p test_vehicle_job.py -v
```

All fixtures are created under `TMPDIR` when set, otherwise the platform's temporary directory. The standard-library mechanics tests use explicitly synthetic PNG/`.blend` bytes, briefs, decisions and authorization records; **none are actual user consent or production evidence**. Coverage includes missing/invalid concept evidence, baseline/preparation/image binding, pending decisions, original/design intent locking, legacy compatibility, tampered history, failed reconstruction bypass attempts, disguised photo-fit reports, stale design metrics/approval, required design checks, unfilled templates, path confinement and atomic publication.

An optional producer/consumer test in the same file runs when actual `bpy` and Pillow are available: it saves a genuine synthetic Blender scene, performs real source preparation, generates a labelled concept drawing, runs real audit/render CLIs, consumes the resulting source hashes/diagnostic JSON/PNG in an original-design blockout transition, and verifies unchanged original-source bytes. Approval/inspection assertions in this test remain **explicitly synthetic mechanics fixtures**, not proof a person approved or aesthetically inspected the asset. Without those runtimes this one integration test is explicitly skipped; it is not replaced with invented tool output.

For an environment with these dependencies already cached and a compatible Python, the following offline invocation exercises the full controller suite including that integration. It is not a requirement to install software or fetch dependencies into a user's production environment:

```sh
uv run --offline --python 3.13 --with bpy --with pillow python -m unittest discover -s "$SKILL/scripts" -p test_vehicle_job.py -v
uv run --offline --python 3.13 --with bpy --with pillow python -m unittest discover -s "$SKILL/scripts" -p test_reconstruct_vehicle.py -k real_fit_report_connects -v
```

The latter retains the real reconstruction producer/consumer camera-fit contract without transcription. Neither integration certifies artistic quality, reference truth/provenance, real-user approval, engine readiness or actual user asset production. No test edits a user's source asset or automatically resumes a previously blocked production job.
