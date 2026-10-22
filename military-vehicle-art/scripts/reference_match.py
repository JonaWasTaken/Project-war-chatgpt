"""Reference-view diagnostics; never a whole-vehicle accuracy score."""
from array import array
import argparse
import base64
import hashlib
import html
from io import BytesIO
import json
from pathlib import Path, PureWindowsPath
import re
import sys

MAX_PIXELS = 4_194_304


def boundary_indices(mask, width, height):
    result = []
    for i, foreground in enumerate(mask):
        if not foreground:
            continue
        x, y = i % width, i // width
        if x == 0 or y == 0 or x == width-1 or y == height-1 or not all(mask[j] for j in (i-1, i+1, i-width, i+width)):
            result.append(i)
    return result


def mask_metrics(reference, model):
    if reference.size != model.size:
        raise ValueError('mask sizes differ; do not silently warp or register masks')
    width, height = reference.size
    if width*height > MAX_PIXELS:
        raise ValueError('diagnostic frame exceeds operational pixel limit')
    a, b = reference.convert('L').tobytes(), model.convert('L').tobytes()
    a, b = bytearray(bool(x) for x in a), bytearray(bool(x) for x in b)
    if not any(a) or not any(b):
        raise ValueError('foreground masks must both be nonempty')
    intersection = sum(x and y for x, y in zip(a, b))
    union = sum(x or y for x, y in zip(a, b))
    def distances(points):
        values = array('i', [width+height]) * (width*height)
        for i in points:
            values[i] = 0
        for i in range(len(values)):
            if i % width:
                values[i] = min(values[i], values[i-1]+1)
            if i >= width:
                values[i] = min(values[i], values[i-width]+1)
        for i in range(len(values)-1, -1, -1):
            if i % width != width-1:
                values[i] = min(values[i], values[i+1]+1)
            if i+width < len(values):
                values[i] = min(values[i], values[i+width]+1)
        return values
    edges_a, edges_b = boundary_indices(a, width, height), boundary_indices(b, width, height)
    distance_a, distance_b = distances(edges_a), distances(edges_b)
    mean = (sum(distance_b[i] for i in edges_a)+sum(distance_a[i] for i in edges_b))/(len(edges_a)+len(edges_b))
    return {'silhouette_iou': intersection/union, 'intersection_pixels': intersection,
            'union_pixels': union, 'reference_foreground_pixels': sum(a),
            'model_foreground_pixels': sum(b), 'mean_boundary_manhattan_px': mean,
            'scope': 'One registered 2D view, supplied foreground masks. Pooled symmetric 4-neighbour boundary Manhattan distance; NOT Euclidean distance, texture match, hidden geometry, or overall detail accuracy.'}


def checked_file(root, raw, expected):
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute() or PureWindowsPath(raw).drive or any(c in raw for c in ('\\', ':', '\x00')) or any(p in ('', '.', '..') for p in raw.split('/')):
        raise ValueError('input paths must be safe job-relative paths')
    if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('each input needs its actual lowercase SHA256')
    try:
        path = (root/raw).resolve(strict=True)
        path.relative_to(root)
        data = path.read_bytes()
    except (OSError, ValueError, RuntimeError) as exc:
        raise ValueError('input missing or escapes job: '+raw) from exc
    if not data or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('input fingerprint differs: '+raw)
    return path, data


def image_from_bytes(data, mask=False):
    from PIL import Image
    with Image.open(BytesIO(data)) as image:
        if image.format not in (('PNG',) if mask else ('PNG', 'JPEG')):
            raise ValueError('use PNG masks and PNG/JPEG reference/detail images')
        if image.width*image.height > MAX_PIXELS:
            raise ValueError('diagnostic image exceeds operational pixel limit')
        if mask and image.convert('RGBA').getchannel('A').getextrema() != (255, 255):
            raise ValueError('mask must be opaque; export a defined foreground/background')
        return image.convert('L' if mask else 'RGB')


