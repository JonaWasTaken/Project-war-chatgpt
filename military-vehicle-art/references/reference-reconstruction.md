# Reference-guided reconstruction: choose the evidence, then the method

## Scope of “copy this vehicle”
Reconstruct observable shape and appearance from permitted references. Do not promise a quality multiplier or “95% original detail” without a defined, independently evaluated target. One photo cannot establish the unseen side, underside, internal construction, true scale, material response, or exact lens. Matching its outline can be achieved by a flat cutout; that is not a complete reconstruction.

Separate the acceptance questions:
1. Does the named variant/configuration agree with reliable sources?
2. Do held-out landmarks and silhouettes agree in registered complementary views?
3. Do visible secondary details have matching shapes, positions, counts, mounting relationships, and negative spaces?
4. Do shaded surfaces and materials hold up under different light/view directions?
5. Does the actual exported unit work at the intended game camera and unit count?

A “0.95 silhouette IoU” target is legitimate only as that ONE diagnostic; never relabel it as 95% of the whole vehicle. A detail ledger is manual evidence, not a statistically complete inventory. Unknown/occluded features stay unknown, not “matched by assumption.”

## Choose a reconstruction route before modelling
Default to agent-authored geometry/materials from permitted reference observations. The first two routes below require explicit authorization; a public file or potentially faster route is not permission to substitute downloaded or image-derived geometry for a from-scratch request.

| Evidence and constraints | Recommended route | Do not claim |
|---|---|---|
| Suitable licensed source mesh and editable delivery allowed | Inspect/rework that asset, verify provenance and variant, then adapt/bake/optimize | Ownership or redistribution rights from a download link alone |
| Many coherent real photographs around the SAME stationary subject | Evaluate a real installed photogrammetry pipeline, then repair/retopologize/bake its result | That reflective paint, featureless armour, moving parts or inconsistent captures will reconstruct cleanly |
| Complementary reliable photos/drawings with known configuration | Camera registration + profile-controlled geometry + reference-specific assembly work | Exact hidden geometry or dimensions unsupported by the evidence |
| Only a single photo | Constrained visible-view approximation and conservative inferred volume; request additional views before accuracy claims | Full photographic copying or unseen-detail recovery |
| Fictional approved concept | Design reconstruction with explicit hidden-side decisions | Historical accuracy from generated art |

The skill does not bundle a photogrammetry service, neural image-to-3D model, asset library, or license. Discover actual tools and ask before installs, uploads, spending or service use. Generated extra views are design hypotheses, not independent observations.

## Executable route for complementary references
1. **Start a controlled job.** Read [job-controller.md](job-controller.md). Use its `init`/`status`/`next` commands and preserve immutable source snapshots. The controller rejects invalid transitions when used; it is not a system hook that can force an agent to invoke it.
2. **Prepare evidence.** Copy permitted originals without destructive edits. Record original dimensions/crop, provenance, variant, pose, and uncertainty. Select complementary views that expose both global shape and important connections. Keep fine-detail crops tied to their whole-vehicle source.
3. **Place honest landmarks.** Create named Blender landmark objects at genuinely identified positions, distributed across the visible vehicle and depth. Do not move them arbitrarily to fit a photo. Reserve supported landmarks as holdouts, not optimizer inputs. Avoid occluded or ambiguous corners.
4. **Register the camera.** Use [reconstruction-tools.md](reconstruction-tools.md) for the fitted perspective-camera helper. Supply a reasonable initial camera and supported point correspondences. Inspect fit residuals, held-out residuals, lens/pose plausibility, and alternate views. A local numerical fit can fail or absorb model errors; it must not silently deform geometry. Never use an orthographic studio render as a calibrated perspective-photo comparison.
5. **Build deliberate primary surfaces.** Trace supported profiles/sections with consistent point correspondence. Use the section-loft helper for suitable hull/fuselage/armour masses; use appropriate direct modelling for features not represented by that construction. Cross-sections are supplied geometry, NOT automatically extracted from photos. Keep unsupported profiles conservative and identified as inference. Inspect transitions in clay before detailing.
6. **Measure the visible difference.** Render the actual prepared camera with [registered-rendering.md](registered-rendering.md), then use [registered-comparison.md](registered-comparison.md) to pair its fingerprinted geometry mask/detail image with independently prepared references. The connector removes manual model-side transcription, not reference observations. See [photo-match-tools.md](photo-match-tools.md) for metric scope. Inspect contour overlay and reference/model crops. Diagnose camera/occlusion/mask errors before deforming geometry. Do not rescale or warp images merely to improve a metric.
7. **Refine reference-specific assemblies.** Establish a representative finished region; propagate only the supported shape/material language. Use crop evidence for mantlets, optics, hatches, tracks, vents, mounts and other identity features. A dark rectangle is not automatically a vent; identify its actual function/shape from complementary references or leave it provisional.
8. **Recheck generalization.** Re-render held-out views, alternate light directions, required poses and intended screen size. A correction must not win only in the fitting view. Update current review evidence, preserve older reviews as historical, and advance through the controller only with the required checks/authorization.

## Repair the failure, not the score
- Good fit points but poor holdouts: suspect overfit, camera ambiguity, bad correspondences, or incorrect geometry; do not remove inconvenient holdouts silently.
- Good silhouette but generic interior detail: use registered detail crops and mounting/negative-space comparisons; more outline optimization cannot fix this.
- Correct reference-view texture but bad side view: suspect projection painting or flattened geometry; inspect volume and materials under new views.
- Consistent geometry but wrong appearance: isolate neutral paint/rubber/metal/glass response, exposure and surface scale before remodelling.
- Repeated failed edits: keep the best snapshot, change the construction/registration method or ask for missing evidence. Do not keep adding paperwork or details to claim progress.
