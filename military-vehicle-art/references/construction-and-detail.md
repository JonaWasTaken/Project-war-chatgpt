# Construction and detail reproduction

## Solve the production bottleneck

Better inspection cannot create a surface that the modeller never constructed. Before adding another metric or a decorative pass, identify the failed construction operation: wrong profile, abrupt transition, paper-thin shell, poorly routed tube, wing treated as a flat triangle, or repeated hardware placed without attachment. Choose a builder/direct-modelling technique for that specific form, then inspect the whole asset.

| Construction problem | Existing/new reusable method | What remains authored |
|---|---|---|
| Convex station-controlled body/fuselage | Existing `reconstruct_vehicle.py loft` | Real sections, correspondence and uncertainty; no image-to-volume recovery |
| Wing, fin or tail with deliberate span/chord/section controls | [Lifting surfaces](lifting-surfaces.md) | Supported station/profile measurements, shape transitions and aircraft integration |
| Turned product, hollow shade or rotational rim | [Component builders](component-builders.md) | Radial profile, openings and meaningful material boundaries |
| Cable, tube, curved support or handle | [Component builders](component-builders.md) | Sampled path, section, endpoints and actual contact checks |
| Reference-specific bolts/vents/pads on an actual mesh | [Surface details](surface-details.md) | Inspected master, evidence-based placements, attachment origin and tangent |
| Explicit UV projection, editable bevel and shading | Existing [finishing](asset-finishing.md) | Semantic seams, topology decisions and useful edge scales |
| Map-backed materials | Existing [PBR builder](pbr-builder.md) | Real maps, material design, UV orientation and physical surface scale |

Use each helper's exact documented schema/CLI and a saved source. New construction is not permission to overwrite an existing object, mesh or collection. When moving/deriving scenes, prepare them from their original location to preserve actual dependencies. Builders produce an authored mesh from supplied controls; none automatically extracts a faithful part from a photograph.

## Capture visible details without inventing completeness

1. Split the subject into a finite, explicit region map. Include underside/rear/joins when they matter to the brief; list missing views instead of silently omitting them.
2. Inspect whole views and connected close crops. Inventory identity features, construction joins and material boundaries before tiny fasteners. Every reference belongs to the exact variant/configuration or is marked comparative/inferred.
3. Give a specific detail a stable feature ID. Record actual evidence crop, confidence/ambiguity, intended representation, target object and unresolved work. The [feature inventory](feature-inventory.md) connects that record to real mesh anchors instead of trusting object names or a manually checked box.
4. Derive placement from supported 3D relationships, registered views or measured design coordinates. A pixel crop alone does not determine 3D position, thickness or orientation. Do not guess a numeric tolerance to satisfy a score.
5. Inspect a real master before repetition. Its local attachment origin must mean contact, its normal/tangent must have a defined convention, and material-slot ownership/UV scale must survive copies. Do not populate the entire asset with a bad master.
6. Use supported surface-hit placement where appropriate. Recheck curved panels, edges, ray misses and obstructions. One surface hit proves neither full-footprint contact nor collision-free hardware.
7. Review actual matched crops for shape, count, mounting, orientation and finish; check alternate views and appropriate geometry probes. The inventory's `geometry_present`/position checks do not perform this review.
8. Retain unresolved, inferred and unknown features in delivery. Never make a list exhaustive by declaration, delete inconvenient missing regions or turn feature-count coverage into whole-object fidelity.

## Build one hard region, not one easy decoration

Choose a representative region containing a large shape transition, a difficult join and meaningful material separation. Examples: canopy/intake/wing root; product rim/handle/body; cabinet door/hardware/frame; wheel arch/body/tyre; window/opening/wall junction. Prove that construction works under clay, grazing and neutral lighting before propagation. A single beautifully shaded bolt is not a quality benchmark for an aircraft.

When geometry needs subdivision, inspect silhouette shrinkage, poles, support loops and highlight flow. When it needs a sharp edge, model the intended plane transition rather than hiding it with a normal map. A denser surface can remain wrong. Do not apply blanket bevels, automatic smoothing, noise or subdivision across anatomy, glazing, thin sheet edges and hard housings alike.

## Materials and realism are separate work

The new builders do not generate photorealistic textures. Use the existing material workflow with observed material families and explicit image provenance. Separate albedo from baked illumination, reference-supported coating boundaries from random panel variation, and geometric scale from arbitrary texture repeat. Check real UV density, local anisotropy, seams and repeat patterns on the evaluated result. Provide distinct edge/end grain, coating/exposed substrate, rubber/glass/metal behaviour where the actual object requires it.

Author new geometry and material systems from scratch by default; permitted photographs, section data and licensed material maps can support that construction. Surface scans, photogrammetry or licensed prebuilt models are separate opt-in routes, not a silent shortcut or the default upgrade. Discover actual tools and permissions before proposing them; do not pretend the skill bundles a scanner, image-to-3D model or rights to someone else's assets. Reflective, featureless, transparent and occluded subjects remain difficult.

## Category breadth without false mastery

- Aircraft: use [aircraft construction](planes.md), not generic extruded tubes and flat wings.
- Military vehicles: retain the category specialist and variant-specific reference discipline; static repeated hardware is not working suspension/articulation.
- Furniture/products: use member/part boundaries, grain direction, actual thickness and joins from [general assets](general-assets.md).
- Architecture: openings/modules/corner joins and intended player/view scale govern, not copied tank methods.
- Organic/characters: references and sculpting/anatomy/retopology/rigging capability are separate. Do not promise character, hair, cloth, skin or deformation mastery from these hard-surface builders. Use an actual specialist pipeline or label the limitation.

No universal script can make a 1:1 copy of every object from incomplete images. A defensible reconstruction states which views, features, measurements and materials were checked, the evidence uncertainty and the remaining gaps. A “5× quality” goal requires a controlled old/new asset comparison and agreed judgments; tests, extra scripts and more prose do not establish it.
