# Materials, UVs, and baking

## Diagnose before repainting
If an existing mesh has correct proportions but unreadable surfaces, isolate lighting/exposure and material problems before replacing geometry. Lock a neutral studio rig and compare controlled changes. Avoid crushing running gear to black or using glossy paint to fake detail.

Separate paint, exposed metal, rubber, plastics, wood, ceramic, glass, composites and fabric where relevant. Base choices on reference/design and target shader; coated surfaces are not uniformly exposed metal. Match roughness and detail scale across assemblies. Orient wood grain deliberately, give fabric meaningful scale and avoid making every surface glossy. Glass needs plausible thickness/shading without becoming an opaque neon rectangle.

## Surface authorship
Prepare UVs where texture delivery requires them. Check stretching, orientation, seams, island padding, repeated/mirrored areas, and consistent useful texel density. Avoid mirrored readable markings. Place dirt/wear by exposure/contact/reference, not an all-over noise layer. Avoid baking dramatic studio shadows into base colour accidentally.

For game-ready work, prefer the least complex representation that preserves the silhouette and intended-distance appearance. For hero/cinematic work, preserve useful surface/geometry detail rather than optimizing prematurely. Propose budgets from intended unit count, hardware, camera, and render requirements; no universal triangle or texture-resolution demand.

For close-up military simulation, follow [the close-up profile](close-up-production.md), preserve the editable high-detail source, and inspect native-pixel material boundaries, seams, edge treatment and shallow relief under changing light. RTS simplification is a separate delivery decision, not a universal source requirement.

Use [asset finishing](asset-finishing.md) for documented explicit new UV projection and editable bevel/shading operations on eligible named meshes. It does not create semantic seams, material grain direction, authored textures, a bake or artistic approval. Use [the PBR builder](pbr-builder.md) for supported actual base-color/roughness/metallic/normal maps and explicit object material-slot/UV binding. It verifies and wires provided files with explicit color/data handling; it does not author maps, unwrap, bake, measure all UV defects or promise export parity. Missing maps are missing, not a reason to invent texture-generation success.

## High-to-low when warranted
Maintain separate high-detail source and delivery meshes with matching assembly identities. Retopologize/simplify for use, unwrap, bake with controlled projection/cage, then inspect seams and isolated parts. Check tangent-space convention, channel packing, colour-space treatment, and how the destination interprets maps. Detail baked into normals does not change silhouette or provide actual recess depth.

Check source and re-imported shading; successful bake/export operations do not prove fidelity. Do not assume Blender procedural nodes travel intact to GLB/FBX. Deliver baked textures or document unsupported features. Verify actual file dependencies; do not claim maps exist unless they were produced and inspected.
