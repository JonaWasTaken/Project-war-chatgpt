# Blender reconstruction tools

- [Runtime and commands](#runtime-and-commands)
- [Loft constructor](#loft-construct-a-controlled-primary-form)
- [Camera fitting](#fit-camera-local-pose-fitting-against-actual-landmarks)
- [Controller integration](#connect-the-fitted-result-to-the-job-controller)
- [Verification](#verification)

`scripts/reconstruct_vehicle.py` performs bounded, offline operations with
real Blender datablocks. It does not generate a whole vehicle from a photograph,
invent landmark coordinates, add decorative cubes, or certify model accuracy.
Use a disposable process; never run it inside an unsaved interactive session.

## Runtime and commands

Requires official Blender Python (`bpy`) and NumPy (a `bpy` dependency). No SciPy,
add-ons, online services, downloaded assets, or authentication are needed.
The examples below run from this skill's directory; supply your own paths.

```sh
uv run --python 3.13 --with bpy python scripts/reconstruct_vehicle.py loft \
  --source source.blend --spec assets/loft-spec.json \
  --output hull-reconstruction.blend --report hull-reconstruction.json

uv run --python 3.13 --with bpy python scripts/reconstruct_vehicle.py fit-camera \
  --source prepared-photo-scene.blend --spec filled-camera-fit.json \
  --output camera-fit.blend --report camera-fit.json
```

When Blender itself is installed, the equivalent launcher is:

```sh
blender --background --factory-startup --disable-autoexec \
  --python scripts/reconstruct_vehicle.py -- loft \
  --source source.blend --spec assets/loft-spec.json \
  --output hull-reconstruction.blend --report hull-reconstruction.json
```

Replace `loft` with `fit-camera` and use its spec to fit a camera. For reliable
shell exit status, prefer the official-`bpy` Python launcher: Blender versions may
handle Python `SystemExit` differently. Read the JSON report, not Blender's log
text, as the machine-readable result.

Before a production job relocates any `.blend`, use `prepare-source` to preserve dependency targets:

```sh
uv run --python 3.13 --with bpy python scripts/reconstruct_vehicle.py prepare-source \
  --source /original/location/source.blend \
  --output /job/work/source-v001.blend --report /job/source-preparation.json
```

This subcommand needs no spec. It opens the ORIGINAL scene at its original location,
turns external-file paths absolute, rejects unresolved relative references and changed
geometry/transforms, then publishes a new snapshot and lineage report. The controller
requires this report before advancing references. Do not prepare from its archived
baseline: relative paths would already resolve against the wrong folder. Assets are
not copied or downloaded; availability and cross-machine portability remain separate.
Only run a dependency-installing `uv --with` command if installation is authorized;
an already installed compatible bpy/Blender can execute the helper instead.

`loft` and `fit-camera` require exactly `--source`, `--spec`, `--output`, and `--report`.
Source/output filenames must end in `.blend`. All four paths must be distinct;
source and spec must exist, both output paths must not exist (including broken
symlinks), and output parent directories must already exist. No overwrite flag
exists. A new source snapshot is saved, never the input file. Reports record
source/spec/output SHA-256 and Blender version. `fit-camera` also records the
actual photo's absolute path, SHA-256 and decoded pixel dimensions.

Embedded script auto-execution is disabled both in preferences and at file load.
This is not a complete security sandbox for hostile `.blend` files. External
file references are made absolute before snapshot saving so moving the result
does not silently retarget source-relative textures/libraries. These assets are
not copied or downloaded. Same-filesystem staging and exclusive publication
refuse even targets created between preflight and saving; the destination
filesystem must support hard links. Save failures return an error rather than
falling back to overwriting anything.

## `loft`: construct a controlled primary form

Copy `assets/loft-spec.json` and edit its measured or explicitly provisional
sections. The supplied example is an illustrative, uncalibrated four-station
hull-like profile, **not measured Leopard geometry**. It creates a tapered,
shouldered 24-vertex mesh, not a primitive cube with detail objects attached.
It can run against an empty or existing `.blend` provided its new names are free.

Schema version 1:

- `object_name`: exact new object and mesh datablock name.
- `collection`: exact new collection name. Any existing object/mesh/collection
  ownership conflict is rejected, never replaced or silently renamed.
- `sections`: at least two entries ordered by strictly increasing `y`.
- Each section has `y`, `labels` and `xz`. `xz` lists ordered `[x,z]` corners
  around one simple, strictly convex ring in the XZ plane. Do not repeat the
  first corner at the end; do not include collinear intermediate corners.
- Each ring must have the same corner count and the identical ordered unique
  `labels`. The labels assert the physical correspondence of those corners;
  they cannot prove that an annotation is semantically correct.
- Coordinates are world-space Blender units. The new object has identity
  transform; X is width, Y is station/length, Z is height. Interpret scale and
  forward direction consistently with the prepared source scene.

Both clockwise and counterclockwise rings are supported, but winding must be
consistent between stations. Corresponding edges may not rotate 90 degrees or
more between adjacent stations. Convexity is checked across the entire linear
interpolation using signed edge/vertex quadratic extrema, including after
Blender float32 conversion; a folded interval between sample slices is refused.
Concave profiles, branching topology, variable corner counts,
resampling, booleans, nonfinite values, zero edges/areas, touching or crossing
rings, unsupported correspondence and float32 collapse are refused. Split such
assemblies into simpler convex lofts with different new names. This is a bounded
primary-form constructor, not arbitrary topology repair.

The output has connected side quads and two polygon caps with outward winding.
Reports contain stored-coordinate bounds, vertex/face counts and signed volume.
The source's existing meshes, object visibility and materials are not changed;
an existing vehicle and a new reconstruction may overlap. Explicitly isolate
assemblies in a separately prepared scene for review instead of assuming that
this tool hides old geometry. A watertight primary form is not a detail pass.

## `fit-camera`: local pose fitting against actual landmarks

`assets/camera-fit-spec.json` is an intentionally **unfilled** template. Null
pixels, empty hashes and placeholder paths are invalid; they must not be turned
into plausible invented observations.

Prepare a separate `.blend` and annotate the actual photograph:

1. Name an existing local perspective camera in the current scene. It must be
   unparented, unconstrained, unanimated/driver-free, with unit scale and identity
   delta transforms. Initialize it reasonably close to the reference view.
   The tool fits this named camera; it does not switch the scene's active camera.
2. Put named static, unconstrained landmark objects at actual model features.
   Their **object origins in world space** are the 3D observations; no coordinates
   are accepted in the JSON and missing objects are never created. Parent
   transforms are included, but landmarks may not descend from the fitted camera.
3. Supply at least six distinct objects: at least four `role: "fit"` and at least
   two `role: "holdout"`. Prefer six or more fit points spread across depth and
   the photo. Fit points must span a nondegenerate 3D volume; coplanar/collinear
   configurations are deliberately unsupported by this local solver.
4. In each `pixel: [x,y]`, annotate the corresponding feature in the actual photo,
   measured continuously from its **top-left**, +X right and +Y down. Coordinates
   must lie inside the full image. Holdouts are excluded from the least-squares
   objective; never promote them to fit merely to lower the reported error.
5. Set `photo.path` to an existing image (relative paths resolve against the spec
   directory), `photo.sha256` to its actual lowercase 64-character SHA-256 and
   `photo.size` to decoded `[width,height]`. Hashes are verified, not trusted.
   Use an uncropped, undistorted/rectified image, or prepare a correctly calibrated
   crop before annotation; no image distortion, crop or principal-point solving
   is performed. Image dimensions must each be 16..32768.
6. Prepare the scene's render width/height to match the photo exactly, at 100%
   resolution, square pixels, without a render border. Existing sensor fit,
   sensor dimensions and lens shifts are used by Blender projection, not replaced.
7. `lens` must be `{"mode":"fixed","millimeters":50}` with the actual existing
   lens substituted. Only fixed-lens pose solving is implemented: no focal-length
   estimation or bounded-lens claims. The tool does not alter camera lens data.
8. Set explicit `solver.max_iterations` (1..500), `fit_rms_limit_px` and
   `holdout_rms_limit_px` (finite positive numbers). The template's 3/5-pixel
   limits are example acceptance policies, not historical accuracy measurements.

For example, calculate the photo hash locally with Python's `hashlib.sha256` over
its bytes; do not copy a hash from another reference or normalize malformed text.

The NumPy damped least-squares solver numerically differentiates **actual Blender
`world_to_camera_view` projections**. It optimizes six pose parameters only, with
position scaled by the fit-point bounding-box diagonal. It rejects initial fit
RMS greater than 25% of the photo diagonal, rank-deficient pose Jacobians,
behind-camera/depth-clipped landmarks and unsupported configurations. Search is
local: translation may move at most two fit-point diagonals and rotation at most
60 degrees from initialization. Convergence requires a normalized-gradient
stationarity test, not merely crossing the user's error threshold.

Before/after hashes cover raw mesh coordinates/topology, evaluated current-scene
meshes, other object world transforms, visibility flags and dependency-graph
instances, including hidden meshes. A camera-dependent rig that changes these
is rejected, not silently saved. This check is not a simulation/export test and
cannot validate uncomputed external caches or a different animation frame.

### Result interpretation and exit codes

- **0**: loft built, or camera solver converged **and** both explicit reprojection
  RMS policies passed. A new `.blend` and JSON report are published.
- **3**: camera converged but a reprojection policy failed. A diagnostic fitted
  snapshot and report are still saved, with `acceptance.passed: false`.
- **2**: invalid input, unsupported configuration, I/O error or nonconvergence.
  No fitted snapshot is saved. Nonconvergence writes a diagnostic JSON report
  (`status: "nonconverged"`); validation errors emit JSON to stderr and normally
  leave neither output. Never reuse the same output/report names on a retry.

Camera reports separate `solver.converged` / `status` from `acceptance.passed`.
They include initial/final camera matrices, lens, solver stop reason, initial fit
RMS, separate fit/holdout count/RMS/mean/max pixel errors and every landmark's
actual world position, observed pixel, projected pixel and error. Source,
specification, photo and saved snapshot lineage are explicit. Converged fits do
not imply good holdout agreement; good sparse agreement does not prove the
unseen silhouette, topology, fine detail, or historical dimensions are correct.

**A photo is not independently measured mesh ground truth. Sparse reprojection
cannot establish “95% model accuracy” or “95% original detail”.** Use multiple
calibrated views and independently measured geometry for such claims. This tool
provides reproducible construction and camera alignment, not a percentage score.

## Connect the fitted result to the job controller

Use `registration.mode: "reconstruction_fit_report"` in the blockout review and
`registration.fit_report: {"path": "fit-current.json", "sha256": "ACTUAL_DIGEST"}`.
Select the **fitted output** `.blend` as the current review source, not the
pre-fit input. The controller reads this report directly, verifies the output
hash and accepted photo hash, independently recomputes landmark/RMS arithmetic,
and requires convergence, preserved geometry and passing fit/holdout policies.
No hand-transcribed camera/landmark wrapper is needed for this route. Supply the
common diagnostic scope/finding and metrics fingerprint described in
[job-controller.md](job-controller.md); this same fit report may be the metrics
report when sparse reprojection is the stated scope. Silhouette/detail evaluation
is still separate. Any subsequent save/edit changes the source bytes and requires
new current evidence; never refresh an old report's source hash to bless it.

## Verification

```sh
uv run --python 3.13 --with bpy python -m unittest discover \
  -s scripts -p test_reconstruct_vehicle.py -v
```

The tests create real synthetic `.blend` and PNG fixtures under `TMPDIR`, derive
2D observations from a known camera and actual named objects, perturb the camera
and check recovery using independent holdouts. They also check capped loft
bounds/manifold edges, source hashes, malformed inputs, output/name ownership,
hidden camera-dependent geometry and moved-snapshot external paths. Synthetic
fixtures test implementation mechanics only; they are not real-vehicle evidence.
Plain Python without `bpy` skips these integration tests rather than mocking
Blender. They must also be executed under real `bpy` before claiming verification.
