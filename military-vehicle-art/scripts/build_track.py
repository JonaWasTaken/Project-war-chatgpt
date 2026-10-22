"""Static, shared-mesh track belts from a prepared existing Blender master."""
import argparse
import bisect
import json
import math
from pathlib import Path
import sys
from copy import deepcopy

# Blender --python does not consistently add the script directory to sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reconstruct_vehicle import check_paths, digest, float32, keys, number, save_snapshot, text


def _polygon(points):
    """Validate a simple polygon, allowing concavity and forward-collinear edges."""
    if not isinstance(points, list) or not 4 <= len(points) <= 1024:
        raise ValueError('path needs 4..1024 vertices, without duplicate closure')
    for p in points:
        if not isinstance(p, list) or len(p) != 2:
            raise ValueError('each path vertex must be a [Y, Z] pair')
        for v in p:
            number(v, 'path coordinate')
    span = max(max(p[k] for p in points)-min(p[k] for p in points) for k in (0, 1))
    if span <= 0:
        raise ValueError('zero path extent')
    q = [[(p[k]-points[0][k])/span for k in (0, 1)] for p in points]
    eps = 1e-10
    def cross(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    def on(a, b, c):
        return all(min(a[k], b[k])-eps <= c[k] <= max(a[k], b[k])+eps for k in (0, 1))
    n = len(q)
    for i, a in enumerate(q):
        b, previous = q[(i+1) % n], q[i-1]
        if math.dist(a, b) <= eps:
            raise ValueError('zero, duplicate, or numerically collapsed path edge')
        u, v = [a[k]-previous[k] for k in (0, 1)], [b[k]-a[k] for k in (0, 1)]
        if abs(cross(previous, a, b)) <= eps and sum(u[k]*v[k] for k in (0, 1)) <= 0:
            raise ValueError('backtracking or reversing adjacent path edges')
        for j in range(i+1, n):
            if j in ((i+1) % n, (i-1) % n):
                continue
            c, d = q[j], q[(j+1) % n]
            values = cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
            x, y, z, w = values
            if ((x > eps and y < -eps or x < -eps and y > eps) and
                (z > eps and w < -eps or z < -eps and w > eps)) or any(
                    abs(t) <= eps and on(e, f, g) for t, e, f, g in
                    ((x, a, b, c), (y, a, b, d), (z, c, d, a), (w, c, d, b))):
                raise ValueError('self-crossing, touching, or overlapping path')
    area = sum(q[i][0]*q[(i+1) % n][1]-q[(i+1) % n][0]*q[i][1] for i in range(n))
    if abs(area) <= eps:
        raise ValueError('zero or numerically degenerate path area')
    return 1 if area > 0 else -1


def validate_spec(spec):
    keys(spec, ('schema_version', 'master', 'collection', 'prefix', 'path', 'count', 'phase'),
         ('requested_pitch', 'max_pitch_error'))
    if type(spec['schema_version']) is not int or spec['schema_version'] != 1:
        raise ValueError('schema_version must be integer 1')
    keys(spec['master'], ('object', 'approved', 'approval_note'))
    text(spec['master']['object'], 'master object')
    if spec['master']['approved'] is not True or not isinstance(spec['master']['approval_note'], str) or not spec['master']['approval_note'].strip():
        raise ValueError('master needs explicit approved:true and a nonempty approval_note')
    text(spec['collection'], 'collection')
    text(spec['prefix'], 'prefix')
    if len((spec['prefix']+'_00000').encode('utf8')) > 63:
        raise ValueError('prefix plus generated suffix must fit 63 UTF-8 bytes')
    if type(spec['count']) is not int or not 4 <= spec['count'] <= 10000:
        raise ValueError('count must be an integer in 4..10000')
    if not 0 <= number(spec['phase'], 'phase') < 1:
        raise ValueError('phase must be in [0, 1), as a fraction of one pitch')
    keys(spec['path'], ('x', 'yz'))
    number(spec['path']['x'], 'constant world X')
    winding = _polygon(spec['path']['yz'])
    result = deepcopy(spec)
    result['path'] = {'x': float32(spec['path']['x']),
                      'yz': [[float32(v) for v in p] for p in spec['path']['yz']]}
    if _polygon(result['path']['yz']) != winding:
        raise ValueError('winding changes at Blender float32 precision')
    if ('requested_pitch' in spec) != ('max_pitch_error' in spec):
        raise ValueError('requested_pitch requires explicit max_pitch_error and vice versa')
    if 'requested_pitch' in spec:
        number(spec['requested_pitch'], 'requested_pitch', positive=True)
        if number(spec['max_pitch_error'], 'max_pitch_error') < 0:
            raise ValueError('max_pitch_error must be nonnegative')
        p = result['path']['yz']
        pitch = sum(math.dist(p[i], p[(i+1) % len(p)]) for i in range(len(p)))/spec['count']
        if abs(pitch-spec['requested_pitch']) > spec['max_pitch_error']:
            raise ValueError('actual arclength pitch exceeds max_pitch_error')
    return result


def _unit(v):
    length = math.hypot(*v)
    if length <= 1e-12:
        raise ValueError('undefined tangent at a reversing corner')
    return [x / length for x in v]


def validate_master(name):
    """Inspect actual local mesh coordinates; never apply or alter the source."""
    import bpy
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != 'MESH':
        raise ValueError('master must name an existing mesh object')
    if (obj.library or obj.override_library or obj.data.library or obj.data.override_library or
        obj.parent or obj.modifiers or obj.constraints or obj.animation_data or obj.data.animation_data or
        obj.data.shape_keys or obj.vertex_groups or obj.instance_type != 'NONE' or obj.mode != 'OBJECT' or
        obj.rigid_body or obj.rigid_body_constraint):
        raise ValueError('master has unsupported library, rig, deformation, modifier, or instancing state; prepare a separate approved mesh')
    bpy.context.view_layer.update()
    if any(not math.isfinite(v) for row in obj.matrix_world for v in row):
        raise ValueError('master transform is nonfinite')
    if (any(abs(obj.scale[k]-1) > 1e-6 or abs(obj.delta_scale[k]-1) > 1e-6 or
            abs(obj.delta_location[k]) > 1e-6 for k in range(3)) or
        any(abs(obj.matrix_basis[i][j]-(1 if i == j else 0)) > 1e-6 for i in range(3) for j in range(3))):
        raise ValueError('prepared master requires unit positive object/delta scale, identity rotation, and zero delta location')
    rotation = (list(obj.rotation_quaternion)[1:] + [abs(obj.rotation_quaternion.w)-1]
                if obj.rotation_mode == 'QUATERNION' else
                [obj.rotation_axis_angle[0]] if obj.rotation_mode == 'AXIS_ANGLE' else list(obj.rotation_euler))
    if (any(abs(v) > 1e-6 for v in rotation) or
        any(abs(v) > 1e-6 for v in obj.delta_rotation_euler) or
        any(abs(v) > 1e-6 for v in list(obj.delta_rotation_quaternion)[1:]) or
        abs(abs(obj.delta_rotation_quaternion.w)-1) > 1e-6):
        raise ValueError('prepared master requires identity rotation channels, including delta rotations')
    coords = [tuple(v.co) for v in obj.data.vertices]
    if not coords or not obj.data.polygons or any(not math.isfinite(x) for p in coords for x in p):
        raise ValueError('master needs nonempty polygon mesh with finite local vertices')
    low = [min(p[k] for p in coords) for k in range(3)]
    high = [max(p[k] for p in coords) for k in range(3)]
    extent = [high[k]-low[k] for k in range(3)]
    span = max(extent)
    if span <= 0 or min(extent) <= span*1e-8:
        raise ValueError('master needs actual nonzero width, tangent length, and thickness')
    if any(abs((low[k]+high[k])/2) > span*1e-6 for k in range(3)):
        raise ValueError('master local bounding-box center must coincide with its origin')
    return obj, {'object': obj.name, 'mesh': obj.data.name, 'local_bounds': [low, high],
                 'local_extents': extent, 'tangent_length': extent[1],
                 'vertices': len(coords), 'faces': len(obj.data.polygons)}


def build_track(spec):
    import bpy
    from mathutils import Matrix
    spec = validate_spec(spec)
    master, master_info = validate_master(spec['master']['object'])
    names = [f"{spec['prefix']}_{index:05d}" for index in range(spec['count'])]
    if spec['collection'] in bpy.data.collections:
        raise ValueError('collection name is already owned; choose a fresh collection')
    if any(name in bpy.data.objects for name in names):
        raise ValueError('generated link name is already owned; choose a fresh prefix')
    points = spec['path']['yz']
    n = len(points)
    edges = [[points[(i+1) % n][k] - points[i][k] for k in (0, 1)] for i in range(n)]
    lengths = [math.hypot(*edge) for edge in edges]
    directions = [_unit(edge) for edge in edges]
    corner_tangents = [_unit([directions[i-1][k] + directions[i][k] for k in (0, 1)]) for i in range(n)]
    cumulative = [0.0]
    for length in lengths:
        cumulative.append(cumulative[-1] + length)
    perimeter = cumulative[-1]
    pitch = perimeter / spec['count']
    winding = _polygon(points)
    report = {'schema_version': 1, 'tool': 'build_track.v1', 'blender_version': bpy.app.version_string,
              'collection': spec['collection'], 'count': spec['count'], 'phase': spec['phase'],
              'effective_path': spec['path'], 'winding': 'CCW' if winding > 0 else 'CW',
              'master': master_info | {'approval_note': spec['master']['approval_note']},
              'path_length': perimeter, 'actual_pitch': pitch, 'closure_arclength_spacing': pitch, 'links': [],
              'requested_pitch': spec.get('requested_pitch'), 'max_pitch_error': spec.get('max_pitch_error'),
              'pitch_error': abs(pitch-spec['requested_pitch']) if 'requested_pitch' in spec else None,
              'limitations': 'Static repeated geometry; not a collision test; not hinge closure, a rig, animation, or export readiness.'}
    def sample(distance):
        distance %= perimeter
        segment = min(bisect.bisect_right(cumulative, distance)-1, n-1)
        fraction = (distance-cumulative[segment]) / lengths[segment]
        position = [points[segment][k]+fraction*edges[segment][k] for k in (0,1)]
        return segment, fraction, position
    samples = [sample((index+spec['phase'])*pitch) for index in range(spec['count'])]
    report['orientation_method'] = 'centered_neighbor_chord'
    matrices = []
    for index in range(spec['count']):
        distance = ((index + spec['phase']) * pitch) % perimeter
        segment, fraction, yz = samples[index]
        p = [spec['path']['x']] + yz
        previous, following = samples[index-1][2], samples[(index+1)%spec['count']][2]
        # Local smoothing over neighboring LINKS, not the full segment length:
        # long straight runs stay tangent-flat instead of tilting toward remote corners.
        t = _unit([following[k]-previous[k] for k in (0,1)])
        tangent = [0, t[0], t[1]]
        normal = [0, winding*t[1], -winding*t[0]]
        width = [-winding, 0, 0]
        matrix = Matrix(((width[0], tangent[0], normal[0], p[0]),
                         (width[1], tangent[1], normal[1], p[1]),
                         (width[2], tangent[2], normal[2], p[2]),
                         (0, 0, 0, 1)))
        matrices.append(matrix)
        report['links'].append({'name': names[index], 'position': list(matrix.translation),
                                'tangent': list(matrix.col[1][:3]), 'normal': list(matrix.col[2][:3]),
                                'width': width, 'frame': [list(row) for row in matrix],
                                'arclength': distance, 'segment': segment, 'segment_fraction': fraction,
                                'segment_tangent': [0] + directions[segment]})
    positions = [item['position'] for item in report['links']]
    chords = [math.dist(positions[i], positions[(i+1) % len(positions)]) for i in range(len(positions))]
    if len({tuple(p) for p in positions}) != len(positions) or min(chords) <= 0:
        raise ValueError('link centers collapse at Blender float32 precision; move/re-scale the working asset')
    for matrix in matrices:
        if not .99999 <= matrix.determinant() <= 1.00001 or any(not math.isfinite(x) for row in matrix for x in row):
            raise ValueError('invalid Blender float32 frame')
        # Three centered extent-axis probes catch catastrophic world-coordinate
        # rounding without scanning every high-detail vertex for every instance.
        probes = []
        for axis, extent in enumerate(master_info['local_extents']):
            ends = [[float32(matrix[k][3]+sign*matrix[k][axis]*extent/2) for k in range(3)] for sign in (-1, 1)]
            probes.append([(ends[1][k]-ends[0][k])/extent for k in range(3)])
        a, b, c = probes
        probe_det = (a[0]*(b[1]*c[2]-b[2]*c[1])-b[0]*(a[1]*c[2]-a[2]*c[1])+c[0]*(a[1]*b[2]-a[2]*b[1]))
        if probe_det <= 1e-6:
            raise ValueError('transformed master extent axes collapse at world float32 precision; recenter/re-scale the working scene')
    turns = [math.degrees(math.atan2(directions[i-1][0]*directions[i][1]-directions[i-1][1]*directions[i][0],
                                     sum(directions[i-1][k]*directions[i][k] for k in (0, 1)))) for i in range(n)]
    link_length = master_info['tangent_length']
    report['neighbor_chord_distances'] = chords
    report['closure_center_spacing'] = chords[-1]
    report['diagnostics'] = {'minimum_neighbor_chord': min(chords),
                             'min_neighbor_chord_over_link_length': min(chords)/link_length,
                             'pitch_over_link_length': pitch/link_length,
                             'corner_turn_degrees': turns, 'corner_warning_threshold_degrees': 15}
    warnings = ['No exact collision/clearance or mechanical hinge-closure guarantee; inspect the assembled geometry.']
    if link_length > min(chords):
        warnings.append('Master link length exceeds minimum neighbor center chord: possible overlap at bends; this is only a geometric diagnostic.')
    if link_length > pitch:
        warnings.append('Master link length exceeds arclength pitch: possible overlap even along straight runs.')
    if any(abs(turn) > 15 for turn in turns):
        warnings.append('Path corner turn exceeds 15 degrees: inspect gaps, overlap, wheel fit, and the smoothed frame alignment.')
    report['warnings'] = warnings
    collection = bpy.data.collections.new(spec['collection'])
    bpy.context.scene.collection.children.link(collection)
    created = []
    try:
        for name, matrix in zip(names, matrices):
            obj = bpy.data.objects.new(name, master.data)
            created.append(obj)
            collection.objects.link(obj)
            # Keep object-scoped materials produced by build_pbr without altering
            # shared mesh slots, the master, or any unselected mesh user.
            for index, slot in enumerate(master.material_slots):
                if slot.link == 'OBJECT':
                    obj.material_slots[index].link = 'OBJECT'
                    obj.material_slots[index].material = slot.material
            obj.matrix_world = matrix
            obj['track_builder'] = 'build_track.v1'
        bpy.context.view_layer.update()
        for entry, obj in zip(report['links'], created):
            entry.update(frame=[list(row) for row in obj.matrix_world],
                         tangent=list(obj.matrix_world.col[1][:3]), normal=list(obj.matrix_world.col[2][:3]),
                         width=list(obj.matrix_world.col[0][:3]))
    except BaseException:
        for obj in created:
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(collection)
        raise
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('source', 'spec', 'output', 'report'):
        parser.add_argument('--'+flag, required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        check_paths(args)
        source_hash, spec_hash = digest(args.source), digest(args.spec)
        spec = json.loads(args.spec.read_text(encoding='utf8'))
        validate_spec(spec)
        import bpy
        bpy.context.preferences.filepaths.use_scripts_auto_execute = False
        bpy.ops.wm.open_mainfile(filepath=str(args.source), load_ui=False, use_scripts=False)
        # Resolve // targets while the active filepath is still the original source.
        bpy.ops.file.make_paths_absolute()
        report = build_track(spec)
        report['lineage'] = {'source': str(args.source), 'source_sha256': source_hash,
                             'spec': str(args.spec), 'spec_sha256': spec_hash}
        if digest(args.source) != source_hash or digest(args.spec) != spec_hash:
            raise ValueError('source or spec changed during the build; refusing publication')
        save_snapshot(args, report)
        print(json.dumps({'output': str(args.output), 'report': str(args.report),
                          'count': report['count'], 'actual_pitch': report['actual_pitch'],
                          'warnings': report['warnings']}, allow_nan=False))
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print('build_track: '+str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    arguments = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]
    raise SystemExit(main(arguments))
