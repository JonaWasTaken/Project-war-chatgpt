# Evidence-led realism production

## Contents
- [Purpose and limits](#purpose-and-limits)
- [Geometry before surface decoration](#geometry-before-surface-decoration)
- [Surface construction and evidence](#surface-construction-and-evidence)
- [Reference fidelity without false certainty](#reference-fidelity-without-false-certainty)
- [Controlled material stress renders](#controlled-material-stress-renders)
- [Integration, correction and handoff](#integration-correction-and-handoff)

## Purpose and limits

Use this route for closer real-object likeness and convincing surfaces. It supplements the existing reconstruction, finishing, PBR, registered-render and review tools; it does not rename those tools as new capabilities. The added executable diagnostics measure specific failure modes. None is an automatic realism judge, historical authenticator, engineering verifier or artistic approval.

Lock the actual subject/version or approved original design first. Record observed dimensions and their units, reference provenance, camera/crop, material evidence, assumptions and unknowns. Do not manufacture a complete set of exact dimensions from one uncalibrated photograph. For original designs, label target values **authored design requirements**, not recovered real-object measurements.

Define any acceptance criteria before examining the candidate. Choose their basis from evidence uncertainty, approved design requirements and the intended view; do not copy universal tolerances from an example. Diagnostic completion, a declared numerical criterion being met, and artistic approval are separate outcomes. Unmeasured/unsupported regions stay unknown.

## Geometry before surface decoration

Use [geometry probes](geometry-probes.md) on the actual saved candidate, not hand-entered model coordinates:

1. **Datum-frame dimensions:** measure evaluated geometry in a declared frame. World-axis bounds of a rotated part are not its local design dimensions. Compare only compatible dimensions, units, configurations and explicit evidence.
2. **Datum/landmark alignment:** inspect real named object/datum transforms against declared positions/relationships. Datums must actually correspond to the claimed feature; a correctly positioned Empty does not prove an adjacent surface is correct.
3. **Directional clearance samples:** cast explicit bounded rays against the supported evaluated surface scope. Record hits, misses, directions and sample locations. A finite set of rays does not establish complete collision-free motion or minimum clearance.
4. **Surface/chord thickness samples:** distinguish an entry/exit span along a ray from normal thickness, minimum wall thickness and mechanical strength. Hidden intersecting shells and unsupported topology require investigation, not a green approval label.

Use source meshes and the documented supported evaluation scope. Do not silently replace omitted instance/Geometry Nodes/render-only contributions with base-mesh guesses. Recheck dependent measurements after changing a governing dimension. Keep scene scale and measurement-frame units explicit.

## Surface construction and evidence

Use [surface audits](surface-audit.md) with the actual explicit UV layer, supported evaluated geometry, source image and texture fingerprints:

5. **Texel density:** compare the number of texture samples per declared physical distance at the real target surfaces. A large image file does not ensure close-up resolution; texture tiling and UV scale govern effective density.
6. **UV stretch/anisotropy:** diagnose locally different directional scale, not just total island area. Correct distortion and wood/fabric/grain direction at the owning seam/layout; do not increase resolution to hide distortion.
7. **UV overlap:** detect supported triangle intersection area, treating shared borders separately from positive-area overlap. Declare intentional mirrored/stacked layouts and unsupported tiling/UDIM regions. No-UV-overlap does not certify enough bake padding or good seam placement.
8. **Texture seam discontinuity:** sample the actual declared source image across supported UV-split mesh edges. Preserve sample scope, wrap/color policy and intentional material boundaries. This does not prove shader-render continuity, texture authorship, calibrated reflectance or tangent-normal correctness.

Choose materials from evidence. A rusty painted surface needs layers with a physical story, not uniformly distributed dirt. Roughness, base color and normal scale must agree at the closest intended view. Normal maps cannot repair silhouette or actual missing thickness. Never treat raw normal-map RGB differences across tangent frames as seam-lighting error.

Retain the external map's actual license, source URL, acquisition method, hashes, dimensions, normal convention and color/data interpretation. A downloaded studio/preview render is not an albedo map. If using publicly exposed preview **maps**, label them as such; do not claim they are the inaccessible full-resolution originals. Do not invent missing scans or material provenance.

Use the existing [PBR builder](pbr-builder.md) for explicit assignments and map decoding/color-space/convention checks. Supply physically meaningful UV scale and grain direction rather than leaving automatic projection as the finished layout. Preserve editable high-detail sources and derive lower-resolution/runtime variants separately.

## Reference fidelity without false certainty

Use [fidelity comparisons](fidelity-comparison.md) alongside the existing registered camera renderer and silhouette IoU diagnostics:

9. **Contour distances:** measure the spatial distance between aligned reference/model boundaries. Read mean, tail and maximum errors together with overlays; a high aggregate overlap can conceal an important protrusion or local cutout error.
10. **Regional appearance differences:** compare declared corresponding regions under explicitly comparable light, exposure, color processing and framing. Report the named pixel/color metric without interpreting it as physical material identity or whole-model realism. Do not normalize away a bad exposure to make it score better.
11. **Multi-view evidence aggregation:** require the declared inspection/held-out views, bind their source and image versions, and retain the worst-view failures. A good side view cannot erase a failing front view. Matching hashes detect changed bytes, not authentic reference content or human approval.

Calibrate the camera and crop before geometry corrections. Preserve an independent checking view when evidence permits; fitting and evaluating the same sparse outline is not independent validation. A self-render used as its own reference is only an openly labelled software test. Real-subject appearance validation requires an actual independent reference and evidence of comparability; original design evaluation instead uses the approved brief.

## Controlled material stress renders

12. **Fixed-camera, explicit-light-plan material stress testing** is implemented by `scripts/render_material_stress.py`. It calls the established renderer without altering/saving the source. It replaces original direct lights/world in disposable diagnostic scenes with each explicit plan, while retaining the same saved camera, crop, geometry pose, Standard/sRGB view, exposure 0 and gamma 1. Source-light hiding is not a material correction.

Start from [material-stress.json](../assets/material-stress.json). It is deliberately incomplete and must be filled from the actual scene. Run with an installed Blender Python (`bpy`) and Pillow, or Blender:

```sh
blender --background --disable-autoexec --python "$SKILL/scripts/render_material_stress.py" -- --source "/actual/candidate.blend" --spec "/actual/filled-stress.json" --output "/actual/NEW-material-stress"
```

The top level has exactly `schema_version: 1`, `render`, and `profiles`. `render` is a complete [registered-rendering](registered-rendering.md) spec. `profiles` contains 2–8 unique explicit light plans. Duplicate numerical plans are refused after float32 conversion, ignoring labels and light-list ordering; this catches equivalent integer/float spellings and values that collapse to the same Blender storage precision. Distinct declared plans do not guarantee a visible appearance difference on a particular object. Every profile has exactly:

- `label`: a lowercase ASCII label `[a-z][a-z0-9_-]{0,39}`;
- `world_color`: three linear RGB factors in [0,1]; `world_strength`: finite nonnegative Background strength;
- `lights`: 1–8 area lights; each has `position` and `target` three-vectors, positive `power_w`, positive `size`, and linear RGB `color` in [0,1].

Positions and area-light diameters use the renderer's world Blender units, treated as metres by this diagnostic scene. Blender `Light.energy` receives `power_w`, not a claim of calibrated measured irradiance. For other authoring scales, deliberately convert coordinates/rig size/energy for the intended comparison; never silently infer real physical size. Positions are bounded to absolute 1e8 world units, positive controls to 1e8, world strength to 1e6, and light aim must survive float32 representation. These are numerical/execution bounds, not asset-quality limits.

Choose neutral broad light, a restrained grazing setup and an alternate direction suited to the asset; the names do not create those conditions automatically. Keep all light positions, sizes, energies, colors and world settings explicit and reuse that plan for before/after corrections. There is no auto-refit. Insufficient samples, clipped framing and unsuitable light direction remain visible review problems, not silently corrected results.

Output is a new directory containing one registered detail/geometry render and manifest per profile plus `material-stress.json`. It binds source/spec hashes, `tool_sha256` entries for the driver, `render_registered.py` and `reconstruct_vehicle.py`, source-loaded file/packed image hashes and the exact requested light plans. Tool files are rehashed before publication; these fingerprints are consistency records, not interpreter/add-on/code-authenticity attestations. Every profile retains the same camera metadata; geometry masks make framing consistency inspectable. There is no `passed_realism` result.

The runner refuses duplicate/unknown fields, unsupported animated/tiled image sources, missing source file images, source/spec aliases, existing or dangling-symlink outputs, and inputs changed during the run. It publishes only after every profile finishes. Scope inherits the registered renderer's viewport-evaluated mesh/instance support; instanced lights, full render-dependency equivalence, media/UDIM and complete external-cache/library fingerprinting are not certified. Python-side handlers/add-ons are not a security sandbox; open only trusted Blender files with autoexecution disabled.

Inspect the real renders at native pixels. Look for oversized grain, repeated marks, seams, normal inversion, unconvincing contact, uniformly glossy surfaces, faceting and bevel highlights that collapse under grazing light. Material parameters that only look acceptable in one flattering setup need diagnosis, not more dramatic lighting.

## Integration, correction and handoff

At primary-form review, attach relevant geometry probes and registered checking views. At representative-finish review, attach relevant surface diagnostics and material-stress images. At reconstruction review, add independent registered reference comparisons and required-view aggregation. Do not run irrelevant checks merely to enlarge a report.

Keep each helper's original structured report and manifest. Bind it to the current candidate, not an earlier input to a source-changing operation. Re-run affected diagnostics after a material/UV/geometry/camera change. New reports do not retroactively refresh an old visual review or approve changed work.

Use the existing controller's actual gates unchanged. These new diagnostic reports supplement evidence; they do not bypass `check_review.py`, manufacture human approval or make unsupported controller claims. If the controller cannot consume a particular report format directly, retain it as a linked diagnostic in the human/agent review rather than rewriting its fields to look accepted.

Deliver the candidate, evidence paths, concrete corrections, measured scope, remaining uncertainty and pending approvals. Report exactly what was exercised: helper tests, synthetic fixtures, actual external maps, rendered inspection, independent reference comparison, full Codex execution and destination validation are different evidence levels.
