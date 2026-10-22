"""Render an existing registered camera, never fit or reposition it.

Use disposable Blender Python; see references/registered-rendering.md.
"""
import argparse
import ctypes
import json
import math
import os
from pathlib import Path
import sys
import tempfile

# Blender --python may not put this script's directory on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_vehicle_tools import digest, selected_objects


CAMERA_FIELDS = {'type': 'type', 'lens_mm': 'lens', 'sensor_width_mm': 'sensor_width',
                 'sensor_height_mm': 'sensor_height', 'sensor_fit': 'sensor_fit',
                 'shift_x': 'shift_x', 'shift_y': 'shift_y', 'ortho_scale': 'ortho_scale',
                 'clip_start': 'clip_start', 'clip_end': 'clip_end'}


def validate_spec(spec):
    required = {'schema_version', 'camera', 'collection', 'resolution', 'samples', 'registration_note'}
    if not isinstance(spec, dict) or set(spec) != required:
        raise ValueError('spec requires exactly: ' + ', '.join(sorted(required)))
    if type(spec['schema_version']) is not int or spec['schema_version'] != 1:
        raise ValueError('schema_version must be integer 1')
    for key in ('camera', 'collection'):
        if not isinstance(spec[key], str) or not spec[key].strip() or '\x00' in spec[key]:
            raise ValueError(key + ' must be an exact nonempty name')
    size = spec['resolution']
    if not isinstance(size, list) or len(size) != 2 or any(type(v) is not int or not 16 <= v <= 16384 for v in size):
        raise ValueError('resolution must contain two integers in 16..16384')
    if type(spec['samples']) is not int or not 1 <= spec['samples'] <= 4096:
        raise ValueError('samples must be integer 1..4096')
    note = spec['registration_note']
    if not isinstance(note, str) or len(note.strip()) < 20 or '\x00' in note or note.strip().lower() in ('replace this registration note', 'todo: describe registration'):
        raise ValueError('registration_note must meaningfully describe registration/crop and uncertainty (20+ characters)')
    return spec


def check_paths(source, spec, output):
    source, spec, output = [Path(p).absolute() for p in (source, spec, output)]
    if source.suffix.lower() != '.blend' or not source.is_file() or not spec.is_file():
        raise ValueError('source must be an existing .blend and spec an existing JSON file')
    if len({p.resolve() for p in (source, spec, output)}) != 3:
        raise ValueError('source, spec, output must be distinct')
    if os.path.lexists(output):
        raise ValueError('output must be a NEW directory, never a symlink or existing target')
    if not output.parent.is_dir():
        raise ValueError('output parent must already exist')
    return source.resolve(), spec.resolve(), output


def camera_metadata(camera, name=None):
    data = camera.data
    result = {'name': name or camera.name, 'matrix_world': [list(row) for row in camera.matrix_world]}
    result.update({key: getattr(data, attr) for key, attr in CAMERA_FIELDS.items()})
    if any(not math.isfinite(v) for row in result['matrix_world'] for v in row):
        raise ValueError('nonfinite camera pose')
    for key, value in result.items():
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError('nonfinite camera ' + key)
    return result


def publish_directory(staged, output):
    """Atomic, exclusive directory publication; no overwrite-empty-dir race."""
    if sys.platform.startswith('linux'):
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, 'renameat2', None)
        if rename is None:
            raise RuntimeError('atomic exclusive directory publication requires renameat2')
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(-100, os.fsencode(staged), -100, os.fsencode(output), 1)
    elif sys.platform == 'darwin':
        libc = ctypes.CDLL(None, use_errno=True)
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(os.fsencode(staged), os.fsencode(output), 4)
    elif os.name == 'nt':
        os.rename(staged, output)  # Windows rename refuses existing destinations.
        return
    else:
        raise RuntimeError('no supported atomic exclusive directory publication on this platform')
    if result:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(output))


