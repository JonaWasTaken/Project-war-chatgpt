# Review and delivery protocol

## Define acceptance before polishing

Record intended views, style, moving parts, outputs, and consequential tolerances in the job spec. Completion means meeting that brief, not exhausting every detail. Review silhouette, proportions, assembly fit, shading, materials, intended-distance readability, motion, and regression. A category may be not applicable only with an explicit stage/brief reason.

Use [art direction and surface recipes](art-direction-and-surface-recipes.md) to establish the feature ledger and representative finished assembly. Use [visual correction](visual-correction-system.md) for reference registration, impact-based defect choice, bounded A/B changes, rollback, and RTS/background tests. Keep those working notes in the existing checkpoint; they are not new validator fields.

## Close-up sources and separate delivery choices

For maximum-fidelity/close-up work, apply [close-up production](close-up-production.md) inside these same gates. Require native-pixel representative-assembly and identity-feature close-ups, clay/grazing-light checks, UV/bake/material inspection and the closest requested camera—not only small whole-asset silhouettes. Keep a high-detail source separate from destination LODs and runtime limits. A former RTS brief must not silently cap a new military-sim request. Source beauty, articulation, export parity and engine/simulator behavior remain separate claims; tools for static geometry and shader assembly do not certify a working simulated vehicle.

## Distinguish readiness claims

These are **acceptance standards within existing gates**, not new gate names or coverage categories. State what actually passed; never promote one kind of readiness into another.

| Claim | Existing gate | Required visual/technical proof | Does not establish |
| --- | --- | --- | --- |
| Blockout-ready | blockout | Complete primary masses, identity/stance, supported major proportions, assembly bounds/interfaces; inspected front/side/top/three-quarter or agreed equivalents plus use-size readability; uncertainties declared; gate approval/delegation | Detailed construction, finished materials, engine performance |
| Model-ready | assemblies | Primary/secondary forms work together; representative finish benchmark established; deliberate connections/negative spaces, clean clay/grazing-light shading, repeated-part consistency, required visible clearances; alternate-view regression | Finished shaders/textures or verified export |
| Material-ready | materials | Approved benchmark propagated coherently; clay vs clean-family vs final finish isolation; consistent surface scale, relevant UV/bake checks, neutral and intended-distance/background evidence | Destination shader parity, packaged dependencies, runtime budgets |
| Engine-ready, only when requested | delivery | Actual clean destination import, correct units/axes/hierarchy/pivots, materials/textures, required motion, relevant LOD/mip/background tests, and agreed measured resource/performance limits | All engines/hardware, unseen poses, or conditions not tested |

A clean Blender re-import verifies that route, not a different engine. If the destination is unavailable, report source/export checks completed and engine readiness blocked/unverified. A static art delivery need not acquire engine requirements. Do not block a serviceable blockout for absent bolts, individual track links, plain temporary materials, or optional weathering. Conversely, do not call a plain blockout a finished model.

## Review record: preserve schema 2

Use `assets/review.json` as the starting record. Keep the existing schema: no new score, readiness, registration, ledger, benchmark, or material-mode fields are required by the validator. Put extra observations in existing `finding`, `reason`, or defect `description` text, with longer working notes beside the review. Additional real render evidence can use descriptive `view` labels; agree mandatory labels in `required_views` before the gate rather than weakening the plan afterwards.

Record source `{path, version, sha256}`: the saved concept image at concept stage, or saved `.blend` at modelling stages. Compute actual lowercase SHA-256 digests for the frozen source and every evidence file using available hash tools or Python hashlib; never invent them. Freeze the source snapshot and save the reproducible review rig/settings, either in the scene or as a separate locked rig, before producing evidence. Never refresh hashes in an old review to make changed files appear previously inspected: save a new review and inspect its actual images. Hashes detect changed bytes, not whether a render truly came from the named source or approval text is authentic.

Set `required_views` from the agreed per-gate inspection plan; default blockout views are `front`, `side`, `top`, and `three_quarter`. Evidence view labels must match. Do not shrink the plan just to pass the validator. Set `motion_required` from the brief; requested motion cannot be waived at delivery. The template's false is a blank starting point, not authorization to skip animation.

