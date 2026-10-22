# Explicit texture-backed PBR builder

`scripts/build_pbr.py` creates **new named Principled BSDF materials** and binds them only to explicitly named local mesh-object slots in a **new `.blend` snapshot**. It consumes actual supplied textures; it does not generate textures, unwrap meshes, judge UV quality, certify close-up art quality, or establish engine parity/export portability. Constants-only rubber or paint is valid, but is reported as `untextured_constants`, not texture-backed work.

## Execute

Run in a disposable official `bpy` Python process, or Blender background mode with automatic script execution disabled. No connection to an agent application or game engine is required. Keep `reconstruct_vehicle.py` beside this script: it supplies the shared path/snapshot safeguards.

```sh
python /path/to/military-vehicle-art/scripts/build_pbr.py \
  --source /project/source.blend \
  --spec /project/filled-pbr.json \
  --output /project/candidates/materials-001.blend \
  --report /project/candidates/materials-001.json
```

Or, with an installed Blender executable:

```sh
blender --background --disable-autoexec --python-exit-code 2 \
  --python /path/to/military-vehicle-art/scripts/build_pbr.py -- \
  --source /project/source.blend --spec /project/filled-pbr.json \
  --output /project/candidates/materials-001.blend \
  --report /project/candidates/materials-001.json
```

Exit code `0` means the snapshot/report were built; `2` means invalid input, an unsupported operation, or an application/I/O error. Errors are printed as JSON on stderr; normal Blender logging can also appear. Failure is not a material-quality score. The output/report must not already exist, including dangling symlinks, and their parent directories must already exist. Source/spec/output/report must be distinct. The source is never saved over. Staging and exclusive publication are inherited from the shared snapshot helper; there is no destructive overwrite option.

## Supply real inputs, not invented metadata

Copy [the incomplete template](../assets/pbr-spec.json) to the project and fill it. Its `null` names, paths, digests, dimensions and normal convention are intentionally invalid. Do not fill unknown measurements with plausible numbers. Remove optional `normal` if absent; replace any of `base_color`, `roughness`, `metallic` with the permitted constants below when no corresponding texture is available. Remove `uv_map` only if the material uses no textures at all.

For each existing file, obtain its SHA-256 from the actual bytes and its dimensions from actual image decoding. This example can run in a disposable Blender Python console or an official `bpy` Python process; replace the path with an actual file:

```python
import bpy, hashlib, json
from pathlib import Path
p = Path('/project/textures/ACTUAL_FILE.png').resolve()
image = bpy.data.images.load(str(p), check_existing=False)
try:
    print(json.dumps({'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                      'size': list(image.size)}, indent=2))
finally:
    bpy.data.images.remove(image)
```

The builder independently rechecks the digest and decoded dimensions. Neither a filename nor a manifest claim substitutes for a decoded image. Select maps by known authorship/role: do not declare a gloss map to be roughness simply to get a successful run. Grayscale pixels alone cannot establish map semantics, provenance, licensing, or physical material accuracy.

## Strict schema version 1

Only the documented keys are allowed; duplicate JSON keys are rejected. Names must be nonempty, at most 63 UTF-8 bytes. Top-level fields:

- `schema_version`: integer `1`, not a boolean or `1.0`.
- `materials`: 1–64 material definitions, each with a unique **new** `name`, and required `base_color`, `roughness`, `metallic`. Every new material needs at least one explicit binding so it cannot disappear as unused data on save.
- `bindings`: 1–4096 exact target bindings. No wildcard/object selection/global replacement mode.

Each material field is **either** a constant **or** one map; factors are not silently multiplied into maps:

| Field | Constant if untextured | Map behavior |
|---|---|---|
| `base_color` | Four finite **linear** RGBA numbers in `[0,1]` | sRGB Image Texture Color → Principled Base Color; image Alpha → Principled Alpha |
| `roughness` | Finite number in `[0,1]` | Non-Color grayscale image → explicit RGB separation, Red → Roughness |
| `metallic` | Finite number in `[0,1]` | Non-Color grayscale image → explicit RGB separation, Red → Metallic |
| `normal` (optional) | Omit the entire field; no implicit constant/strength/convention | Non-Color image → tangent-space Normal Map, strength `1` → Principled Normal |

All numeric booleans, NaN/infinity, and out-of-range factors are rejected. Base-color alpha is connected/set, but this is not an engine transparency/alpha-mode setup tool.

A normal map requires **exactly** `path`, `sha256`, `size`, `convention`. Other maps require **exactly** `path`, `sha256`, `size`:

- `path`: actual existing PNG/JPEG file, absolute or relative to the **spec file's directory**, not the current working directory or source `.blend`. `.png`, `.jpg`, `.jpeg` are supported and file signatures must agree. TIFF/EXR/TGA/WebP, UDIMs, image sequences, and movies are unsupported inputs.
- `sha256`: actual 64-character lowercase hexadecimal SHA-256. No normalization of invalid identifiers; stale digests fail before opening the source.
- `size`: actual `[width, height]` integer pixel dimensions, each 1–32768 and at most 67,108,864 total pixels. Blender must successfully decode that exact size as a FILE PNG/JPEG. This resource bound is not an untrusted-file security sandbox.
- Normal `convention`: exactly `OpenGL` or `DirectX`, both **tangent space**. OpenGL connects directly. DirectX uses explicit Separate Color → `1 - Green` Math → Combine Color, preserving red/blue, then Normal Map. There is no silent convention guess. Object/world-space normals and unlisted options are rejected.

