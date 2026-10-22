"""Non-destructive vehicle inspection. Run in disposable Blender Python.

CLI and complete limitations: references/blender-review-tools.md.
No function in this module saves the source .blend or executes embedded scripts.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys


def validate_config(c):
    import re
    def number(v, positive=False):
        return type(v) in (int, float) and math.isfinite(v) and (not positive or v > 0)
    def vector(v):
        return isinstance(v, list) and len(v) == 3 and all(number(x) for x in v)
    if not isinstance(c, dict) or type(c.get('schema_version')) is not int or c['schema_version'] != 1:
        raise ValueError('schema_version must be 1')
    if not isinstance(c.get('collection'), str) or not c['collection'].strip():
        raise ValueError('name the exact vehicle collection; an unfilled template is not runnable')
    r = c.get('resolution')
    if not isinstance(r, list) or len(r) != 2 or any(type(x) is not int or not 16 <= x <= 8192 for x in r):
        raise ValueError('resolution requires two integers from 16 to 8192')
    if type(c.get('samples')) is not int or not 1 <= c['samples'] <= 4096:
        raise ValueError('samples must be an integer from 1 to 4096')
    modes = c.get('modes')
    if not isinstance(modes, list) or not modes or any(m not in ('material', 'clay', 'silhouette') for m in modes) or len(set(modes)) != len(modes):
        raise ValueError('modes must be unique material/clay/silhouette names')
    views = c.get('views')
    if not isinstance(views, list) or not views:
        raise ValueError('at least one review view is required')
    names = set()
    for v in views:
        if not isinstance(v, dict) or not isinstance(v.get('name'), str) or not re.fullmatch(r'[A-Za-z0-9_-]+', v['name']) or v['name'] in names:
            raise ValueError('view names must be unique safe filename tokens')
        names.add(v['name'])
        if not vector(v.get('direction')) or sum(x*x for x in v['direction']) <= 0:
            raise ValueError('view direction must be a finite nonzero vector')
        if 'ortho_scale' in v and not number(v['ortho_scale'], True):
            raise ValueError('locked ortho_scale must be finite and positive')
    frame = c.get('frame')
    if frame is not None and (not isinstance(frame, dict) or not vector(frame.get('center')) or not number(frame.get('extent'), True)):
        raise ValueError('frame requires finite center and positive extent')
    if not number(c.get('exposure')) or not number(c.get('world_strength')) or c['world_strength'] < 0:
        raise ValueError('finite exposure and nonnegative world_strength are required')
    previews = c.get('preview_frame_heights', [])
    if not isinstance(previews, list) or any(type(h) is not int or not 16 <= h <= r[1] for h in previews) or len(set(previews)) != len(previews):
        raise ValueError('preview frame heights must be unique integers between 16 and render height')
    return c


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def selected_objects(collection_name):
    import bpy
    collection = bpy.data.collections.get(collection_name)
    if collection is None:
        raise ValueError('exact collection not found: ' + collection_name)
    selected = {}
    layer = bpy.context.view_layer
    def visit(node, inside=False):
        # Use the visible viewport/render intersection for diagnostic consistency.
        # Do not flatten excluded alternatives back into the review scene.
        if node.exclude or node.hide_viewport or node.collection.hide_viewport or node.collection.hide_render:
            return
        inside = inside or node.collection == collection
        if inside:
            if node.holdout or node.indirect_only:
                raise ValueError('holdout/indirect-only collection needs an explicitly prepared review selection: ' + node.name)
            for obj in node.collection.objects:
                if not obj.hide_render and not obj.hide_viewport and obj.visible_get(view_layer=layer):
                    selected[obj.as_pointer()] = obj
        for child in node.children:
            visit(child, inside)
    visit(layer.layer_collection)
    if not selected:
        raise ValueError('collection is empty, excluded, or has no eligible visible objects in current view layer: ' + collection_name)
    return list(selected.values())


def evaluated_instances(objects):
    import bpy
    allowed = {o.as_pointer() for o in objects}
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for instance in depsgraph.object_instances:
        obj = instance.object
        original = obj.original
        parent = instance.parent.original if instance.parent else None
        if instance.is_instance:
            included = parent is not None and parent.as_pointer() in allowed
        else:
            included = original.as_pointer() in allowed
        if included and obj.type == 'MESH' and not original.hide_render and instance.show_self:
            yield obj, instance.matrix_world.copy(), depsgraph


def audit_scene(collection_name, source):
    import bpy
    from mathutils import Vector
    objects = selected_objects(collection_name)
    rows, points = [], []
    totals = {'vertices': 0, 'triangles': 0, 'instances': 0}
    for obj, matrix, depsgraph in evaluated_instances(objects):
        mesh = obj.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
        try:
            mesh.calc_loop_triangles()
            warnings = []
            coords = [matrix @ v.co for v in mesh.vertices]
            if any(not math.isfinite(v) for p in coords for v in p):
                raise ValueError('nonfinite evaluated vertex coordinates: ' + obj.name)
            points.extend(coords)
            if not obj.material_slots or any(slot.material is None for slot in obj.material_slots):
                warnings.append('no_material')
            if not mesh.uv_layers:
                warnings.append('no_uv_layer')
            if any(p.area <= 0 for p in mesh.polygons):
                warnings.append('zero_area_faces')
            uses = {}
            for poly in mesh.polygons:
                for edge in poly.edge_keys:
                    key = tuple(sorted(edge))
                    uses[key] = uses.get(key, 0) + 1
            boundary = sum(uses.get(tuple(sorted(e.vertices)), 0) == 1 for e in mesh.edges)
            unusual = sum(uses.get(tuple(sorted(e.vertices)), 0) != 2 for e in mesh.edges)
            dims = [max(p[i] for p in coords)-min(p[i] for p in coords) for i in range(3)] if coords else [0, 0, 0]
            rows.append({'name': obj.original.name, 'mesh': obj.original.data.name,
                         'vertices': len(mesh.vertices), 'triangles': len(mesh.loop_triangles),
                         'world_aabb_dimensions': dims, 'matrix_world': [list(r) for r in matrix],
                         'uv_layers': [u.name for u in mesh.uv_layers],
                         'materials': [s.material.name if s.material else None for s in obj.material_slots],
                         'boundary_edges': boundary, 'edges_not_two_faces': unusual,
                         'warnings': warnings})
            totals['vertices'] += len(mesh.vertices)
            totals['triangles'] += len(mesh.loop_triangles)
            totals['instances'] += 1
        finally:
            obj.to_mesh_clear()
    if not rows or not points:
        raise ValueError('no evaluated mesh geometry in current view layer for collection: ' + collection_name)
    lo = [min(p[i] for p in points) for i in range(3)]
    hi = [max(p[i] for p in points) for i in range(3)]
    missing_images = []
    for image in bpy.data.images:
        if image.source == 'FILE' and image.filepath and not image.packed_file:
            path = Path(bpy.path.abspath(image.filepath))
            if '<UDIM>' not in str(path) and not path.exists():
                missing_images.append({'name': image.name, 'path': str(path)})
    return {'schema_version': 1, 'source_path': str(Path(source).resolve()),
            'source_sha256': digest(source), 'blender_version': bpy.app.version_string,
            'collection': collection_name, 'frame': bpy.context.scene.frame_current,
            'units': {'system': bpy.context.scene.unit_settings.system,
                      'scale_length': bpy.context.scene.unit_settings.scale_length},
            'bounds_world': {'min': lo, 'max': hi}, 'evaluated_totals': totals,
            'objects': rows, 'missing_external_images': missing_images,
            'limitations': 'This is not an artistic, historical, UV-quality, collision, or game-readiness verdict. Counts include evaluated mesh instances in the current view-layer/viewport dependency graph; render-only modifier differences, non-mesh forms, and hidden/excluded collections may differ. World AABBs are not local assembly measurements. Open edges may be intentional. Missing-file scan is file-wide, skips UDIM paths, and is not dependency-completeness proof.'}


def render_review(config, source, output):
    import bpy
    from mathutils import Vector
    from itertools import product
    config = json.loads(json.dumps(validate_config(config), allow_nan=False))
    audit = audit_scene(config['collection'], source)
    objects = selected_objects(config['collection'])
    lo, hi = audit['bounds_world']['min'], audit['bounds_world']['max']
    if config.get('frame') is None:
        center = [(a+b)/2 for a, b in zip(lo, hi)]
        extent = math.sqrt(sum((b-a)**2 for a, b in zip(lo, hi))) * 1.16
        if extent <= 0:
            raise ValueError('cannot frame zero-size geometry')
        config['frame'] = {'center': center, 'extent': extent}
    center = Vector(config['frame']['center'])
    extent = config['frame']['extent']
    corners = [Vector(p) for p in product(*zip(lo, hi))]
    aspect = config['resolution'][0]/config['resolution'][1]
    outside_views = []
    for view in config['views']:
        rotation = (-Vector(view['direction']).normalized()).to_track_quat('-Z', 'Y')
        projected = [rotation.conjugated() @ (p-center) for p in corners]
        required_scale = 2 * max(max(abs(p.y) for p in projected), max(abs(p.x) for p in projected)/aspect)
        if 'ortho_scale' not in view:
            view['ortho_scale'] = required_scale * 1.12
        elif required_scale > view['ortho_scale'] * (1+1e-6):
            outside_views.append(view['name'])
    outside = any((p-center).length > extent/2 for p in corners)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    lockpath = output / 'rig-lock.json'
    lockpath.write_text(json.dumps(config, indent=2, allow_nan=False), encoding='utf-8')
    scene = bpy.data.scenes.new('VehicleReview')
    original_scene = bpy.context.scene
    original_frame = original_scene.frame_current
    scene.frame_set(original_frame)
    for obj in objects:
        if obj.type not in ('CAMERA', 'LIGHT'):
            scene.collection.objects.link(obj)
    camera_data = bpy.data.cameras.new('VehicleReviewCamera')
    camera = bpy.data.objects.new('VehicleReviewCamera', camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera_data.type = 'ORTHO'
    # Pin vertical fit: ortho_scale is image height even for landscape frames.
    camera_data.sensor_fit = 'VERTICAL'
    camera_data.ortho_scale = extent * max(1, config['resolution'][1]/config['resolution'][0])
    camera_data.clip_start = max(extent/10000, 0.00001)
    camera_data.clip_end = extent * 30
    world = bpy.data.worlds.new('VehicleReviewWorld')
    if bpy.app.version < (5, 0, 0):
        world.use_nodes = True
    background = world.node_tree.nodes.get('Background')
    scene.world = world
    lights = []
    for name, direction, strength in [('Key', (1, 1, 2), 35), ('Fill', (-1, 0.5, 1), 25), ('Rim', (0, -1, 1.5), 30)]:
        data = bpy.data.lights.new('Review'+name, 'AREA')
        data.energy = strength * extent * extent
        data.shape = 'DISK'
        data.size = extent * 1.2
        light = bpy.data.objects.new('Review'+name, data)
        scene.collection.objects.link(light)
        light.location = center + Vector(direction)*extent
        light.rotation_euler = (center-light.location).to_track_quat('-Z', 'Y').to_euler()
        lights.append(light)
    clay = bpy.data.materials.new('VehicleReviewClay')
    if bpy.app.version < (5, 0, 0):
        clay.use_nodes = True
    shader = clay.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (0.35, 0.35, 0.35, 1)
    shader.inputs['Roughness'].default_value = 0.7
    black = bpy.data.materials.new('VehicleReviewSilhouette')
    if bpy.app.version < (5, 0, 0):
        black.use_nodes = True
    tree = black.node_tree
    tree.nodes.clear()
    emission = tree.nodes.new('ShaderNodeEmission')
    emission.inputs['Color'].default_value = (0, 0, 0, 1)
    target = tree.nodes.new('ShaderNodeOutputMaterial')
    tree.links.new(emission.outputs[0], target.inputs['Surface'])
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = config['samples']
    scene.cycles.seed = 0
    scene.cycles.use_denoising = False
    scene.render.resolution_x, scene.render.resolution_y = config['resolution']
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.film_transparent = False
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = config['exposure']
    scene.view_settings.gamma = 1
    images, matrices = [], {}
    try:
        if bpy.context.window:
            bpy.context.window.scene = scene
        for view in config['views']:
            direction = Vector(view['direction']).normalized()
            camera_data.ortho_scale = view['ortho_scale']
            camera.location = center + direction*extent*3
            camera.rotation_euler = (-direction).to_track_quat('-Z', 'Y').to_euler()
            scene.view_layers[0].update()
            matrices[view['name']] = [list(r) for r in camera.matrix_world]
            for mode in config['modes']:
                scene.view_layers[0].material_override = {'clay': clay, 'silhouette': black}.get(mode)
                silhouette = mode == 'silhouette'
                background.inputs['Color'].default_value = (1, 1, 1, 1) if silhouette else (0.18, 0.18, 0.18, 1)
                background.inputs['Strength'].default_value = 1 if silhouette else config['world_strength']
                scene.view_settings.exposure = 0 if silhouette else config['exposure']
                for light in lights:
                    light.hide_render = silhouette
                path = output / (view['name']+'-'+mode+'.png')
                scene.render.filepath = str(path)
                bpy.ops.render.render(write_still=True, scene=scene.name)
                images.append({'view': view['name'], 'mode': mode, 'path': path.name,
                               'frame_size': config['resolution'], 'sha256': digest(path)})
                for height in config.get('preview_frame_heights', []):
                    image = bpy.data.images.load(str(path), check_existing=False)
                    try:
                        width = max(1, round(config['resolution'][0]*height/config['resolution'][1]))
                        image.scale(width, height)
                        preview = output / (path.stem+'-frame'+str(height)+'.png')
                        image.filepath_raw = str(preview)
                        image.file_format = 'PNG'
                        image.save()
                        images.append({'view': view['name'], 'mode': mode, 'path': preview.name,
                                       'frame_size': [width, height], 'sha256': digest(preview)})
                    finally:
                        bpy.data.images.remove(image)
        report = {'schema_version': 1, 'source_path': str(Path(source).resolve()),
                  'source_sha256': digest(source), 'blender_version': bpy.app.version_string,
                  'tool_sha256': digest(__file__),
                  'rig_sha256': digest(lockpath), 'camera_matrices': matrices,
                  'render_engine': 'CYCLES CPU', 'frame': original_frame,
                  'camera_sensor_fit': camera_data.sensor_fit,
                  'bounds_outside_locked_sphere': outside,
                  'bounds_outside_locked_views': outside_views,
                  'images': images, 'limitations': 'Diagnostic studio renders, not an artistic score or engine test. Preview heights describe the image frame, NOT vehicle pixel height. Orthographic cameras are review cameras, not calibrated reference or gameplay cameras. A locked rig must be reused for comparison; model/engine/version changes can still change rendering. Audit uses viewport evaluation; rendering uses render modifiers. Embedded collection instances may contain their own lights. Non-mesh forms are rendered but not included in automatic mesh bounds.'}
        (output / 'render-manifest.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
        return report
    finally:
        if bpy.context.window:
            bpy.context.window.scene = original_scene
        bpy.data.scenes.remove(scene)
        for obj in [camera]+lights:
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.cameras.remove(camera_data)
        for material in [clay, black]:
            bpy.data.materials.remove(material)
        bpy.data.worlds.remove(world)


def main():
    try:
        import bpy
    except ImportError:
        print('Blender Python is required: blender --background --factory-startup --disable-autoexec --python <this-script> -- <arguments>', file=sys.stderr)
        return 2
    args = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['audit', 'render'])
    parser.add_argument('--blend', required=True)
    parser.add_argument('--collection', help='exact collection name for audit')
    parser.add_argument('--config', help='review rig JSON for render')
    parser.add_argument('--output', required=True)
    opts = parser.parse_args(args)
    try:
        source = Path(opts.blend).resolve(strict=True)
        output = Path(opts.output).resolve()
        if output.exists() or output == source:
            raise ValueError('output already exists; choose a new evidence path')
        bpy.context.preferences.filepaths.use_scripts_auto_execute = False
        bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
        if opts.command == 'render':
            if not opts.config:
                raise ValueError('render requires --config')
            config = validate_config(json.loads(Path(opts.config).read_text(encoding='utf-8')))
            render_review(config, source, output)
        else:
            if not opts.collection:
                raise ValueError('audit requires --collection')
            report = audit_scene(opts.collection, source)
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open('x', encoding='utf-8') as stream:
                json.dump(report, stream, indent=2, allow_nan=False)
        print('WROTE', output)
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
