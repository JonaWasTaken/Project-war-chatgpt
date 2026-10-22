# Registered-camera material and geometry rendering

`../scripts/render_registered.py` renders an **existing named camera** in an existing `.blend`. It does not fit, create a new viewpoint, recenter, resize the frame, or repair a poor registration. Use it for full-resolution photo/model diagnostics and close-up military-simulation asset inspection as well as more distant views. A successful render is not a calibration certificate, historical-accuracy claim, reference measurement, visual approval, or engine acceptance.

## Prepare actual inputs

1. Keep the source and dependencies at their current location. If relocation is necessary, first prepare a path-safe versioned snapshot with the reconstruction helper; byte-copying a file with `//` textures/libraries is not relocation safety.
2. Obtain an existing `PERSP` or `ORTHO` camera with the intended current evaluated pose. For fitted reconstruction, use the fitter's **output scene**, not its original unfitted input. Independently assess held-out points and registration uncertainty. The renderer neither consumes nor validates a fitting report.
3. Name the exact subject collection. Exclude ground, background plates, alternate variants, and clutter from that collection. The tool cannot identify which selected objects are actually vehicle parts.
4. Inspect the source's current scene/view layer, frame/subframe, camera settings, render dimensions, sensor fit/shifts, and square-pixel setting. Full-frame resolution percentage must already be 100. Border/crop-to-border, panoramic and stereo/multiview rendering are refused. Existing camera shifts and natural edge clipping are retained; **no auto-fit is performed**, even if the subject is clipped.
5. Copy `../assets/registered-render-spec.json` to a work file and fill every null with real values. The shipped template is intentionally not executable. Required keys are exactly `schema_version`, `camera`, `collection`, `resolution`, `samples`, `registration_note`. Schema version is integer 1; camera/collection are literal exact names; resolution is `[width,height]`, integer dimensions 16..16384, identical to the source scene. Samples is integer 1..4096; booleans and nonfinite values are not numbers. A meaningful registration note is required (at least 20 non-whitespace-trimmed characters); describe the governing reference/frame/crop, registration method, and known uncertainty. Text length cannot authenticate truth.

Illustrative structure only—not measured reference evidence:

```json
{
  "schema_version": 1,
  "camera": "PhotoCamera",
  "collection": "Vehicle",
  "resolution": [3840, 2160],
  "samples": 128,
  "registration_note": "Use the saved fitted camera at this full reference frame; held-out registration evidence and unresolved lens uncertainty are recorded separately."
}
```

Do not copy the example's dimensions or note as a substitute for checking the real source/reference.

## Run in a disposable Blender process

From a shell, substitute real absolute paths and an output directory that does not exist:

```sh
blender --background --factory-startup --disable-autoexec \
  --python /path/to/skill/scripts/render_registered.py -- \
  --source /path/to/fitted-scene.blend \
  --spec /path/to/filled-registered-render.json \
  --output /path/to/new-registered-render
```

An already provisioned Python environment with official `bpy` and its NumPy dependency can instead run:

```sh
python /path/to/skill/scripts/render_registered.py \
  --source /path/to/fitted-scene.blend \
  --spec /path/to/filled-registered-render.json \
  --output /path/to/new-registered-render
```

No Pillow is used. CPU Cycles performs actual offscreen rendering. The source is opened at its original resolved path with script execution disabled (`use_scripts=False` and auto-execution preference false); no source-save operation occurs. Run only in a disposable process: loading a scene replaces the current in-memory document. This is not a sandbox for hostile native `.blend` files or external dependency code.

Exit 0 means the output directory was published; exit 2 means invalid/unsupported input or runtime failure. The output parent must already exist. Source, spec, and output must resolve to distinct paths. Existing outputs—including directories, files, and live or dangling symlinks—are never overwritten. Rendering and manifest creation happen in a same-parent staging directory. Atomic **exclusive** directory publication uses Linux `renameat2(RENAME_NOREPLACE)`, macOS `renamex_np(RENAME_EXCL)`, or Windows's exclusive rename semantics. A race-created destination is refused even if it is empty; unsupported operating systems/filesystems fail closed. Ordinary failures clean staging and publish no partial success. Process termination/power loss can leave a hidden staging directory, not a completed published result. Linux publication has been exercised; macOS/Windows branches are not runtime-tested here.

## Output contract

The new directory contains exactly:

- `detail.png`: actual material render, opaque RGBA PNG, native full-frame dimensions. No preview scaling, thumbnail substitution, detail downsampling, image alignment, or post-render crop.
- `mask.png`: opaque RGBA binary geometry mask, foreground `[255,255,255,255]`, background `[0,0,0,255]`. A separate opaque white-emission material override on the same frozen mesh geometry, black world, and no lights is rendered with the same camera/projection/size. Its coverage is thresholded at 0.5, producing strictly binary pixels. Material alpha, glass/transmission, shadow catchers, ground/clutter outside the chosen collection, and material shading cannot define foreground. Consequently a transparent mesh master still contributes its geometry. Very thin/subpixel features can disappear at the binary threshold; this is not a fractional coverage mask.
- `render-manifest.json`: `schema_version: 1`, `kind: "registered_camera_render"`, `source: {path: absolute_resolved_source, sha256}`, `camera: {name,type,matrix_world,lens_mm,sensor_width_mm,sensor_height_mm,sensor_fit,shift_x,shift_y,ortho_scale,clip_start,clip_end}`, `image_size: [width,height]`, `artifacts: {mask: {path:"mask.png",sha256}, detail: {path:"detail.png",sha256}}`, and the user's `registration_note`. Additional diagnostic fields include current frame/subframe, pixel aspect, collection, samples, instance count, and lighting/limitations. Camera metadata records the actual isolated rendered camera, not requested guesses. Matrices are row-major Blender world matrices.

