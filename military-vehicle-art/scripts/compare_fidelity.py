"""Read-only aligned-reference diagnostics, not registration or artistic acceptance."""
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import warnings

from PIL import Image
import numpy as np

from render_registered import CAMERA_FIELDS, publish_directory

MAX_PIXELS = 4_194_304
MAX_CONTOUR_PAIRS = 32_000_000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def binary_array(mask):
    require(isinstance(mask, np.ndarray) and mask.dtype == np.bool_ and mask.ndim == 2,
            'mask must be a 2D boolean array')
    require(0 < mask.size <= MAX_PIXELS and max(mask.shape) <= 16384 and mask.any(),
            'empty mask or unsupported image workload')
    return mask


def summary(values):
    return {'mean_px': float(np.mean(values)), 'p95_px': float(np.percentile(values, 95, method='linear')),
            'max_px': float(np.max(values))}


def boundary_centres(mask):
    padded = np.pad(mask, 1, constant_values=False)
    interior = (padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:])
    return np.argwhere(mask & ~interior).astype(np.int64)


def contour_distances(model, reference):
    """Exact centre distances, 4-neighbour foreground boundary; exterior is false."""
    binary_array(model)
    binary_array(reference)
    require(model.shape == reference.shape, 'mask dimensions must match')
    a, b = boundary_centres(model), boundary_centres(reference)
    require(len(a)*len(b) <= MAX_CONTOUR_PAIRS, 'exact contour workload exceeds pair limit')
    # All pairs, in bounded temporary blocks, without SciPy or an approximate EDT.
    aa, bb = np.full(len(a), np.inf), np.full(len(b), np.inf)
    for start in range(0, len(a), 256):
        for other in range(0, len(b), 256):
            difference = a[start:start+256, None, :] - b[None, other:other+256, :]
            squared = np.sum(difference*difference, axis=2)
            aa[start:start+256] = np.minimum(aa[start:start+256], squared.min(axis=1))
            bb[other:other+256] = np.minimum(bb[other:other+256], squared.min(axis=0))
    ab, ba = np.sqrt(aa), np.sqrt(bb)
    return {'boundary_counts': [len(a), len(b)], 'model_to_reference': summary(ab),
            'reference_to_model': summary(ba), 'pooled': summary(np.concatenate((ab, ba)))}


def appearance_statistics(model, reference, region):
    """Encoded [0,1] / linear sRGB errors and CIELAB D65 DeltaE76; model-reference."""
    binary_array(region)
    for image in (model, reference):
        require(isinstance(image, np.ndarray) and image.dtype == np.uint8 and
                image.shape == (*region.shape, 3), 'images must be matching RGB uint8 arrays')
    m, r = model[region].astype(np.float64)/255, reference[region].astype(np.float64)/255
    def linear(rgb):
        return np.where(rgb <= .04045, rgb/12.92, ((rgb+.055)/1.055)**2.4)
    def lab(rgb):
        xyz = rgb @ np.array([[.4124564,.2126729,.0193339],
                              [.3575761,.7151522,.1191920],
                              [.1804375,.0721750,.9503041]])
        xyz /= np.array([.95047, 1, 1.08883])
        f = np.where(xyz > (6/29)**3, np.cbrt(xyz), xyz/(3*(6/29)**2)+4/29)
        x, y, z = f.T
        return np.stack((116*y-16, 500*(x-y), 200*(y-z)),axis=1)
    def errors(delta):
        return {'signed_mean': delta.mean(axis=0).tolist(), 'mae': np.abs(delta).mean(axis=0).tolist(),
                'rmse': np.sqrt(np.square(delta).mean(axis=0)).tolist()}
    ml, rl = linear(m), linear(r)
    de = np.linalg.norm(lab(ml)-lab(rl), axis=1)
    return {'pixels': int(region.sum()), 'encoded_srgb': errors(m-r), 'linear_srgb': errors(ml-rl),
            'delta_e76': {'mean': float(de.mean()), 'p95': float(np.percentile(de,95,method='linear')),
                          'max': float(de.max())}}


