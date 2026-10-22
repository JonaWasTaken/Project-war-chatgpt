"""Offline, non-destructive loft construction and sparse photo camera fitting.

Run in a disposable process with official bpy, or Blender --background
--disable-autoexec --python this_file -- <subcommand> ... . See
references/reconstruction-tools.md for supported geometry and evidence limits.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import struct
import tempfile


def number(value, label, positive=False):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and (not positive or value > 0)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(label + ' must be a finite ' + ('positive ' if positive else '') + 'number, not a boolean')
    return float(value)


def float32(value):
    try:
        result = struct.unpack('f', struct.pack('f', value))[0]
    except (OverflowError, struct.error) as exc:
        raise ValueError('coordinate is outside supported Blender float32 range') from exc
    if not math.isfinite(result):
        raise ValueError('nonfinite coordinate after float32 conversion')
    return result


def keys(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError('expected keys: ' + ', '.join(required) + '; optional: ' + ', '.join(optional))


def text(value, label):
    if not isinstance(value, str) or not value.strip() or '\x00' in value or len(value.encode('utf8')) > 63:
        raise ValueError(label + ' must be a nonempty name of at most 63 UTF-8 bytes')
    return value


def validate_ring(ring):
    if not isinstance(ring, list) or len(ring) < 3:
        raise ValueError('rings need at least three XZ vertices')
    for point in ring:
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError('XZ vertices must contain two numbers')
        for v in point:
            number(v, 'XZ coordinate')
    span = max(max(p[i] for p in ring) - min(p[i] for p in ring) for i in (0, 1))
    if span <= 1e-9:
        raise ValueError('degenerate ring extent')
    eps = span * span * 1e-10
    def cross(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])
    def on(a, b, c):
        return (min(a[0], b[0])-span*1e-10 <= c[0] <= max(a[0], b[0])+span*1e-10 and
                min(a[1], b[1])-span*1e-10 <= c[1] <= max(a[1], b[1])+span*1e-10)
    n = len(ring)
    for i in range(n):
        a, b = ring[i], ring[(i+1) % n]
        if sum((x-y)**2 for x,y in zip(a,b)) <= eps:
            raise ValueError('degenerate ring edge')
        for j in range(i+1, n):
            if j in ((i+1) % n, (i-1) % n):
                continue
            c, d = ring[j], ring[(j+1) % n]
            u, v, w, t = cross(a,b,c), cross(a,b,d), cross(c,d,a), cross(c,d,b)
            if (u*v < 0 and w*t < 0) or any(abs(q) <= eps and on(e,f,g) for q,e,f,g in ((u,a,b,c),(v,a,b,d),(w,c,d,a),(t,c,d,b))):
                raise ValueError('self-intersecting or touching ring')
    area = sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(ring, ring[1:]+ring[:1]))
    if abs(area) <= eps:
        raise ValueError('degenerate ring area')
    # This deliberately bounded loft supports strictly convex sections only.
    if any(cross(ring[i-1], ring[i], ring[(i+1)%n]) * area <= eps*abs(area) for i in range(n)):
        raise ValueError('supported rings must be strictly convex, without collinear corners')
    return area


def validate_transition(a, b, sign):
    """Require strict convexity for the whole interpolation, not sample slices.

    Each edge/other-vertex signed half-plane distance numerator is quadratic
    in station fraction. Its endpoint values and interior extremum bound it.
    """
    def sub(p, q):
        return [p[k]-q[k] for k in (0,1)]
    def cross(p, q):
        return p[0]*q[1]-p[1]*q[0]
    span = max(max(p[k] for ring in (a,b) for p in ring)-min(p[k] for ring in (a,b) for p in ring) for k in (0,1))
    eps = span*span*1e-10
    for i in range(len(a)):
        j = (i+1) % len(a)
        u = sub(a[j], a[i])
        du = sub(sub(b[j], b[i]), u)
        for k in range(len(a)):
            if k in (i,j):
                continue
            v = sub(a[k], a[i])
            dv = sub(sub(b[k], b[i]), v)
            c0 = sign*cross(u,v)
            c1 = sign*(cross(du,v)+cross(u,dv))
            c2 = sign*cross(du,dv)
            values = [c0, c0+c1+c2]
            if c2 > 0:
                t = -c1/(2*c2)
                if 0 < t < 1:
                    values.append(c0+c1*t+c2*t*t)
            if min(values) <= eps:
                raise ValueError('correspondence folds or degenerates between stations')


def validate_loft(spec):
    keys(spec, ('schema_version', 'object_name', 'collection', 'sections'))
    if type(spec['schema_version']) is not int or spec['schema_version'] != 1:
        raise ValueError('schema_version must be integer 1')
    for field in ('object_name', 'collection'):
        text(spec[field], field)
    sections = spec['sections']
    if not isinstance(sections, list) or not 2 <= len(sections) <= 4096:
        raise ValueError('need 2..4096 ordered sections')
    previous = None
    for section in sections:
        keys(section, ('y', 'labels', 'xz'))
        number(section['y'], 'Y station')
        area = validate_ring(section['xz'])
        validate_ring([[float32(v) for v in point] for point in section['xz']])
        float32(section['y'])
        labels = section['labels']
        if not isinstance(labels, list) or len(labels) != len(section['xz']):
            raise ValueError('each ring needs one correspondence label per vertex')
        for label in labels:
            text(label, 'correspondence label')
        if len(set(labels)) != len(labels):
            raise ValueError('correspondence labels must be unique')
        if previous is not None:
            if section['y'] <= previous['y'] or float32(section['y']) <= float32(previous['y']):
                raise ValueError('Y stations must be strictly increasing and distinct at Blender float32 precision')
            if labels != previous['labels']:
                raise ValueError('same-count rings require identical ordered correspondence labels')
            if area * validate_ring(previous['xz']) <= 0:
                raise ValueError('inconsistent winding')
            a, b = previous['xz'], section['xz']
            for i in range(len(a)):
                j = (i+1) % len(a)
                if sum((a[j][k]-a[i][k])*(b[j][k]-b[i][k]) for k in (0,1)) <= 0:
                    raise ValueError('correspondence rotates or reverses an edge by 90 degrees or more')
            validate_transition([[float32(v) for v in point] for point in a],
                                [[float32(v) for v in point] for point in b], 1 if area > 0 else -1)
        previous = section
    return spec


def check_paths(args):
    names = ['source', 'output', 'report'] + (['spec'] if args.spec is not None else [])
    for name in names:
        setattr(args, name, getattr(args, name).absolute())
    paths = [getattr(args, name).resolve() for name in names]
    if len(set(paths)) != len(names):
        raise ValueError('source, spec when supplied, output and report must be distinct paths')
    if args.source.suffix.lower() != '.blend' or args.output.suffix.lower() != '.blend':
        raise ValueError('source and output must use .blend suffix')
    if not args.source.is_file() or (args.spec is not None and not args.spec.is_file()):
        raise ValueError('source and spec must be existing files')
    for path in (args.output,args.report):
        if os.path.lexists(path):
            raise ValueError('refusing existing output: ' + str(path))
        if not path.parent.is_dir():
            raise ValueError('output parent directory must already exist')


def save_snapshot(args, report):
    import bpy
    # Same-filesystem staging + hard-link publication refuses even race-created targets.
    # No source save, no .blend1 sidecars, and no partial snapshot on validation failure.
    with tempfile.TemporaryDirectory(prefix='.reconstruct-', dir=args.output.parent) as tmp:
        staged = Path(tmp) / args.output.name
        bpy.context.preferences.filepaths.save_version = 0
        # Resolve dependencies relative to the source before moving the snapshot.
        # Keeping // paths unchanged would silently retarget textures/libraries.
        bpy.ops.file.make_paths_absolute()
        bpy.ops.wm.save_as_mainfile(filepath=str(staged), check_existing=False, relative_remap=False)
        report['lineage'].update(output=str(args.output), output_sha256=digest(staged))
        encoded = json.dumps(report, indent=2, allow_nan=False) + '\n'
        os.link(staged, args.output)
        report_created = False
        try:
            with args.report.open('x', encoding='utf8') as stream:
                report_created = True  # Own the path even if write/close fails.
                stream.write(encoded)
        except BaseException:
            args.output.unlink()
            if report_created:
                args.report.unlink()
            raise


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def build_loft(spec):
    import bpy
    import bmesh
    name = spec['object_name']
    if name in bpy.data.objects or name in bpy.data.meshes:
        raise ValueError('object/mesh name is already owned: ' + name)
    if spec['collection'] in bpy.data.collections:
        raise ValueError('collection name is already owned; use a new collection name')
    sections = spec['sections']
    n = len(sections[0]['xz'])
    vertices = [(float32(x), float32(s['y']), float32(z)) for s in sections for x, z in s['xz']]
    faces = [list(range(n))]
    for k in range(len(sections) - 1):
        for i in range(n):
            j = (i + 1) % n
            a, b = k * n + i, k * n + j
            faces.append([a, a + n, b + n, b])
    faces.append(list(reversed(range((len(sections) - 1) * n, len(vertices)))))
    area = sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(sections[0]['xz'], sections[0]['xz'][1:] + sections[0]['xz'][:1]))
    if area < 0:
        faces = [list(reversed(f)) for f in faces]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection = bpy.data.collections.get(spec['collection'])
    if collection is None:
        collection = bpy.data.collections.new(spec['collection'])
        bpy.context.scene.collection.children.link(collection)
    collection.objects.link(obj)
    obj['reconstruction_tool'] = 'reconstruct_vehicle.loft.v1'
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        volume = bm.calc_volume(signed=True)
    finally:
        bm.free()
    return {'vertices': len(vertices), 'faces': len(faces), 'volume': volume,
            'bounds': [[min(v[i] for v in vertices) for i in range(3)],
                       [max(v[i] for v in vertices) for i in range(3)]]}


def validate_camera_spec(spec, spec_path):
    import re
    keys(spec, ('schema_version', 'camera', 'photo', 'lens', 'landmarks', 'solver'))
    if type(spec['schema_version']) is not int or spec['schema_version'] != 1:
        raise ValueError('schema_version must be integer 1')
    text(spec['camera'], 'camera')
    photo = spec['photo']
    keys(photo, ('path', 'sha256', 'size'))
    if not isinstance(photo['path'], str) or not photo['path']:
        raise ValueError('photo path must be a nonempty string')
    path = Path(photo['path'])
    if not path.is_absolute():
        path = spec_path.parent / path
    path = path.resolve()
    if not path.is_file() or not isinstance(photo['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', photo['sha256']):
        raise ValueError('photo needs an existing path and lowercase 64-character SHA-256')
    if digest(path) != photo['sha256']:
        raise ValueError('photo SHA-256 mismatch')
    size = photo['size']
    if not isinstance(size, list) or len(size) != 2 or any(type(v) is not int or not 16 <= v <= 32768 for v in size):
        raise ValueError('photo size must be two integer dimensions in 16..32768')
    keys(spec['lens'], ('mode', 'millimeters'))
    if spec['lens']['mode'] != 'fixed':
        raise ValueError('only fixed lens fitting is supported; focal length is never optimized')
    number(spec['lens']['millimeters'], 'fixed lens millimeters', True)
    rows = spec['landmarks']
    if not isinstance(rows, list) or not 6 <= len(rows) <= 4096:
        raise ValueError('need at least 6 named 3D landmarks')
    names = set()
    roles = {'fit': 0, 'holdout': 0}
    for row in rows:
        keys(row, ('object', 'role', 'pixel'))
        text(row['object'], 'landmark object')
        if row['object'] in names:
            raise ValueError('duplicate landmark object')
        names.add(row['object'])
        if not isinstance(row['role'], str) or row['role'] not in roles:
            raise ValueError('landmark role must be fit or holdout')
        roles[row['role']] += 1
        pixel = row['pixel']
        if not isinstance(pixel, list) or len(pixel) != 2:
            raise ValueError('pixel requires [x, y] measured from photo top-left')
        for v, extent in zip(pixel, size):
            number(v, 'pixel coordinate')
            if not 0 <= v < extent:
                raise ValueError('observed pixel is outside the full photo')
    if roles['fit'] < 4 or roles['holdout'] < 2:
        raise ValueError('need at least 4 fit and 2 holdout landmarks')
    solver = spec['solver']
    keys(solver, ('max_iterations', 'fit_rms_limit_px', 'holdout_rms_limit_px'))
    if type(solver['max_iterations']) is not int or not 1 <= solver['max_iterations'] <= 500:
        raise ValueError('max_iterations must be integer 1..500')
    for key in ('fit_rms_limit_px', 'holdout_rms_limit_px'):
        number(solver[key], key, True)
    return path


def geometry_signature(camera):
    """Hash raw and evaluated meshes, other object transforms and visibility.

    Includes hidden datablocks: no special exemption for hidden alternatives.
    Not a substitute for runtime testing of simulations or external assets.
    """
    import bpy
    import numpy as np
    h = hashlib.sha256()
    graph = bpy.context.evaluated_depsgraph_get()
    def mesh_bytes(mesh):
        for collection, prop, width, dtype in ((mesh.vertices, 'co', 3, np.float32),
                (mesh.loops, 'vertex_index', 1, np.int32), (mesh.polygons, 'loop_total', 1, np.int32)):
            values = np.empty(len(collection)*width, dtype=dtype)
            collection.foreach_get(prop, values)
            h.update(values.tobytes())
    for mesh in sorted(bpy.data.meshes, key=lambda m: m.name):
        h.update(mesh.name.encode())
        mesh_bytes(mesh)
    for obj in sorted(bpy.data.objects, key=lambda o: o.name):
        if obj == camera:
            continue
        h.update(json.dumps([obj.name, obj.type, [list(r) for r in obj.matrix_world], obj.hide_render, obj.hide_viewport]).encode())
        if obj.name in bpy.context.scene.objects:
            evaluated = obj.evaluated_get(graph)
            h.update(json.dumps([list(r) for r in evaluated.matrix_world]).encode())
            if evaluated.type == 'MESH':
                mesh_bytes(evaluated.data)
    for instance in graph.object_instances:
        h.update(json.dumps([instance.object.original.name, list(instance.persistent_id), [list(r) for r in instance.matrix_world]]).encode() if instance.object.original != camera else b'')
    return h.hexdigest()


def fit_camera(spec, photo_path):
    import bpy
    import numpy as np
    from mathutils import Quaternion, Vector
    from bpy_extras.object_utils import world_to_camera_view
    scene = bpy.context.scene
    camera = scene.objects.get(spec['camera'])
    if camera is None or camera.type != 'CAMERA' or camera.data.type != 'PERSP':
        raise ValueError('exact named perspective camera must exist in the current scene')
    if camera.parent or camera.constraints or camera.animation_data or camera.data.animation_data or camera.library or camera.data.library:
        raise ValueError('camera must be local, unparented, unconstrained and unanimated (including drivers)')
    if any(abs(v-1) > 1e-6 for v in camera.scale) or camera.delta_location.length > 1e-8 or camera.delta_rotation_euler.to_quaternion().angle > 1e-6 or camera.delta_rotation_quaternion.angle > 1e-6 or any(abs(v-1)>1e-6 for v in camera.delta_scale):
        raise ValueError('camera requires unit scale and identity delta transforms')
    if abs(camera.data.lens-spec['lens']['millimeters']) > 1e-5:
        raise ValueError('fixed lens must match the existing camera lens')
    w, h = spec['photo']['size']
    if scene.render.resolution_percentage != 100 or [scene.render.resolution_x, scene.render.resolution_y] != [w,h] or scene.render.use_border or abs(scene.render.pixel_aspect_x/scene.render.pixel_aspect_y-1) > 1e-6:
        raise ValueError('scene must use full-photo resolution, 100 percent, square pixels and no render border')
    image = bpy.data.images.load(str(photo_path), check_existing=False)
    try:
        if list(image.size) != [w,h] or image.source != 'FILE':
            raise ValueError('actual photo dimensions do not match photo.size')
    finally:
        bpy.data.images.remove(image)
    bpy.context.view_layer.update()
    points = []
    for row in spec['landmarks']:
        obj = scene.objects.get(row['object'])
        if obj is None or obj == camera:
            raise ValueError('actual named landmark object not found: ' + row['object'])
        # Camera-dependent rigs would invalidate fixed-world correspondences.
        parent = obj.parent
        while parent:
            if parent == camera:
                raise ValueError('landmarks must not descend from fitted camera')
            parent = parent.parent
        if obj.constraints or obj.animation_data:
            raise ValueError('landmarks must be static and unconstrained')
        p = obj.matrix_world.translation.copy()
        if not all(math.isfinite(v) for v in p):
            raise ValueError('nonfinite landmark world position')
        points.append(p)
    worlds = np.array([list(p) for p in points], dtype=float)
    if len(np.unique(worlds, axis=0)) != len(points):
        raise ValueError('landmark objects must have distinct world positions')
    mask = np.array([row['role'] == 'fit' for row in spec['landmarks']])
    fit_worlds = worlds[mask]
    scale = float(np.linalg.norm(np.ptp(fit_worlds, axis=0)))
    singular = np.linalg.svd(fit_worlds-fit_worlds.mean(axis=0), compute_uv=False)
    if scale <= 1e-8 or singular[-1] < scale*1e-5:
        raise ValueError('fit landmarks must span a nondegenerate 3D volume, not a plane or line')
    geometry_before = geometry_signature(camera)
    initial_matrix = camera.matrix_world.copy()
    initial_mode = camera.rotation_mode
    q0 = initial_matrix.to_quaternion()
    position0 = np.array(list(initial_matrix.translation), dtype=float)
    observed = np.array([row['pixel'] for row in spec['landmarks']], dtype=float)
    p0 = np.zeros(6)
    p0[:3] = position0 / scale
    state = {'evaluations': 0}

    def project(parameters):
        state['evaluations'] += 1
        if not np.isfinite(parameters).all() or np.linalg.norm(parameters[:3]-p0[:3]) > 2 or np.linalg.norm(parameters[3:]) > math.pi/3:
            raise ValueError('local solver exceeded pose trust region; initialize camera closer')
        rotation = Vector(parameters[3:].tolist())
        angle = rotation.length
        delta = Quaternion(rotation.normalized(), angle) if angle > 1e-12 else Quaternion()
        camera.rotation_mode = 'QUATERNION'
        camera.rotation_quaternion = delta @ q0
        camera.location = (parameters[:3]*scale).tolist()
        bpy.context.view_layer.update()
        projected = []
        for point in points:
            p = world_to_camera_view(scene, camera, point)
            if not math.isfinite(p.z) or p.z <= camera.data.clip_start or p.z >= camera.data.clip_end:
                raise ValueError('landmark behind camera or outside camera depth clipping range')
            projected.append([p.x*w, (1-p.y)*h])
        arr = np.array(projected, dtype=float)
        if not np.isfinite(arr).all():
            raise ValueError('nonfinite Blender projection')
        return arr

    def residual(parameters):
        return (project(parameters)[mask]-observed[mask]).reshape(-1)

    try:
        p = p0.copy()
        initial_projection = project(p)
        r = (initial_projection[mask]-observed[mask]).reshape(-1)
        if float(np.sqrt(np.mean(r*r)*2)) > math.hypot(w,h)*.25:
            raise ValueError('initial camera mismatch exceeds 25 percent of photo diagonal; initialize closer')
        damping = 1e-3
        converged = False
        reason = 'iteration_limit'
        iterations = 0
        for iterations in range(1, spec['solver']['max_iterations']+1):
            columns = []
            for j in range(6):
                step = np.zeros(6)
                step[j] = 1e-3
                columns.append((residual(p+step)-residual(p-step))/(2e-3))
            jac = np.column_stack(columns)
            s = np.linalg.svd(jac, compute_uv=False)
            if s[-1] <= s[0]*1e-8:
                raise ValueError('pose Jacobian is rank deficient or ill-conditioned')
            gradient = jac.T @ r
            if float(np.max(np.abs(gradient)/np.maximum(np.linalg.norm(jac, axis=0),1e-12))) < 1e-3:
                converged = True
                reason = 'scaled_gradient_below_0.001_px'
                break
            normal = jac.T @ jac
            step = np.linalg.solve(normal + damping*np.diag(np.maximum(np.diag(normal),1e-12)), -gradient)
            # Limit individual LM steps; the entire local search is bounded above.
            length = np.linalg.norm(step)
            if length > .2:
                step *= .2/length
            try:
                candidate_r = residual(p+step)
            except ValueError:
                damping *= 10
                continue
            if float(candidate_r @ candidate_r) < float(r @ r):
                p += step
                r = candidate_r
                damping = max(1e-9, damping/3)
            else:
                damping *= 10
            if damping > 1e12:
                reason = 'damping_exhausted'
                break
        final_projection = project(p)
        errors = np.linalg.norm(final_projection-observed, axis=1)
        def stats(selection):
            e = errors[selection]
            return {'count': int(len(e)), 'rms_px': float(np.sqrt(np.mean(e*e))),
                    'mean_px': float(np.mean(e)), 'max_px': float(np.max(e))}
        fit_stats, holdout_stats = stats(mask), stats(~mask)
        report = {'status': 'converged' if converged else 'nonconverged',
                  'solver': {'method': 'local_damped_least_squares_actual_blender_projection',
                             'iterations': iterations, 'evaluations': state['evaluations'],
                             'converged': converged, 'stop_reason': reason,
                             'optimized_parameters': ['position_xyz', 'rotation_xyz'],
                             'holdouts_used_in_objective': False},
                  'camera': {'name': camera.name, 'lens_mm': camera.data.lens,
                             'initial_matrix_world': [list(row) for row in initial_matrix],
                             'final_matrix_world': [list(row) for row in camera.matrix_world]},
                  'photo': {'path': str(photo_path), 'sha256': spec['photo']['sha256'], 'size': [w,h]},
                  'evidence': {'kind': 'sparse_photo_reprojection_not_mesh_accuracy',
                               'limitation': 'A photo is not independently measured mesh ground truth. Sparse fitting cannot establish 95% model accuracy.'},
                  'acceptance': {'passed': converged and fit_stats['rms_px'] <= spec['solver']['fit_rms_limit_px'] and holdout_stats['rms_px'] <= spec['solver']['holdout_rms_limit_px'],
                                 'fit_rms_limit_px': spec['solver']['fit_rms_limit_px'],
                                 'holdout_rms_limit_px': spec['solver']['holdout_rms_limit_px']},
                  'reprojection': {'fit': fit_stats, 'holdout': holdout_stats,
                      'initial_fit_rms_px': float(np.sqrt(np.mean(np.sum((initial_projection[mask]-observed[mask])**2,axis=1)))),
                      'landmarks': [{'object': row['object'], 'role': row['role'], 'world': worlds[i].tolist(),
                                     'observed_pixel': observed[i].tolist(), 'projected_pixel': final_projection[i].tolist(),
                                     'error_px': float(errors[i])} for i,row in enumerate(spec['landmarks'])]}}
        if not converged:
            # Caller emits this machine-readable report, but never a fitted snapshot.
            raise FitFailure(report)
        # Preserve the camera's original representation, including Euler rigs without animation.
        matrix = camera.matrix_world.copy()
        camera.rotation_mode = initial_mode
        camera.matrix_world = matrix
        bpy.context.view_layer.update()
        geometry_after = geometry_signature(camera)
        if geometry_after != geometry_before:
            raise ValueError('camera fitting changed other transforms or raw/evaluated mesh geometry; camera-dependent scenes are unsupported')
        report['geometry_preservation'] = {'unchanged': True, 'before_sha256': geometry_before, 'after_sha256': geometry_after}
        return report
    except BaseException:
        camera.rotation_mode = initial_mode
        camera.matrix_world = initial_matrix
        bpy.context.view_layer.update()
        raise


class FitFailure(ValueError):
    def __init__(self, report):
        super().__init__('camera fit did not converge: ' + report['solver']['stop_reason'])
        self.report = report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('loft', 'fit-camera', 'prepare-source'):
        p = sub.add_parser(command)
        p.set_defaults(spec=None)
        for arg in ('source', 'output', 'report') + (() if command == 'prepare-source' else ('spec',)):
            p.add_argument('--' + arg, required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        import bpy
        bpy.context.preferences.filepaths.use_scripts_auto_execute = False
        check_paths(args)
        spec = json.loads(args.spec.read_text()) if args.spec is not None else None
        if args.command == 'loft':
            validate_loft(spec)
            photo_path = None
        elif args.command == 'fit-camera':
            photo_path = validate_camera_spec(spec, args.spec)
            if photo_path in (args.source.resolve(), args.spec.resolve(), args.output.resolve(), args.report.resolve()):
                raise ValueError('photo must be distinct from source/spec/output/report')
        lineage = {'source': str(args.source.resolve()), 'source_sha256': digest(args.source),
                   'blender_version': bpy.app.version_string}
        if args.spec is not None:
            lineage.update(spec=str(args.spec.resolve()), spec_sha256=digest(args.spec))
        bpy.ops.wm.open_mainfile(filepath=str(args.source.resolve()), use_scripts=False)
        report = {'schema_version': 1, 'command': args.command, 'lineage': lineage}
        if args.command == 'loft':
            report.update(status='built', mesh=build_loft(spec))
        elif args.command == 'fit-camera':
            report.update(fit_camera(spec, photo_path))
        else:
            before = geometry_signature(None)
            bpy.ops.file.make_paths_absolute()
            paths = bpy.utils.blend_paths(absolute=False)
            if any(path.startswith('//') for path in paths):
                raise ValueError('unresolved relative dependencies; prepare linked libraries at their own origin')
            if geometry_signature(None) != before:
                raise ValueError('source preparation changed geometry or object transforms')
            report.update(status='prepared', dependency_paths_absolute=True,
                          external_paths=paths,
                          geometry_preservation={'unchanged': True, 'before_sha256': before, 'after_sha256': before},
                          limitation='Absolute paths preserve dependency targets; assets are not copied and availability/portability is not certified.')
        if digest(args.source) != lineage['source_sha256']:
            raise ValueError('source changed during operation; refusing publication')
        save_snapshot(args, report)
        return 3 if args.command == 'fit-camera' and not report['acceptance']['passed'] else 0
    except FitFailure as exc:
        diagnostic = {'schema_version': 1, 'command': args.command, 'lineage': lineage, **exc.report}
        try:
            with args.report.open('x', encoding='utf8') as stream:
                stream.write(json.dumps(diagnostic, indent=2, allow_nan=False) + '\n')
        except OSError as write_error:
            print(json.dumps({'status': 'error', 'error': str(write_error)}), file=sys.stderr)
        print(json.dumps({'status': 'nonconverged', 'error': str(exc)}), file=sys.stderr)
        return 2
    except (ValueError, KeyError, OSError, RuntimeError, ImportError) as exc:
        print(json.dumps({'status': 'error', 'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    cli = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    raise SystemExit(main(cli))
