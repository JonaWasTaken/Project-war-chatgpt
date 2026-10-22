# Art direction and surface recipes

Use this with [visual correction](visual-correction-system.md) and [gate/delivery rules](quality-and-delivery.md). These are artwork tests, not manufacturing or weapon-design instructions.

## Lock an evidence-backed visual target

Choose a coherent look board: silhouette language, plane/curvature transitions, edge treatment, finish, material relationships, and useful detail scale. Real-subject references govern identity/version/configuration; original designs follow their approved authored invariants. A generated concept can guide presentation but cannot establish historical facts. Do not improve a deliberately boxy variant by importing unsupported wedge armour or other neighbouring-variant features.

Keep a **small feature ledger in the existing job notes**, not a second specification. One row per identity-defining or disputed feature:

| Feature / assembly | Governing evidence | Decision / uncertainty | Preserve / verify |
| --- | --- | --- | --- |
| Name and visible region | Source URL or permitted local image, variant/operator/period if established, view/crop | Observed, inferred, conflicting, or unknown; why this source governs | Must-have, must-not-have, or provisional; next view needed |

Fill rows from actual evidence; the table contains no vehicle facts. Separate observed shape from interpretation. A hidden attachment is unknown, not absent. Resolve conflicting configurations before combining them; where identification remains uncertain, preserve the approved choice as provisional and name the missing evidence. Use authenticated drawings/measurements within their stated scope; do not treat every downloaded diagram as authoritative. Record authorized fictional departures explicitly.

## Review primary, secondary, then tertiary forms

| Layer | Inspect | Exit before escalating |
| --- | --- | --- |
| Primary | Complete silhouette, overall mass/stance, broad plane changes, relative assembly placement in front/side/top and intended perspective | Identity and major relationships hold across supported views; unresolved camera issues are identified, not sculpted around |
| Secondary | Identity-bearing housings, openings, rims, panel breaks, attachment interfaces, repeated-part envelope | Parts connect deliberately; negative spaces and overlap read in clay and at use distance; no floating or compensating cover-up parts |
| Tertiary | Fasteners, shallow seams, edge breaks, labels, fine surface texture | Scale and density support the focal hierarchy; details survive where needed without noisy repetition or hiding weak larger forms |

For planar armour, build deliberate connected surfaces from supported outlines and slope changes; do not merely decorate a rectangular primitive. Flat and boxy can be correct. For curved bodies, use front/top/side constraints and useful cross-sections, inspect highlight continuity, and keep unsupported hidden profiles provisional. A single side photo cannot determine cross-sections.

Use thickness where it changes visible edges, silhouette, or shadows. Use mapped shallow information where it gives the same result at the required distance. Give edge treatments a consistent visual scale, but do not round every transition equally. Fix a repeated source part and its mounting relationship before multiplying it.

## Prove one assembly before propagating the finish

Choose a **representative assembly beauty benchmark**: a region containing a major surface transition, an attachment, an edge treatment, and the material families actually needed. Do not choose only an isolated bolt or the easiest flat panel. Keep the whole asset as context.

1. Finish that assembly through geometry, normals, UV/bake where required, and neutral materials. Save a checkpoint and fixed inspection rig.
2. Render a clay view, neutral beauty view, useful grazing-light view, and intended-distance view. Inspect both crop and full asset; close-up quality alone is insufficient.
3. Compare with the governing reference/look board. Require deliberate form transitions, readable joining/negative spaces, clean highlights, and consistent material scale. Record remaining limits rather than calling it polished.
4. Review the benchmark internally; seek human approval only if the agreed scope requires it. This is not an extra mandatory user gate. Preserve the separate first-finished-asset approval before roster expansion. Reuse benchmark **decisions**—edge language, roughness hierarchy, texel/detail scale—not identical numeric settings on physically different parts. Recheck the benchmark in context after propagation.

If the benchmark fails, correct it before distributing its mesh/shader recipe across the asset or asset family.

## Material swatch ladder under neutral light

Lock camera, light rig, exposure, colour management, and render settings for comparisons. Use a neutral environment with broad key and sufficient fill to inspect shaded construction; keep a separate grazing-light diagnostic. Disable cosmetic bloom, heavy AO, depth of field, motion blur, and dramatic grading during diagnosis. Neutral is a repeatable test, not proof of the final game look.

Build a compact swatch strip using flat and curved/edge-bearing samples at consistent scale. Include only relevant material families. Use the same materials on the benchmark, not unrelated demo shaders.

1. **Clay:** one neutral material on the assembly. Resolve silhouette, normals, bevel interaction, and highlight wobble first.
2. **Clean families:** separate paint, rubber, exposed metal, optics/glass, fabric/composite as supported. Match broad value/colour and reflection character; painted metal is not bare metal. Optics must not become opaque emissive blocks without design support.
3. **Roughness ladder:** compare the current response with a visibly smoother and rougher candidate, one variable at a time. Select from the reference appearance under broad light, then verify on the actual curved and planar surfaces. There are no universal roughness numbers.
4. **Surface scale:** add only supported normal/roughness variation and markings; inspect UV stretch, repeated noise, edge response, and consistency between assemblies. Do not use random per-panel hues to manufacture interest.
5. **Optional condition:** clean, worn, dusty, muddy, or repainted is a brief/reference decision. Wear follows contact/exposure and material boundaries where evidence supports it; neither dirt nor all-over edge wear is mandatory.

If materials fail, compare clay → clean families → detailed finish without changing lights. If the clean material only fails in another rig, test lighting/exposure separately before repainting. If a plate has wavy highlights in clay, inspect topology/normals/bevels rather than hiding it with roughness or noise.

## Readability is the detail budget

Inspect at actual intended screen size, not just a zoomed crop. If wheel/track/wing forms merge, test shape, overlap, lighting, and material separation before adding detail. Spend detail on identity, mounting relationships, silhouette breaks, and useful material transitions. Preserve intended camouflage and palette; do not solve every contrast problem with bright outlines. Use the [multi-background and correction tests](visual-correction-system.md) before claiming the recipe is ready to propagate.
