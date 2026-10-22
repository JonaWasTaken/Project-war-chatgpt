# Registered render → reference comparison

Use `scripts/compare_registered.py` to connect an ACTUAL `render_registered.py` manifest to `reference_match.py` without manually transcribing model/source hashes and file names. It requires Pillow, as does the diagnostic backend; discover the environment and obtain permission before installing dependencies.

## Inputs

Keep the saved model, renderer directory, reference images/masks, reference spec and comparison output inside the job root. Source and all artifacts must match their fingerprints. The renderer's manifest must declare `kind: registered_camera_render`; the separate orthographic studio-review manifest is not a registered photo render.

Copy [registered-reference-spec.json](../assets/registered-reference-spec.json). Its unfilled fields deliberately fail. Supply only:

- `schema_version: 1`.
- `reference`: real job-relative photo and independently prepared opaque PNG mask, actual SHA-256 for each, `foreground: light|dark`, and a meaningful provenance/configuration/uncertainty note.
- `registration`: `confirmed: true` only after actual projection/pose/crop/occlusion inspection, plus the actual registration note. A saved camera is not automatically calibrated to a photo.
- `features`: the existing explicit visible/occluded/unknown feature ledger. Visible features require actual in-frame pixel regions; unknown or occluded features remain unverified. Assessments are manual, never invented by the tool.

Do not add a `model` field: the connector derives it from the renderer's current material detail image, opaque white-foreground geometry mask and saved-source fingerprint. It also records the actual camera metadata and manifest hash.

```sh
python "$SKILL/scripts/compare_registered.py" \
  --manifest "$JOB/registered-view/render-manifest.json" \
  --reference-spec "$JOB/registered-reference.json" \
  --root "$JOB" --output "$JOB/comparison-view-v001"
```

Use the manifest filename actually written by the renderer. Output must be a NEW directory; no source, reference, manifest, or existing comparison is overwritten. Absolute input paths are allowed only INSIDE the chosen job; artifact paths in the manifest remain relative to its render directory. Traversal and symlink inputs/outputs are refused.

## Result and limits

Success writes actual `comparison.html`, `overlay.png`, normalized masks, `report.json` and the generated `paired-spec.json`. HTML embeds real rendered/reference crops without network loads. No resizing, warping, automatic segmentation, feature recognition, artistic approval or whole-vehicle accuracy percentage is performed. Exit 0 means `computed_not_acceptance`; exit 2 means invalid/unsupported/stale inputs or failure. Inputs are checked again before publication; a caught publication error cleans the output owned by that attempt.

The manifest's frame dimensions must equal decoded mask/detail dimensions. Reference and model frames must also match exactly, as required by the backend. Retain full-resolution renders for native-pixel inspection: the backend's current operational pixel cap does not define the asset's quality target. Any separately prepared crop/reduced diagnostic pair must preserve compatible framing and originals.

**Tool tests may use same-scene renders and synthetic masks to check the connector. They are not reconstruction-quality evidence.** For a real subject, reference masks must come from the permitted independent reference, and complementary/held-out views must check volume, secondary details and materials separately.