MAX_JSON_BYTES = 2_097_152
MAX_IMAGE_BYTES = 67_108_864
MAX_SOURCE_BYTES = 536_870_912
MAX_READ_BYTES = 2_147_483_648
MAX_REGIONS = 32
MAX_VIEWS = 16
UNBOUND = object()
REPORT_LIMITS = ('No automatic registration, exposure normalization, image authenticity/provenance verification, '
                 'physical material certification, whole-model fidelity percentage or artistic acceptance. '
                 'Uncontrolled or uncalibrated photos give appearance differences only. '
                 'Declarations are supplied evidence, not independently authenticated facts.')


def exact_object(value, keys, label):
    require(isinstance(value, dict) and set(value) == set(keys.split()), label+' has incorrect fields')
    return value


def note(value, label):
    require(isinstance(value, str) and 20 <= len(value.strip()) <= 4096 and '\x00' not in value and
            not value.strip().lower().startswith(('todo', 'replace', '<')), label+' needs an actual explanatory note')


def token(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', value), 'invalid view/region id')


def version(value):
    require(type(value) is int and value == 1, 'schema_version must be integer 1')


def fingerprint(value):
    require(isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value), 'invalid SHA-256 fingerprint')


def json_data(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key: '+key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError('nonfinite JSON value: '+value)
    try:
        value = json.loads(data,object_pairs_hook=pairs,parse_constant=constant)
    except (RecursionError, UnicodeError) as exc:
        raise ValueError('unsupported JSON encoding or nesting') from exc
    def walk(item, depth=0):
        require(depth <= 32, 'JSON nesting exceeds workload limit')
        if isinstance(item,float):
            require(math.isfinite(item), 'nonfinite JSON number')
        elif isinstance(item,dict):
            for v in item.values():
                walk(v,depth+1)
        elif isinstance(item,list):
            for v in item:
                walk(v,depth+1)
    walk(value)
    return value


def confined(root, raw, relative=False, exists=True):
    require(isinstance(raw,(str,Path)), 'path must be a string or Path')
    raw = str(raw)
    require(raw and '\\' not in raw and ':' not in raw and '\x00' not in raw, 'invalid path')
    parts = raw.split('/')
    require(all(p not in ('.','..') for p in parts) and not any(p == '' for p in parts[1:]), 'path traversal or empty segment')
    path = Path(raw)
    require(not relative or not path.is_absolute(), 'job-relative path required')
    path = path if path.is_absolute() else root/path
    try:
        components = path.relative_to(root).parts
    except ValueError as exc:
        raise ValueError('all paths must remain inside root') from exc
    require(components, 'file/directory path required')
    cursor = root
    for part in components:
        cursor /= part
        require(not cursor.is_symlink(), 'symlink paths are unsupported')
    if exists:
        require(cursor.is_file() and stat.S_ISREG(cursor.stat().st_mode), 'missing regular input: '+str(cursor))
    return cursor


class Inputs:
    """Bounded immutable byte snapshots plus before-publication full re-hash."""
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        require(self.root.is_dir(), 'root must be a directory')
        self.records, self.cache, self.used = {}, {}, 0

    def read(self, raw, expected=UNBOUND, limit=None, source=False, relative=False):
        if limit is None:
            limit = MAX_IMAGE_BYTES
        path = confined(self.root,raw,relative=relative)
        name = path.relative_to(self.root).as_posix()
        if expected is not UNBOUND:
            fingerprint(expected)
        if name not in self.records:
            digest, data = self.raw(path,limit,retain=not source)
            self.records[name] = {'path':name,'sha256':digest}
            if not source:
                self.cache[name] = data
        require(expected is UNBOUND or self.records[name]['sha256'] == expected, 'stale file fingerprint: '+name)
        if source:
            return dict(self.records[name])
        require(name in self.cache, 'source cannot also be an image/JSON input')
        require(len(self.cache[name]) <= limit, 'input exceeds read workload limit')
        return dict(self.records[name]), self.cache[name]

    def raw(self, path, limit, retain):
        size = path.stat().st_size
        require(0 < size <= limit, 'empty file or input exceeds read workload limit')
        require(self.used+size <= MAX_READ_BYTES, 'total read workload exceeded')
        digest = hashlib.sha256()
        pieces, total = [], 0
        fd = os.open(path,os.O_RDONLY | getattr(os,'O_NOFOLLOW',0) | getattr(os,'O_NONBLOCK',0))
        with os.fdopen(fd,'rb') as stream:
            require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), 'regular file required')
            while True:
                chunk = stream.read(min(1_048_576,limit-total+1))
                if not chunk:
                    break
                total += len(chunk)
                self.used += len(chunk)
                require(total <= limit and self.used <= MAX_READ_BYTES,'read workload exceeded')
                digest.update(chunk)
                if retain:
                    pieces.append(chunk)
        require(total == size, 'input changed while reading')
        return digest.hexdigest(), b''.join(pieces) if retain else None

    def document(self, raw, expected=UNBOUND):
        record, data = self.read(raw,expected,MAX_JSON_BYTES)
        return record, json_data(data)

    def verify(self):
        for record in self.records.values():
            path = confined(self.root,record['path'],relative=True)
            digest, _ = self.raw(path,MAX_SOURCE_BYTES,retain=False)
            require(digest == record['sha256'], 'input changed during comparison: '+record['path'])


