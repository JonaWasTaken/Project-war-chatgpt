---
name: military-vehicle-art
description: "Build, reconstruct, refine and review Blender assets: props, products, furniture, buildings, modular environments, civilian or military vehicles, machines and original fictional/stylized designs. Use for editable high-detail sources, deliberate modelling, UV/surface finishing, PBR materials, fixed-camera inspection, scoped feedback correction and verified delivery. Includes military specialists; not engineering certification, general coding/UI or a guarantee of character/rig expertise."
---

# Blender Asset Production

Build a coherent asset, not a decorated primitive. This is the expanded **existing** skill; the legacy folder and `$military-vehicle-art` invocation remain for compatibility. Blender performs the work; the skill supplies methods and tested helpers. More instructions, polygons or passing tests do not establish better artwork.

## Choose the task before choosing the tests

Identify **original design**, **real-subject reconstruction**, **existing-asset refinement**, or **resume**. For original/fictional work, the approved brief/design governs; real references inform construction, not an obligation to copy a real object. For reconstruction, independently supported subject/configuration references govern. Never turn a failed reconstruction into an original design without actual authorization and a new truthful brief/history.

Choose **blockout**, **secondary construction**, **finished benchmark**, **materials**, or **delivery** as the current stage. Do not assess a blockout as a finished hero asset or present a primitive blockout as the finished benchmark. Preserve accepted primary forms unless a concrete defect justifies revisiting them.

## Non-negotiables

- Preserve originals, accepted identity and animation interfaces. New jobs get fresh folders; refine existing work in versioned snapshots. Do not create a repository merely for using the skill; follow project/repository requirements for actual new coding projects.
- For new models, author geometry and materials from scratch by default. Photographs, permitted section data and licensed material maps can inform that work; downloading a prebuilt model or kitbashing is not the default quality upgrade. Use sourced-model or image-derived-geometry routes only when explicitly authorized, and retain provenance.
- Discover available Blender/image-generation/image-inspection/render/export capabilities and versions. Blender MCP is optional. Do not invent tools, install/upload/buy without authorization, or execute downloaded scripts simply because they accompany an asset.
- Inspect actual rendered images. Name the owning defect, make a bounded correction, then inspect the changed result and affected neighbours. If image inspection is unavailable, do not claim visual approval.
- Separate source modelling, surface quality, articulation, export and destination readiness. No arbitrary quality multipliers, historical claims, fidelity percentages or automatic aesthetic scores from tool success.
- Keep observed, authored, inferred, conflicting and unknown information distinct. A generated concept is not real-world evidence; an uncertain hidden surface is not verified geometry.
- Preserve high-detail editable sources. Derive runtime/LOD/export variants from actual use, hardware, distance and count requirements; no universal polygon or texture-resolution cap.
- Do not hide unresolved form with grime, dramatic light, random greebles or texture noise. Plain/clean materials and deliberate boxiness can be correct.
- Calling a design fictional does not establish legal clearance. Track asset/reference provenance and redistribution permissions; avoid copied branding and do not give legal guarantees.

## Load only the relevant guidance

