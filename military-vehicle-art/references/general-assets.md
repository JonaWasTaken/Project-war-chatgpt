# General Blender asset methods

## Contents
- [Choose form and finish methods](#choose-form-and-finish-methods)
- [Props and product objects](#props-and-product-objects)
- [Furniture and materials](#furniture-and-materials)
- [Architecture and modular environments](#architecture-and-modular-environments)
- [Civilian vehicles and machines](#civilian-vehicles-and-machines)
- [Organic and stylized work](#organic-and-stylized-work)
- [Use the tools where they fit](#use-the-tools-where-they-fit)
- [Proof and limits](#proof-and-limits)

## Choose form and finish methods

Choose a construction method that controls the important shape, not whichever primitive is easiest to script. Establish the whole object before detailing parts. Keep a small, coherent visual target: silhouette, major curvature/plane changes, connection logic, edge language, material families and intended view. Reference images can guide construction without authorizing copied branding or redistribution.

| Form | Useful approach | Inspect before detail |
|---|---|---|
| Axially symmetric shade, knob, bottle, turned leg | Revolve a deliberate radial profile; enough segments for the closest silhouette | Axis alignment, profile transitions, actual rim/wall/base thickness, smooth highlights; do not seal an intended opening |
| Hose, cable, handle, pipe | Controlled curve with deliberate section and endpoints | Bend radius visually plausible, endpoints attached, no unintended penetrations or zero-thickness ends; an artistic route is not a physical cable simulation |
| Planar shell or panel with openings | Connected outlines, thickness, supported booleans or explicit mesh | Flat highlights, recess depth, rim/chamfer shape, topology at corners, no coincident cap faces |
| Smooth manufactured enclosure | Profiles/cross-sections with subdivision or controlled bevels | Highlight flow, pole pinching, silhouette stability and mounting seams; subdivision does not rescue arbitrary topology |
| Frame/carcass/module | Separate structural members with coherent dimensions and joints | Contact, load-bearing visual story, local thickness, mating planes and negative spaces; not engineering certification |
| Genuinely repeated parts | Shared inspected master/instances with explicit placement | First/last and corner conditions, direction, scale, material ownership, clipping and delivery support |
| Organic mass | Sculpt/subdivision with appropriate anatomy/design reference | Whole silhouette, landmark/mass relationships, curvature and intended deformation; not a hard-surface bevel recipe |

A UV layout or bevel is a surface operation, not a new primary-form design. Do not claim better likeness merely because a modifier increases evaluated triangles.

For supported actual construction, use the [component builders](component-builders.md) for deliberate revolved profiles and routed tubes, and [surface details](surface-details.md) for an inspected master attached to explicitly supplied surface-hit placements. The [construction selector](construction-and-detail.md) explains where these fit and what remains authored. Do not assume a geometry helper solves joins, material design or reference recovery.

## Props and product objects

1. Establish the primary silhouette and intended handheld/tabletop/world scale from the brief or supported measurements. Fictional dimensions are authored choices; measured replicas need real measurements.
2. Resolve purposeful part boundaries: lid/body, lens/housing, shade/rim, button/bezel, cable/entry. Give visible seams and openings meaningful depth and thickness.
3. Finish one junction where a broad surface, a curved region and different materials meet. Check close-up and whole-object views under neutral and grazing light.
4. Use curves/lathe sections for cylindrical and flowing shapes rather than stacking unrelated boxes. Keep manufacturing cues coherent without claiming a manufacturable design.
5. Choose detail density by actual viewing distance. An unbranded original product is valid; fictional text/logos need deliberate design, not random unreadable labels.

For a lamp, inspect the hollow shade's inner surface and rim, bulb/support visibility, joint collars, stable-looking base and cable entry. A glowing shader alone is not a tested light source, electrical design or functioning articulation. Keep glow/bloom out of geometry diagnosis.

## Furniture and materials

Use a consistent authored/observed dimensional language for supports, rails, panels, cushions and hardware. Check the underside and joints the intended camera exposes. Do not leave a floating seat, paper-thin shelf, intersecting drawer or unsupported rear panel while polishing wood grain.

For wood, distinguish edge/end grain and longitudinal grain. Deliberately orient UVs or coordinates per member; a smart UV layout does not choose grain direction. Preserve real seams between separately built boards. For upholstered forms, establish cushion volume, compression/contact, useful seam placement and material scale before scattered wrinkles; fabric is not glossy painted metal. Do not promise cloth simulation from a static sculpt.

Inspect chair/table/cabinet leg-to-frame contact, consistent material boundaries, edge treatments appropriate to each material and actual openings. Drawer/door motion is required only by the brief; if required, inspect intermediate positions and hinges/clearance rather than merely naming pivots. Visual plausibility is not a furniture safety certification.

## Architecture and modular environments

Lock a module/scale contract, origin/pivots, grid, wall/floor thicknesses and intended camera route. Form the building volume, openings and circulation/readability before facade ornament. A window is an opening/recess with frame and glass treatment where visible, not a flat dark rectangle posing as interior depth.

Test module joins, corner variants, repeated facade endpoints, floor alignment, UV/trim continuity, light leakage and visible back faces. Keep instancing where useful, but verify actual destination representation. Avoid unique high-cost materials on every repeated module without a brief-derived reason.

An exterior-only asset may use deliberately limited interiors; disclose it and make exposed openings coherent. Do not claim architectural/code compliance, structural safety or construction documentation. For game environments, inspect player-scale views, collision/navigation if requested, LOD transitions and lighting in the destination separately.

## Civilian vehicles and machines

Use the military skill's coherent body/assembly/repetition discipline without importing armour, weapon mounts or camouflage requirements. Establish wheel/contact envelope, cabin/body volumes, doors/covers, mechanical interfaces and reference-specific identity where reconstructing a real machine. Product family, model year and configuration matter; do not mix incompatible versions.

For fictional machines, define function, scale, access/maintenance story and visual hierarchy, then author a consistent design. References explain how parts might join, not proof that the fictional mechanism works. Hoses, guard rails, handles and vents need attachment and purpose. Test required articulation as artwork, not mechanical simulation.

## Organic and stylized work

The general process supports choosing a sculpt/subdivision route, not automatic character mastery. Require relevant proportion/anatomy/creature/design references and a suitable brush/sculpt or mesh workflow actually available. Preserve silhouette and major masses before pores, scales or repeated panels. Stylized proportions are authored invariants, not errors to normalize toward realism.

Deforming characters need separate topology, UV, rig, skinning and pose tests. Static sculpt success does not prove animation, expression or anatomy. Hair/fur, cloth, skin shading and simulations are separate capability/dependency checks. Do not apply the hard-surface finishing helper's smart projection/bevel defaults to a character as a substitute for retopology, semantic seams or deformation-ready work. If specialist capability is unavailable, narrow and label the deliverable rather than pretending it is supported end to end.

## Use the tools where they fit

- `reconstruct_vehicle.py prepare-source` preserves actual source-relative dependency targets when creating a new working copy. Its legacy filename is not a subject limitation.
- `finish_asset.py` performs only its documented explicit UV/surface operations on eligible named meshes. Inspect actual UV/shading results; semantic seams, authored textures and topology repair remain separate work.
- `build_components.py` constructs supported profile-revolved and routed tubular shapes from explicit controls; it is not an automatic product/furniture designer or cable simulator.
- `build_lifting_surface.py` constructs supported station/profile wing-like solids; use only where that form fits, not as a universal enclosure or organic-body builder.
- `place_surface_details.py` places copies of an inspected master using explicit target rays/tangents. Check full-footprint seating, surrounding parts and the actual variant evidence separately.
- `audit_feature_inventory.py` connects reference crops and explicit feature IDs to actual evaluated mesh anchors. It reports absent/unresolved/position-drift states without turning a manually supplied list into universal fidelity.
- `build_pbr.py` consumes actual PNG/JPEG maps or explicit constants and named UVs/slots. It does not create artwork, bake or certify material plausibility. New object-linked assignments need correct repetition/export handling.
- `render_registered.py` renders the saved named camera/collection without fitting. For an original design, that can be a locked design-review camera; the filename does not prove photographic calibration. Honor all documented geometry/visibility limits.
- `compare_registered.py` is for properly registered independent reference/model pairs. Never turn the model's own mask into independent design/reconstruction evidence. Synthetic self-reference is a tool test only.
- Studio audit/review helpers are useful for eligible arbitrary geometry, but their vehicle-axis/view naming conventions must match the asset's declared frame. Front labels are conventions, not recognized semantics.
- The controller can record general source-backed jobs using documented intent/authorization. Its legacy name and reserved storage remain for compatibility; never modify old state/history to rename a project.

## Proof and limits

For each demonstrated category, save the actual source, render with reproducible settings, open the real images, state concrete defects and correct a bounded problem. Test save/reopen, explicit UV/material bindings and the real next helper's input. Test on more than one object type; a single cube does not establish general asset production.

Keep helper mechanics, visual review, destination export and user acceptance separate. Do not claim human-level/AAA output, a fivefold gain, legal clearance or production readiness from a broader description or passing test suite.
