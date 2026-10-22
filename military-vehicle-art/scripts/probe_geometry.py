#!/usr/bin/env python3
"""Read-only, evaluated-mesh measurements. See references/geometry-probes.md."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

LIMITATIONS = [
    'Diagnostics only: no artistic/reference correctness, collision proof, minimum-wall or engineering certification.',
    'Explicit scene/view-layer/frame; evaluated viewport mesh, not render-time displacement or arbitrary instances.',
    'Bounds are extrema of evaluated vertices in the specified rigid measurement frame, not semantic shape dimensions.',
    'SI conversion uses source scene scale_length. Reference/design evidence is declared, not authenticated.',
    'Dependencies outside the source/spec are not fingerprinted; Blender evaluation and rays have floating-point limits.',
    'Rays cover only specified seeds/directions/ranges and named meshes; misses are not zero gaps or clearance proofs.',
    'Successive oriented intersections are directional wall/chord samples, not minimum walls or verified closed solids.',
    'Caller epsilon advances past a hit and can skip thinner features; normals follow transformed triangle winding.',
]
MAX_CHECKS = 128
MAX_OBJECTS = 128
MAX_VERTICES = 2000000
MAX_TRIANGLES = 4000000
MAX_SAMPLES = 4096
MAX_SPEC_BYTES = 1048576


def require(ok, message):
    if not ok:
        raise ValueError(message)


def fields(value, required, optional=()):
    require(isinstance(value, dict) and set(required) <= set(value) <= set(required) | set(optional),
            'Expected exactly required fields ' + ', '.join(sorted(required)) +
            ('; optional: ' + ', '.join(sorted(optional)) if optional else ''))


def text(value, label):
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= 4096 and '\x00' not in value,
            label + ' must be a nonempty exact string (max 4096 characters)')
    return value


def number(value, label, minimum=None, positive=False):
    require(type(value) in (int,float), label + ' must be a finite number, not boolean')
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError(label + ' is outside finite numeric range') from exc
    require(math.isfinite(value), label + ' must be finite')
    require(minimum is None or value >= minimum, label + ' is below allowed minimum')
    require(not positive or value > 0, label + ' must be positive')
    return value


def vector(value, label):
    require(isinstance(value, list) and len(value) == 3, label + ' requires three numbers')
    return [number(v,label) for v in value]


def basis(value):
    fields(value, {'kind','note','sha256'})
    require(value['kind'] in ('reference','design_brief'), 'basis.kind must be reference or design_brief')
    text(value['note'], 'basis.note')
    require(isinstance(value['sha256'],str) and re.fullmatch('[0-9a-f]{64}',value['sha256']) is not None,
            'basis.sha256 must fingerprint the actual reference or original design brief')


def validate_frame(value):
    require(isinstance(value,dict), 'frame must be explicit')
    if value.get('kind') == 'world':
        fields(value, {'kind'})
    else:
        fields(value, {'kind','object'})
        require(value['kind'] == 'object', 'frame.kind must be world or object')
        text(value['object'],'frame.object')


def validate_spec(spec):
    fields(spec, {'schema_version','scene','view_layer','evaluation_frame','units','checks'})
    require(type(spec['schema_version']) is int and spec['schema_version'] == 1, 'schema_version must be integer 1')
    text(spec['scene'],'scene')
    text(spec['view_layer'],'view_layer')
    require(type(spec['evaluation_frame']) is int and -1000000 <= spec['evaluation_frame'] <= 1000000,
            'evaluation_frame must be an integer in -1000000..1000000')
    require(spec['units'] == 'm', 'units must be m (all lengths are SI metres)')
    checks = spec['checks']
    require(isinstance(checks,list) and 1 <= len(checks) <= MAX_CHECKS, 'checks must contain 1..128 records')
    ids = set()
    sample_count = 0
    for check in checks:
        require(isinstance(check,dict),'check must be an object')
        kind = check.get('type')
        extras = {'dimensions':{'objects'}, 'datum':{'landmark','axis'},
                  'clearance':{'from_object','to_object','samples','max_distance_m','epsilon_m'},
                  'thickness':{'object','samples','max_distance_m','epsilon_m'}}
        require(isinstance(kind,str) and kind in extras,'unsupported check type')
        required = {'id','type','frame'} | extras[kind]
        fields(check, required, {'target'})
        text(check['id'],'check.id')
        require(check['id'] not in ids,'check IDs must be unique')
        ids.add(check['id'])
        validate_frame(check['frame'])
        if kind == 'dimensions':
            names = check['objects']
            require(isinstance(names,list) and 1 <= len(names) <= MAX_OBJECTS, 'objects must contain 1..128 names')
            for name in names:
                text(name,'object name')
            require(len(set(names)) == len(names),'duplicate object names')
        elif kind == 'datum':
            landmark = check['landmark']
            require(isinstance(landmark,dict),'landmark must select an actual object point')
            fields(landmark, {'object','point'}, {'index'} if landmark.get('point') == 'vertex' else ())
            text(landmark['object'],'landmark.object')
            require(landmark['point'] in ('origin','vertex'),'landmark.point must be origin or evaluated vertex')
            if landmark['point'] == 'vertex':
                require(type(landmark.get('index')) is int and 0 <= landmark['index'] < MAX_VERTICES,
                        'vertex index must be a nonnegative integer within workload bounds')
            require(check['axis'] in ('X','Y','Z'),'axis must be X, Y or Z (positive local object axis)')
        else:
            if kind == 'clearance':
                text(check['from_object'],'from_object')
                text(check['to_object'],'to_object')
                require(check['from_object'] != check['to_object'],'clearance requires two distinct objects')
            else:
                text(check['object'],'object')
            maximum = number(check['max_distance_m'],'max_distance_m',positive=True)
            epsilon = number(check['epsilon_m'],'epsilon_m',positive=True)
            require(epsilon < maximum,'epsilon_m must be smaller than max_distance_m')
            samples = check['samples']
            require(isinstance(samples,list) and 1 <= len(samples) <= MAX_SAMPLES,'samples must contain 1..4096 records')
            sample_count += len(samples)
            require(sample_count <= MAX_SAMPLES,'total sample workload must not exceed 4096')
            sample_ids = set()
            for sample in samples:
                fields(sample, {'id','origin_m','direction'})
                text(sample['id'],'sample.id')
                require(sample['id'] not in sample_ids,'sample IDs must be unique within a check')
                sample_ids.add(sample['id'])
                vector(sample['origin_m'],'origin_m')
                require(math.hypot(*vector(sample['direction'],'direction')) > 0,'ray direction must be nonzero')
        if 'target' in check:
            target = check['target']
            if kind == 'dimensions':
                fields(target, {'dimensions_m','tolerance_m','basis'})
                require(all(v > 0 for v in vector(target['dimensions_m'],'dimensions_m')), 'target dimensions must be positive')
                require(all(v >= 0 for v in vector(target['tolerance_m'],'tolerance_m')), 'tolerances must be nonnegative')
            elif kind == 'datum':
                fields(target, {'position_m','position_tolerance_m','direction','angle_tolerance_deg','basis'})
                vector(target['position_m'],'position_m')
                number(target['position_tolerance_m'],'position_tolerance_m',0)
                require(math.hypot(*vector(target['direction'],'direction')) > 0,'target direction must be nonzero')
                require(number(target['angle_tolerance_deg'],'angle_tolerance_deg',0) <= 180,'angle tolerance must be <= 180 degrees')
            else:
                scalar = 'gap_m' if kind == 'clearance' else 'thickness_m'
                fields(target, {scalar,'tolerance_m','basis'})
                number(target[scalar],scalar,0)
                number(target['tolerance_m'],'tolerance_m',0)
            basis(target['basis'])
    return spec


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):
            h.update(block)
    return h.hexdigest()


def read_spec(path):
    def unique(pairs):
        result = {}
        for key,value in pairs:
            require(key not in result,'duplicate JSON field: ' + key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('nonfinite JSON token: ' + value)
    return validate_spec(json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=unique,parse_constant=invalid))


def exact_object(name, scene, layer):
    import bpy
    matches = [obj for obj in bpy.data.objects if obj.name == name]
    require(len(matches) == 1, 'missing or ambiguous exact object name: ' + name)
    obj = matches[0]
    require(obj.name in scene.objects and obj.name in layer.objects, 'object outside evaluated scene/view-layer: ' + name)
    require(obj.visible_get(view_layer=layer) and not obj.hide_viewport,
            'hidden/excluded object is outside supported viewport evaluation scope: ' + name)
    require(obj.instance_type == 'NONE' and not obj.is_instancer, 'instances are unsupported: ' + name)
    require(not any(m.type == 'NODES' for m in obj.modifiers),
            'Geometry Nodes (including unrealized instances) require an explicit mesh snapshot: ' + name)
    parent = obj.parent
    while parent is not None:
        require(parent.instance_type == 'NONE' and not parent.is_instancer,
                'child of an instancer requires an explicit mesh snapshot: ' + name)
        parent = parent.parent
    return obj


def finite_matrix(matrix):
    require(all(math.isfinite(v) for row in matrix for v in row), 'nonfinite evaluated transform')


def measurement_frame(spec, scene, layer, graph):
    from mathutils import Matrix
    if spec['kind'] == 'world':
        return Matrix.Identity(4)
    obj = exact_object(spec['object'],scene,layer)
    matrix = obj.evaluated_get(graph).matrix_world.copy()
    finite_matrix(matrix)
    rotation = matrix.to_3x3()
    # Float roundoff guard only, not an asset accuracy tolerance.
    require(all(abs(rotation.col[i].length-1) <= 1e-6 for i in range(3)) and
            all(abs(rotation.col[i].dot(rotation.col[j])) <= 1e-6 for i in range(3) for j in range(i)) and
            abs(rotation.determinant()-1) <= 1e-6, 'measurement frame must be rigid, unit-scale, right-handed')
    return matrix


def evaluated_geometry(obj, graph, budget):
    require(obj.type == 'MESH','mesh object required: ' + obj.name)
    evaluated = obj.evaluated_get(graph)
    matrix = evaluated.matrix_world.copy()
    finite_matrix(matrix)
    mesh = evaluated.to_mesh(preserve_all_data_layers=False,depsgraph=graph)
    try:
        require(mesh is not None and 0 < len(mesh.vertices) <= MAX_VERTICES, 'empty or excessive evaluated mesh: ' + obj.name)
        mesh.calc_loop_triangles()
        require(len(mesh.loop_triangles) <= MAX_TRIANGLES,'evaluated triangle workload exceeded')
        budget['vertices'] += len(mesh.vertices)
        budget['triangles'] += len(mesh.loop_triangles)
        require(budget['vertices'] <= MAX_VERTICES and budget['triangles'] <= MAX_TRIANGLES,
                'global evaluated mesh workload exceeded')
        vertices = [matrix @ v.co for v in mesh.vertices]
        require(all(math.isfinite(v) for p in vertices for v in p),'nonfinite evaluated mesh coordinates')
        return vertices, [tuple(t.vertices) for t in mesh.loop_triangles]
    finally:
        evaluated.to_mesh_clear()


def evaluated_vertices(obj, graph, budget):
    return evaluated_geometry(obj,graph,budget)[0]


def compare_vector(actual, desired, tolerance):
    errors = [abs(a-b) for a,b in zip(actual,desired)]
    return {'error_m':errors,'within_tolerance':all(e <= t for e,t in zip(errors,tolerance))}


def unit_direction(value):
    from mathutils import Vector
    length = math.hypot(*value)
    require(math.isfinite(length) and length > 0,'direction must have finite nonzero length')
    return Vector([v/length for v in value])


def datum_measurement(check, scene, layer, graph, inverse, scale, budget):
    from mathutils import Vector
    landmark = check['landmark']
    obj = exact_object(landmark['object'],scene,layer)
    matrix = obj.evaluated_get(graph).matrix_world
    finite_matrix(matrix)
    if landmark['point'] == 'origin':
        position = matrix.translation
    else:
        vertices = evaluated_vertices(obj,graph,budget)
        require(landmark['index'] < len(vertices),'landmark index outside evaluated vertex array')
        position = vertices[landmark['index']]
    position = inverse @ position * scale
    axis = Vector(tuple(1 if i == 'XYZ'.index(check['axis']) else 0 for i in range(3)))
    direction = unit_direction(inverse.to_3x3() @ matrix.to_3x3() @ axis)
    require(all(math.isfinite(v) for v in position),'nonfinite datum position')
    row = {'landmark':landmark,'axis':check['axis'],'position_m':list(position),'direction':list(direction),'status':'measured'}
    if 'target' in check:
        target = check['target']
        error = math.dist(position,target['position_m'])
        wanted = unit_direction(target['direction'])
        # atan2 avoids acos instability near an aligned axis.
        angle = math.degrees(math.atan2(direction.cross(wanted).length,direction.dot(wanted)))
        row['target'] = target
        row['comparison'] = {'position_error_m':error,'angle_error_deg':angle,
                             'within_tolerance':error <= target['position_tolerance_m'] and angle <= target['angle_tolerance_deg']}
        row['status'] = 'within-tolerances' if row['comparison']['within_tolerance'] else 'needs-correction'
    return row


def probe_tree(name, scene, layer, graph, inverse, scale, budget):
    from mathutils.bvhtree import BVHTree
    obj = exact_object(name,scene,layer)
    vertices, triangles = evaluated_geometry(obj,graph,budget)
    require(triangles,'ray probes require evaluated surface triangles: ' + name)
    points = [inverse @ p * scale for p in vertices]
    require(all(math.isfinite(v) for p in points for v in p),'nonfinite probe coordinates')
    return BVHTree.FromPolygons(points,triangles,all_triangles=True,epsilon=0.0)


def ray_hit(tree, origin, direction, maximum, offset=0.0):
    from ctypes import c_float
    require(all(math.isfinite(v) for v in (*origin,*direction)) and math.isfinite(c_float(maximum).value),
            'ray origin/direction/range overflows Blender float precision')
    if maximum <= 0:
        return None
    position, normal, index, distance = tree.ray_cast(origin,direction,maximum)
    if position is None:
        return None
    require(all(math.isfinite(v) for v in (*position,*normal,distance)),'nonfinite ray result')
    return {'position_m':list(position),'normal':list(normal),'evaluated_triangle_index':index,
            'distance_from_origin_m':distance+offset,'normal_dot_direction':normal.dot(direction)}


def ray_measurement(check, scene, layer, graph, inverse, scale, budget):
    from ctypes import c_float
    from mathutils import Vector
    clearance = check['type'] == 'clearance'
    source = probe_tree(check['from_object'] if clearance else check['object'],scene,layer,graph,inverse,scale,budget)
    target = probe_tree(check['to_object'],scene,layer,graph,inverse,scale,budget) if clearance else source
    first_key,second_key,scalar = ('from_hit','to_hit','gap_m') if clearance else ('entry_hit','exit_hit','thickness_m')
    first_miss,second_miss = ('from-miss','to-miss') if clearance else ('entry-miss','exit-miss')
    maximum, epsilon = check['max_distance_m'],check['epsilon_m']
    require(math.isfinite(c_float(maximum).value) and c_float(epsilon).value > 0,
            'ray range/epsilon is not representable at Blender float precision')
    rows = []
    for sample in check['samples']:
        origin, direction = Vector(sample['origin_m']),unit_direction(sample['direction'])
        first = ray_hit(source,origin,direction,maximum)
        row = {**sample,'direction':list(direction),first_key:first,second_key:None,scalar:None,'status':first_miss}
        if first is not None:
            offset = first['distance_from_origin_m']+epsilon
            second = ray_hit(target,Vector(first['position_m'])+direction*epsilon,direction,maximum-offset,offset)
            row[second_key] = second
            row['status'] = second_miss
            if second is not None:
                row[scalar] = (Vector(second['position_m'])-Vector(first['position_m'])).dot(direction)
                oriented = (first['normal_dot_direction'] > 0 and second['normal_dot_direction'] < 0) if clearance else (first['normal_dot_direction'] < 0 and second['normal_dot_direction'] > 0)
                row['status'] = 'measured' if oriented else 'orientation-inconsistent'
                if clearance:
                    rehit = ray_hit(source,Vector(first['position_m'])+direction*epsilon,direction,maximum-offset,offset)
                    row['source_rehit'] = rehit
                    if rehit is not None and rehit['distance_from_origin_m'] <= second['distance_from_origin_m']:
                        row['status'] = 'source-obstructed'
                if row['status'] == 'measured' and 'target' in check:
                    error = abs(row[scalar]-check['target'][scalar])
                    row['comparison'] = {'error_m':error,'within_tolerance':error <= check['target']['tolerance_m']}
                    row['status'] = 'within-tolerances' if row['comparison']['within_tolerance'] else 'needs-correction'
        rows.append(row)
    complete = {'measured','within-tolerances','needs-correction'}
    status = ('incomplete' if any(r['status'] not in complete for r in rows) else
              'needs-correction' if any(r['status']=='needs-correction' for r in rows) else
              'within-tolerances' if 'target' in check else 'measured')
    scope = {'from_object':check['from_object'],'to_object':check['to_object']} if clearance else {'object':check['object']}
    result = {**scope, 'samples':rows,
              'max_distance_m':maximum,'epsilon_m':epsilon,'status':status}
    if 'target' in check:
        result['target'] = check['target']
    return result


def evaluate(spec):
    import bpy
    scenes = [scene for scene in bpy.data.scenes if scene.name == spec['scene']]
    require(len(scenes) == 1,'missing or ambiguous exact scene name')
    scene = scenes[0]
    layer = scene.view_layers.get(spec['view_layer'])
    require(layer is not None,'exact view_layer not found')
    bpy.context.window.scene = scene
    bpy.context.window.view_layer = layer
    scene.frame_set(spec['evaluation_frame'],subframe=0.0)
    layer.update()
    require(scene.unit_settings.system in ('METRIC','IMPERIAL'), 'scene units must explicitly be METRIC or IMPERIAL')
    scale = number(scene.unit_settings.scale_length,'scene scale_length',positive=True)
    graph = bpy.context.evaluated_depsgraph_get()
    budget = {'vertices':0,'triangles':0}
    rows = []
    names = set()
    for check in spec['checks']:
        if check['frame']['kind'] == 'object':
            names.add(check['frame']['object'])
        if check['type'] == 'dimensions':
            names.update(check['objects'])
        elif check['type'] == 'datum':
            names.add(check['landmark']['object'])
        elif check['type'] == 'clearance':
            names.update((check['from_object'],check['to_object']))
        else:
            names.add(check['object'])
        frame = measurement_frame(check['frame'],scene,layer,graph)
        inverse = frame.inverted()
        if check['type'] in ('datum','clearance','thickness'):
            measure = datum_measurement if check['type'] == 'datum' else ray_measurement
            row = measure(check,scene,layer,graph,inverse,scale,budget)
            row.update(id=check['id'],type=check['type'],frame=check['frame'],
                       frame_matrix_world_bu=[list(r) for r in frame])
            rows.append(row)
            continue
        points = []
        for name in check['objects']:
            obj = exact_object(name,scene,layer)
            points.extend([inverse @ p * scale for p in evaluated_vertices(obj,graph,budget)])
            require(len(points) <= MAX_VERTICES,'evaluated vertex workload exceeded')
        require(all(math.isfinite(v) for point in points for v in point), 'nonfinite evaluated coordinates')
        minimum = [min(p[i] for p in points) for i in range(3)]
        maximum = [max(p[i] for p in points) for i in range(3)]
        actual = [b-a for a,b in zip(minimum,maximum)]
        row = {'id':check['id'], 'type':check['type'], 'objects':check['objects'], 'frame':check['frame'],
               'frame_matrix_world_bu':[list(r) for r in frame], 'bounds_min_m':minimum,
               'bounds_max_m':maximum, 'dimensions_m':actual,'evaluated_vertices':len(points), 'status':'measured'}
        if 'target' in check:
            row['target'] = check['target']
            row['comparison'] = compare_vector(actual,check['target']['dimensions_m'],check['target']['tolerance_m'])
            row['status'] = 'within-tolerances' if row['comparison']['within_tolerance'] else 'needs-correction'
        rows.append(row)
    objects = []
    for name in sorted(names):
        obj = exact_object(name,scene,layer)
        matrix = obj.evaluated_get(graph).matrix_world
        finite_matrix(matrix)
        objects.append({'name':name,'type':obj.type,'matrix_world_bu':[list(r) for r in matrix]})
    return {'evaluation':{'scene':scene.name,'view_layer':layer.name,'frame':scene.frame_current,
                          'geometry':'evaluated viewport mesh','blender_version':bpy.app.version_string},
            'evaluated_objects':objects,
            'units':'m','scene_unit_system':scene.unit_settings.system, 'metres_per_blender_unit':scale, 'checks':rows,
            'status':'incomplete' if any(r['status']=='incomplete' for r in rows) else
                     'needs-correction' if any(r['status']=='needs-correction' for r in rows) else 'complete'}


def publish_json(path, report):
    """Publish complete JSON with an exclusive hard link; never replace a name."""
    encoded = (json.dumps(report,indent=2,allow_nan=False)+'\n').encode('utf-8')
    descriptor, staged = tempfile.mkstemp(prefix='.geometry-',dir=path.parent)
    try:
        with os.fdopen(descriptor,'wb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(staged,path,follow_symlinks=False)
    finally:
        os.unlink(staged)


def run(source, specpath, reportpath):
    import bpy
    source, specpath, reportpath = [Path(p).absolute() for p in (source,specpath,reportpath)]
    for path in (source,specpath,reportpath):
        require('..' not in path.parts and not any(p.is_symlink() for p in (path,*path.parents)),
                'symlink paths/ancestors and traversal are unsupported; use original input locations')
    require(source.is_file() and source.suffix.lower()=='.blend', 'source must be an existing .blend file')
    require(specpath.is_file(),'spec must be an existing JSON file')
    require(len({p.resolve() for p in (source,specpath,reportpath)}) == 3,'input/output aliases are forbidden')
    require(not os.path.lexists(reportpath),'report must be a NEW file, not existing file or symlink')
    require(reportpath.parent.is_dir(),'report parent must already exist')
    require(specpath.stat().st_size <= MAX_SPEC_BYTES,'spec exceeds 1 MiB workload limit')
    hashes = [digest(p) for p in (source,specpath)]
    spec = read_spec(specpath)
    bpy.context.preferences.filepaths.use_scripts_auto_execute = False
    bpy.ops.wm.open_mainfile(filepath=str(source),load_ui=False,use_scripts=False)
    report = evaluate(spec)
    report.update(schema_version=1,command='probe-geometry',source=str(source),source_sha256=hashes[0],
                  spec=str(specpath),spec_sha256=hashes[1],limitations=LIMITATIONS)
    require(hashes == [digest(p) for p in (source,specpath)],'source/spec changed during measurement')
    publish_json(reportpath,report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True)
    parser.add_argument('--spec',required=True)
    parser.add_argument('--report',required=True)
    if argv is None:
        argv = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]
    args = parser.parse_args(argv)
    try:
        report = run(args.source,args.spec,args.report)
    except (ValueError,OSError,RuntimeError,OverflowError,RecursionError) as exc:
        print(json.dumps({'status':'input-error','error':str(exc)}))
        return 2
    print(json.dumps({'status':report['status'],'report':str(Path(args.report).absolute())}))
    return 0 if report['status']=='complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