def validate_camera_dependencies(camera):
    """Conservatively reject animated camera rigs, including constraint targets."""
    seen = set()
    def visit(obj):
        if obj is None or obj.as_pointer() in seen:
            return
        seen.add(obj.as_pointer())
        if obj.animation_data or (obj.data and obj.data.animation_data):
            raise ValueError('animated camera/rig dependency (including drivers) is unsupported: ' + obj.name)
        visit(obj.parent)
        for constraint in obj.constraints:
            for prop in constraint.bl_rna.properties:
                if prop.type == 'POINTER':
                    target = getattr(constraint, prop.identifier, None)
                    if target is not None and hasattr(target, 'matrix_world'):
                        visit(target)
            for item in getattr(constraint, 'targets', []):
                visit(item.target)
    visit(camera)
    visit(camera.data.dof.focus_object)


def validate_scope(collection_name):
    import bpy
    target = bpy.data.collections.get(collection_name)
    def visit(node, inside=False, blocked=False):
        if node.exclude or node.hide_viewport or node.collection.hide_viewport or node.collection.hide_render:
            return
        inside = inside or node.collection == target
        blocked = blocked or node.holdout or node.indirect_only
        if inside and blocked:
            raise ValueError('holdout/indirect-only collection scope or ancestor is unsupported: ' + node.name)
        for child in node.children:
            visit(child, inside, blocked)
    visit(bpy.context.view_layer.layer_collection)


def validate_geometry_object(obj):
    if obj.is_instancer and obj.show_instancer_for_render and not obj.show_instancer_for_viewport:
        raise ValueError('render-visible emitter mesh is absent from viewport evaluation; prepare a matching mesh snapshot: ' + obj.name)
    if getattr(obj, 'is_holdout', False):
        raise ValueError('holdout object scope is unsupported: ' + obj.name)
    if obj.type in {'CURVE','SURFACE','FONT','META','VOLUME','POINTCLOUD','GREASEPENCIL'}:
        raise ValueError('prepare mesh-only geometry before rendering: ' + obj.name)
    for modifier in obj.modifiers:
        if modifier.show_render != modifier.show_viewport or (modifier.type == 'SUBSURF' and modifier.show_render and modifier.levels != modifier.render_levels):
            raise ValueError('viewport/render modifier divergence; prepare matching evaluated geometry: ' + obj.name)


def eligible_instances(objects):
    """Filter evaluated instances without resurrecting hidden master collections."""
    import bpy
    allowed = {obj.as_pointer(): obj for obj in objects}
    master_members = {}
    def members(collection, stack=()):
        if collection.as_pointer() in stack or collection.hide_render or collection.hide_viewport:
            return set()
        stack = (*stack, collection.as_pointer())
        result = set()
        for obj in collection.objects:
            if obj.hide_render or obj.hide_viewport:
                continue
            if obj.instance_type != 'NONE' and not obj.visible_camera:
                raise ValueError('camera-hidden nested instancer requires a prepared render-matched mesh snapshot: ' + obj.name)
            validate_geometry_object(obj)
            result.add(obj.as_pointer())
            if obj.instance_type == 'COLLECTION' and obj.instance_collection:
                result.update(members(obj.instance_collection, stack))
        for child in collection.children:
            result.update(members(child, stack))
        return result
    for pointer, obj in allowed.items():
        if obj.visible_camera and obj.instance_type == 'COLLECTION' and obj.instance_collection:
            master_members[pointer] = members(obj.instance_collection)
    graph = bpy.context.evaluated_depsgraph_get()
    for instance in graph.object_instances:
        evaluated = instance.object
        original = evaluated.original
        if instance.is_instance:
            parent = instance.parent.original if instance.parent else None
            if parent is None or parent.as_pointer() not in allowed or not parent.visible_camera:
                continue
            permitted = master_members.get(parent.as_pointer())
            if permitted is not None and original.as_pointer() not in permitted:
                continue
        elif original.as_pointer() not in allowed:
            continue
        elif original.parent and original.parent.instance_type in {'VERTS','FACES'}:
            # Blender renders the generated copies, not an extra source child.
            continue
        self_visible = (original.show_instancer_for_render
                        if not instance.is_instance and original.is_instancer else instance.show_self)
        if evaluated.type == 'MESH' and original.visible_camera and not original.hide_render and not original.hide_viewport and self_visible:
            yield evaluated, instance.matrix_world.copy(), graph


