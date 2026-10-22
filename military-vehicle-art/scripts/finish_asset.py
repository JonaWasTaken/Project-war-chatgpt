"""Add explicit UVs, editable bevels and bounded shading in a NEW snapshot.

Use official bpy Python or Blender --background --disable-autoexec --python
finish_asset.py -- --source existing.blend --spec filled.json --output NEW.blend
--report NEW.json. See references/asset-finishing.md for schema and limits.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys

# Blender --python/runpy need not add this directory to sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reconstruct_vehicle import check_paths, digest, float32, keys, number, save_snapshot, text


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def ranged(value, label, low, high):
    number(value, label)
    if not low <= value <= high:
        raise ValueError(f'{label} must be in [{low}, {high}]')


def validate(spec):
    keys(spec, ('schema_version', 'targets'))
    if type(spec['schema_version']) is not int or spec['schema_version'] != 1:
        raise ValueError('schema_version must be integer 1')
    if not isinstance(spec['targets'], list) or not 1 <= len(spec['targets']) <= 128:
        raise ValueError('targets must contain 1..128 explicit named meshes')
    names = set()
    for row in spec['targets']:
        keys(row, ('object', 'shared_mesh', 'uv', 'bevel', 'shading'))
        text(row['object'], 'object')
        if row['object'] in names:
            raise ValueError('duplicate target object')
        names.add(row['object'])
        if row['shared_mesh'] not in ('reject', 'copy_for_target'):
            raise ValueError('shared_mesh must be reject or copy_for_target')
        if all(row[name] is None for name in ('uv', 'bevel', 'shading')):
            raise ValueError('each target requires at least one finishing operation')
        uv = row['uv']
        if uv is not None:
            keys(uv, ('name', 'method', 'angle_limit_degrees', 'island_margin'))
            text(uv['name'], 'new UV name')
            if uv['method'] != 'smart_project':
                raise ValueError('only smart_project UV method is supported')
            ranged(uv['angle_limit_degrees'], 'UV angle_limit_degrees', 1, 89)
            ranged(uv['island_margin'], 'UV island_margin', 0, .1)
        bevel = row['bevel']
        if bevel is not None:
            keys(bevel, ('name', 'width', 'segments', 'angle_degrees', 'clamp_overlap'))
            text(bevel['name'], 'new modifier name')
            number(bevel['width'], 'bevel width', positive=True)
            if bevel['width'] > 1e6 or float32(bevel['width']) <= 0:
                raise ValueError('bevel width must be float32-positive and at most 1000000 Blender units')
            if type(bevel['segments']) is not int or not 1 <= bevel['segments'] <= 32:
                raise ValueError('bevel segments must be integer 1..32')
            ranged(bevel['angle_degrees'], 'bevel angle_degrees', 0, 180)
            if type(bevel['clamp_overlap']) is not bool:
                raise ValueError('bevel clamp_overlap must be a boolean')
        shading = row['shading']
        if shading is not None:
            if not isinstance(shading, dict) or shading.get('mode') not in ('flat', 'smooth', 'smooth_by_angle'):
                raise ValueError('shading mode must be flat, smooth or smooth_by_angle')
            keys(shading, ('mode', 'angle_degrees') if shading['mode'] == 'smooth_by_angle' else ('mode',))
            if shading['mode'] == 'smooth_by_angle':
                number(shading['angle_degrees'], 'shading angle_degrees', positive=True)
                ranged(shading['angle_degrees'], 'shading angle_degrees', 0, 180)
    return spec


def geometry_digest(mesh):
    """Base coordinates/connectivity only, deliberately excluding editable finish data."""
    data = [[list(v.co) for v in mesh.vertices], [list(e.vertices) for e in mesh.edges],
            [list(p.vertices) for p in mesh.polygons]]
    return hashlib.sha256(json.dumps(data, allow_nan=False).encode()).hexdigest()


def uv_report(mesh, layer):
    points = [tuple(item.uv) for item in layer.data]
    if not points or not all(math.isfinite(v) for uv in points for v in uv):
        raise ValueError('unwrap produced empty/nonfinite UV coordinates')
    mesh.calc_loop_triangles()
    areas = []
    face_areas = [0.0] * len(mesh.polygons)
    for tri in mesh.loop_triangles:
        a, b, c = [points[i] for i in tri.loops]
        area = abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])) / 2
        areas.append(area)
        face_areas[tri.polygon_index] += area
    if not math.isfinite(sum(areas)) or sum(areas) <= 1e-12:
        raise ValueError('unwrap produced no usable UV area (>1e-12 required)')
    parents = list(range(len(mesh.polygons)))
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    edges = {}
    for face in mesh.polygons:
        loops = list(face.loop_indices)
        for i, loop in enumerate(loops):
            nxt = loops[(i+1) % len(loops)]
            va, vb = mesh.loops[loop].vertex_index, mesh.loops[nxt].vertex_index
            pair = (points[loop], points[nxt]) if va < vb else (points[nxt], points[loop])
            edges.setdefault(mesh.loops[loop].edge_index, []).append((face.index, pair))
    for uses in edges.values():
        for j, (a, uv_a) in enumerate(uses):
            for b, uv_b in uses[j+1:]:
                if all(abs(x-y) <= 1e-6 for u, v in zip(uv_a, uv_b) for x, y in zip(u, v)):
                    parents[root(b)] = root(a)
    groups = {}
    for face in mesh.polygons:
        groups.setdefault(root(face.index), []).append(face.index)
    def bounds(coords):
        return [[min(p[i] for p in coords) for i in (0, 1)],
                [max(p[i] for p in coords) for i in (0, 1)]]
    islands = []
    for faces in groups.values():
        coords = [points[i] for f in faces for i in mesh.polygons[f].loop_indices]
        islands.append({'faces': len(faces), 'bounds': bounds(coords),
                        'triangle_area_sum': sum(face_areas[f] for f in faces)})
    islands.sort(key=lambda row: (-row['triangle_area_sum'], row['bounds']))
    return {'name': layer.name, 'loops': len(points), 'bounds': bounds(points),
            'triangle_area_sum': sum(areas), 'zero_area_triangles': sum(a <= 1e-12 for a in areas),
            'island_count': len(islands), 'islands': islands[:256],
            'islands_omitted': max(0, len(islands)-256), 'island_report_limit': 256,
            'island_method': 'mesh-edge adjacency with UV endpoints matching within 1e-6',
            'overlap_tested': False, 'texel_density_tested': False}


def smart_uv(obj, spec):
    import bpy
    mesh = obj.data
    active = mesh.uv_layers.active_index if mesh.uv_layers else None
    layer = mesh.uv_layers.new(name=spec['name'])
    mesh.uv_layers.active = layer
    selected = list(bpy.context.selected_objects)
    old_active = bpy.context.view_layer.objects.active
    flags = [[(item.hide, item.select) for item in items]
             for items in (mesh.vertices, mesh.edges, mesh.polygons)]
    try:
        for item in selected:
            item.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        for items in (mesh.vertices, mesh.edges, mesh.polygons):
            for item in items:
                item.hide = False
                item.select = True
        bpy.ops.object.mode_set(mode='EDIT')
        result = bpy.ops.uv.smart_project(angle_limit=math.radians(spec['angle_limit_degrees']),
            margin_method='SCALED', rotate_method='AXIS_ALIGNED',
            island_margin=spec['island_margin'], area_weight=0,
            correct_aspect=False, scale_to_bounds=False)
        if 'FINISHED' not in result:
            raise ValueError('Blender smart_project did not finish')
    finally:
        if obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for items, states in zip((mesh.vertices, mesh.edges, mesh.polygons), flags):
            for item, (hidden, select) in zip(items, states):
                item.hide = hidden
                item.select = select
        obj.select_set(False)
        for item in selected:
            item.select_set(True)
        bpy.context.view_layer.objects.active = old_active
        if active is not None:
            mesh.uv_layers.active_index = active
    report = uv_report(mesh, mesh.uv_layers[spec['name']])
    report.update(method='smart_project', controls={
        'angle_limit_degrees': spec['angle_limit_degrees'], 'island_margin': spec['island_margin'],
        'margin_method': 'SCALED', 'rotate_method': 'AXIS_ALIGNED', 'area_weight': 0,
        'correct_aspect': False, 'scale_to_bounds': False})
    return report


def preflight(spec):
    """Resolve every target and reject conflicts before any mesh/UV/modifier edit."""
    import bpy
    validate(spec)
    if bpy.context.mode != 'OBJECT' or any(mesh.is_editmode for mesh in bpy.data.meshes):
        raise ValueError('edit/sculpt/paint mode is unsupported; use an Object-mode source')
    bpy.context.view_layer.update()
    objects = []
    total_loops = 0
    for row in spec['targets']:
        matches = [obj for obj in bpy.data.objects if obj.name == row['object']]
        if len(matches) != 1 or matches[0].type != 'MESH':
            raise ValueError('target must be an unambiguous exact named mesh: ' + row['object'])
        obj = matches[0]
        mesh = obj.data
        if any(block.library or block.override_library or not block.is_editable for block in (obj, mesh)):
            raise ValueError('targets must be local editable non-overridden object/mesh data: ' + obj.name)
        if obj.name not in bpy.context.view_layer.objects or not obj.visible_get() or obj.hide_select:
            raise ValueError('target must be visible/selectable in the current view layer: ' + obj.name)
        if obj.parent or obj.children or obj.constraints or obj.animation_data or mesh.animation_data or mesh.shape_keys or obj.vertex_groups or obj.rigid_body or obj.rigid_body_constraint or obj.instance_type != 'NONE':
            raise ValueError('target rig/parent/animation/shape-key/vertex-group/physics/instancing complexity is unsupported: ' + obj.name)
        if any(mod.type not in {'BEVEL', 'WEIGHTED_NORMAL'} for mod in obj.modifiers):
            raise ValueError('existing target modifiers must be BEVEL or WEIGHTED_NORMAL; prepare a separate static mesh source: ' + obj.name)
        if any(not math.isfinite(v) for row_matrix in obj.matrix_world for v in row_matrix):
            raise ValueError('nonfinite object transform: ' + obj.name)
        if any(not math.isfinite(v) or abs(v-1) > 1e-6 for values in (obj.scale, obj.delta_scale, obj.matrix_world.to_scale()) for v in values):
            raise ValueError('target requires unit object/delta/world scale; Blender-unit width would be ambiguous: ' + obj.name)
        if mesh.users != 1 and row['shared_mesh'] == 'reject':
            raise ValueError('shared mesh rejected; explicitly choose copy_for_target: ' + obj.name)
        if len(mesh.vertices) > 400000 or len(mesh.edges) > 400000:
            raise ValueError('target must have at most 400000 base vertices and edges, including loose geometry: ' + obj.name)
        if not mesh.polygons or len(mesh.polygons) > 100000 or len(mesh.loops) > 400000:
            raise ValueError('target must have 1..100000 base faces and at most 400000 loops: ' + obj.name)
        total_loops += len(mesh.loops)
        if total_loops > 1000000:
            raise ValueError('combined target loop limit is 1000000')
        if any(not math.isfinite(v) for vertex in mesh.vertices for v in vertex.co) or not any(face.area > 1e-20 for face in mesh.polygons):
            raise ValueError('target needs finite coordinates and nonempty usable geometric area: ' + obj.name)
        if row['uv'] is not None:
            edge_uses = [0] * len(mesh.edges)
            for loop in mesh.loops:
                edge_uses[loop.edge_index] += 1
            if any(count > 2 for count in edge_uses):
                raise ValueError('UV projection of nonmanifold edge fans (>2 faces per edge) is unsupported: ' + obj.name)
            name = row['uv']['name']
            if name in mesh.uv_layers or name in mesh.attributes:
                raise ValueError('new UV/attribute name is already owned: ' + name)
            if len(mesh.uv_layers) >= 8:
                raise ValueError('target already has the supported maximum of 8 UV layers: ' + obj.name)
        if row['shading'] is not None and mesh.has_custom_normals:
            raise ValueError('shading preparation with existing custom normals is unsupported: ' + obj.name)
        if row['bevel'] is not None and row['bevel']['name'] in obj.modifiers:
            raise ValueError('new modifier name is already owned: ' + row['bevel']['name'])
        objects.append(obj)
    # ID references reveal Boolean/Object Info/texture-coordinate/driver users,
    # whose evaluated output could otherwise change outside the explicit scope.
    # Collection Info and similar consumers refer to a collection, not its
    # individual objects. Walk all containing ancestors as well as direct users.
    users_by_id = bpy.data.user_map()
    for obj in objects:
        if any(not isinstance(user, (bpy.types.Scene, bpy.types.Collection))
               for user in users_by_id.get(obj, ())):
            raise ValueError('target has dependent ID users; prepare an isolated static source: ' + obj.name)
    pending = {collection for obj in objects for collection in obj.users_collection}
    seen = set()
    while pending:
        collection = pending.pop()
        if collection in seen:
            continue
        seen.add(collection)
        for user in users_by_id.get(collection, ()):
            if isinstance(user, bpy.types.Collection):
                pending.add(user)
            elif not isinstance(user, bpy.types.Scene):
                raise ValueError('target collection has dependent ID users; prepare an isolated static source: ' + collection.name)
    for candidate in bpy.data.objects:
        if candidate.instance_collection and any(obj.name in candidate.instance_collection.all_objects for obj in objects):
            raise ValueError('target has dependent collection instances: ' + candidate.name)
    return objects


def finish(spec):
    import bpy
    objects = preflight(spec)
    rows = []
    for target, obj in zip(spec['targets'], objects):
        original_mesh = obj.data.name
        copied = obj.data.users != 1
        if copied:
            obj.data = obj.data.copy()
        before = geometry_digest(obj.data)
        uv = smart_uv(obj, target['uv']) if target['uv'] is not None else None
        bevel = target['bevel']
        if bevel is not None:
            mod = obj.modifiers.new(bevel['name'], 'BEVEL')
            mod.width = bevel['width']
            mod.segments = bevel['segments']
            mod.limit_method = 'ANGLE'
            mod.angle_limit = math.radians(bevel['angle_degrees'])
            mod.use_clamp_overlap = bevel['clamp_overlap']
            mod.offset_type = 'OFFSET'
            mod.affect = 'EDGES'
            bevel = {'name': mod.name, 'width': mod.width, 'segments': mod.segments,
                     'angle_degrees': math.degrees(mod.angle_limit), 'clamp_overlap': mod.use_clamp_overlap,
                     'offset_type': mod.offset_type, 'applied': False}
        shading = target['shading']
        if shading is not None:
            for face in obj.data.polygons:
                face.use_smooth = shading['mode'] != 'flat'
            if shading['mode'] == 'smooth_by_angle':
                obj.data.set_sharp_from_angle(angle=math.radians(shading['angle_degrees']))
        after = geometry_digest(obj.data)
        if before != after:
            raise ValueError('base topology or coordinates changed unexpectedly')
        rows.append({'object': obj.name, 'mesh': obj.data.name, 'original_mesh': original_mesh,
                     'mesh_copied': copied, 'shared_mesh': target['shared_mesh'], 'uv': uv,
                     'bevel': bevel, 'shading': shading,
                     'base_geometry': {'unchanged': True, 'before_sha256': before, 'after_sha256': after}})
    return {'targets': rows,
            'limitations': 'Mechanics checks only. Evaluated bevel changes geometry; base geometry is preserved. No overlap/texel-density, retopology, baking, texture generation, artistic or export-quality certification.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'spec', 'output', 'report'):
        parser.add_argument('--'+name, required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        check_paths(args)
        if os.path.samefile(args.source, args.spec):
            raise ValueError('source and spec must be distinct files, not hardlink aliases')
        source_hash, spec_hash = digest(args.source), digest(args.spec)
        spec = validate(json.loads(args.spec.read_text(encoding='utf8'), object_pairs_hook=unique_object))
        if digest(args.spec) != spec_hash:
            raise ValueError('spec changed during validation; refusing to open source')
        import bpy
        bpy.context.preferences.filepaths.use_scripts_auto_execute = False
        lineage = {'source': str(args.source.resolve()), 'source_sha256': source_hash,
                   'spec': str(args.spec.resolve()), 'spec_sha256': spec_hash,
                   'blender_version': bpy.app.version_string}
        bpy.ops.wm.open_mainfile(filepath=str(args.source.resolve()), use_scripts=False)
        report = {'schema_version': 1, 'command': 'finish-asset', 'status': 'finished',
                  'lineage': lineage, **finish(spec)}
        if digest(args.source) != lineage['source_sha256'] or digest(args.spec) != lineage['spec_sha256']:
            raise ValueError('source or spec changed during operation; refusing publication')
        save_snapshot(args, report)
        return 0
    except (ValueError, KeyError, OSError, RuntimeError, ImportError) as exc:
        print(json.dumps({'status': 'error', 'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    cli = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]
    raise SystemExit(main(cli))