| Need | Guidance |
|---|---|
| Props, products, furniture, architecture, civilian machines, organic/stylized scope | [General asset methods](references/general-assets.md) |
| Original versus reconstruction, approval scope, rejection and project lessons | [Design and feedback](references/design-and-feedback.md) |
| High-detail source and native-pixel close inspection | [Close-up production](references/close-up-production.md) — apply universal surface/inspection principles; vehicle-specific parts only when relevant |
| Actually build better shapes and reference-specific details | [Construction and detail reproduction](references/construction-and-detail.md): lifting surfaces, revolved/tubular components and surface-mounted inspected masters |
| Connect a visible bolt/panel/vent observation to real scene geometry | [Feature inventory](references/feature-inventory.md); supplied evidence and geometry-anchor checks, not automatic recognition or a completeness score |
| Realism upgrade: geometry probes, UV/texture diagnostics, reference errors and controlled lighting | [Evidence-led realism](references/realism-production.md); load only the linked diagnostics relevant to the current defect |
| New or existing source-backed production job | [Job controller](references/job-controller.md) |
| Safe source preparation, section solids, measured camera fitting | [Reconstruction tools](references/reconstruction-tools.md) |
| Real-subject photo copying | [Reconstruction route](references/reference-reconstruction.md) |
| Actual UV projection and editable surface preparation | [Asset finishing](references/asset-finishing.md) |
| Supplied texture maps and explicit slots/UVs | [PBR builder](references/pbr-builder.md) |
| Saved reference/design camera without refitting | [Registered rendering](references/registered-rendering.md) |
| Independent reference masks / paired diagnostic manifest | [Registered comparison](references/registered-comparison.md), [photo diagnostics](references/photo-match-tools.md) |
| Actual audit and studio review views | [Blender review tools](references/blender-review-tools.md) |
| Before/after consistency | [Review comparison](references/review-comparison.md) |
| Construction / assembly interfaces | [Blender production](references/blender-production.md), [assembly precision](references/assembly-and-precision.md) |
| Representative finish / material isolation | [Art direction](references/art-direction-and-surface-recipes.md), [materials and baking](references/materials-and-baking.md) |
| Corrections / acceptance / supported measurements | [Visual correction](references/visual-correction-system.md), [review and delivery](references/quality-and-delivery.md), [measurement tools](references/measurement-tools.md) |
| Vehicle image-first configuration | [Concept and references](references/concept-and-reference.md) |
| Static repeated track geometry | [Track builder](references/track-builder.md) |

Military subjects may additionally load one specialist: [tracked](references/tanks-and-tracked.md), [planes](references/planes.md), [artillery](references/artillery.md), [helicopters](references/helicopters.md), [drones](references/drones.md), or [wheeled/support](references/wheeled-vehicles.md). Do not load tank rules for a chair, demand camouflage for a lamp or apply hard-surface defaults to anatomy.

## Executable start and resume

The canonical CLI keeps its legacy filename. For an original new prop/furniture/product/vehicle job, after saving a real authorized starter scene:

```sh
python3 "$SKILL/scripts/vehicle_job.py" init --job "$JOB" --source "/actual/starter.blend" --route new --intent original_design
```

A new copy of a specific real object instead uses `--intent reconstruction`. These are alternative invocations into a **fresh** job, not two commands for one directory. Initialization does not imply approval; the references transition consumes the actual concept authorization. `design-spec.json` is working notes; `references.json` uses the controller's documented `intent` key.

1. Read project instructions and supplied assets. Establish intent, current stage, style, closest view, required motion, outputs and consequential budgets. Ask only questions that change the next action; state reversible assumptions for the rest.
2. Maintain [design-spec.json](assets/design-spec.json) and a short checkpoint. [Production controls](assets/production-controls.json) are optional working notes, not invented approval. Unknown fields remain unknown.
3. Read the controller guide; use actual `vehicle_job.py --help`, `status` and `next`. Use its documented new-design authorization and intent route, not an imaginary pre-existing source. Preserve immutable history and versioned candidates. The legacy controller name does not restrict its documented asset scope.
4. Before relocating/editing a source, use `reconstruct_vehicle.py prepare-source` from the original source location. It opens the original, preserves dependency targets and creates a new working snapshot/report. A byte-identical archived `.blend` with `//` paths is not a safe relocated editable copy.
5. For new work, obtain actual concept/design authorization, save a real Blender baseline and use the documented new-job path. Do not invent a source, prior approval or history. If a tool is blocked, disclose it and the affected claims; do not pretend manually produced work was controller-accepted.
6. For existing assets, inspect actual scene data with the audit helper when supported and save/render the baseline before destructive changes. Do not infer topology, UVs or functioning pivots from pictures.

