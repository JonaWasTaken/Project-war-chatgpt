"""Source-preserving, explicit ray placement of an inspected static master mesh.

Run in a disposable official-bpy process, or Blender --background
--disable-autoexec --python place_surface_details.py -- --source ... --spec ...
--output NEW.blend --report NEW.json. See references/surface-details.md.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reconstruct_vehicle import check_paths, digest, float32, keys, number, text

MAX_PLACEMENTS = 256
MAX_COORD = 10000000


def bounded(value, label, positive=False):
    value = number(value, label, positive)
    if abs(value) > MAX_COORD or (value != 0 and float32(value) == 0):
        raise ValueError(label + ' exceeds supported range or collapses at float32 precision')
    return value


def vector(value, label, nonzero=False):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(label + ' must contain three numbers')
    result = [bounded(v, label) for v in value]
    if nonzero and math.hypot(*result) == 0:
        raise ValueError(label + ' must be nonzero')
    return result


def validate(spec):
    """Validate explicit request data without importing bpy or editing the scene."""
    keys(spec, ('schema_version', 'collection', 'master', 'placements'))
    if type(spec['schema_version']) is not int or spec['schema_version'] != 1:
        raise ValueError('schema_version must be integer 1')
    text(spec['collection'], 'new collection name')
    master = spec['master']
    keys(master, ('object', 'attachment_origin', 'normal_axis', 'tangent_axis'))
    text(master['object'], 'master object')
    vector(master['attachment_origin'], 'master attachment_origin')
    if master['normal_axis'] != '+Z' or master['tangent_axis'] != '+X':
        raise ValueError('master local attachment convention must be +Z normal and +X tangent')
    placements = spec['placements']
    if not isinstance(placements, list) or not 1 <= len(placements) <= MAX_PLACEMENTS:
        raise ValueError('placements must contain 1..256 explicit requests')
    ids, names = set(), set()
    for row in placements:
        keys(row, ('feature_id', 'object_name', 'target', 'ray', 'tangent', 'offset',
                   'rotation_degrees', 'scale', 'support'))
        for field in ('feature_id', 'object_name', 'target'):
            text(row[field], field)
        if row['feature_id'] in ids or row['object_name'] in names:
            raise ValueError('duplicate feature ID or output object name')
        ids.add(row['feature_id'])
        names.add(row['object_name'])
        ray = row['ray']
        keys(ray, ('origin', 'direction', 'max_distance'))
        origin = vector(ray['origin'], 'ray origin')
        direction = vector(ray['direction'], 'ray direction', True)
        distance = bounded(ray['max_distance'], 'ray max_distance', True)
        length = math.hypot(*direction)
        if all(float32(origin[i] + direction[i]/length*distance) == float32(origin[i]) for i in range(3)):
            raise ValueError('ray range collapses at float32 precision')
        vector(row['tangent'], 'world tangent', True)
        bounded(row['offset'], 'offset')
        rotation = bounded(row['rotation_degrees'], 'rotation_degrees')
        if not -360 <= rotation <= 360:
            raise ValueError('rotation_degrees must be in [-360, 360]')
        for value in vector(row['scale'], 'local scale'):
            bounded(value, 'local scale', True)
        support = row['support']
        keys(support, ('kind', 'description'))
        if support['kind'] not in ('authored', 'reference'):
            raise ValueError('support kind must be authored or reference')
        description = support['description']
        if not isinstance(description, str) or not description.strip() or '\x00' in description or len(description) > 4096:
            raise ValueError('support description must be nonempty text, at most 4096 characters')
    return spec


def inspect_static(name, master=False):
    """Bound local static support before asking Blender for evaluated meshes."""
    import bpy
    from mathutils import Matrix
    matches = [obj for obj in bpy.data.objects if obj.name == name]
    if len(matches) != 1 or matches[0].type != 'MESH':
        raise ValueError('exact unambiguous named mesh required: ' + name)
    obj = matches[0]
    mesh = obj.data
    if any(block.library or block.override_library or not block.is_editable for block in (obj, mesh)):
        raise ValueError('linked/overridden/noneditable meshes are unsupported: ' + name)
    if obj.name not in bpy.context.view_layer.objects or not obj.visible_get() or obj.hide_render or obj.hide_select:
        raise ValueError('mesh must be visible in viewport/render and selectable: ' + name)
    if (obj.parent or obj.children or obj.constraints or obj.animation_data or mesh.animation_data or
            mesh.shape_keys or obj.vertex_groups or obj.rigid_body or obj.rigid_body_constraint or
            obj.instance_type != 'NONE' or obj.particle_systems):
        raise ValueError('parent/rig/animation/physics/instancing dependencies unsupported: ' + name)
    if (any(abs(v) > 1e-8 for v in obj.delta_location) or
            obj.delta_rotation_euler.to_quaternion().angle > 1e-6 or obj.delta_rotation_quaternion.angle > 1e-6 or
            any(abs(v-1) > 1e-6 for v in obj.delta_scale)):
        raise ValueError('delta transforms are unsupported: ' + name)
    # Unparented static objects: matrix_basis reflects unsynchronized channel
    # edits without forcing evaluation of an unsupported modifier stack first.
    matrix = obj.matrix_basis
    for r in matrix:
        for value in r:
            bounded(value, 'object transform')
    linear = matrix.to_3x3()
    scales = [linear.col[i].length for i in range(3)]
    if (min(scales) < 1e-6 or max(scales)/min(scales) > 1e6 or
            linear.determinant() <= 0 or any(v <= 0 for v in obj.scale)):
        raise ValueError('singular/mirrored/ill-conditioned transform unsupported: ' + name)
    if any(abs(linear.col[i].dot(linear.col[j])) > 1e-5*scales[i]*scales[j]
           for i in range(3) for j in range(i)):
        raise ValueError('sheared transform unsupported: ' + name)
    if master and any(abs(linear[i][j]-Matrix.Identity(3)[i][j]) > 1e-6 for i in range(3) for j in range(3)):
        raise ValueError('master rotation/scale must be applied; its local mesh defines the frame')
    if not mesh.polygons or len(mesh.vertices) > 100000 or len(mesh.edges) > 200000 or len(mesh.loops) > 200000:
        raise ValueError('base mesh exceeds 100000 vertices/200000 edges/200000 loops, or has no faces')
    if any(item.hide for items in (mesh.vertices, mesh.edges, mesh.polygons) for item in items):
        raise ValueError('hidden base mesh elements are unsupported: ' + name)
    for vertex in mesh.vertices:
        for value in vertex.co:
            bounded(value, 'base mesh coordinate')
    estimate = len(mesh.loops)
    if master and obj.modifiers:
        raise ValueError('master must be an inspected modifier-free static mesh')
    if len(obj.modifiers) > 4:
        raise ValueError('at most four supported target modifiers')
    for mod in obj.modifiers:
        if mod.type not in {'BEVEL', 'SUBSURF', 'SOLIDIFY', 'TRIANGULATE', 'WEIGHTED_NORMAL'}:
            raise ValueError('unsupported target modifier: ' + mod.type)
        if not mod.show_viewport or not mod.show_render:
            raise ValueError('modifier viewport/render visibility must match and be enabled')
        if mod.type == 'SUBSURF':
            if mod.levels > 2 or mod.render_levels != mod.levels or mod.subdivision_type != 'CATMULL_CLARK':
                raise ValueError('subdivision must be Catmull-Clark at matching viewport/render levels 0..2')
            estimate *= 4**mod.levels
        if mod.type == 'BEVEL':
            if mod.segments > 8 or mod.vertex_group:
                raise ValueError('bevel requires at most 8 segments and no vertex-group dependency')
            estimate *= 4*(mod.segments+1)
        if mod.type == 'SOLIDIFY':
            if mod.vertex_group:
                raise ValueError('solidify vertex-group dependencies unsupported')
            estimate *= 4
        if mod.type == 'TRIANGULATE':
            estimate *= 2
    if estimate > 600000:
        raise ValueError('conservative evaluated target workload exceeds 600000 loops')
    return obj


def reject_dependencies(objects):
    import bpy
    users = bpy.data.user_map()
    for obj in objects:
        if any(not isinstance(user, (bpy.types.Scene, bpy.types.Collection)) for user in users.get(obj, ())):
            raise ValueError('object has dependent ID users: ' + obj.name)
    pending = {bpy.context.scene.collection} | {c for obj in objects for c in obj.users_collection}
    seen = set()
    while pending:
        coll = pending.pop()
        if coll in seen:
            continue
        seen.add(coll)
        if coll.hide_render or coll.hide_viewport or coll.library or coll.override_library:
            raise ValueError('hidden/linked input collection unsupported: ' + coll.name)
        for user in users.get(coll, ()):
            if isinstance(user, bpy.types.Collection):
                pending.add(user)
            elif not isinstance(user, bpy.types.Scene):
                raise ValueError('collection has dependent ID users/instances: ' + coll.name)
    for obj in bpy.data.objects:
        if obj.instance_collection in seen:
            raise ValueError('dependent collection instance unsupported: ' + obj.name)


def checked_triangles(mesh, coords):
    """Reject nonfinite/degenerate triangles, including float32 transform collapse."""
    mesh.calc_loop_triangles()
    if not mesh.loop_triangles or len(mesh.vertices) > 200000 or len(mesh.loops) > 600000 or len(mesh.loop_triangles) > 200000:
        raise ValueError('evaluated mesh exceeds bounded workload or has no triangles')
    for point in coords:
        for value in point:
            bounded(value, 'transformed mesh coordinate')
    result = []
    for tri in mesh.loop_triangles:
        a, b, c = [coords[i] for i in tri.vertices]
        u, v = b-a, c-a
        if u.length == 0 or v.length == 0 or u.cross(v).length <= 1e-7*u.length*v.length:
            raise ValueError('degenerate or float32-collapsed triangle')
        result.append(tuple(tri.vertices))
    return result


def preflight(spec):
    """Compute every evaluated world-space hit and placement before creating IDs."""
    import bpy
    from mathutils import Matrix, Vector
    from mathutils.bvhtree import BVHTree
    validate(spec)
    if bpy.context.mode != 'OBJECT' or any(mesh.is_editmode for mesh in bpy.data.meshes):
        raise ValueError('only an Object-mode source is supported')
    if spec['collection'] in bpy.data.collections:
        raise ValueError('new collection name is already owned')
    ids = {row['feature_id'] for row in spec['placements']}
    if any(obj.get('surface_detail_feature_id') in ids for obj in bpy.data.objects
           if isinstance(obj.get('surface_detail_feature_id'), str)):
        raise ValueError('feature ID is already owned in the source')
    for row in spec['placements']:
        if row['object_name'] in bpy.data.objects or row['object_name'] in bpy.data.meshes:
            raise ValueError('output object/mesh name is already owned: ' + row['object_name'])
        if row['target'] == spec['master']['object']:
            raise ValueError('master cannot also be a target')
    master = inspect_static(spec['master']['object'], master=True)
    targets = {row['target']: None for row in spec['placements']}
    for name in targets:
        targets[name] = inspect_static(name)
    if len(master.data.vertices)*len(spec['placements']) > 1000000 or len(master.data.loops)*len(spec['placements']) > 2000000:
        raise ValueError('independent output copies exceed 1000000 vertices/2000000 loops')
    reject_dependencies([master, *targets.values()])
    bpy.context.view_layer.update()
    checked_triangles(master.data, [v.co.copy() for v in master.data.vertices])
    graph = bpy.context.evaluated_depsgraph_get()
    trees = {}
    total_vertices = total_triangles = 0
    plans = []
    for row in spec['placements']:
        name = row['target']
        if name not in trees:
            target = targets[name]
            evaluated = target.evaluated_get(graph)
            mesh = evaluated.to_mesh()
            try:
                coords = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
                triangles = checked_triangles(mesh, coords)
                total_vertices += len(coords)
                total_triangles += len(triangles)
                if total_vertices > 500000 or total_triangles > 500000:
                    raise ValueError('combined evaluated target budget exceeds 500000 vertices/triangles')
                trees[name] = (BVHTree.FromPolygons(coords, triangles, all_triangles=True),
                               [tri.polygon_index for tri in mesh.loop_triangles])
            finally:
                evaluated.to_mesh_clear()
        tree, polygons = trees[name]
        origin = Vector(row['ray']['origin'])
        raw_direction = row['ray']['direction']
        direction_length = math.hypot(*raw_direction)
        direction = Vector([v/direction_length for v in raw_direction])
        hit, normal, triangle, distance = tree.ray_cast(origin, direction, row['ray']['max_distance'])
        if hit is None:
            raise ValueError('ray miss for feature: ' + row['feature_id'])
        normal.normalize()
        # Normalize accepted nonzero inputs in double precision BEFORE
        # mathutils' float32 conversion/small-length normalization cutoff.
        tangent_length = math.hypot(*row['tangent'])
        tangent = Vector([v/tangent_length for v in row['tangent']])
        tangent -= normal * tangent.dot(normal)
        if tangent.length <= 1e-7:
            raise ValueError('invalid tangent parallel to surface normal: ' + row['feature_id'])
        tangent.normalize()
        angle = math.radians(row['rotation_degrees'])
        x = tangent*math.cos(angle) + normal.cross(tangent)*math.sin(angle)
        y = normal.cross(x)
        rotation = Matrix((x, y, normal)).transposed().to_4x4()
        anchor = hit + normal*row['offset']
        if row['offset'] and anchor == hit:
            raise ValueError('offset collapses at float32 world precision')
        transform = (Matrix.Translation(anchor) @ rotation @ Matrix.Diagonal((*row['scale'], 1)) @
                     Matrix.Translation(-Vector(spec['master']['attachment_origin'])))
        checked_triangles(master.data, [transform @ v.co for v in master.data.vertices])
        recovered_anchor = transform @ Vector(spec['master']['attachment_origin'])
        if (recovered_anchor-anchor).length > max(1e-6, anchor.length*5e-7):
            raise ValueError('attachment transform loses supported precision')
        plans.append((row, transform, {'feature_id': row['feature_id'], 'object': row['object_name'],
            'target': name, 'hit_position': list(hit), 'hit_normal': list(normal),
            'normal_method': 'evaluated_world_triangle_winding',
            'tangent': list(tangent), 'distance': distance, 'triangle_index': triangle,
            'polygon_index': polygons[triangle], 'attachment_position': list(anchor),
            'offset': row['offset'], 'rotation_degrees': row['rotation_degrees'],
            'scale': row['scale'], 'support': row['support']}))
    return master, plans


def state_digest(obj):
    """Scoped base mesh/UV/frame/slot fingerprint; not a whole-scene certificate."""
    mesh = obj.data
    state = {'object': obj.name, 'mesh': mesh.name,
             'vertices': [list(v.co) for v in mesh.vertices],
             'edges': [list(e.vertices) for e in mesh.edges],
             'faces': [[list(p.vertices), p.material_index, p.use_smooth] for p in mesh.polygons],
             'uv': [[layer.name, [list(item.uv) for item in layer.data]] for layer in mesh.uv_layers],
             'matrix': [list(row) for row in obj.matrix_world],
             'slots': [[s.link, s.material.name if s.material else None] for s in obj.material_slots],
             'data_materials': [m.name if m else None for m in mesh.materials],
             'visibility': [obj.hide_get(), obj.hide_render, obj.hide_viewport, obj.hide_select],
             'collections': sorted(c.name for c in obj.users_collection)}
    return hashlib.sha256(json.dumps(state, allow_nan=False, sort_keys=True).encode()).hexdigest()


def place(spec):
    """Place independent mesh copies; return JSON-serializable mechanics evidence."""
    import bpy
    master, plans = preflight(spec)
    originals = [master] + [bpy.data.objects[name] for name in sorted({r['target'] for r in spec['placements']})]
    before = {obj.name: state_digest(obj) for obj in originals}
    made_objects, made_meshes = [], []
    collection = None
    try:
        collection = bpy.data.collections.new(spec['collection'])
        bpy.context.scene.collection.children.link(collection)
        rows = []
        for row, transform, report in plans:
            mesh = master.data.copy()
            made_meshes.append(mesh)
            mesh.name = row['object_name']
            obj = bpy.data.objects.new(row['object_name'], mesh)
            made_objects.append(obj)
            collection.objects.link(obj)
            for source_slot, target_slot in zip(master.material_slots, obj.material_slots):
                target_slot.link = source_slot.link
                target_slot.material = source_slot.material
            obj.matrix_world = transform
            obj['surface_detail_feature_id'] = row['feature_id']
            obj['surface_detail_master'] = master.name
            obj['surface_detail_target'] = row['target']
            bpy.context.view_layer.update()
            report['matrix_world'] = [list(r) for r in obj.matrix_world]
            report['mesh'] = mesh.name
            report['mesh_shared'] = False
            report['material_datablocks_shared'] = True
            report['material_slots'] = [{'index': i, 'link': slot.link,
                                         'material': slot.material.name if slot.material else None}
                                        for i, slot in enumerate(obj.material_slots)]
            rows.append(report)
        preservation = []
        for original in originals:
            after = state_digest(original)
            if before[original.name] != after:
                raise ValueError('original master/target state changed unexpectedly')
            preservation.append({'object': original.name, 'unchanged': True,
                                 'before_sha256': before[original.name], 'after_sha256': after})
        return {'placements': rows, 'count': len(rows), 'collection': collection.name,
                'preservation': preservation,
                'master': master.name, 'collision_tested': False,
                'surface_contact_scope': 'single ray hit and local attachment anchor only',
                'limitations': 'Authored/reference-backed requests only; no automatic photo detection, full-footprint contact, hidden contact, collision or fidelity certification.'}
    except BaseException:
        for obj in made_objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        for mesh in made_meshes:
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        if collection is not None:
            bpy.data.collections.remove(collection)
        raise


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def assert_lineage(args, report):
    if (digest(args.source) != report['lineage']['source_sha256'] or
            digest(args.spec) != report['lineage']['spec_sha256']):
        raise ValueError('source or spec changed during operation; refusing publication')


def save_snapshot(args, report):
    """Same lineage pattern as reconstruct_vehicle, with a post-save hash gate.

    Both files are completely staged before exclusive hard-link publication.
    Pair rollback handles ordinary errors; this is not a crash-atomic two-file
    transaction or a sandbox against a malicious concurrent filesystem actor.
    """
    import bpy
    with tempfile.TemporaryDirectory(prefix='.surface-details-', dir=args.output.parent) as tmp:
        staged = Path(tmp)/args.output.name
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.file.make_paths_absolute()
        bpy.ops.wm.save_as_mainfile(filepath=str(staged), check_existing=False, relative_remap=False)
        assert_lineage(args, report)
        report['lineage'].update(output=str(args.output), output_sha256=digest(staged))
        encoded = json.dumps(report, indent=2, allow_nan=False)+'\n'
        with tempfile.TemporaryDirectory(prefix='.surface-report-', dir=args.report.parent) as report_tmp:
            staged_report = Path(report_tmp)/'report.json'
            staged_report.write_text(encoded, encoding='utf8')
            assert_lineage(args, report)
            os.link(staged, args.output)
            try:
                os.link(staged_report, args.report)
            except BaseException:
                # Never delete a competitor's replacement on ordinary rollback.
                if args.output.exists() and os.path.samefile(staged, args.output):
                    args.output.unlink()
                raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'spec', 'output', 'report'):
        parser.add_argument('--'+name, required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        check_paths(args)
        if os.path.samefile(args.source, args.spec):
            raise ValueError('source and spec must be distinct files, not hardlink aliases')
        if args.spec.stat().st_size > 1048576:
            raise ValueError('spec exceeds 1048576 byte workload limit')
        source_hash, spec_hash = digest(args.source), digest(args.spec)
        spec = validate(json.loads(args.spec.read_text(encoding='utf8'), object_pairs_hook=unique_object))
        if digest(args.spec) != spec_hash:
            raise ValueError('spec changed during validation')
        import bpy
        bpy.context.preferences.filepaths.use_scripts_auto_execute = False
        bpy.ops.wm.open_mainfile(filepath=str(args.source.resolve()), use_scripts=False)
        lineage = {'source': str(args.source.resolve()), 'source_sha256': source_hash,
                   'spec': str(args.spec.resolve()), 'spec_sha256': spec_hash,
                   'blender_version': bpy.app.version_string}
        report = {'schema_version': 1, 'command': 'place-surface-details', 'status': 'placed',
                  'lineage': lineage, **place(spec)}
        if digest(args.source) != source_hash or digest(args.spec) != spec_hash:
            raise ValueError('source or spec changed during operation; refusing publication')
        save_snapshot(args, report)
        return 0
    except (ValueError, KeyError, OSError, RuntimeError, ImportError) as exc:
        print(json.dumps({'status': 'error', 'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    cli = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]
    raise SystemExit(main(cli))
