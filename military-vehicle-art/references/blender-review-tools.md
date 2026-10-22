# Blender audit and controlled review tools

## Run safely
Use a disposable Blender background process, not an unsaved interactive scene. Opening a file replaces the process's current scene. These tools never save the source `.blend`; existing evidence output paths are refused. Disable auto-execution and do not run unknown add-ons or accompanying scripts. Blender parsing is not a security sandbox: use normal OS isolation for untrusted files. Do not install Blender, add-ons, dependencies, or MCP servers without authorization; discover an existing runtime first.

Set `SKILL` to this installed skill's directory; paths below are placeholders. With a supported local Blender:

```sh
blender --background --factory-startup --disable-autoexec --python "$SKILL/scripts/blender_vehicle_tools.py" -- audit --blend "/job/source-v001.blend" --collection "Vehicle" --output "/job/audit-v001.json"
blender --background --factory-startup --disable-autoexec --python "$SKILL/scripts/blender_vehicle_tools.py" -- render --blend "/job/source-v001.blend" --config "/job/review-rig.json" --output "/job/review-v001"
```

Alternatively, a Python environment that ALREADY has the official `bpy` module can run `python "$SKILL/scripts/blender_vehicle_tools.py" ...` without Blender's `--` separator. The authoring forward-test used bpy 5.2.2; do not assume all Blender versions were tested. Discover actual installed version and adapt any changed API explicitly.

## Select only the vehicle
Inspect exact scene and collection names first. `--collection` and JSON `collection` refer to a real named collection in the active view layer, not a fuzzy search. Diagnostic selection uses the **viewport-visible/render-enabled intersection**: excluded or hidden collection branches, locally hidden objects, and render-disabled objects are not reactivated in the review scene. Holdout/indirect-only selected branches require an explicitly prepared review selection rather than silently changing compositing semantics. Generated instances must originate from selected instancers; an unrelated scene instancer of a selected mesh is not included. Select the intended source/detail or export representation, not both if one duplicates the other. Do not include a floor, presentation lights, spare hidden copies, collision proxies, or other vehicles in framing bounds.

If no vehicle-root collection exists, create a temporary collection in the disposable process and link explicitly selected existing objects, deduplicated by object identity. Record the source collection/object list. Do not save that organizational change into the user's file without authorization. Check excluded/hidden collections and viewport-versus-render modifiers; no evaluated geometry is an error, not a passing empty audit.

## Audit: useful facts, not a score
The JSON records source SHA256, runtime version/frame/units, evaluated mesh-instance vertices and triangles, world AABB bounds, each instance transform, material/UV-layer presence, zero-area-face warnings, and edge adjacency counts. File-wide missing external image candidates are included, except UDIM paths.

Interpretation:
- Counts are from current view-layer viewport evaluation, including instances; render-only modifiers can differ. They are NOT exported runtime draw calls, total unique mesh storage, or target-engine performance.
- Mesh only: curves, volumes and other non-mesh forms are not included in audit bounds/counts. Convert an export COPY when their geometry must be counted.
- World AABBs are NOT local design dimensions or valid inputs to assembly measurements without frame conversion. A rotated part grows its world bounds without becoming physically larger.
- Open edges, no UVs, or no materials are diagnostic facts, not universal defects. Procedural source meshes and intentional open planes may be legitimate. UV presence does not mean good UVs.
- No collision detection, automatic historical identification, pivot validation, source authentication, or aesthetic assessment is performed.

## Render: fit once, lock, compare
Copy [the rig template](../assets/review-rig.json) into the job. Its null `collection` is intentionally invalid. The sample direction vectors assume **+Y forward and +Z up**. Verify actual axes before calling a view `front`: directions point from the vehicle center **towards the camera**. Rename/reorient views for the asset; never guess front/rear from a filename. All generated views are orthographic inspection views, not photo-matched views.

The first run fits mesh bounds, pins the camera to vertical sensor fit so landscape/portrait framing uses the same scale convention, resolves each view's `ortho_scale`, and writes `rig-lock.json`. To compare a correction, use the previous `rig-lock.json` as `--config`, a new source version, and a NEW output directory. Do not start from the unfilled template again: automatic reframing could disguise shape changes. The source can change; camera, scale, light, exposure, and render settings must not change during a geometry A/B comparison. If `bounds_outside_locked_views` is nonempty or bounds exceed the locked sphere, inspect clipping and start a separate explicitly labelled framing experiment rather than quietly refitting.

Outputs:
- `*-clay.png`: shared neutral material; isolate form/shading from paint.
- `*-material.png`: actual materials under the same neutral world and three area lights, excluding directly selected source lights/cameras. Nested collection instances can still contain their own lights; inspect those separately.
- `*-silhouette.png`: black unlit surfaces on white; legitimate gaps remain white. Antialiasing is normal, and an antenna can vanish at small sizes.
- `*-frame96.png` etc.: downsampled image frames. **96 is frame height, not tank pixel height.** These are early readability probes, NOT proof of an actual RTS camera, terrain contrast, LODs, or aliasing in the destination engine.
- `render-manifest.json`: source/rig/image hashes, camera matrices, engine/version/frame and image dimensions. It is a separate render-tool record, not schema-2 `review.json` and not an approval. Copy evidence paths/hashes into the existing review only AFTER inspecting the actual images.

The rig deliberately uses CPU Cycles, fixed seed, no denoising, no depth of field, and a neutral Standard view transform. Increase samples/resolution when noise hides a defect; do not mistake a low-sample probe for a final beauty render. These are diagnostic settings, not a universal art direction. Keep a separate beauty rig and actual engine test.

If a tool run fails, preserve incomplete output as failed evidence; choose a new output directory after diagnosing. Never manufacture a successful manifest. No export or animation test is performed by these commands.
