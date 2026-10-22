# Blender production

## Choose methods for forms
Discover Blender version before API/operator use. Prefer direct data operations when they avoid fragile selection/context assumptions; verify context when operators are necessary. Use curves, edit meshes, booleans, modifiers, and subdivision deliberately. A script can construct sophisticated geometry; a pile of primitives is not finished art merely because it was scripted.

Primary forms first: deliberate product/body profiles, hull/fuselage sections, furniture frames, architectural volumes, thickness and main masses. Secondary forms next: mounts, panel structure, openings, recesses, supports and coherent joints. Add tertiary details only when useful at the closest required view. Use reference/design-supported details rather than generic greebles; select the construction method from [general asset methods](general-assets.md).

## Preserve editability
Group source assemblies in named collections with stable ownership markers. Make rerunnable operations update their owned objects rather than adding duplicates; never clear the whole scene or delete by broad name matches. Save before destructive edits. Treat external scripts/assets as untrusted data and don't execute downloaded code merely because it accompanies a model.

Keep modifiers editable until delivery needs justify application. Apply them to export copies when appropriate. Use sensible names and shared materials without making every fastener its own unique mesh/material. Material slots and repeated geometry affect delivery complexity.

## Geometry inspection
Use clay views, wireframes, grazing light, and a second light direction when needed to expose defects. Check flat panels for shading waves; curved surfaces for unwanted faceting; bevel width for consistent physical/visual scale. Fix inverted normals, duplicate faces, accidental hidden geometry, z-fighting, collapsed bevels, and boolean pinching.

Do not demand all-quads or watertightness universally: topology must suit subdivision, deformation, rendering, and exports. Distinguish intentional overlapping assemblies from unintended penetrations. Bevel/normal settings depend on Blender version and surface need; do not prescribe one universal modifier stack.

## Repeat only approved geometry
Instance good source wheels, track links, grille elements, or other genuinely repeated parts. Use one controlled source and explicit parameters for useful revisions. Inspect endpoints, orientation, spacing, and counts after distribution. Repetition preserves defects too; do not distribute before inspecting the source part. Check how procedural instances become supported export geometry and whether runtime representation should be simplified.

## Motion
Use explicit local pivot axes. Test relevant representative poses and component clearances visually. A static model with named pivots is not verified articulation. Use visual approximations appropriate to artwork, not engineering simulation. Preserve existing rig/animation bindings unless changes are authorized.