def evaluate(spec, root, output):
    from PIL import Image, ImageChops
    root = Path(root).resolve(strict=True)
    output = Path(output).resolve()
    try:
        output.relative_to(root)
    except ValueError as exc:
        raise ValueError('output must stay inside job root') from exc
    if output.exists():
        raise FileExistsError('choose a new output directory')
    if not isinstance(spec, dict) or type(spec.get('schema_version')) is not int or spec['schema_version'] != 1:
        raise ValueError('schema_version must be integer 1')
    reference, model, registration = (spec.get(k) for k in ('reference', 'model', 'registration'))
    if not all(isinstance(v, dict) for v in (reference, model, registration)):
        raise ValueError('reference, model, and registration objects are required')
    if registration.get('confirmed') is not True or not isinstance(registration.get('note'), str) or not registration['note'].strip():
        raise ValueError('declare supported registration and its uncertainty before comparing')
    if not isinstance(reference.get('source_note'), str) or not reference['source_note'].strip():
        raise ValueError('reference source_note must identify evidence/provenance limits')
    inputs = {}
    for label, row, pathkey, hashkey in [('reference', reference, 'path', 'sha256'),
                                          ('reference_mask', reference, 'mask_path', 'mask_sha256'),
                                          ('model_mask', model, 'path', 'sha256'),
                                          ('source', model, 'source_path', 'source_sha256')]:
        inputs[label] = checked_file(root, row.get(pathkey), row.get(hashkey))
    photo = image_from_bytes(inputs['reference'][1])
    refmask = image_from_bytes(inputs['reference_mask'][1], True)
    modmask = image_from_bytes(inputs['model_mask'][1], True)
    detail = None
    if 'detail_path' in model or 'detail_sha256' in model:
        inputs['model_detail'] = checked_file(root, model.get('detail_path'), model.get('detail_sha256'))
        detail = image_from_bytes(inputs['model_detail'][1])
    if any(image.size != photo.size for image in [refmask, modmask]+([detail] if detail else [])):
        raise ValueError('all frames must match exactly; no rescaling/cropping is performed')
    for mask, row in [(refmask, reference), (modmask, model)]:
        if row.get('foreground') not in ('light', 'dark'):
            raise ValueError('declare light or dark foreground for each mask')
    refmask = refmask.point(lambda v: 255 if (v >= 128) == (reference['foreground'] == 'light') else 0)
    modmask = modmask.point(lambda v: 255 if (v >= 128) == (model['foreground'] == 'light') else 0)
    features = spec.get('features')
    if not isinstance(features, list) or not features:
        raise ValueError('nonempty explicit feature ledger required; no claim from an empty checklist')
    ids = set()
    counts = dict(visible=0, match=0, mismatch=0, unverified=0, occluded=0, unknown=0)
    for feature in features:
        if not isinstance(feature, dict) or not isinstance(feature.get('id'), str) or not feature['id'].strip() or feature['id'] in ids:
            raise ValueError('feature IDs must be nonempty and unique')
        ids.add(feature['id'])
        visibility, assessment = feature.get('visibility'), feature.get('assessment')
        if visibility not in ('visible', 'occluded', 'unknown') or assessment not in ('match', 'mismatch', 'unverified'):
            raise ValueError('feature visibility/assessment is invalid')
        if not isinstance(feature.get('note'), str) or not feature['note'].strip():
            raise ValueError('each feature needs evidence/uncertainty notes')
        box = feature.get('region')
        if visibility == 'visible':
            if not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box) or not (0 <= box[0] < box[2] <= photo.width and 0 <= box[1] < box[3] <= photo.height):
                raise ValueError('visible features need an in-frame [left,top,right,bottom] region')
            counts['visible'] += 1
            counts[assessment] += 1
        else:
            if assessment != 'unverified':
                raise ValueError('occluded/unknown features cannot count as matches or mismatches')
            counts[visibility] += 1
    metrics = mask_metrics(refmask, modmask)
    overlay = photo.copy()
    edge_images = []
    for mask in (refmask, modmask):
        data = bytearray(photo.width*photo.height)
        for index in boundary_indices(mask.tobytes(), photo.width, photo.height):
            data[index] = 255
        edge_images.append(Image.frombytes('L', photo.size, bytes(data)))
    edge_a, edge_b = edge_images
    overlay.paste((0, 255, 255), mask=edge_a)
    overlay.paste((255, 0, 255), mask=edge_b)
    overlay.paste((255, 255, 255), mask=ImageChops.multiply(edge_a, edge_b))
    report = {'schema_version': 1, 'diagnostic_status': 'computed_not_acceptance',
              'scope': 'One declared registered reference view; manually supplied masks and feature assessments.',
              'metrics': metrics, 'manual_feature_coverage': counts,
              'registration': registration, 'features': features,
              'inputs': {label: {'path': str(path.relative_to(root)), 'sha256': hashlib.sha256(data).hexdigest()} for label, (path, data) in inputs.items()},
              'tool_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'limitation': 'NOT overall reconstruction accuracy. A high silhouette IoU does not prove internal detail, materials, unseen surfaces, scale, or historical accuracy. Feature assessments and registration are supplied declarations, not authenticated automatic judgments.'}
    def embedded(image, label):
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        return '<figure><figcaption>'+html.escape(label)+'</figcaption><img alt="'+html.escape(label, quote=True)+'" src="data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode('ascii')+'"></figure>'
    document = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
                '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
                '<title>Reference-view diagnostics</title><style>body{font:16px system-ui;background:#171a20;color:#eee;margin:24px}figure{margin:0}img{display:block;max-width:680px;height:auto}.pair{display:flex;gap:20px;overflow:auto}section{margin:24px 0}pre{white-space:pre-wrap}figcaption{margin:8px 0}</style>',
                '<h1>Reference-view diagnostics</h1><p>'+html.escape(report['limitation'])+'</p><p>Cyan: reference boundary. Magenta: model boundary. White: shared boundary. No image warping or automatic registration performed.</p>',
                '<pre>'+html.escape(json.dumps(metrics, indent=2))+'</pre><div class="pair">',
                embedded(photo, 'Reference: '+reference['source_note']), embedded(overlay, 'Registered boundary overlay'), '</div>']
    if detail is not None:
        document.extend(['<h2>Full-frame model detail render</h2>', embedded(detail, 'Model detail render')])
    document.append('<h2>Manual feature evidence — not automated detection</h2>')
    for feature in features:
        document.append('<section><h3>'+html.escape(feature['id'])+'</h3><p>'+html.escape(feature['visibility']+' / '+feature['assessment']+': '+feature['note'])+'</p>')
        if feature['visibility'] == 'visible':
            box = tuple(feature['region'])
            document.extend(['<div class="pair">', embedded(photo.crop(box), 'Reference crop')])
            document.append(embedded(detail.crop(box), 'Model crop') if detail else '<p>No material/detail render supplied; internal detail cannot be compared here.</p>')
            document.append('</div>')
        document.append('</section>')
    document.append('</html>')
    output.mkdir(parents=True, exist_ok=False)
    overlay.save(output/'overlay.png')
    refmask.save(output/'reference-mask.png')
    modmask.save(output/'model-mask.png')
    (output/'comparison.html').write_text(''.join(document), encoding='utf-8')
    (output/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec', type=Path)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        report = evaluate(json.loads(args.spec.read_text()), args.root, args.output)
    except ImportError:
        print('reference_match: Pillow is required in this Python environment; request authorization before installing.', file=sys.stderr)
        return 2
    except (ValueError, OSError, TypeError, KeyError, RuntimeError) as exc:
        print('reference_match:', exc, file=sys.stderr)
        return 2
    print(json.dumps({'status': report['diagnostic_status'], 'metrics': report['metrics'], 'output': str(args.output)}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
