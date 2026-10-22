# Assembly and precision

## Establish a shared coordinate contract
Choose units, scale, forward/up axes, origin, and ground reference. Record dimensions with evidence and confidence. Use supported exact dimensions, normalized ratios when scale is unknown, or bounded estimates where occlusion/perspective prevents precision. Do not derive exact world dimensions from uncalibrated pixels.

For each assembly record ID, parent, bounding dimensions, local transform, source reference, attachment position/orientation, pivot axis, required motion, material family, and dependencies. Null values are unresolved, not zero. Keep useful parameters for shared dimensions and source geometry; don't build a sprawling parameter system without a revision need.

## Proportion and landmark checks
Select landmarks relevant to identity: body extremities, wheel centres, turret/cockpit centre, wing roots/tips, rotor hubs. Compare length/width/height relationships and component spacing in aligned views. Camera perspective and image distortion limit precision. Propose brief-specific tolerances and get agreement when consequential; do not invent universal percentages.

Use orthographic front/side/top checks for the model; a separately estimated perspective camera for matching a perspective reference. Freeze camera, focal settings, exposure, and light rig between before/after comparisons. Use an overlay only if viewpoints align; raw image pixel similarity is not a general quality measure.

## Numerical support
Use the measurement-tools reference and supplied JSON templates when supported measurements exist. Helpers compare aligned landmark coordinates, assembly dimensions/ratios, and endpoint gaps. They do not read meshes, calibrate cameras, solve collisions, or determine beauty. Unknown dimensions remain unknown. Keep original targets/threshold rationale; do not silently widen them to hide a defect.

## Dependency-aware changes
Build and approve a complete blockout first. Refine one assembly while keeping its neighbours visible. If a governing hull dimension changes, inspect turret placement, skirts, wheel spacing, tracks, attachment positions, and export transforms. Recheck motion interfaces after pivot changes. Detail does not excuse a broken interface.

Keep separate source assemblies where articulation/editing/materials warrant it. Logical grouping is not the same as joining every mesh. Avoid independent high-detail part generation without shared bounds. If independent workers are used, give them the same design contract, separate working files/collections, and one integrator; do not allow concurrent writes to the master .blend.

## Checkpoints
Use source filenames/versions, not vague latest labels. Save approved blockout and pre-destructive milestones. Record next action, open defects, design changes, and approval references. Reopen/check actual source after interruption; do not assume tool or editor state persisted.