The controller validates evidence records, not truth, image authorship, human identity or artistic merit. It cannot force Codex to invoke it. No transition is complete if its mandatory checks fail.

## Production loop

### 0 — Design/reference readiness

For original work, establish a small coherent look board or explicit design brief and an actual inspectable design proposal. Prefer an informative generated concept when available; preserve real prompt/output/version. Supplied approved designs need no regeneration. If generation is unavailable, request approval of an available drawn/Blender proposal route rather than fabricating an image or installing a paid service. The original design's functional story and silhouette govern; unknown authored surfaces need design decisions, not false historical claims.

For reconstruction, identify the exact object/version/configuration and complementary whole/connection/surface references. Preserve provenance and independent checking views. Do not import another variant's identity features. Establish camera/projection/crop before numerical photo differences.

Exit: actual approved design/configuration, scope, invariants and uncertainties. Do not restart already approved work to manufacture a new concept gate.

### 1 — Complete primary forms

Choose methods from the asset's geometry: connected profiles, section lofts, lathe/revolved surfaces, curves, booleans, subdivision or sculpting as appropriate. Establish scale/axes, silhouette, mass, major negative spaces, thickness, assembly bounds and pivots. A building needs openings and module relationships; furniture needs supports and joinery; a vehicle needs complete body/running-gear envelopes.

Use the [construction toolkit](references/construction-and-detail.md) when a supported operation fits: deliberate wing/fin sections, revolved profiles, routed tubular members and later surface details. Inputs must come from actual observations, supported measurements or an explicit authored design; builders do not recover unseen geometry from photographs. Aircraft load [aircraft construction](references/planes.md) before choosing a surface strategy. Do not substitute more validation rules for actually constructing the difficult transition.

Render front/side/top/useful perspective or agreed equivalents in clay and silhouette. Fit inspection cameras once, lock them and disclose clipping rather than silently reframing revisions. Measurements require actual data, compatible frames and justified tolerances; world AABBs are not local design dimensions.

For close likeness, use the [evaluated geometry probes](references/geometry-probes.md) where applicable: datum-frame dimensions, actual landmark positions, directional clearance samples and surface-span/thickness samples. Keep measured scope, units and reference uncertainty explicit. A datum is not automatically a surface feature; sampled ray spans are not whole-object collision or engineering certification.

Exit: coherent complete primary forms and scoped blockout approval. Missing bolts, textures, UVs or individual links do not block a blockout. Major unresolved proportion/connection defects do. Conditional permission to work is not proof of dimensional accuracy or a waiver of failed mandatory checks; record exactly what remains provisional and editable.

### 2 — One representative finished region, then assemblies

Choose a demanding region with a major form transition, a connection, meaningful thickness/negative space and relevant material boundaries. Finish it in whole-asset context before distributing its methods. A shiny isolated fastener is not a quality benchmark.

Refine secondary construction and clean shading before tertiary ornament. Inspect joins, contact, overlaps, bevel scale, highlights and dependent views. Repeat only an inspected master; retain its actual mesh/UV/material ownership and verify endpoints/orientation/spacing. Keep source modifiers editable where useful. Use the finishing helper only for supported explicit UV/bevel/shading operations; it does not redesign a weak form or certify UV quality. Static track construction is not a rig, suspension or collision solver.

For detail-faithful reconstruction, map all relevant regions and missing views, inventory actual visible features and connect them to named geometry with the [feature inventory](references/feature-inventory.md). Place an inspected master using [surface details](references/surface-details.md) where suitable; then inspect count, shape, orientation, mounting and materials in matched crops. A ray hit or correct anchor is not full-footprint contact, exhaustive inventory or 95% whole-object fidelity. Keep unknowns and unmodelled items visible in the record.

Exit: deliberate forms and connections, clean neutral/grazing-light shading, representative finish established, no important regressions. Do not request new human permission for every minor operation.

