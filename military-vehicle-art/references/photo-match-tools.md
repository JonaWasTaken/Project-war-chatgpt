# Photo/reference matching diagnostics

Use `scripts/reference_match.py` to expose differences in a **registered visible view**, not to certify a percentage of a whole vehicle. It uses Pillow for image decoding/overlays; discover whether Pillow is already present in the selected Python environment and request authorization before installing it. It does not require Blender. PNG masks and PNG/JPEG photos/detail renders are supported.

## Inputs and actual command
Copy [reference-match-spec.json](../assets/reference-match-spec.json) into the job. The unfilled template intentionally fails. All image/source paths are relative to `--root`, must resolve within it, and require actual SHA256s. Copy permitted outside references into the job explicitly; never silently upload or redistribute them.

```sh
python "$SKILL/scripts/reference_match.py" /job/reference-match.json --root /job --output /job/match-v001
```

`--output` must be a NEW directory inside the job. Inputs and source are not edited. A successful run writes `report.json`, `comparison.html`, `overlay.png`, and normalized reference/model masks. HTML embeds its actual PNGs and does not load external code or network resources. Exit 0 means computed diagnostics, NOT artistic acceptance; invalid/missing inputs exit 2. Keep failed output distinct from reviewed evidence.

Required data:
- `reference.path/sha256`: actual reference photo or explicitly labelled reference image; `source_note` identifies provenance, configuration, and relevant uncertainty.
- `reference.mask_path/mask_sha256`: opaque PNG foreground mask independently traced/segmented from that reference. Do not derive the reference mask from the model to manufacture a match. `foreground` is `light` or `dark`.
- `model.path/sha256`: opaque PNG silhouette rendered from the frozen model snapshot. `foreground` usually `dark` for the included diagnostic renderer. `source_path/source_sha256` identify the frozen actual source file.
- Optional `model.detail_path/detail_sha256`: matched material/clay/detail render for internal-feature crops. Without it, the report explicitly cannot compare internal detail. It must have the SAME camera/projection/framing as the reference and mask.
- `registration.confirmed: true` and a meaningful `note`: only after inspecting compatible pose, camera, crop, dimensions and occlusions. This is a declaration, not automatic camera calibration. Record supporting camera-fit output or orthographic evidence in job notes/review. Use a native fitted perspective-camera render for a perspective photo; the existing orthographic studio renderer is not a replacement.
- `features`: a nonempty, reference-driven visible-feature ledger. Each entry has unique `id`, `visibility` (`visible`, `occluded`, `unknown`), `assessment` (`match`, `mismatch`, `unverified`), and `note`. Visible entries require integer `region: [left, top, right, bottom]` within the common frame. Right/bottom are exclusive. Occluded/unknown entries must remain unverified and do not count as matches.

All frames must already have exactly matching dimensions. The tool performs **no scaling, stretching, cropping, image alignment, segmentation, or feature recognition**. Mask threshold is 128; alpha masks with transparent pixels are refused instead of guessing the background. The operational cap is 4,194,304 pixels per frame to bound diagnostic memory/time, not a visual-quality cutoff. Resize all inputs consistently only as an explicit separate reference-preparation step and retain originals.

## What the report means
- `silhouette_iou`: intersecting foreground area divided by union foreground area in THIS view. It detects contour/envelope discrepancies; it ignores texture, colour, and geometry inside that outline.
- `mean_boundary_manhattan_px`: pooled symmetric distance between foreground boundary pixels using four-neighbour Manhattan distance. It is not Euclidean distance and is resolution-dependent. Compare only compatible registered frames.
- `manual_feature_coverage`: explicit counts of visible matches, mismatches and unverified features; occluded/unknown features remain separate. These are the inspector's supplied assessments, not detected facts. Do not cherry-pick the ledger or relabel unknowns to increase coverage.
- Cyan overlay boundary comes from the reference mask, magenta from the model, white from shared boundaries. Side-by-side crops expose actual photo/model details when a detail render is supplied.

**A silhouette IoU of 0.95 is NOT 95% of original detail.** A flat cutout can match a silhouette while having no correct volume. Require complementary views, held-out landmarks, visible-feature comparisons, clean shaded geometry, and destination tests. No single aggregate score substitutes for those checks. Hashes verify bytes, not that images truly came from the declared camera/model, and supplied feature statements still require actual image inspection.

Never use same-model self-reference or deliberately shifted-mask test fixtures as evidence of reconstruction quality. Those are valid TOOL tests only and must be labelled accordingly.
