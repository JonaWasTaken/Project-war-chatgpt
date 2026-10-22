# Visual correction system

Use for an existing asset or each production gate. Keep only the current defect queue and evidence decisions in job notes; do not create a second review schema. Follow [surface/benchmark recipes](art-direction-and-surface-recipes.md) and [record semantics](quality-and-delivery.md).

## 1. Establish what the images can prove

Inspect actual reference and render images; a script log, object count, or passing measurement is not image review. Confirm vehicle orientation, variant, pose, and occlusion before diagnosing missing features. Use the feature ledger to protect established identity and flag uncertain evidence.

For each governing comparison, record a compact **camera/reference registration note** in the existing checkpoint: source/crop; useful landmarks; perspective or orthographic status; camera/pose assumptions; remaining uncertainty; which feature comparisons are supported. Use a saved rig/manifest if available rather than transcribing it twice.

- Start with whole framing and stable landmarks distributed across the visible vehicle, not one local detail. Match view direction, camera elevation, framing, perspective strength, and articulated pose. Keep source pixels/crop provenance; do not stretch a photograph non-uniformly to force agreement.
- Separate silhouette mismatch from foreshortening, lens distortion, uncertain crop, terrain tilt, and changed suspension/pose. Unknown focal length is not an exact calibrated camera. An apparently orthographic drawing may contain inconsistent projections.
- Register against supported primary landmarks, then test other landmarks not used for fitting. If matching the turret makes the hull fail, investigate variant, projection, pose, or geometry instead of silently moving every part.
- When more than one plausible camera explains the photo, compare the alternatives first. If the apparent defect changes or disappears across those fits, label it camera-sensitive and seek a complementary view. Do not prescribe exact geometry changes from it.
- Change geometry only for a discrepancy supported by the useful views or an explicit design decision. Do not distort an approved model to match every inconsistent photograph. Leave hidden structure as an inference and exact uncalibrated dimensions unverified.

Registration is sufficient when the particular comparison is stable enough to decide the next correction; perfect camera recovery is not required. Use orthographic inspection views for model consistency, a registered camera for reference comparison, and the use camera for readability. None substitutes for the others.

## 2. Choose the defect with the largest visual consequence

First inspect the whole vehicle at the agreed display size, then inspect diagnostic crops. Apply primary → secondary → tertiary review, but fix a dominating material/lighting failure before adding geometry when clay shows the forms already work. Technical delivery failures remain blockers even if visually invisible.

For each candidate, write **visible observation and location → evidence → likely owning layer → intended improvement**. Label hypotheses as hypotheses. Compare consequences, not arbitrary point totals:

- Does it change identity, silhouette, stance, or an important assembly connection?
- Does it dominate a broad/high-contrast region or repeatedly attract attention at use size?
- Does it recur across required views/backgrounds, or only in a magnified unusual angle?
- How confident is the diagnosis? What is the smallest test that separates plausible causes?

Use existing severities: **blocker** prevents the agreed identity/use or makes a required gate/delivery check impossible; **important** materially weakens a required view or finish at this stage; **minor** is localized and does not undermine the agreed use. State the consequence, not just the label. A bolt invisible at game distance is not automatically urgent; a wrong variant-defining form can be urgent even when geometrically simple. Do not invent scores, percentages, or universal pixel cutoffs.

## 3. Run a bounded A/B correction

1. **A / baseline:** preserve the best source and its actual inspected images. Freeze cameras, lights, render settings, display framing, and comparison size. Name the single defect and predicted visible result; identify untouched assemblies and interfaces.
2. **B / candidate:** change one owning layer or one coherent assembly correction, not geometry, lighting, and weathering together. Use the smallest render set that settles the hypothesis: matched problem view, an alternate view, affected neighbouring interfaces, and the use-size view. Keep required final gate coverage intact.
3. **Compare:** inspect A and B side by side at equal whole-vehicle framing/size, then the relevant crop. Check whether the named problem improved and whether a new silhouette, fit, shading, material, or readability defect appeared. If the light is the variable, keep camera/material/geometry fixed; run the other diagnostic modes separately.
4. **Keep or roll back:** keep B only if the predicted improvement is visible without an unacceptable regression. If worse or inconclusive, restore A and retain the failed hypothesis in a short note. Do not prefer B because it is newer or more detailed. If a trade-off needs authorization, keep the best verified baseline while asking.
5. **Stop blind iteration:** after two targeted attempts without a clear improvement, stop that treatment. Recheck reference registration and root cause or request the missing evidence/decision. Do not restart the same loop under a new filename. Once the observable defect and regression checks pass, move on instead of polishing indefinitely.

At the gate, rerender/review the full agreed view set from the chosen saved source. Historical A evidence stays with its historical review/version; do not relabel it as current. Cite current B recheck evidence for fixed defects and current regression evidence, describing any historical comparison truthfully in findings/job notes. Never update old fingerprints to disguise changed files.

## 4. Test use-distance readability across backgrounds

For RTS work, lock the agreed gameplay camera, expected unit screen size, display resolution, and relevant zoom range. Record actual settings; if no engine/camera is available, label the Blender test a proxy and keep engine readability unverified. Review native-size images without enlarging them; enlarged crops are diagnostics only.

- Include representative bright, dark, and textured backgrounds from the intended environment where available. If terrain is unknown, use clearly labelled neutral stand-ins to expose contrast failures, not to claim game validation. Use the same framing/scale and controlled lighting across the background comparison.
- Check overall identity, assembly separation, facing/orientation cues, silhouette interruptions, and whether markings/fine patterning alias or turn into noise. Where roster context matters, compare approved neighbours at the same scale rather than judging the asset in isolation.
- If forms merge, isolate overlap/shape, value/roughness, and light before inventing geometry or bright edge paint. Keep intended camouflage and documented finish; some background blending can be intentional. A readability change that alters the approved design needs authorization.
- Retest the candidate on every required background and relevant zoom, plus the neutral benchmark. A fix that only works on one contrasting backdrop is not a general solution. Check real destination lighting, shadows, LOD/mips, and motion when those are delivery requirements; still images cannot certify temporal stability.

Completion: the chosen version addresses the named defect in the actual target presentation, preserves protected features and adjacent assemblies, and has current inspected regression evidence. Otherwise report the specific unresolved or blocked check, not a quality claim.
