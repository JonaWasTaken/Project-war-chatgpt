# Close-up asset production

Use this profile for maximum fidelity, product/hero assets, close inspection, first-person military simulation or cinematic sources. Apply the universal geometry, material and inspection standards to the chosen asset; running-gear examples are vehicle-specific. RTS simplification is an OPTIONAL separate delivery profile, not the source-quality ceiling. These are standards within existing stages, not extra paperwork or invented quality percentages.

## Choose the subject and evidence precisely

For real-subject reconstruction, lock the exact version/configuration and permitted visual modifications before copying details. For original work, lock the actually approved design language and authored invariants instead; a photo match to a real object is not mandatory. Separate sources for overall shape, connections, surface materials and markings. Photographs of different variants are not automatically complementary views of one configuration. Do not invent historical fittings or hidden features as observed facts; explicitly authored fictional features need design purpose. A generated view is a design hypothesis, not new real-world evidence.

Use full-resolution original references plus regions showing critical details. Reserve complementary photographs/viewpoints for verification rather than optimizing every judgment against one fitting view. Camera pose and focal length can absorb mesh errors; validate independent landmarks and the overall volume. Unknown underside/interior surfaces remain unknown until referenced or explicitly authorized as inference. Never describe a single-view cutout or projected texture as complete reconstruction.

## Establish a high-fidelity source before a delivery mesh

Keep a versioned, editable source assembly with coherent units, axes, identities, pivots and dependency paths. Do not decimate the source to an arbitrary universal triangle count. Use enough topology for the closest agreed view, smooth curved profiles and reliable shading; retain modifiers where useful. Keep the runtime/export representation separate so changing an LOD does not destroy the source.

Primary form: capture characteristic plane breaks, shoulders, slopes, transitions, local thickness and major negative spaces. Secondary construction: model the visible mounting, recesses, overlapping panels and interfaces that explain how forms join. Tertiary detail: add supported visible fasteners, seals, seams, tread/contact surfaces, markings and surface relief at coherent physical scale. Do not scatter generic greebles or use weathering to conceal a missing connection.

Use geometry for silhouette-changing forms, substantial recesses and exposed edge thickness. Use appropriate normal/texture representation for genuinely shallow surface detail; inspect it under changing light to detect a flat painted-on result. Neither all-quads nor universal watertightness is a quality criterion: topology must suit shading, subdivision, articulation and the actual export.

## Finish one difficult, representative assembly first

Choose a demanding region that combines curved and planar form, a recess/connection, exposed edges, repeated parts and different materials. Examples include a product housing/control junction, furniture frame/handle connection, architectural opening, or vehicle wheel/track or turret/mantlet region. Finish and inspect it in whole-asset context before distributing its recipe. A beautifully rendered isolated bolt does not establish the rest of the asset.

For running gear, author and approve the actual master link/wheel first. Preserve its UVs, material boundaries and local axis/origin contract. The track builder repeats that master on a supported closed path; it does not create missing track details, suspension, physical hinge motion or collision correctness. Check outward orientation, closure, corner spacing, guide-feature clearance and surrounding assemblies from both sides and below.

For a textured repeated master, run the PBR builder on its explicit existing slots/UVs into a new prepared snapshot, then pass that actual output to the track builder. Both DATA-linked materials and OBJECT-linked overrides are retained on the new links without changing shared mesh slots. Use the resulting belt snapshot—not the pre-material source—for registered rendering, then pass its actual manifest to the comparison connector. Reopen the saved result and inspect the material boundaries: isolated helpers passing tests does not prove their outputs cooperate.

## Surface quality must survive neutral light

Separate opaque paint, exposed metal, rubber, optics, fabric and any other genuinely visible material families. Painted armour is not uniformly metallic; roughness and edge treatment must match the source. Avoid nearly black surfaces that hide the running gear, glowing opaque glass and globally identical roughness. Weathering must follow reference, exposure/contact and the requested condition; clean paint remains valid.

For texture-backed materials, verify the actual image files and color/data interpretation. Base color uses its declared color space; roughness/metallic/normal are data. Explicitly identify tangent-normal convention and UV map. The PBR builder wires supported supplied maps; it does NOT author detailed textures, unwrap the mesh, validate all UV islands, bake an asset, or guarantee destination shader parity.

Check UV seams, stretching, padding, consistent useful density, repeated/mirrored areas and readable markings on the actual mesh. Use real high-to-low bakes with controlled cage/projection where required. Inspect a close-up normal checker/grazing-light pass after re-import; high texture resolution alone cannot correct bad UVs, bad baking, unsupported node logic or wrong tangents.

## Required inspection set: whole asset AND close-ups

Agree exact view labels in existing `required_views`. For maximum-fidelity work, normally inspect:

- Whole-asset front, side, rear, top and useful three-quarter angles, or brief-appropriate equivalents, using governing references/designs where available.
- Neutral clay and grazing light from at least two directions to expose pinching, bevel collapse, faceting, waviness, duplicate faces and z-fighting.
- Saved-camera close-ups of the representative benchmark and every conspicuous identity feature, at the closest required use distance. Inspect native image pixels, not only downsampled thumbnails.
- Unoccluded assembly/underside views where references or the required user viewpoint make them important. Hidden meshes must not contaminate the accepted configuration.
- Material isolation and final textured views under neutral and a different plausible lighting setup. A scene that only works under its beauty light is not robustly reviewed.
- Required door/drawer, joint, product mechanism, turret/gun, wheel/suspension, hatch, rotor or other authorized artwork articulation, with visual clearances checked through intermediate poses. Static pivots are not a tested rig.

The registered renderer preserves a prepared scene camera rather than inventing a photographic match. Use it for reference-paired views; use the studio renderer for separate neutral inspection. The comparison connector reads actual render/source hashes, builds the model side automatically and retains manual reference/feature declarations. It never generates the reference mask from the model. A matching silhouette is not proof of internal detail or material fidelity.

The current mask-distance tool has an operational full-frame pixel cap. Inspect original high-resolution renders separately; if diagnostic preparation needs a crop or lower-resolution pair, prepare BOTH sides consistently, preserve originals, and disclose the scope. Do not silently reduce the only visual evidence to pass a tool.

## Destination verification, without destroying source quality

For a real-time military sim, derive runtime limits from actual target hardware, closest view, unit count, animation and shader costs. High fidelity does not excuse unlimited draw calls, unique materials or tiny LODs with unstable shading. Establish separate near/mid/far/collision representations only as required, preserve silhouette through transitions, and check mip/normal shimmer and material consistency in motion. A static high-detail belt is not an optimized animated game track.

Export the requested format into a NEW delivery path, re-import cleanly, and inspect actual normals/tangents, UVs/maps, units/axes, hierarchy and required motion. Then test the actual destination engine/simulator if available. Export success or a Blender re-import cannot establish engine performance, suspension behavior, all required poses or shader equivalence. If those tests are unavailable, label them unverified instead of calling the asset simulation-ready.

## AI effort and completion discipline

Spend work on the largest remaining evidenced defect at the closest required view. Use a bounded one-cause edit with locked before/after camera/light and recheck adjacent/held-out views. Do not keep adding micro-detail while the main silhouette is wrong. After two failed targeted fixes, change the diagnosis or construction method; retain the best version.

For genuinely poor output, inspect a real run for skill loading, executed tools, actual image inspection, reference quality and missing capabilities before writing another longer instruction file. A functioning tool suite is not a successful artistic result. Deliver actual source/render/export/texture paths with model, materials, articulation and engine checks distinguished. No tool may self-award human approval, historical correctness, a percentage of original detail or an 'AAA' label.