def image_array(data, mask=False, foreground='light'):
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as image:
            w, h = image.size
            require(0 < w*h <= MAX_PIXELS and max(w,h) <= 16384,'image pixel workload exceeded')
            require(image.format in ('PNG','JPEG') and getattr(image,'n_frames',1) == 1,'single PNG/JPEG required')
            if image.format == 'PNG':
                require(len(data) > 24 and (data[24] == 8 or (mask and data[24] == 1)),
                        '8-bit PNG required (1-bit binary masks also supported); no silent bit depth truncation')
            require(image.getexif().get(274,1) == 1,'EXIF orientation must be baked into aligned image')
            require(not image.info.get('icc_profile'),'embedded ICC unsupported; explicitly convert to sRGB first')
            require(image.mode in (('1','L','RGB','RGBA') if mask else ('RGB','RGBA')),'unsupported image mode')
            if 'gamma' in image.info:
                require(abs(image.info['gamma']-.45455) <= .00005,'non-sRGB gamma unsupported')
            rgba = np.array(image.convert('RGBA'),dtype=np.uint8)
            require(np.all(rgba[:,:,3] == 255),'transparent pixels unsupported; precompose explicitly')
            rgb = rgba[:,:,:3]
            if not mask:
                return rgb
            require(image.format == 'PNG' and np.all(rgb == rgb[:,:,:1]) and
                    np.all((rgb == 0) | (rgb == 255)), 'mask must be strictly binary opaque PNG')
            return binary_array(rgb[:,:,0] == (255 if foreground == 'light' else 0))


def validate_spec(spec):
    exact_object(spec,'schema_version view reference evidence registration appearance regions','comparison spec')
    version(spec['schema_version'])
    view = exact_object(spec['view'],'id role','view')
    token(view['id'])
    require(view['role'] in ('fit','check','held_out'),'invalid view role')
    reference = exact_object(spec['reference'],'path sha256 mask_path mask_sha256 foreground source_note','reference')
    require(reference['foreground'] in ('light','dark'),'foreground must be light or dark')
    note(reference['source_note'],'reference source_note')
    evidence = exact_object(spec['evidence'],'kind independent','evidence')
    require(evidence['kind'] in ('independent_photo','authorized_design','synthetic_test') and
            type(evidence['independent']) is bool,'declare actual reference kind and independence')
    require(evidence['independent'] or evidence['kind'] == 'synthetic_test','non-synthetic reference must be independently supplied')
    registration = exact_object(spec['registration'],'confirmed note','registration')
    require(registration['confirmed'] is True,'actual confirmed registration required')
    note(registration['note'],'registration note')
    appearance = exact_object(spec['appearance'],'color_encoding controlled_lighting calibrated note','appearance')
    require(appearance['color_encoding'] == 'srgb' and type(appearance['controlled_lighting']) is bool and
            type(appearance['calibrated']) is bool, 'explicit sRGB/lighting/calibration declarations required')
    note(appearance['note'],'appearance note')
    regions = spec['regions']
    require(isinstance(regions,list) and 0 < len(regions) <= MAX_REGIONS,'regions must be a nonempty bounded list')
    ids = set()
    for item in regions:
        exact_object(item,'id mask_path mask_sha256','region')
        token(item['id'])
        require(item['id'] not in ids,'duplicate region id')
        ids.add(item['id'])