Roughness/metallic maps must actually decode as grayscale: RGB channels must agree within `1e-5` in Non-Color values. Colored/packed scalar maps are rejected rather than picking a guessed channel. Packed-map/channel selectors, gloss/smoothness inversion, AO packing, displacement, bump/parallax, arbitrary procedural graphs, and extra shader controls are unsupported keys. Convert/unpack known sources explicitly in an appropriate authoring workflow, record that processing, then fingerprint the resulting files. A semantically mislabeled grayscale map cannot be automatically detected.

Each map use loads a **separate new image datablock** with `check_existing=False`. Even when a single input filepath is deliberately used for both base color and scalar data, its sRGB/Non-Color settings cannot overwrite each other or any existing image's colorspace/pixels. Source materials are never edited. Texture extension is explicitly Repeat, interpolation Linear. No texture scaling/texel-density guess is made.

### UV binding

A material using **any** texture must provide a nonempty `uv_map` name. That exact layer must already exist on **every** targeted mesh for that material. Image Texture Vector inputs are explicitly linked to a UV Map node with that name; Normal Map uses that same named UV layer for the tangent basis. Missing layers fail; there is no automatic unwrap or active-UV fallback. Existence says nothing about stretch, overlaps, texel density, seams, tangent quality, or bake quality.

### Slot policy and ownership

Each binding contains `object` and `material` plus **exactly one** of:

```json
{"object": "Hull", "material": "Paint_Closeup_v003", "slot": 1}
```

`slot` is an **existing, zero-based** object material-slot index. The selected slot becomes an OBJECT-linked override. Mesh-data slots and other objects sharing that mesh retain their prior materials. Unselected slots, face material indices, mesh geometry, transforms and modifiers are not rewritten.

```json
{"object": "Hull", "material": "Paint_Closeup_v003", "append": true}
```

`append: true` adds exactly one material slot; **faces are not reassigned**. The report records the resulting index. A mesh must be single-user for append: otherwise appending could change an unselected shared-mesh object. Make it single-user explicitly in a separate approved modelling step if needed. At most one append binding per object is accepted; different existing slots on that object may still be bound explicitly.

Material names already owned anywhere in the file, duplicate object/slot bindings, ambiguous local/linked object names, absent/non-mesh targets, and linked/noneditable/library-override object or mesh data are rejected. Bindings can only reference the newly declared materials. Existing linked source dependencies are not automatically made local.

### Constants-only example

This deliberately **untextured** example shows syntax; its artistic factors are illustrative choices, not measurements or a universal rubber recipe. Change names/slot and tune factors using the actual asset/reference swatches:

```json
{
  "schema_version": 1,
  "materials": [{
    "name": "Rubber_Untextured_v001",
    "base_color": [0.025, 0.025, 0.025, 1.0],
    "roughness": 0.7,
    "metallic": 0.0
  }],
  "bindings": [{"object": "Tyre", "material": "Rubber_Untextured_v001", "slot": 0}]
}
```

Mixed constant/texture materials are also permitted: e.g. supplied base-color texture with explicit roughness/metallic constants. Only fields actually backed by decoded textures appear in the map list.

For an approved prepared track-link master, pass this builder's actual output snapshot to `build_track.py`; its object-scoped slot overrides are explicitly copied to each new link while mesh data remains shared. Verify the propagated material on the saved belt and in an actual render, not just on the original master.

## Evidence, dependencies and limits

The JSON report records actual new material names, `texture_backed` versus `untextured_constants`, exact slot policies/indices, each decoded map's absolute path/digest/size/colorspace, explicit normal convention, source/spec/output fingerprints, and Blender version. `texture_backed` means at least one map, not necessarily a complete authored texture set. It is construction/integrity evidence, not visual approval.

Before saving, dependency paths are made absolute while the source is open at its own location. Existing image/library dependency **path strings** may consequently be rebased in the new snapshot; their intended targets are preserved, not their relative spelling. Existing material graphs and image colorspace/pixel data are not modified. The original source bytes remain unchanged. New image paths are already absolute. External assets are **not copied or packed**; their later availability and the portability of linked-library internals are not certified. Keep source files/textures stable during the operation; texture hashes are rechecked before construction and publication, but this is not a filesystem-wide transactional asset store.

For close-up military-sim work, still inspect authored surfaces, UVs, bakes, edge/detail scale, normal seams, roughness response, wear logic and neutral/grazing-light renders at the actual intended camera distance. Validate export/reimport, tangent conventions, transparency and target-engine shaders separately. No textures generated, improved aesthetics, bake correctness, complete export portability, engine parity, or finished-asset readiness is implied by a successful build.

## Regression tests

For close-up finish, follow the built snapshot with [evaluated surface diagnostics](surface-audit.md) and [explicit controlled-light stress renders](realism-production.md#controlled-material-stress-renders). Audit the actual named UV/material/map scope; this builder's successful binding is not a texel-density, overlap, stretch or seam result. Inspect evaluated bevel-corner mapping and native-pixel shading, not just the base UV inventory.

From the skill directory, with official `bpy` available:

```sh
python -m unittest discover -s scripts -p test_build_pbr.py -v
```

Where the official wheel is already cached, an isolated offline runtime can be used without a system install:

```sh
uv run --offline --python 3.13 --with bpy python -m unittest discover -s scripts -p test_build_pbr.py -v
```

Tests create only scratch scenes and **synthetic mechanics textures**, then reopen the saved snapshots. They cover actual node links/colorspaces, shared-path image separation, decoded PNG/JPEG dimensions, explicit UV bindings, missing UV rejection, DirectX green inversion, scoped slot changes, shared/linked ownership rejection, absolute dependencies, source hashes and overwrite refusal. A CPU Cycles integration renders the actual texture-backed Principled material with a known synthetic +green tangent normal under a +Y light: OpenGL must be brighter than the explicitly green-inverted DirectX result. This proves exercised shader mechanics, not production texture or vehicle quality.