Both images share the same static camera and resolution. Camera data is copied from the current evaluated camera, not reconstructed from just a lens value. Static parents/constraints are evaluated, then the world pose is frozen. Blender's matrix-to-transform round trip is checked within float precision (`abs_tol=1e-6`, `rel_tol=1e-6` per component; this permits Blender float32 TRS round-trip noise, including a measured one-ULP rotation difference, not meaningful shear); projection settings must match exactly. A transform outside that precision is refused, never silently refitted. Recorded metadata uses the actual rendered matrix. Camera/rig animation and drivers (including parent/constraint target dependencies) are refused rather than changing pose while rendering. Render event guards and before/after checks reject detectable camera/projection/resolution changes. Source SHA-256 is checked before opening and after rendering, before publication.

## Selection, geometry integrity, and lighting boundaries

The actual named collection is matched in the current view layer. Selection uses the **visible viewport/render intersection**, honoring object hide flags and camera-ray visibility, view-layer exclusion, ancestor collection visibility, and eligible instances. Collection-instance master trees also honor collection/object render visibility. Direct camera-hidden instancers contribute no camera geometry. An emitter's own mesh honors `show_instancer_for_render` rather than the viewport-only self-display flag; vertex/face instancing does not render the source child as an extra copy. A render-visible emitter hidden from viewport evaluation is refused because its self mesh may be absent from that graph; prepare matching display flags or an explicitly validated mesh snapshot. Camera-hidden nested instancers inside a selected instance tree are conservatively refused: the viewport graph does not expose a reliable full visibility chain for every shared master, so prepare a render-matched mesh snapshot instead of accepting resurrected geometry. An outsider instance of the same master does not become selected. The tool snapshots evaluated meshes/instances into a separate render scene; it does not hide original objects or re-link source instancers, which could suppress shared masters or resurrect excluded alternatives. Source object-linked material assignments and mesh attributes/UVs are retained. Holdout or indirect-only selected layer scopes/ancestors and holdout objects are refused. Selected non-mesh renderable types are refused; prepare an explicit mesh snapshot first. Empty eligible geometry or an empty final foreground fails without publication.

Mesh evaluation is the viewport dependency graph at the saved current frame. Explicit viewport/render modifier enable differences and subdivision level differences are refused. Nonuniform parent/child transforms that introduce shear not representable by the isolated object are refused instead of distorting geometry; prepare an explicitly baked versioned snapshot. Simulations, geometry nodes with render-context-dependent behavior, adaptive subdivision, render-time procedural assets, object-identity/random shader variation, external object-coordinate references, and material-driven displacement are not proven equivalent to the original full scene. For close-up work, bake/validate a controlled evaluated mesh and UV/material state, inspect native-resolution detail crops, and keep shader/displacement tests separate. Do not mistake this helper for a complete pipeline validator.

For the material diagnostic, the source world is copied and visible direct scene lights are copied with evaluated transforms/data, including lights outside the subject collection. If the source has no world, a deterministic neutral ambient world `(0.25,0.25,0.25)` is used; there is no invented photo-light estimate. Hidden/excluded light scopes are omitted. Instanced lights are omitted. Source ground/clutter meshes do not cast shadows or reflections into the isolated scene. Color transform is Standard, look None, exposure 0, gamma 1; scene compositing, source film transparency, and source motion blur are not copied. This diagnostic can therefore differ from the source beauty render, and **is not photometric photo matching**. A deliberately dark source world/light rig can produce a dark detail image; the tool does not secretly relight it to look successful.

Full resolution preserves image sampling, not absent model detail. Close-up simulation assets still require independently assessed shapes, panel transitions, seams/welds, fasteners, materials, texel density, normal/displacement behavior, mechanical clearances, cockpit/crew-visible areas where relevant, and actual engine/target-camera checks. No automatic quality percentage or completed-asset claim follows from this render.

## Verify and consume evidence

For fixed-camera material inspection across deliberately different light plans, use [the controlled-light runner](realism-production.md#controlled-material-stress-renders). The ordinary CLI and schema here retain their source-light behavior; the runner invokes the renderer's explicit diagnostic-light override in disposable scenes. For additional aligned-reference contour/appearance/multi-view diagnostics, consume each actual schema-1 render manifest with [fidelity comparison](fidelity-comparison.md), not the material-stress bundle manifest.

Inspect both actual images at native resolution. Confirm landmarks against the original named camera/reference, check clipping, and independently prepare reference masks. The renderer never manufactures reference masks, observed detail labels, measured landmarks, fit approvals, or calibrated lens-distortion/crop evidence. A consumer may pair the artifact paths/hashes from this manifest with user-confirmed reference inputs; it must verify current source/artifact hashes and dimensions and retain honest registration limitations.

Run real tests in an existing Blender-Python environment:

```sh
python -m unittest discover -s /path/to/skill/scripts -p test_render_registered.py -v
python -m unittest discover -s /path/to/skill/scripts -p 'test_*.py' -v
```

Tests create labelled synthetic scenes under `TMPDIR`/the platform temporary-directory policy, render actual CPU Cycles images, read pixels through `bpy`, project known landmarks using Blender's camera projection, exercise PERSP and ORTHO/sensor-fit/portrait cases, preserve source hashes, and reject invalid scenes/paths/animations/publication races. They do not establish the quality of any user vehicle, photometric equivalence, or arbitrary Blender-version/platform compatibility.
