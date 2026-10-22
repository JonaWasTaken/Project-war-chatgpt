#!/usr/bin/env python3
"""Local evidence-gated Blender asset controller; no external agent control."""
from contextlib import contextmanager
import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import shlex
import stat
import struct
import sys
import tempfile
import zlib

# Same-directory modules are the authoritative existing validators.
import check_review
import measure_vehicle

STAGES = ('references', 'blockout', 'assemblies', 'materials', 'delivery')
INTENTS = ('reconstruction', 'original_design')
CONTROL = '.vehicle-job'
LIMITATION = ('Enforces only transitions made through this program; cannot force Codex to use it, '
              'inspect aesthetics, authenticate references or user approval, or prove provenance.')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def decode(data):
    def duplicate_check(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    def reject_constant(value):
        raise ValueError(f'Nonfinite JSON constant: {value}')
    return json.loads(data, object_pairs_hook=duplicate_check, parse_constant=reject_constant)


def confined(root, raw, internal=False, file=True):
    """Reject traversal, reserved paths, and every symlink, including in parents."""
    require(text(raw) and '\\' not in raw, 'Artifact path must be a job-relative POSIX path.')
    path = Path(raw)
    require(not path.is_absolute() and not PureWindowsPath(raw).is_absolute() and
            not PureWindowsPath(raw).drive and '..' not in path.parts and path.parts,
            'Artifact path must not be absolute or contain traversal.')
    require(internal or path.parts[0] != CONTROL, 'Controller storage is reserved.')
    candidate = root
    for part in path.parts:
        candidate = candidate / part
        require(not candidate.is_symlink(), f'Symlink artifact path refused: {raw}')
    try:
        candidate.resolve(strict=True).relative_to(root)
        if file:
            require(stat.S_ISREG(candidate.stat().st_mode) and candidate.stat().st_size > 0,
                    f'Artifact must be a nonempty regular file: {raw}')
    except (OSError, RuntimeError) as exc:
        raise ValueError(f'Missing or invalid job artifact: {raw}') from exc
    return candidate


def atomic_write(path, data):
    """Same-directory replacement: a failed write never publishes partial JSON."""
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def locked(root):
    root = Path(root).resolve(strict=True)
    require(root.is_dir(), 'Job root must be a directory.')
    control = confined(root, CONTROL, internal=True, file=False)
    require(control.is_dir(), 'Missing controller directory.')
    lock = control / 'lock'
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ValueError('Job is locked; concurrent operation refused. See recovery documentation.') from exc
    try:
        os.close(fd)
        yield root
    finally:
        lock.unlink()


def genesis_digest(state):
    # Omitting intent preserves the exact genesis of pre-intent schema-1 jobs.
    fields = {key: state[key] for key in ('route', 'baseline')}
    if 'intent' in state:
        fields['intent'] = state['intent']
    return digest(encode(fields))


def init_job(root, source, route='existing', intent=None):
    root, source = Path(root), Path(source)
    require(route in ('existing', 'new'), 'route must be existing or new')
    require(intent is None or intent in INTENTS, 'intent must be reconstruction or original_design')
    require(source.suffix.lower() == '.blend' and source.is_file(), 'source must be an existing .blend file')
    data = source.read_bytes()
    require(data, 'source must not be empty')
    root.mkdir()  # Exclusive: never adopt or overwrite an existing job.
    control = root / CONTROL
    control.mkdir()
    baseline = control / 'baseline.blend'
    baseline.write_bytes(data)
    baseline.chmod(0o444)
    (root / 'work').mkdir()
    # Do not relocate the editable scene by byte-copy: // dependencies would retarget.
    # A real Blender prepare-source pass creates the first working snapshot.
    (control / 'history').mkdir()
    state = {'schema_version': 1, 'route': route, 'source_origin': str(source.resolve()),
             'baseline': {'path': f'{CONTROL}/baseline.blend', 'sha256': digest(data)},
             'history': []}
    if intent is not None:
        state['intent'] = intent
    state['genesis'] = genesis_digest(state)
    atomic_write(control / 'state.json', encode(state))
    return state


def load_verified(root):
    state = decode(confined(root, f'{CONTROL}/state.json', internal=True).read_bytes())
    require(isinstance(state, dict) and state.get('schema_version') == 1, 'Invalid job state.')
    require(state.get('route') in ('existing', 'new'), 'Invalid route.')
    require(state.get('intent', 'reconstruction') in INTENTS, 'Invalid intent.')
    baseline = state.get('baseline')
    require(isinstance(baseline, dict) and baseline.get('path') == f'{CONTROL}/baseline.blend', 'Invalid baseline.')
    require(digest(confined(root, baseline['path'], internal=True).read_bytes()) == baseline.get('sha256'),
            'Immutable baseline bytes changed.')
    genesis = genesis_digest(state)
    require(state.get('genesis') == genesis, 'Genesis digest mismatch.')
    history = state.get('history')
    require(isinstance(history, list) and len(history) <= len(STAGES), 'Invalid history length.')
    previous = genesis
    expected_dirs = set()
    for index, entry in enumerate(history):
        name = f'{index + 1:04d}-{STAGES[index]}'
        expected_dirs.add(name)
        raw = f'{CONTROL}/history/{name}/manifest.json'
        require(isinstance(entry, dict) and entry.get('path') == raw, 'History stage order mismatch.')
        data = confined(root, raw, internal=True).read_bytes()
        require(digest(data) == entry.get('sha256'), 'Immutable history manifest digest mismatch.')
        manifest = decode(data)
        require(manifest.get('stage') == STAGES[index] and manifest.get('previous') == previous,
                'History digest chain or stage mismatch.')
        require(manifest.get('intent', 'reconstruction') == state.get('intent', 'reconstruction'),
                'History intent differs from the locked job intent.')
        files = manifest.get('files')
        require(isinstance(files, list) and files, 'History snapshot has no files.')
        for item in files:
            require(isinstance(item, dict), 'Invalid history file entry.')
            live = confined(root, item.get('path'))
            snapshot_raw = item.get('snapshot')
            require(text(snapshot_raw) and snapshot_raw.startswith(f'{CONTROL}/history/{name}/'),
                    'Snapshot path outside its history entry.')
            snapshot = confined(root, snapshot_raw, internal=True)
            require(digest(snapshot.read_bytes()) == item.get('sha256'), 'Immutable history snapshot bytes changed.')
            require(digest(live.read_bytes()) == item.get('sha256'),
                    f'Earlier evidence bytes changed: {item["path"]}')
        previous = entry['sha256']
    directory = confined(root, f'{CONTROL}/history', internal=True, file=False)
    require({p.name for p in directory.iterdir()} == expected_dirs,
            'Uncommitted or unexpected history directory; job is blocked for recovery.')
    return state


def image_file(path):
    """Structural PNG/JPEG validation, not visual inspection or authenticity."""
    data = path.read_bytes()
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        pos, kinds, payload = 8, [], bytearray()
        while pos + 12 <= len(data):
            size = struct.unpack('>I', data[pos:pos + 4])[0]
            kind = data[pos + 4:pos + 8]
            end = pos + 8 + size
            require(end + 4 <= len(data), 'Truncated PNG image.')
            body = data[pos + 8:end]
            require(zlib.crc32(kind + body) == struct.unpack('>I', data[end:end + 4])[0], 'PNG CRC mismatch.')
            kinds.append(kind)
            if kind == b'IHDR':
                require(len(kinds) == 1 and len(body) == 13, 'Invalid PNG header.')
                width, height = struct.unpack('>II', body[:8])
                require(width > 0 and height > 0, 'Empty PNG image.')
            if kind == b'IDAT':
                payload.extend(body)
            pos = end + 4
            if kind == b'IEND':
                break
        require(kinds and kinds[0] == b'IHDR' and kinds[-1] == b'IEND' and pos == len(data) and payload,
                'Invalid PNG image structure.')
        try:
            decoder = zlib.decompressobj()
            # A structural probe, bounded even if the image has huge declared dimensions.
            require(decoder.decompress(payload, 1024 * 1024), 'Empty PNG raster data.')
        except zlib.error as exc:
            raise ValueError('Invalid PNG raster compression.') from exc
        return
    if data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9'):
        pos, dimensions = 2, False
        while pos + 4 <= len(data):
            require(data[pos] == 255, 'Invalid JPEG marker.')
            while pos < len(data) and data[pos] == 255:
                pos += 1
            require(pos < len(data), 'Truncated JPEG marker.')
            marker = data[pos]
            pos += 1
            if marker == 0xDA:
                require(dimensions and pos + 2 < len(data) - 2, 'JPEG has no image dimensions or scan.')
                return
            size = int.from_bytes(data[pos:pos + 2], 'big')
            require(size >= 2 and pos + size <= len(data), 'Truncated JPEG segment.')
            if marker in (0xC0, 0xC1, 0xC2):
                require(size >= 8 and int.from_bytes(data[pos + 3:pos + 5], 'big') > 0 and
                        int.from_bytes(data[pos + 5:pos + 7], 'big') > 0, 'Invalid JPEG dimensions.')
                dimensions = True
            pos += size
    raise ValueError('Reference/render must be an actual supported PNG or JPEG image, not a renamed text file.')


def fingerprint_file(root, item, files):
    require(isinstance(item, dict), 'Fingerprint must be an object.')
    raw = item.get('path')
    path = confined(root, raw)
    data = path.read_bytes()
    require(digest(data) == item.get('sha256'), f'Stale or invalid fingerprint: {raw}')
    files[raw] = data
    return path


def reference_files(root, raw, files, state):
    path = confined(root, raw)
    data = path.read_bytes()
    files[raw] = data
    record = decode(data)
    require(isinstance(record, dict) and type(record.get('schema_version')) is int and
            record['schema_version'] == 1, 'References schema_version must be integer 1.')
    images = record.get('images')
    require(isinstance(images, list) and images, 'references.images must contain real images.')
    known = set()
    for item in images:
        path = fingerprint_file(root, item, files)
        require(item['path'] not in known, 'Duplicate reference image path.')
        known.add(item['path'])
        require(text(item.get('view')) and text(item.get('description')), 'Reference image view/description required.')
        image_file(path)
    for field in ('features', 'checks'):
        rows = record.get(field)
        require(isinstance(rows, list) and rows, f'references.{field} must be nonempty; no vacuous passes.')
        for row in rows:
            require(isinstance(row, dict), f'Invalid reference {field} row.')
            cited = row.get('reference_paths')
            require(isinstance(cited, list) and cited and all(text(p) and p in known for p in cited),
                    f'Reference {field} must cite actual reference_paths.')
            if field == 'features':
                require(text(row.get('id')) and text(row.get('description')) and text(row.get('uncertainty')) and
                        row.get('basis') in ('observed', 'inferred'),
                        'Each feature needs id, description, observed/inferred basis, uncertainty, and image citations.')
            else:
                require(text(row.get('name')) and row.get('status') == 'pass' and text(row.get('reason')),
                        'Reference checks need a name, pass status, and actual reason.')
    require(record.get('intent', 'reconstruction') == state.get('intent', 'reconstruction'),
            'References intent must match the job intent; never relabel reconstruction as original design.')
    if state['route'] == 'new' or state.get('intent') == 'original_design' or 'authorization' in record:
        authorization_files(root, state, record, files)
    return record


def json_artifact(root, item, files, label):
    path = fingerprint_file(root, item, files)
    value = decode(files[item['path']])
    require(isinstance(value, dict) and value, f'{label} must be a nonempty machine-readable JSON object.')
    return value


def authorization_files(root, state, references, files):
    """Bind a documentary concept decision to the baseline, brief and exact images."""
    authorization = json_artifact(root, references.get('authorization'), files, 'Concept/design authorization')
    intent = state.get('intent', 'reconstruction')
    require(type(authorization.get('schema_version')) is int and authorization['schema_version'] == 1,
            'Concept/design authorization schema_version must be integer 1.')
    require(authorization.get('intent') == intent and
            authorization.get('objective') == ('create_original' if intent == 'original_design' else 'reconstruct_real_subject'),
            'Concept/design authorization intent and objective must match the job.')
    require(authorization.get('baseline_sha256') == state['baseline']['sha256'],
            'Concept/design authorization must identify the actual source baseline.')
    if intent == 'original_design':
        require(text(authorization.get('originality_statement')),
                'Original design needs an actual original brief and explicit originality_statement; not a failed reconstruction.')
    fingerprint_file(root, authorization.get('brief'), files)
    images = authorization.get('reference_images')
    require(isinstance(images, list) and images, 'Authorization must bind the governing reference images.')
    bound = {}
    for image in images:
        fingerprint_file(root, image, files)
        require(image['path'] not in bound, 'Duplicate authorized image path.')
        bound[image['path']] = image['sha256']
    require(bound == {image['path']: image['sha256'] for image in references['images']},
            'Authorization must bind the exact accepted reference image paths and hashes.')
    approval = authorization.get('approval')
    require(isinstance(approval, dict) and approval.get('status') in ('approved', 'delegated') and
            approval.get('gate') == 'concept' and text(approval.get('reference')) and text(approval.get('scope')),
            'Explicit concept/design approval or delegation with actual reference and scope is required.')
    fingerprint_file(root, approval.get('evidence'), files)
    return authorization


def preparation_files(root, state, source, files):
    report = json_artifact(root, {'path': 'source-preparation.json',
                                 'sha256': digest(confined(root, 'source-preparation.json').read_bytes())},
                           files, 'Source preparation report')
    require(type(report.get('schema_version')) is int and report['schema_version'] == 1 and
            report.get('command') == 'prepare-source' and report.get('status') == 'prepared' and
            report.get('dependency_paths_absolute') is True,
            'Real Blender source preparation is required before using a relocated working copy.')
    lineage = report.get('lineage')
    require(isinstance(lineage, dict) and lineage.get('source_sha256') == state['baseline']['sha256'] and
            lineage.get('output_sha256') == digest(files[source]),
            'Source preparation lineage must match the original baseline and current first snapshot.')
    require(text(state.get('source_origin')) and lineage.get('source') == state['source_origin'],
            'Source preparation origin must match the recorded original source location, not an archival baseline or relocated copy.')
    preservation = report.get('geometry_preservation')
    require(isinstance(preservation, dict) and preservation.get('unchanged') is True and
            text(preservation.get('before_sha256')) and preservation.get('before_sha256') == preservation.get('after_sha256'),
            'Source preparation must preserve geometry.')


def reconstruction_fit_report(root, registration, record, references, files):
    """Consume the real fitter's report without hand-transcribing its measurements."""
    import math
    fit = json_artifact(root, registration.get('fit_report'), files, 'Reconstruction camera-fit report')
    require(type(fit.get('schema_version')) is int and fit['schema_version'] == 1 and
            fit.get('command') == 'fit-camera' and fit.get('status') == 'converged',
            'Expected a converged reconstruct_vehicle fit-camera report.')
    for field in ('lineage', 'solver', 'geometry_preservation', 'photo', 'acceptance', 'reprojection'):
        require(isinstance(fit.get(field), dict), 'Camera-fit ' + field + ' must be an object.')
    require(fit.get('lineage', {}).get('output_sha256') == record['source']['sha256'],
            'Fitted output must be the exact current review source, not its pre-fit input.')
    solver = fit.get('solver', {})
    require(solver.get('converged') is True and solver.get('holdouts_used_in_objective') is False,
            'Camera solver must converge without optimizing holdouts.')
    preservation = fit.get('geometry_preservation', {})
    require(preservation.get('unchanged') is True and text(preservation.get('before_sha256')) and
            preservation.get('before_sha256') == preservation.get('after_sha256'),
            'Camera fitting must preserve other geometry.')
    photo = fit.get('photo', {})
    cited = set(registration['reference_paths'])
    require(photo.get('sha256') in {image['sha256'] for image in references['images'] if image['path'] in cited},
            'Fitted photo must match an actual cited accepted reference image.')
    size = photo.get('size')
    require(isinstance(size, list) and len(size) == 2 and all(type(v) is int and v > 0 for v in size),
            'Camera report needs positive integer photo dimensions.')
    acceptance = fit.get('acceptance', {})
    require(acceptance.get('passed') is True, 'Camera report failed its explicit acceptance policy.')
    reprojection = fit.get('reprojection', {})
    rows = reprojection.get('landmarks')
    require(isinstance(rows, list) and len(rows) >= 6, 'Need actual fit and held-out landmark results.')
    errors, names = {'fit': [], 'holdout': []}, set()
    for row in rows:
        require(isinstance(row, dict) and text(row.get('object')) and row['object'] not in names,
                'Camera-fit landmark object names must be unique.')
        names.add(row['object'])
        role = row.get('role')
        require(role in ('fit', 'holdout'), 'Camera-fit landmark role must be fit or holdout.')
        observed = measure_vehicle.vector(row.get('observed_pixel'), 2, 'observed_pixel')
        projected = measure_vehicle.vector(row.get('projected_pixel'), 2, 'projected_pixel')
        measure_vehicle.vector(row.get('world'), 3, 'landmark.world')
        require(all(0 <= v < extent for v, extent in zip(observed, size)), 'Observed landmark outside photo.')
        error = math.dist(observed, projected)
        require(math.isclose(error, measure_vehicle.number(row.get('error_px'), 'error_px', 0),
                             rel_tol=1e-6, abs_tol=1e-6), 'Inconsistent camera-fit landmark error.')
        errors[role].append(error)
    for role, minimum in (('fit', 4), ('holdout', 2)):
        values = errors[role]
        require(len(values) >= minimum, 'Insufficient independent fit/holdout landmarks.')
        stats = reprojection.get(role, {})
        require(isinstance(stats, dict) and type(stats.get('count')) is int and stats['count'] == len(values),
                'Camera-fit count/statistics mismatch.')
        rms = math.hypot(*values) / math.sqrt(len(values))
        require(math.isclose(rms, measure_vehicle.number(stats.get('rms_px'), role + '.rms_px', 0),
                             rel_tol=1e-6, abs_tol=1e-6), 'Inconsistent camera-fit RMS.')
        limit = measure_vehicle.number(acceptance.get(role + '_rms_limit_px'), role + '_rms_limit_px', 0)
        require(limit > 0 and rms <= limit, 'Camera fit is outside its declared RMS policy.')


def design_registration_files(root, registration, record, references, metrics, files):
    """Review the accepted original design, not a fit to a photographed real object."""
    require(not any(key in registration for key in ('fit_report', 'camera_report', 'landmarks', 'orthographic_reason')) and
            metrics.get('command') != 'fit-camera',
            'Design review cannot relabel reconstruction photo-fit evidence as original-design diagnostics.')
    accepted = registration.get('accepted_design')
    require(isinstance(accepted, dict) and accepted == references.get('authorization'),
            'Design review must identify the exact accepted design authorization fingerprint.')
    json_artifact(root, accepted, files, 'Accepted design authorization')
    lineage = metrics.get('lineage', {})
    current_hashes = [metrics['source_sha256']] if 'source_sha256' in metrics else []
    if isinstance(lineage, dict) and 'output_sha256' in lineage:
        current_hashes.append(lineage['output_sha256'])
    require(current_hashes and all(value == record['source']['sha256'] for value in current_hashes),
            'Design diagnostic report must identify the exact current source bytes.')
    checks = registration.get('design_checks')
    require(isinstance(checks, list) and checks, 'Design review needs actual nonempty design_checks.')
    inspected = {item['path'] for item in record['evidence']
                 if item.get('kind') == 'render' and item.get('inspected') is True}
    for check in checks:
        require(isinstance(check, dict) and text(check.get('requirement')) and
                check.get('status') == 'pass' and text(check.get('finding')),
                'Design checks must identify actual brief requirements, pass status and findings.')
        paths = check.get('evidence_paths')
        require(isinstance(paths, list) and paths and all(text(p) and p in inspected for p in paths),
                'Design checks must cite actual current inspected renders.')
    approval = registration.get('approval')
    require(isinstance(approval, dict) and approval.get('status') in ('approved', 'delegated') and
            approval.get('gate') == 'design_review' and approval.get('model_version') == record['model_version'] and
            approval.get('source_sha256') == record['source']['sha256'] and
            approval.get('accepted_design_sha256') == accepted['sha256'] and
            text(approval.get('reference')) and text(approval.get('scope')),
            'Design review needs actual current approval/delegation tied to the accepted design and source.')
    fingerprint_file(root, approval.get('evidence'), files)


def registration_files(root, state, record, files):
    registration = record.get('registration')
    require(isinstance(registration, dict), 'Blockout needs a registration documentary record.')
    require(registration.get('model_version') == record['model_version'] and
            registration.get('source_sha256') == record['source']['sha256'],
            'Registration source/version is stale.')
    require(text(registration.get('diagnostic_scope')) and text(registration.get('metrics_finding')),
            'Current metrics need diagnostic_scope and an actual metrics_finding, not aesthetic scoring.')
    # The report producer owns its schema. This wrapper documents scope/currentness;
    # no invented generic metric score or assumption that a nonempty report is a pass.
    metrics = json_artifact(root, registration.get('metrics_report'), files, 'Metrics report')
    entry = state['history'][0]
    reference_manifest = decode(confined(root, entry['path'], internal=True).read_bytes())
    reference_config = reference_manifest['references']
    references = decode(confined(root, reference_config).read_bytes())
    known = {item['path'] for item in references['images']}
    cited = registration.get('reference_paths')
    require(isinstance(cited, list) and cited and all(text(p) and p in known for p in cited),
            'Registration must cite the actual accepted reference images.')
    mode = registration.get('mode')
    if state.get('intent', 'reconstruction') == 'original_design':
        require(mode == 'design_review', 'Original design requires design_review against its accepted brief.')
        design_registration_files(root, registration, record, references, metrics, files)
    elif mode == 'reconstruction_fit_report':
        reconstruction_fit_report(root, registration, record, references, files)
    elif mode == 'measured_camera_fit':
        camera = json_artifact(root, registration.get('camera_report'), files, 'Actual camera parameter report')
        require(camera.get('model_version') == record['model_version'] and
                camera.get('source_sha256') == record['source']['sha256'], 'Measured camera source/version is stale.')
        require(camera.get('projection') in ('ORTHO', 'PERSP'), 'Measured camera projection must be ORTHO or PERSP.')
        matrix = camera.get('matrix_world')
        require(isinstance(matrix, list) and len(matrix) == 4, 'Measured camera matrix_world must have four rows.')
        for row in matrix:
            measure_vehicle.vector(row, 4, 'camera.matrix_world row')
        require(matrix[3] == [0, 0, 0, 1], 'Measured camera matrix_world must be an affine world transform.')
        size = measure_vehicle.vector(camera.get('image_size'), 2, 'camera.image_size')
        require(all(v > 0 for v in size), 'Measured camera image dimensions must be positive.')
        fields = ('ortho_scale',) if camera['projection'] == 'ORTHO' else ('lens_mm', 'sensor_width_mm')
        for key in fields:
            require(measure_vehicle.number(camera.get(key), 'camera.' + key, 0) > 0,
                    'Measured camera projection parameters must be positive.')
        measurements = json_artifact(root, registration.get('landmarks'), files, 'Measured projected landmarks')
        require(measurements.get('model_version') == record['model_version'], 'Measured camera fit version is stale.')
        require(measurements.get('model_size') == camera['image_size'], 'Measured camera image_size must match landmark model_size.')
        report = measure_vehicle.landmarks(measurements)
        require(report['status'] == 'within-tolerances', 'Measured camera fit is outside justified landmark tolerances.')
    elif mode == 'orthographic_approved':
        approval = registration.get('approval')
        require(text(registration.get('orthographic_reason')), 'Explain why these references legitimately support orthographic registration.')
        require(isinstance(approval, dict) and approval.get('status') == 'approved' and
                approval.get('gate') == 'registration' and approval.get('model_version') == record['model_version'] and
                text(approval.get('reference')) and text(approval.get('scope')),
                'Orthographic registration requires explicit current approval; never infer it from a render rig.')
    else:
        raise ValueError('Registration mode must be reconstruction_fit_report, measured_camera_fit or orthographic_approved.')


def review_files(root, state, stage, source, raw, files):
    path = confined(root, raw)
    data = path.read_bytes()
    files[raw] = data
    record = decode(data)
    require(isinstance(record, dict), 'Review must be a JSON object.')
    require(record.get('intent', state.get('intent', 'reconstruction')) == state.get('intent', 'reconstruction'),
            'Review intent must match the locked job intent; no reconstruction-to-design bypass.')
    require(record.get('gate') == stage, 'Review gate does not match the current stage.')
    require(isinstance(record.get('source'), dict) and record['source'].get('path') == source,
            'Review source.path must match the explicitly selected current source path.')
    # Confinement is stricter than the existing read-only validator: reject even
    # in-root symlinks and lexical traversal before handing it any file paths.
    fingerprint_file(root, record['source'], files)
    evidence = record.get('evidence')
    require(isinstance(evidence, list), 'Review evidence must be a list.')
    for item in evidence:
        path = fingerprint_file(root, item, files)
        if item.get('kind') == 'render':
            image_file(path)
    errors = check_review.validate(record, root)
    require(not errors, 'Review not ready: ' + '; '.join(errors))
    approval = record['approval']
    require(approval.get('gate') == stage and approval.get('model_version') == record['model_version'],
            'Approval gate/model_version must match even when not_required.')
    if approval.get('status') == 'not_required':
        require(text(approval.get('scope')) and text(approval.get('reference')),
                'not_required approval needs the actual policy/delegation scope and reference.')
    if stage == 'blockout':
        registration_files(root, state, record, files)
    return record


def current_stage(state):
    return STAGES[len(state['history'])] if len(state['history']) < len(STAGES) else 'complete'


def status_result(state):
    stage = current_stage(state)
    unmet = [] if stage == 'complete' else ['Supply and validate current-stage evidence.']
    return {'stage': stage, 'route': state['route'], 'intent': state.get('intent', 'reconstruction'), 'history_verified': True,
            'unmet_checks': unmet, 'limitation': LIMITATION}


def describe(root, state, *, source=None, review=None, references=None):
    result = status_result(state)
    stage = result['stage']
    result.update({'commands': [], 'instructions': []})
    if stage == 'complete':
        result['instructions'] = ['All recorded gates passed record-integrity checks. Preserve the job and report the limits of the real delivery tests.']
        return result
    source = source or f'work/source-v{len(state["history"]) + 1:03d}.blend'
    references = references or 'references.json'
    review = review or f'{stage}-review.json'
    result['selected_source'] = source
    scripts = Path(__file__).resolve().parent
    command = [sys.executable, str(scripts / 'vehicle_job.py'), 'advance', '--job', str(root),
               '--stage', stage, '--source', source]
    try:
        path = confined(root, source)
        require(path.suffix.lower() == '.blend', 'Current source must be a .blend file.')
        files = {source: path.read_bytes()}
        if stage == 'references':
            preparation_files(root, state, source, files)
            reference_files(root, references, files, state)
        else:
            review_files(root, state, stage, source, review, files)
        result['unmet_checks'] = []
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        result['unmet_checks'] = [str(exc)]
    if stage == 'references':
        result['instructions'] = [
            'Before relocating/editing the scene, run reconstruct_vehicle.py prepare-source from the ORIGINAL source location, not the archived baseline. It creates work/source-v001.blend and source-preparation.json with absolute dependency targets. Requires a real bpy runtime; never fabricate the report.',
            'Copy actual PNG/JPEG reference images into the job, never edit the user original.',
            f'Create {references}: schema_version 1, nonempty images with path/sha256/view/description; features with id, observed/inferred basis, description, uncertainty, reference_paths; nonempty passing checks with name/reason/reference_paths. See references/job-controller.md.',
            'Perform the actual observations yourself; this controller does not inspect image meaning.',
            'Run the advance command only after the reference evidence is complete.'
        ]
        if state['route'] == 'new' or state.get('intent') == 'original_design':
            result['instructions'].append('Include references.authorization: fingerprint of actual explicit concept/design authorization, its governing brief, exact reference images and baseline. Use assets/design-authorization.json as an unfilled shape only; never invent consent.')
        if not (root / 'work/source-v001.blend').exists() and text(state.get('source_origin')):
            prepare = [str(scripts / 'reconstruct_vehicle.py'), 'prepare-source', '--source', state['source_origin'],
                       '--output', str(root / 'work/source-v001.blend'), '--report', str(root / 'source-preparation.json')]
            blender = shutil.which('blender')
            launcher = [blender, '--background', '--factory-startup', '--disable-autoexec', '--python', prepare[0], '--'] if blender else [sys.executable, prepare[0]]
            result['commands'].append(shlex.join(launcher + prepare[1:]))
        command += ['--references', references]
    else:
        result['instructions'] = [
            f'Create or select {source} inside the job; copy the last accepted source to a NEW version path before editing. Never overwrite earlier evidence.',
            f'Produce actual controlled renders of that source, inspect them using a real image-capable tool, and fill {review} from assets/review.json (schema 2); gate must be {stage}. Record actual source/render SHA-256, current findings, defects/rechecks, and real approval/delegation or documented not_required policy.',
            'This is a record gate, not automatic visual inspection or an aesthetic score. Do not invent evidence when a producer is unavailable.',
        ]
        if stage == 'blockout':
            if state.get('intent', 'reconstruction') == 'original_design':
                result['instructions'].append('Include registration mode design_review: exact accepted_design authorization fingerprint, current-source diagnostic JSON, actual design_checks citing inspected renders, and actual current design approval/delegation evidence. Review original design against its authorized brief/images; no photo fitting to a real object. See assets/design-review-registration.json and references/job-controller.md.')
            else:
                result['instructions'].append('Include registration: a current diagnostic metrics JSON fingerprint and scope/finding plus reconstruction_fit_report (preferred: actual bundled fitter report, fitted output must be current source), measured_camera_fit (other actual camera JSON and measured landmarks), OR orthographic_approved with explicit real reference authorization. See references/job-controller.md.')
                result['commands'].append(shlex.join([sys.executable, str(scripts / 'measure_vehicle.py'),
                                                     'landmarks', str(root / 'landmarks.json')]))
        result['commands'].append(shlex.join([sys.executable, str(scripts / 'check_review.py'),
                                             str(root / review), '--root', str(root)]))
        command += ['--review', review]
        blender = shutil.which('blender')
        if blender:
            result['instructions'].append('A local Blender executable was found; verify its runtime and fill review-rig.json with the ACTUAL vehicle collection before rendering. No camera-fit is implied by an orthographic review rig.')
            result['commands'].insert(0, shlex.join([
                blender, '--background', '--factory-startup', '--disable-autoexec', '--python',
                str(scripts / 'blender_vehicle_tools.py'), '--', 'render', '--blend', str(root / source),
                '--config', str(root / 'review-rig.json'), '--output', str(root / f'render-{stage}')]))
        else:
            result['instructions'].append('No blender executable discovered on PATH. Use an already-supported real renderer/runtime; do not install or fabricate renders. Record/advance remains blocked until real evidence exists.')
    result['commands'].append(shlex.join(command))
    return result


def status(root, *, source=None, review=None, references=None):
    with locked(root) as root:
        return describe(root, load_verified(root), source=source, review=review, references=references)


def advance(root, stage, source, *, references=None, review=None):
    with locked(root) as root:
        state = load_verified(root)
        require(stage == current_stage(state) and stage in STAGES, 'Requested stage cannot skip or repeat the current stage.')
        source_path = confined(root, source)
        require(source_path.suffix.lower() == '.blend', 'Current source must be a .blend file.')
        files = {source: source_path.read_bytes()}
        if stage == 'references':
            preparation_files(root, state, source, files)
            reference_files(root, references, files, state)
        else:
            review_files(root, state, stage, source, review, files)
        index = len(state['history'])
        name = f'{index + 1:04d}-{stage}'
        target = root / CONTROL / 'history' / name
        target.mkdir()
        published = False
        try:
            rows = []
            for number, (raw, data) in enumerate(sorted(files.items())):
                filename = f'{number:04d}' + Path(raw).suffix
                snapshot = target / filename
                snapshot.write_bytes(data)
                snapshot.chmod(0o444)
                rows.append({'path': raw, 'sha256': digest(data),
                             'snapshot': snapshot.relative_to(root).as_posix()})
            previous = state['history'][-1]['sha256'] if state['history'] else state['genesis']
            manifest = encode({'stage': stage, 'previous': previous, 'source': source,
                               'intent': state.get('intent', 'reconstruction'),
                               'references': references, 'review': review, 'files': rows})
            atomic_write(target / 'manifest.json', manifest)
            (target / 'manifest.json').chmod(0o444)
            # Verify captured bytes did not change during validation/copying.
            for row in rows:
                require(digest(confined(root, row['path']).read_bytes()) == row['sha256'],
                        'Evidence changed while recording; transition refused.')
            entry = {'path': (target / 'manifest.json').relative_to(root).as_posix(), 'sha256': digest(manifest)}
            state['history'].append(entry)
            atomic_write(root / CONTROL / 'state.json', encode(state))
            published = True
        finally:
            if not published:
                # A replace may have committed even when an interrupt/error was
                # reported immediately afterwards. Never delete referenced history.
                try:
                    committed = decode((root / CONTROL / 'state.json').read_bytes())
                    published = any(isinstance(entry, dict) and entry.get('path') ==
                                    (target / 'manifest.json').relative_to(root).as_posix()
                                    for entry in committed.get('history', []))
                except (OSError, ValueError, AttributeError, TypeError):
                    published = True  # Uncertain state: keep evidence and fail closed.
                if not published:
                    shutil.rmtree(target)
        return describe(root, load_verified(root))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    initialize = commands.add_parser('init', help='Create a NEW job from an explicit existing source .blend.')
    initialize.add_argument('--job', required=True, type=Path)
    initialize.add_argument('--source', required=True, type=Path)
    initialize.add_argument('--route', choices=('existing', 'new'), default='existing')
    initialize.add_argument('--intent', choices=INTENTS,
                            help='Locked at initialization; omitted intent remains reconstruction for compatibility.')
    for name in ('status', 'next', 'advance', 'record'):
        command = commands.add_parser(name)
        command.add_argument('--job', required=True, type=Path)
        command.add_argument('--source', required=name in ('advance', 'record'),
                             help='Explicit job-relative current .blend; not an external source.')
        command.add_argument('--references', help='Job-relative references manifest.')
        command.add_argument('--review', help='Job-relative existing schema-2 review JSON.')
        if name in ('advance', 'record'):
            command.add_argument('--stage', choices=STAGES, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            init_job(args.job, args.source, args.route, intent=args.intent)
            result = status(args.job)
        elif args.command in ('status', 'next'):
            result = status(args.job, source=args.source, references=args.references, review=args.review)
        else:
            result = advance(args.job, args.stage, args.source, references=args.references, review=args.review)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        print(json.dumps({'status': 'blocked', 'errors': [str(exc)], 'limitation': LIMITATION}, indent=2))
        return 2
    result['status'] = 'complete' if result['stage'] == 'complete' else 'blocked' if result['unmet_checks'] else 'ready-to-record'
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
