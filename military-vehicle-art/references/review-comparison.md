# Strict before/after review comparison

From the skill directory, using ordinary Python 3 (stdlib only; Blender is not required):

```sh
python3 scripts/compare_reviews.py \
  /path/to/before/render-manifest.json \
  /path/to/after/render-manifest.json \
  --output /path/to/new-comparison.html
```

Keep each manifest beside its original `rig-lock.json` and PNGs. Keep both
source `.blend` snapshots at the absolute `source_path` recorded in each manifest;
editing the same source file in place invalidates the earlier snapshot. Output's
parent directory must already exist. Every existing output, including a source,
image, manifest, rig, directory, or dangling symlink, is refused. Inputs are read
only. Invalid input exits nonzero with a diagnostic on stderr; validation failure
creates no HTML.

## What must match

- Both manifests use integer `schema_version: 1`. Source and rig hashes must match
  current source-file bytes and adjacent `rig-lock.json` bytes, respectively.
- `rig_sha256`, required `tool_sha256` (the rendering script's SHA256),
  `camera_matrices`, integer `frame`, `render_engine`, and `blender_version` must
  match between reviews. Camera matrices must be finite numeric 4×4 lists; camera
  matching is exact, not approximate. Byte-identical rigs also lock per-view
  `ortho_scale` and lighting/render configuration. Rehashing an altered rig does
  not make it match the other review.
- Images form nonempty, equal sets of unique `(view, mode, frame_size)` keys.
  Thus full renders and different preview-frame heights pair separately; row
  ordering and filenames need not match. Same-size duplicate rows are rejected.
- Each image's current bytes must match its SHA256, and its PNG signature,
  first IHDR chunk/CRC, and header dimensions must agree with `frame_size`.
  Image views must have recorded camera matrices. SHA256 values are lowercase
  64-character hexadecimal strings.
- Image paths must be relative and resolve inside the manifest directory.
  Absolute/drive paths, backslashes, colons, empty/dot/traversal components,
  missing files, directories, and symlink escapes are rejected. Nested paths
  and symlinks remaining inside the directory are allowed.

## Display and limitations

Open the resulting HTML locally. PNG bytes are embedded as base64: no JavaScript,
external fonts, image requests, or other network dependencies. Labels and source
hashes are escaped and displayed. Smaller frames within each view/mode group are
native-size previews (one image pixel per CSS pixel at browser zoom 100%); the
largest frame is bounded to 640 CSS pixels or 80% of viewport width. Side-by-side
pairs scroll horizontally when needed. Frame height is **not** vehicle pixel height.

This is deterministic integrity checking and evidence display, **not an artistic
judge**: no automatic aesthetic score, improvement verdict, geometry validation,
or claim that image content is correct. It does not open `.blend` files, execute
embedded scripts, rerender, decode the complete PNG pixel stream, or authenticate
manifest provenance. `tool_sha256` is format-checked and compared, not verified
against a local tool installation. Matching metadata cannot prove an image came
from its claimed source; a person can rewrite files and hashes. Use trusted,
unchanging local input directories; concurrent file edits are not transactionally
locked. Large PNG sets increase memory use and HTML size.

Tests (real filesystem fixtures and stdlib-generated valid PNGs, not artwork evidence):

```sh
python3 -m unittest discover -s scripts -p test_compare_reviews.py -v
```

Tests honor `TMPDIR`; symlink tests skip only on platforms that cannot create symlinks.