def evaluate(manifest_path, spec_path, inputs):
    records = {}
    records['render_manifest'], manifest = inputs.document(manifest_path)
    records['spec'], spec = inputs.document(spec_path)
    validate_spec(spec)
    require(isinstance(manifest,dict),'render manifest must be an object')
    version(manifest.get('schema_version'))
    require(manifest.get('kind') == 'registered_camera_render','actual registered_camera_render manifest required')
    source = exact_object(manifest.get('source'),'path sha256','manifest source')
    require(isinstance(source['path'],str) and Path(source['path']).suffix.lower() == '.blend','saved .blend source required')
    records['source'] = inputs.read(source['path'],source['sha256'],MAX_SOURCE_BYTES,source=True)
    size = manifest.get('image_size')
    require(isinstance(size,list) and len(size) == 2 and all(type(v) is int and 0 < v <= 16384 for v in size)
            and size[0]*size[1] <= MAX_PIXELS,'bounded integer image_size required')
    camera = manifest.get('camera')
    require(isinstance(camera,dict) and camera.get('type') in ('PERSP','ORTHO') and
            isinstance(camera.get('name'),str) and camera['name'].strip(),'named PERSP/ORTHO camera required')
    require(set(camera) <= set(CAMERA_FIELDS) | {'name','matrix_world'},'unknown camera field')
    for key,value in camera.items():
        if key in CAMERA_FIELDS and key not in ('type','sensor_fit'):
            require(type(value) in (int,float) and math.isfinite(value),'finite numeric camera field required, not bool')
            if key not in ('shift_x','shift_y'):
                require(value > 0,'positive camera scale/lens/sensor/clip required')
    if 'sensor_fit' in camera:
        require(camera['sensor_fit'] in ('AUTO','HORIZONTAL','VERTICAL'),'invalid camera sensor_fit')
    matrix = camera.get('matrix_world')
    require(isinstance(matrix,list) and len(matrix) == 4 and all(isinstance(row,list) and len(row) == 4 and
            all(type(v) in (int,float) and math.isfinite(v) for v in row) for row in matrix)
            and matrix[3] == [0,0,0,1],'finite affine camera matrix required')
    note(manifest.get('registration_note'),'renderer registration_note')
    artifacts = exact_object(manifest.get('artifacts'),'mask detail','render artifacts')
    arrays = {}
    base = Path(records['render_manifest']['path']).parent
    for role, key in (('mask','model_mask'),('detail','model_image')):
        item = exact_object(artifacts[role],'path sha256','render artifact')
        # Validate the artifact token BEFORE joining it to the render directory.
        confined(inputs.root,item['path'],relative=True,exists=False)
        path = base/item['path']
        records[key], data = inputs.read(path,item['sha256'],relative=True)
        arrays[key] = image_array(data,mask=role=='mask')
    reference = spec['reference']
    for key, field, hashfield in (('reference_image','path','sha256'),('reference_mask','mask_path','mask_sha256')):
        records[key], data = inputs.read(reference[field],reference[hashfield],relative=True)
        arrays[key] = image_array(data,mask=key=='reference_mask',foreground=reference['foreground'])
    if spec['evidence']['kind'] != 'synthetic_test':
        for ref_key in ('reference_image','reference_mask'):
            for model_key in ('model_image','model_mask'):
                require(not os.path.samefile(inputs.root/records[ref_key]['path'],inputs.root/records[model_key]['path']),
                        'independent reference may not alias renderer image/self-mask')
        require(records['reference_image']['sha256'] != records['model_image']['sha256'],
                'independent reference image may not be a byte-copy of the rendered image')
    require(all(list(a.shape[:2][::-1]) == size for a in arrays.values()),'aligned image dimensions must match manifest')
    common = arrays['model_mask'] & arrays['reference_mask']
    regions, region_hashes = {}, set()
    for item in spec['regions']:
        key = 'region:'+item['id']
        records[key], data = inputs.read(item['mask_path'],item['mask_sha256'],relative=True)
        region = image_array(data,mask=True)
        region_hash = hashlib.sha256(np.packbits(region).tobytes()).hexdigest()
        require(region_hash not in region_hashes,'duplicate region mask pixels')
        region_hashes.add(region_hash)
        require(region.shape == common.shape and np.all(~region | common),'common region must lie inside both foregrounds')
        regions[item['id']] = appearance_statistics(arrays['model_image'],arrays['reference_image'],region)
    return {'schema_version':1,'command':'compare-fidelity','source_sha256':source['sha256'],
            'source':records['source'],'view':spec['view'],
            'reference_evidence':{**spec['evidence'],'source_note':reference['source_note']},
            'registration':spec['registration'],'appearance_declaration':spec['appearance'],
            'render_camera':camera,'renderer_registration_note':manifest['registration_note'],
            'inputs':records,'metrics':{'contour':contour_distances(arrays['model_mask'],arrays['reference_mask']),
                                       'regions':regions},
            'diagnostic_status':'computed_not_acceptance','limitations':REPORT_LIMITS}