### 3 — Material system and intended-distance inspection

Use the families the asset actually contains: paint, bare metal, rubber, plastics, wood, fabric, ceramic, glass or other supported surfaces. Separate lighting/exposure, shader, UV and geometry problems. Inspect swatches on planar AND curved/edge-bearing regions under locked neutral light and another plausible light setup. Avoid crushed-black construction, uniform gloss, glowing opaque glass and physically oversized noise.

Use actual maps and explicit UVs/color spaces/normal conventions with the PBR helper when applicable. Check stretch, seams, grain direction, padding, markings and useful density on the real mesh. Smart projection supplies a layout, not semantic seams, grain correctness or a bake. Bake/retopologize only when the brief requires it; preserve the high-detail source.

Use the [surface audit](references/surface-audit.md) for actual texel density, directional UV distortion, supported geometric UV overlap and sampled source-texture seams. Use [controlled material-stress renders](references/realism-production.md#controlled-material-stress-renders) to keep the saved camera fixed under explicit neutral/grazing/alternate light plans. Correct the owning UV, material or geometry cause; no automatic quality score follows from a clean diagnostic.

Inspect the closest requested view at native pixels and the intended operating distance. Frame-size previews are not object screen size. Keep whole-asset and focal-region quality consistent.

For registered reconstruction evidence, add [contour distances, regional appearance differences and source-bound multi-view aggregation](references/fidelity-comparison.md) when suitable independent references exist. Preserve failing/worst checking views and lighting/color-calibration limitations; do not average them into a fidelity percentage. Original designs remain governed by their approved brief, not an unrelated real object's photograph.

Exit: geometry and materials separately reviewed; relevant UV/bake tests and intended-view readability established; destination claims still separate.

### 4 — Motion and delivery

Test requested representative/intermediate poses and visible clearance, not only pivot names. Export to a new delivery path, re-import cleanly and inspect scale/axes/hierarchy/normals/UVs/materials/dependencies and required motion. Test the actual destination engine when required and available, including relevant LOD, aliasing and performance. A static lamp/product render need not acquire game-engine requirements.

Exit: actual requested deliverables and verified claims. Label unavailable engine/export/rig checks unverified rather than declaring universal readiness.

## Correction and feedback

Pick the largest visible defect at the intended distance. Save a version; form a specific camera/form/normal/UV/material/light/export hypothesis; change one causal system; render with locked settings and inspect affected neighbours. Keep or revert based on actual evidence. After two unproductive attempts, change diagnosis/method rather than repeating the treatment or adding decorative detail.

When the user says no, identify what failed or ask one short clarifying question. Fix the current asset first. Record project-local lessons with the feedback reference, version, observation, correction, actual before/after evidence and limits. A taste preference is not a universal physical fact. Global skill changes require separately approved scope, a backup and regression tests; no autonomous self-rewriting, lowered thresholds or invented approval.

## Approval, records and completion

Default human gates: design/concept, complete blockout and first finished asset before batch/roster expansion. Explicit bounded delegation can replace a gate; never invent it. A representative benchmark review is not automatically another mandatory human gate. Keep actual approval scope distinct from accuracy acceptance.

Use [schema-2 review.json](assets/review.json) and `check_review.py` unchanged for gate records; follow documented controller extensions for intent/authorization. The validator checks record consistency, versions/hashes, required views/motion and coverage; it does not inspect artwork. Never refresh old hashes and claim a changed source was already reviewed.

Checkpoint exact source/version, design/references, last inspected evidence, current stage, remaining defects, actual approval scope and next action. Deliver real source/texture/render/comparison/export paths, substantive changes, executed checks, uncertainties and pending acceptance. Distinguish **blockout accepted**, **modelling reviewed**, **materials reviewed**, **articulation tested** and **destination verified**. Never fabricate quality, provenance, measurements, exports or legal clearance.