Migrate schema-1 reviews by rechecking actual source/evidence and recording truthful fingerprints/required views/motion requirements. Old approvals cannot authorize a changed design automatically.

- `gate` is `concept`, `blockout`, `assemblies`, `materials`, or `delivery`. `model_version` identifies the source used for evidence; concept stage can use its concept version. Source version and evidence versions must match it. Evidence paths are job-relative. Never add fictional evidence or mark an unseen image inspected.
- Render entries record `path`, actual `sha256`, `kind` (`render`), `version`, `view`, `inspected` (boolean), and `finding` (specific observation). Record actual generated/rendered review images, not logs, placeholders, or unrelated screenshots. Use `kind: artifact` for delivery files with factual findings; artifacts are not image inspection and cannot stand in for coverage render evidence.
- Coverage categories remain `silhouette`, `proportions`, `fit`, `shading`, `materials`, `readability`, `motion`, and `regression`. Each has `status` (`pass`/`fail`/`na`/`blocked`) and a concrete `reason`; pass/fail entries cite current inspected renders in `evidence_paths` drawn from recorded evidence. `na` requires a reason. Silhouette/readability are mandatory at every gate; proportions/fit/regression after concept; shading from assemblies onward; materials at materials/delivery. Required categories cannot be `na`. Requested motion must pass by delivery. Do not pass later-stage checks on a blockout: use `na` with the gate-specific reason where permitted.
- Defects have `id`, `severity` (`blocker`/`important`/`minor`), `state` (`open`/`fixed`/`accepted`), and `description`. A fixed defect requires `recheck_evidence` pointing to a current inspected render. An accepted defect requires an actual user `acceptance_reference`. Never accept a blocker: resolve it or leave the gate blocked. Important open defects prevent readiness; minor open defects remain disclosed. Acceptance cannot override mandatory coverage: a failed required check remains unready unless resolved or the brief is legitimately revised and re-reviewed.
- Approval has `status` (`pending`/`approved`/`delegated`/`not_required`), `reference` to actual authorization, `scope`, `model_version`, and `gate`. Approved/delegated records must match the current version/gate. Concept/blockout require approved or delegated readiness; later gates may use not_required only when no applicable authorization is outstanding. A first-finished-example approval requirement does not disappear merely because its gate permits that value. Never reuse stale earlier approval for changed scope/design.

Run `python <skill-directory>/scripts/check_review.py review.json --root <job-directory>`. The read-only validator checks structural readiness, source/evidence fingerprints, required views, requested motion coverage, and evidence-file integrity. It does **not** determine artistic merit, inspect images, or authenticate approval text. Return code 0 means record-ready; 1 means issues found; 2 means invocation/input error. Record-ready is not visual approval.

## Correction and gate review

Choose the largest **observable** defect at the real viewing size, not an arbitrary numeric quality score. Diagnose its owning reference/camera/form/normal/UV/material/light/export layer. Follow the bounded A/B system; preserve the best source, inspect alternate views and adjacent assemblies, and roll back regressions. After two unproductive targeted attempts, diagnose or request missing evidence rather than repeating the treatment.

At each gate inspect the chosen saved version's full agreed view set. Do not carry old images forward as current evidence. A separate defect-finding review is useful; a separate agent is optional, and its claims still need actual artifact evidence. Do not say professional/AAA merely because a checklist or script passes.

## Export and final report

Check source/version consistency, texture dependencies, axes, units, transforms, hierarchy, normals, intended material response, and pivots through required representative poses. Export requested formats only. Re-import into a clean scene or destination and inspect; record actual re-import evidence, not only source beauty renders. Disclose unsupported procedural material/rig/modifier behaviour. Do not silently omit failed outputs or claim runtime tests from a successful export operation.

Deliver organized editable `.blend`, approved concept and actual prompt where applicable, reference provenance/permissions as appropriate, useful renders, exports, required textures, and factual verification/limitations. Do not redistribute reference images without permission. Separate blockout/model/material/destination readiness, completed/blocked/unverified checks, and outstanding approval. Ask for acceptance of any permissible important trade-off with evidence; do not call a blocked gate complete.