def render_loaded(spec, source, stage, diagnostic_lighting=None):
    import bpy
    import numpy as np
    original = bpy.context.scene
    layer = bpy.context.view_layer
    original_window = bpy.context.window
    camera = original.objects.get(spec['camera'])
    if camera is None or camera.type != 'CAMERA' or camera.data.type not in ('PERSP', 'ORTHO'):
        raise ValueError('existing named PERSP/ORTHO camera required')
    render = original.render
    if render.resolution_percentage != 100 or [render.resolution_x, render.resolution_y] != spec['resolution']:
        raise ValueError('resolution must match scene full frame at 100 percent')
    if render.use_border or render.use_crop_to_border or render.use_multiview:
        raise ValueError('border/crop/stereo multiview rendering is unsupported')
    if render.pixel_aspect_x != render.pixel_aspect_y:
        raise ValueError('square pixels required')
    layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    evaluated_camera = camera.evaluated_get(graph)
    before = camera_metadata(evaluated_camera, camera.name)
    validate_camera_dependencies(camera)
    validate_scope(spec['collection'])
    objects = selected_objects(spec['collection'])
    for obj in objects:
        validate_geometry_object(obj)
    # Freeze evaluated geometry into a separate scene. Never hide source masters.
    scene = bpy.data.scenes.new('RegisteredDiagnostic')
    owned_objects, owned_meshes, owned_materials, owned_cameras, owned_lights, owned_worlds = [], [], [], [], [], []
    expected_transforms = []
    def own_object(name, data):
        obj = bpy.data.objects.new(name, data)
        owned_objects.append(obj)
        scene.collection.objects.link(obj)
        return obj
    try:
        scene.frame_set(original.frame_current, subframe=original.frame_subframe)
        count = 0
        for evaluated, matrix, depsgraph in eligible_instances(objects):
            validate_geometry_object(evaluated.original)
            mesh = bpy.data.meshes.new_from_object(evaluated, preserve_all_data_layers=True, depsgraph=depsgraph)
            owned_meshes.append(mesh)
            if not mesh.polygons:
                continue
            if any(not math.isfinite(v) for row in matrix for v in row) or any(not math.isfinite(v) for vertex in mesh.vertices for v in vertex.co):
                raise ValueError('nonfinite evaluated geometry')
            obj = own_object('Subject_' + str(count), mesh)
            obj.matrix_world = matrix
            expected_transforms.append((obj,matrix.copy()))
            # Preserve object-linked slots as actual material assignments.
            mesh.materials.clear()
            for slot in evaluated.material_slots:
                mesh.materials.append(slot.material)
            count += 1
        if count == 0:
            raise ValueError('no eligible evaluated mesh geometry')
        data = evaluated_camera.data.copy()
        owned_cameras.append(data)
        data.animation_data_clear()
        frozen = own_object('RegisteredCameraSnapshot', data)
        frozen.matrix_world = evaluated_camera.matrix_world.copy()
        scene.camera = frozen
        scene.render.resolution_x, scene.render.resolution_y = spec['resolution']
        scene.render.resolution_percentage = 100
        scene.render.pixel_aspect_x = render.pixel_aspect_x
        scene.render.pixel_aspect_y = render.pixel_aspect_y
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'CPU'
        scene.cycles.samples = spec['samples']
        scene.cycles.seed = 0
        scene.cycles.use_denoising = False
        scene.render.film_transparent = False
        scene.render.image_settings.file_format = 'PNG'
        scene.render.image_settings.color_mode = 'RGBA'
        scene.render.image_settings.color_depth = '8'
        scene.render.threads_mode = 'FIXED'
        scene.render.threads = min(8, os.cpu_count() or 1)
        scene.view_settings.view_transform = 'Standard'
        scene.view_settings.look = 'None'
        scene.view_settings.exposure = 0
        scene.view_settings.gamma = 1
        if diagnostic_lighting is None:
            if original.world:
                scene.world = original.world.copy()
                owned_worlds.append(scene.world)
            else:
                scene.world = bpy.data.worlds.new('DiagnosticAmbient')
                owned_worlds.append(scene.world)
                scene.world.color = (.25,.25,.25)
        light_count = 0
        visible_scoped = set()
        def collect_visible(node):
            if node.exclude or node.hide_viewport or node.collection.hide_viewport or node.collection.hide_render:
                return
            if not node.holdout and not node.indirect_only:
                visible_scoped.update(obj.as_pointer() for obj in node.collection.objects)
            for child in node.children:
                collect_visible(child)
        collect_visible(layer.layer_collection)
        for light in original.objects:
            if diagnostic_lighting is None and light.type == 'LIGHT' and light.as_pointer() in visible_scoped and not light.hide_render and not light.hide_viewport and light.visible_get(view_layer=layer):
                lightdata = light.evaluated_get(graph).data.copy()
                lightdata.animation_data_clear()
                owned_lights.append(lightdata)
                obj = own_object('DiagnosticLight', lightdata)
                obj.matrix_world = light.evaluated_get(graph).matrix_world.copy()
                light_count += 1
        if diagnostic_lighting is not None:
            from mathutils import Vector
            scene.world = bpy.data.worlds.new('ExplicitDiagnosticWorld')
            owned_worlds.append(scene.world)
            if scene.world.node_tree is None:
                scene.world.use_nodes = True
            background = next(n for n in scene.world.node_tree.nodes if n.type == 'BACKGROUND')
            background.inputs['Color'].default_value = (*diagnostic_lighting['world_color'], 1)
            background.inputs['Strength'].default_value = diagnostic_lighting['world_strength']
            for item in diagnostic_lighting['lights']:
                lightdata = bpy.data.lights.new('ExplicitDiagnosticArea', 'AREA')
                owned_lights.append(lightdata)
                lightdata.energy = item['power_w']
                lightdata.shape = 'DISK'
                lightdata.size = item['size']
                lightdata.color = item['color']
                obj = own_object('ExplicitDiagnosticArea', lightdata)
                obj.location = item['position']
                obj.rotation_euler = (Vector(item['target']) - obj.location).to_track_quat('-Z', 'Y').to_euler()
                light_count += 1
        if original_window:
            original_window.scene = scene
        scene.view_layers[0].update()
        for obj, matrix in expected_transforms:
            if any(not math.isclose(a,b,rel_tol=1e-6,abs_tol=1e-6)
                   for row_a,row_b in zip(obj.matrix_world,matrix) for a,b in zip(row_a,row_b)):
                raise ValueError('isolated geometry transform changed (shear is unsupported); bake a prepared snapshot')
        actual = camera_metadata(frozen.evaluated_get(bpy.context.evaluated_depsgraph_get()), camera.name)
        if any(actual[key] != before[key] for key in actual if key != 'matrix_world') or any(
                not math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6)
                for row_a, row_b in zip(actual['matrix_world'], before['matrix_world']) for a, b in zip(row_a,row_b)):
            raise ValueError('camera snapshot changed evaluated pose/projection beyond Blender float precision')
        def rendered_signature():
            if scene.camera != frozen:
                return None
            return (camera_metadata(frozen, camera.name),
                    [scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage,
                     scene.render.pixel_aspect_x, scene.render.pixel_aspect_y,
                     scene.render.use_border, scene.render.use_crop_to_border],
                    [data.dof.use_dof, data.dof.focus_distance, data.dof.aperture_fstop])
        locked_signature = rendered_signature()
        def guarded_render():
            violations = []
            def check_event(rendered_scene, *unused):
                if rendered_scene == scene and rendered_signature() != locked_signature:
                    violations.append('camera/projection/resolution changed during render')
            check_event(scene)
            bpy.app.handlers.render_pre.append(check_event)
            bpy.app.handlers.render_post.append(check_event)
            try:
                bpy.ops.render.render(write_still=True, scene=scene.name)
                check_event(scene)
                with bpy.context.temp_override(scene=original, view_layer=layer):
                    layer.update()
                    source_now = camera_metadata(camera.evaluated_get(bpy.context.evaluated_depsgraph_get()), camera.name)
                if source_now != before:
                    violations.append('source camera changed during render')
                if violations:
                    raise ValueError(violations[0])
            finally:
                bpy.app.handlers.render_pre.remove(check_event)
                bpy.app.handlers.render_post.remove(check_event)
        scene.render.filepath = str(stage / 'detail.png')
        guarded_render()
        material = bpy.data.materials.new('OpaqueGeometryOnly')
        owned_materials.append(material)
        if bpy.app.version < (5, 0, 0):
            material.use_nodes = True
        tree = material.node_tree
        tree.nodes.clear()
        emission = tree.nodes.new('ShaderNodeEmission')
        emission.inputs['Color'].default_value = (1,1,1,1)
        target = tree.nodes.new('ShaderNodeOutputMaterial')
        tree.links.new(emission.outputs[0], target.inputs['Surface'])
        scene.view_layers[0].material_override = material
        mask_world = bpy.data.worlds.new('GeometryBlackBackground')
        owned_worlds.append(mask_world)
        mask_world.color = (0,0,0)
        scene.world = mask_world
        for obj in owned_objects:
            if obj.type == 'LIGHT':
                obj.hide_render = True
        scene.render.filepath = str(stage / 'geometry.png')
        guarded_render()
        image = bpy.data.images.load(str(stage / 'geometry.png'), check_existing=False)
        try:
            width, height = image.size
            pixels = np.array(image.pixels[:], dtype=np.float32).reshape((-1,4))
            foreground = pixels[:,:3].max(axis=1) >= .5
            if not foreground.any():
                raise ValueError('empty foreground at registered camera; no camera refit performed')
            pixels[:,:3] = foreground[:,None]
            pixels[:,3] = 1
            image.pixels.foreach_set(pixels.ravel())
            image.filepath_raw = str(stage / 'mask.png')
            image.file_format = 'PNG'
            image.save()
        finally:
            bpy.data.images.remove(image)
        (stage / 'geometry.png').unlink()
        return {'schema_version': 1, 'kind': 'registered_camera_render',
                'source': {'path': str(source), 'sha256': digest(source)},
                'camera': actual, 'image_size': [width,height],
                'artifacts': {key: {'path': key+'.png', 'sha256': digest(stage / (key+'.png'))} for key in ('mask','detail')},
                'registration_note': spec['registration_note'], 'collection': spec['collection'],
                'frame': original.frame_current, 'frame_subframe': original.frame_subframe,
                'pixel_aspect': [render.pixel_aspect_x, render.pixel_aspect_y],
                'render_engine': 'CYCLES CPU', 'samples': spec['samples'], 'mesh_instances': count,
                'lighting': ({'mode': 'explicit_diagnostic', 'settings': diagnostic_lighting,
                              'visible_source_lights': 0, 'explicit_lights': light_count}
                             if diagnostic_lighting is not None else
                             {'world': 'source copy' if original.world else 'diagnostic ambient', 'visible_source_lights': light_count}),
                'limitations': 'Material diagnostic, not photometric photo matching. Frozen evaluated viewport mesh/instance geometry; configured source or explicit diagnostic world/direct lights used; instanced lights omitted. Standard color transform, no compositor or ground/clutter outside chosen collection. Binary mask thresholds opaque emission geometry at linear 0.5; no material transparency, displacement, shadows or background geometry. No reference measurement or approval is established.'}
    finally:
        if original_window:
            original_window.scene = original
        bpy.data.scenes.remove(scene)
        for obj in owned_objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        for datablocks, items in ((bpy.data.meshes,owned_meshes),(bpy.data.materials,owned_materials),
                                 (bpy.data.cameras,owned_cameras),(bpy.data.lights,owned_lights),(bpy.data.worlds,owned_worlds)):
            for item in items:
                datablocks.remove(item)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('source','spec','output'):
        parser.add_argument('--'+key, required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        import bpy
        bpy.context.preferences.filepaths.use_scripts_auto_execute = False
        source, specpath, output = check_paths(args.source, args.spec, args.output)
        spec = validate_spec(json.loads(specpath.read_text(encoding='utf8')))
        source_hash = digest(source)
        bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
        with tempfile.TemporaryDirectory(prefix='.registered-', dir=output.parent) as temporary:
            stage = Path(temporary) / 'result'
            stage.mkdir()
            report = render_loaded(spec, source, stage)
            if digest(source) != source_hash:
                raise ValueError('source changed during rendering; refusing publication')
            report['source']['sha256'] = source_hash
            (stage / 'render-manifest.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf8')
            publish_directory(stage, output)
        print('WROTE', output)
        return 0
    except (ValueError, OSError, RuntimeError, ImportError, KeyError) as exc:
        print('ERROR:', exc, file=sys.stderr)
        return 2


if __name__ == '__main__':
    cli = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]
    raise SystemExit(main(cli))