def output_path(inputs, output):
    path = confined(inputs.root,output,exists=False)
    if os.path.lexists(path):
        raise FileExistsError('output must be a NEW directory')
    require(path.parent.is_dir(),'output parent must exist')
    return path


def publish(report, inputs, output):
    with tempfile.TemporaryDirectory(prefix='.fidelity-',dir=output.parent) as temporary:
        stage = Path(temporary)/'result'
        stage.mkdir()
        (stage/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf8')
        inputs.verify()
        confined(inputs.root,output,exists=False)
        publish_directory(stage,output)
    return report


def compare(manifest_path, spec_path, root, output):
    inputs = Inputs(root)
    target = output_path(inputs,output)
    return publish(evaluate(manifest_path,spec_path,inputs),inputs,target)


LIMIT_NAMES = ('contour_p95_px','contour_max_px','region_delta_e76_mean','region_delta_e76_max')


def aggregate(spec_path, root, output):
    inputs = Inputs(root)
    target = output_path(inputs,output)
    spec_record, spec = inputs.document(spec_path)
    exact_object(spec,'schema_version purpose required_views reports limits','aggregation spec')
    version(spec['schema_version'])
    require(spec['purpose'] in ('reference_review','synthetic_test'),'explicit aggregation purpose required')
    limits = exact_object(spec['limits'],' '.join(LIMIT_NAMES),'limits')
    for value in limits.values():
        require(type(value) in (int,float) and math.isfinite(value) and value >= 0,
                'limits must be finite nonnegative numbers, not booleans')
    required, records = spec['required_views'], spec['reports']
    require(isinstance(required,list) and 0 < len(required) <= MAX_VIEWS,'required_views must be a nonempty bounded list')
    require(isinstance(records,list) and len(records) == len(required),'reports must exactly cover required views')
    wanted = {}
    for item in required:
        exact_object(item,'id role','required view')
        token(item['id'])
        require(item['role'] in ('fit','check','held_out') and item['id'] not in wanted,'duplicate/invalid required view')
        wanted[item['id']] = item['role']
    seen_views, seen_reports, seen_manifests, seen_cameras = set(), set(), set(), []
    source, worst, views = None, {}, []
    for record in records:
        exact_object(record,'path sha256','comparison report fingerprint')
        confined(inputs.root,record['path'],relative=True)
        record, report = inputs.document(record['path'],record['sha256'])
        require(record['path'] not in seen_reports,'duplicate report')
        seen_reports.add(record['path'])
        require(isinstance(report,dict) and report.get('command') == 'compare-fidelity','actual comparison output required')
        bindings = report.get('inputs')
        require(isinstance(bindings,dict),'comparison input bindings required')
        for name in ('render_manifest','spec'):
            binding = exact_object(bindings.get(name),'path sha256','comparison binding')
            inputs.read(binding['path'],binding['sha256'],MAX_JSON_BYTES,relative=True)
        # Recompute from bound inputs, not user-entered scores or edited metric summaries.
        actual = evaluate(bindings['render_manifest']['path'],bindings['spec']['path'],inputs)
        require(json.dumps(report,sort_keys=True,allow_nan=False) == json.dumps(actual,sort_keys=True,allow_nan=False),
                'comparison report does not match recomputed actual outputs')
        view_id, role = report['view']['id'], report['view']['role']
        require(view_id in wanted and wanted[view_id] == role and view_id not in seen_views,
                'duplicate, unexpected or role-mismatched comparison view')
        seen_views.add(view_id)
        manifest_key = report['inputs']['render_manifest']['sha256']
        require(manifest_key not in seen_manifests,'duplicate render manifest is not another view')
        seen_manifests.add(manifest_key)
        # Numeric structural equality preserves signed-zero/int-float equivalence.
        # At most 16 views: a list avoids lossy/representation-dependent hashing.
        camera_key = {k:v for k,v in report['render_camera'].items() if k != 'name'}
        require(camera_key not in seen_cameras,'duplicate camera projection/pose is not another view')
        seen_cameras.append(camera_key)
        if source is None:
            source = report['source']
        require(report['source'] == source and report['source_sha256'] == source['sha256'],'mixed-source comparisons rejected')
        if spec['purpose'] == 'reference_review':
            require(report['reference_evidence']['kind'] != 'synthetic_test' and report['reference_evidence']['independent'],
                    'reference_review requires actual independent reference evidence, not synthetic tests')
        contour = report['metrics']['contour']
        values = [('contour_p95_px',None,max(contour[name]['p95_px'] for name in ('model_to_reference','reference_to_model'))),
                  ('contour_max_px',None,contour['pooled']['max_px'])]
        for region_id, region in report['metrics']['regions'].items():
            values.extend((('region_delta_e76_mean',region_id,region['delta_e76']['mean']),
                           ('region_delta_e76_max',region_id,region['delta_e76']['max'])))
        failures = []
        for metric, region_id, value in values:
            result = {'value':value,'view_id':view_id,'role':role,'region_id':region_id}
            if metric not in worst or value > worst[metric]['value']:
                worst[metric] = result
            if value > limits[metric]:
                failures.append({'metric':metric,'region_id':region_id,'value':value,'limit':limits[metric]})
        views.append({'id':view_id,'role':role,'report':record,'metrics':report['metrics'],
                      'reference_evidence':report['reference_evidence'],
                      'appearance_declaration':report['appearance_declaration'],
                      'threshold_status':'exceeded' if failures else 'not_exceeded','failures':failures})
    require(seen_views == set(wanted),'missing required views')
    roles = {}
    for role in ('fit','check','held_out'):
        selected = [view for view in views if view['role'] == role]
        roles[role] = {'view_ids':[view['id'] for view in selected],
                       'threshold_status':('exceeded' if any(v['failures'] for v in selected) else
                                           'not_exceeded' if selected else 'not_present')}
    result = {'schema_version':1,'command':'aggregate-fidelity','source_sha256':source['sha256'],'source':source,
              'purpose':spec['purpose'],'aggregate_spec':spec_record,'required_views':required,'limits':limits,
              'views':views,'roles':roles,'worst':worst,
              'threshold_status':'exceeded' if any(v['failures'] for v in views) else 'not_exceeded',
              'diagnostic_status':'computed_not_acceptance','limitations':REPORT_LIMITS}
    return publish(result,inputs,target)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode',required=True)
    for name in ('compare','aggregate'):
        mode = modes.add_parser(name)
        for key in ('spec','root','output'):
            mode.add_argument('--'+key,required=True,type=Path)
        if name == 'compare':
            mode.add_argument('--manifest',required=True,type=Path)
    args = parser.parse_args(argv)
    try:
        report = (compare(args.manifest,args.spec,args.root,args.output) if args.mode == 'compare' else
                  aggregate(args.spec,args.root,args.output))
    except (OSError,ValueError,TypeError,KeyError,RuntimeError,OverflowError,ImportError,Image.DecompressionBombWarning) as exc:
        print(json.dumps({'status':'error','error':str(exc)},allow_nan=False))
        return 2
    print(json.dumps({'status':'computed','command':report['command'],'diagnostic_status':report['diagnostic_status'],
                      'threshold_status':report.get('threshold_status'),'output':str(args.output)},allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
