"""Real-bpy tests. All images/scenes are synthetic mechanics fixtures, not asset-quality evidence."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

try:
    import bpy
except ImportError:
    bpy = None

MODULE = Path(__file__).with_name('build_pbr.py')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def png(path, rgba=(120, 120, 120, 255), size=(4, 3)):
    """Tiny, explicitly synthetic RGBA PNG using only the standard library."""
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    w, h = size
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) +
                     chunk(b'IDAT', zlib.compress((b'\0' + bytes(rgba) * w) * h)) + chunk(b'IEND', b''))
    return {'path': path.name, 'sha256': sha(path), 'size': list(size)}


@unittest.skipIf(bpy is None, 'requires real bpy; uv run --offline --python 3.13 --with bpy python -m unittest discover -s scripts -p test_build_pbr.py -v')
class PBRTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), 'PBR builder implementation does not exist')
        module = importlib.util.spec_from_file_location('pbr_builder', MODULE)
        self.tool = importlib.util.module_from_spec(module)
        module.loader.exec_module(self.tool)
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.blend'
        self.output = self.root / 'new.blend'
        self.report = self.root / 'new.json'
        self.spec_path = self.root / 'spec.json'
        bpy.ops.wm.read_factory_settings(use_empty=True)
        mesh = bpy.data.meshes.new('HullMesh')
        mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
        uv = mesh.uv_layers.new(name='SurfaceUV')
        for item, co in zip(uv.data, [(0, 0), (1, 0), (1, 1), (0, 1)]):
            item.uv = co
        for name in ('KeepA', 'KeepB'):
            mat = bpy.data.materials.new(name)
            mat.diffuse_color = (.1, .2, .3, 1)
            mesh.materials.append(mat)
        mesh.polygons[0].material_index = 1
        obj = bpy.data.objects.new('Hull', mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.modifiers.new('KeepBevel', 'BEVEL').width = .0123
        self.save_source()

    def tearDown(self):
        if hasattr(self, 'tmp'):
            self.tmp.cleanup()

    def save_source(self):
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        self.source_hash = sha(self.source)

    def config(self):
        return {'schema_version': 1, 'materials': [{'name': 'NewPaint', 'base_color': [.15, .25, .35, 1],
                'roughness': .65, 'metallic': .0}],
                'bindings': [{'object': 'Hull', 'material': 'NewPaint', 'slot': 1}]}

    def run_tool(self, spec=...):
        self.spec_path.write_text(json.dumps(self.config() if spec is ... else spec))
        return self.tool.main(['--source', str(self.source), '--spec', str(self.spec_path),
                               '--output', str(self.output), '--report', str(self.report)])

    def reopen(self):
        bpy.ops.wm.open_mainfile(filepath=str(self.output), use_scripts=False)

    def test_constants_create_new_principled_material_preserving_source_slots_and_geometry(self):
        self.assertEqual(self.run_tool(), 0)
        self.assertEqual(sha(self.source), self.source_hash)
        report = json.loads(self.report.read_text())
        self.assertEqual(report['status'], 'built')
        self.assertEqual(report['lineage']['source_sha256'], self.source_hash)
        self.assertEqual(report['lineage']['output_sha256'], sha(self.output))
        self.assertEqual(report['materials'][0]['representation'], 'untextured_constants')
        self.reopen()
        obj = bpy.data.objects['Hull']
        self.assertEqual([slot.material.name for slot in obj.material_slots], ['KeepA', 'NewPaint'])
        self.assertEqual([mat.name for mat in obj.data.materials], ['KeepA', 'KeepB'])
        self.assertEqual(obj.material_slots[1].link, 'OBJECT')
        self.assertEqual(obj.data.polygons[0].material_index, 1)
        self.assertEqual(len(obj.data.vertices), 4)
        self.assertEqual(len(obj.modifiers), 1)
        self.assertAlmostEqual(obj.modifiers['KeepBevel'].width, .0123)
        mat = bpy.data.materials['NewPaint']
        principled = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        output = next(n for n in mat.node_tree.nodes if n.type == 'OUTPUT_MATERIAL')
        self.assertEqual(output.inputs['Surface'].links[0].from_node, principled)
        self.assertAlmostEqual(principled.inputs['Roughness'].default_value, .65)
        self.assertEqual(tuple(round(v, 4) for v in principled.inputs['Base Color'].default_value), (.15, .25, .35, 1))
        self.assertEqual(tuple(round(v, 4) for v in bpy.data.materials['KeepB'].diffuse_color), (.1, .2, .3, 1))

    def test_texture_links_colorspaces_uv_and_shared_path_image_isolation_survive_reopen(self):
        mapping = png(self.root / 'synthetic-gray.png')
        existing = bpy.data.images.load(str(self.root / mapping['path']), check_existing=False)
        existing.name = 'ExistingSharedImage'
        existing.colorspace_settings.name = 'sRGB'
        existing.use_fake_user = True
        self.save_source()
        config = self.config()
        row = config['materials'][0]
        row.update(base_color=copy.deepcopy(mapping), roughness=copy.deepcopy(mapping),
                   metallic=copy.deepcopy(mapping), uv_map='SurfaceUV')
        self.assertEqual(self.run_tool(config), 0)
        self.reopen()
        nodes = bpy.data.materials['NewPaint'].node_tree.nodes
        shader = next(n for n in nodes if n.type == 'BSDF_PRINCIPLED')
        maps = {n.label: n for n in nodes if n.type == 'TEX_IMAGE'}
        self.assertEqual(set(maps), {'base_color', 'roughness', 'metallic'})
        self.assertEqual(len({n.image.as_pointer() for n in maps.values()}), 3)
        self.assertEqual(bpy.data.images['ExistingSharedImage'].colorspace_settings.name, 'sRGB')
        for role, node in maps.items():
            self.assertNotEqual(node.image.name, 'ExistingSharedImage')
            self.assertEqual(node.image.colorspace_settings.name, 'sRGB' if role == 'base_color' else 'Non-Color')
            self.assertEqual(list(node.image.size), [4, 3])
            self.assertEqual(Path(node.image.filepath), self.root / mapping['path'])
            uv = node.inputs['Vector'].links[0].from_node
            self.assertEqual(uv.type, 'UVMAP')
            self.assertEqual(uv.uv_map, 'SurfaceUV')
        self.assertEqual(shader.inputs['Base Color'].links[0].from_node, maps['base_color'])
        self.assertEqual(shader.inputs['Alpha'].links[0].from_socket.name, 'Alpha')
        for name, role in (('Roughness', 'roughness'), ('Metallic', 'metallic')):
            separate = shader.inputs[name].links[0].from_node
            self.assertEqual(separate.type, 'SEPARATE_COLOR')
            self.assertEqual(shader.inputs[name].links[0].from_socket.name, 'Red')
            self.assertEqual(separate.inputs['Color'].links[0].from_node, maps[role])
        report = json.loads(self.report.read_text())
        self.assertEqual(report['materials'][0]['representation'], 'texture_backed')
        for entry in report['materials'][0]['maps']:
            self.assertEqual(entry['sha256'], mapping['sha256'])
            self.assertEqual(entry['size'], [4, 3])
            self.assertEqual(entry['path'], str(self.root / mapping['path']))
        self.assertEqual(sha(self.source), self.source_hash)

    def test_maps_require_real_files_sha256_and_bounded_integer_dimensions_before_open(self):
        good = png(self.root / 'synthetic-gray.png')
        variants = []
        for field, values in (('path', ['', None, True, 'missing.png', '.', 'bad.tiff']),
                              ('sha256', ['', None, True, 'g' * 64, 'A' * 64, '0' * 64]),
                              ('size', [None, [4], [True, 3], [4.0, 3], [0, 3], [32769, 3]])):
            for value in values:
                bad = copy.deepcopy(good)
                bad[field] = value
                variants.append(bad)
        (self.root / 'bad.tiff').write_bytes(b'II*\0unsupported')
        bad_signature = self.root / 'fake.png'
        bad_signature.write_bytes(b'not an image')
        variants.append({'path': bad_signature.name, 'sha256': sha(bad_signature), 'size': [4, 3]})
        for extra in ('channel', 'packed', 'gloss', 'colorspace'):
            bad = copy.deepcopy(good)
            bad[extra] = 'ambiguous'
            variants.append(bad)
        for mapping in variants:
            config = self.config()
            config['materials'][0].update(base_color=mapping, uv_map='SurfaceUV')
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                self.tool.validate(config, self.spec_path)
        marker = bpy.data.objects.new('NotOpened', None)
        bpy.context.scene.collection.objects.link(marker)
        config = self.config()
        config['materials'][0].update(base_color={**good, 'sha256': '0' * 64}, uv_map='SurfaceUV')
        self.assertEqual(self.run_tool(config), 2)
        self.assertIn('NotOpened', bpy.data.objects)
        self.assertFalse(self.output.exists())

    def test_decoded_dimensions_must_match_claim_not_just_metadata(self):
        mapping = png(self.root / 'synthetic-gray.png')
        mapping['size'] = [4, 4]
        config = self.config()
        config['materials'][0].update(base_color=mapping, uv_map='SurfaceUV')
        self.assertEqual(self.run_tool(config), 2)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.report.exists())

    def test_failed_image_decode_is_not_success(self):
        path = self.root / 'truncated.png'
        path.write_bytes(b'\x89PNG\r\n\x1a\n')
        config = self.config()
        config['materials'][0].update(base_color={'path': path.name, 'sha256': sha(path), 'size': [4, 3]}, uv_map='SurfaceUV')
        self.assertEqual(self.run_tool(config), 2)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.report.exists())

    def test_scene_preflight_rejects_conflicts_missing_uv_and_invalid_targets_without_edits(self):
        mapping = png(self.root / 'synthetic-gray.png')
        variants = []
        for kind in ('owned_material', 'missing_object', 'nonmesh', 'missing_slot', 'duplicate_binding', 'missing_uv'):
            config = self.config()
            if kind == 'owned_material':
                config['materials'][0]['name'] = 'KeepB'
                config['bindings'][0]['material'] = 'KeepB'
            elif kind == 'missing_object':
                config['bindings'][0]['object'] = 'NoSuchObject'
            elif kind == 'nonmesh':
                config['bindings'][0]['object'] = 'NotMesh'
            elif kind == 'missing_slot':
                config['bindings'][0]['slot'] = 2
            elif kind == 'duplicate_binding':
                config['bindings'].append(copy.deepcopy(config['bindings'][0]))
            else:
                config['materials'][0].update(base_color=mapping, uv_map='DoesNotExist')
            variants.append((kind, config))
        for kind, config in variants:
            bpy.ops.wm.open_mainfile(filepath=str(self.source), use_scripts=False)
            obj = bpy.data.objects.new('NotMesh', None)
            bpy.context.scene.collection.objects.link(obj)
            with self.subTest(kind=kind):
                config = self.tool.validate(copy.deepcopy(config), self.spec_path)
                with self.assertRaises(ValueError):
                    self.tool.build(config)
                self.assertNotIn('NewPaint', bpy.data.materials)
                self.assertEqual([s.material.name for s in bpy.data.objects['Hull'].material_slots], ['KeepA', 'KeepB'])
        self.assertEqual(sha(self.source), self.source_hash)

    def test_append_is_explicit_preserves_existing_slots_and_reports_actual_new_index(self):
        config = self.config()
        config['bindings'][0] = {'object': 'Hull', 'material': 'NewPaint', 'append': True}
        self.assertEqual(self.run_tool(config), 0)
        self.reopen()
        obj = bpy.data.objects['Hull']
        self.assertEqual([s.material.name for s in obj.material_slots], ['KeepA', 'KeepB', 'NewPaint'])
        self.assertEqual(obj.data.polygons[0].material_index, 1, 'append must not silently reassign faces')
        report = json.loads(self.report.read_text())
        self.assertEqual(report['bindings'][0]['slot'], 2)
        self.assertEqual(report['bindings'][0]['policy'], 'append')

    def test_shared_mesh_existing_slot_override_does_not_touch_unselected_object(self):
        other = bpy.data.objects.new('Unselected', bpy.data.objects['Hull'].data)
        bpy.context.scene.collection.objects.link(other)
        self.save_source()
        self.assertEqual(self.run_tool(), 0)
        self.reopen()
        self.assertEqual([s.material.name for s in bpy.data.objects['Unselected'].material_slots], ['KeepA', 'KeepB'])
        self.assertEqual([s.material.name for s in bpy.data.objects['Hull'].material_slots], ['KeepA', 'NewPaint'])
        self.assertEqual(bpy.data.objects['Hull'].data, bpy.data.objects['Unselected'].data)
        bpy.ops.wm.open_mainfile(filepath=str(self.source), use_scripts=False)
        config = self.config()
        config['bindings'][0] = {'object': 'Hull', 'material': 'NewPaint', 'append': True}
        with self.assertRaisesRegex(ValueError, 'shared'):
            self.tool.build(self.tool.validate(config, self.spec_path))
        self.assertNotIn('NewPaint', bpy.data.materials)

    def test_linked_object_is_rejected_without_material_edits(self):
        library = self.root / 'library.blend'
        bpy.data.libraries.write(str(library), {bpy.data.objects['Hull']})
        bpy.data.objects.remove(bpy.data.objects['Hull'], do_unlink=True)
        with bpy.data.libraries.load(str(library), link=True) as (_, data):
            data.objects = ['Hull']
        bpy.context.scene.collection.objects.link(data.objects[0])
        self.assertIsNotNone(data.objects[0].library)
        self.save_source()
        self.assertEqual(self.run_tool(), 2)
        self.assertFalse(self.output.exists())
        self.assertNotIn('NewPaint', bpy.data.materials)
        self.assertEqual(sha(self.source), self.source_hash)

    def test_tangent_normal_opengl_directx_green_inversion_nodes_are_explicit(self):
        normal = png(self.root / 'synthetic-normal.png', (128, 230, 204, 255))
        config = self.config()
        config['materials'][0].update(normal={**normal, 'convention': 'OpenGL'}, uv_map='SurfaceUV')
        directx = copy.deepcopy(config['materials'][0])
        directx.update(name='DXPaint', normal={**normal, 'convention': 'DirectX'})
        config['materials'].append(directx)
        config['bindings'].append({'object': 'Hull', 'material': 'DXPaint', 'slot': 0})
        self.assertEqual(self.run_tool(config), 0)
        self.reopen()
        for name, convention in (('NewPaint', 'OpenGL'), ('DXPaint', 'DirectX')):
            nodes = bpy.data.materials[name].node_tree.nodes
            shader = next(n for n in nodes if n.type == 'BSDF_PRINCIPLED')
            normal_map = shader.inputs['Normal'].links[0].from_node
            self.assertEqual(normal_map.type, 'NORMAL_MAP')
            self.assertEqual(normal_map.space, 'TANGENT')
            self.assertEqual(normal_map.uv_map, 'SurfaceUV')
            self.assertEqual(normal_map.inputs['Strength'].default_value, 1)
            texture = next(n for n in nodes if n.type == 'TEX_IMAGE')
            self.assertEqual(texture.image.colorspace_settings.name, 'Non-Color')
            incoming = normal_map.inputs['Color'].links[0].from_node
            if convention == 'OpenGL':
                self.assertEqual(incoming, texture)
            else:
                self.assertEqual(incoming.type, 'COMBINE_COLOR')
                invert = incoming.inputs['Green'].links[0].from_node
                self.assertEqual(invert.type, 'MATH')
                self.assertEqual(invert.operation, 'SUBTRACT')
                self.assertEqual(invert.inputs[0].default_value, 1)
                self.assertEqual(invert.inputs[1].links[0].from_socket.name, 'Green')
                self.assertEqual(incoming.inputs['Red'].links[0].from_socket.name, 'Red')
                self.assertEqual(incoming.inputs['Blue'].links[0].from_socket.name, 'Blue')
                separate = invert.inputs[1].links[0].from_node
                self.assertEqual(separate.inputs['Color'].links[0].from_node, texture)
        reports = json.loads(self.report.read_text())['materials']
        self.assertEqual([r['maps'][0]['normal_convention'] for r in reports], ['OpenGL', 'DirectX'])

    def test_colored_scalar_maps_are_rejected_instead_of_guessing_packed_channels(self):
        mapping = png(self.root / 'synthetic-packed.png', (20, 180, 80, 255))
        config = self.config()
        config['materials'][0].update(roughness=mapping, uv_map='SurfaceUV')
        self.assertEqual(self.run_tool(config), 2)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.report.exists())

    def test_cpu_cycles_render_consumes_texture_and_normal_green_sign(self):
        """Synthetic mechanics test: actual Principled shading, not visual approval."""
        from mathutils import Vector
        normal = png(self.root / 'synthetic-normal.png', (128, 230, 204, 255))
        albedo = png(self.root / 'synthetic-red.png', (220, 30, 15, 255))
        config = self.config()
        config['materials'][0].update(base_color=albedo, roughness=1,
            normal={**normal, 'convention': 'OpenGL'}, uv_map='SurfaceUV')
        directx = copy.deepcopy(config['materials'][0])
        directx.update(name='DXPaint', normal={**normal, 'convention': 'DirectX'})
        config['materials'].append(directx)
        config['bindings'].append({'object': 'Hull', 'material': 'DXPaint', 'slot': 0})
        self.assertEqual(self.run_tool(config), 0)
        self.reopen()
        scene = bpy.context.scene
        camera = bpy.data.objects.new('SyntheticCamera', bpy.data.cameras.new('SyntheticCamera'))
        scene.collection.objects.link(camera)
        camera.location = (0, 0, 4)
        camera.data.type = 'ORTHO'
        camera.data.ortho_scale = 2.5
        scene.camera = camera
        sun = bpy.data.objects.new('SyntheticSun', bpy.data.lights.new('SyntheticSun', 'SUN'))
        scene.collection.objects.link(sun)
        sun.rotation_euler = Vector((0, 1, 1)).to_track_quat('Z', 'Y').to_euler()
        sun.data.energy = 2
        scene.world = bpy.data.worlds.new('BlackWorld')
        scene.world.color = (0, 0, 0)
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'CPU'
        scene.cycles.samples = 8
        scene.cycles.use_denoising = False
        scene.cycles.seed = 1
        scene.render.threads_mode = 'FIXED'
        scene.render.threads = 2
        scene.render.resolution_x = scene.render.resolution_y = 32
        scene.render.resolution_percentage = 100
        scene.view_settings.view_transform = 'Standard'
        scene.view_settings.look = 'None'
        scene.render.image_settings.file_format = 'PNG'
        pixels = {}
        for material in ('NewPaint', 'DXPaint'):
            obj = bpy.data.objects['Hull']
            obj.material_slots[1].material = bpy.data.materials[material]
            path = self.root / (material + '-synthetic.png')
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            self.assertTrue(path.is_file())
            image = bpy.data.images.load(str(path), check_existing=False)
            i = (16 * 32 + 16) * 4
            pixels[material] = list(image.pixels[i:i + 3])
            bpy.data.images.remove(image)
        self.assertGreater(pixels['NewPaint'][0], pixels['NewPaint'][1] * 3)
        self.assertGreater(pixels['NewPaint'][0], pixels['DXPaint'][0] * 2,
                           'OpenGL +green must face +Y sun; DirectX must invert green')
        print('SYNTHETIC_PBR_CPU_RENDER=' + json.dumps(pixels, sort_keys=True))

    def test_duplicate_json_keys_are_rejected_before_source_open(self):
        marker = bpy.data.objects.new('NotOpened', None)
        bpy.context.scene.collection.objects.link(marker)
        raw = json.dumps(self.config()).replace('"roughness": 0.65', '"roughness": 0.65, "roughness": 0.2')
        self.spec_path.write_text(raw)
        result = self.tool.main(['--source', str(self.source), '--spec', str(self.spec_path),
                                '--output', str(self.output), '--report', str(self.report)])
        self.assertEqual(result, 2)
        self.assertIn('NotOpened', bpy.data.objects)
        self.assertFalse(self.output.exists())

    def test_texture_changed_after_validation_is_rejected_before_build(self):
        mapping = png(self.root / 'synthetic-gray.png')
        config = self.config()
        config['materials'][0].update(base_color=mapping, uv_map='SurfaceUV')
        config = self.tool.validate(config, self.spec_path)
        png(self.root / 'synthetic-gray.png', (240, 10, 10, 255))
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.tool.build(config)
        self.assertNotIn('NewPaint', bpy.data.materials)

    def test_every_new_material_must_have_explicit_binding(self):
        config = self.config()
        unused = copy.deepcopy(config['materials'][0])
        unused['name'] = 'UnboundWouldDisappearOnSave'
        config['materials'].append(unused)
        with self.assertRaisesRegex(ValueError, 'bound'):
            self.tool.validate(config, self.spec_path)

    def test_existing_outputs_source_alias_and_dangling_symlink_are_never_overwritten(self):
        for path in (self.output, self.report):
            path.write_bytes(b'keep exactly')
            self.assertEqual(self.run_tool(), 2)
            self.assertEqual(path.read_bytes(), b'keep exactly')
            path.unlink()
        self.output.symlink_to(self.root / 'absent.blend')
        self.assertEqual(self.run_tool(), 2)
        self.assertTrue(self.output.is_symlink())
        self.output.unlink()
        self.output.symlink_to(self.source)
        self.assertEqual(self.run_tool(), 2)
        self.assertEqual(sha(self.source), self.source_hash)
        self.output.unlink()
        self.spec_path.write_text(json.dumps(self.config()))
        self.assertEqual(self.tool.main(['--source', str(self.source), '--spec', str(self.spec_path),
            '--output', str(self.source), '--report', str(self.report)]), 2)
        self.assertEqual(sha(self.source), self.source_hash)
        self.assertFalse(self.report.exists())

    def test_relative_existing_and_new_texture_dependencies_survive_relocation(self):
        mapping = png(self.root / 'synthetic-gray.png')
        image = bpy.data.images.load(str(self.root / mapping['path']), check_existing=False)
        image.name = 'RelativeExisting'
        image.filepath = '//' + mapping['path']
        image.use_fake_user = True
        self.save_source()
        destination = self.root / 'relocated'
        destination.mkdir()
        self.output = destination / 'new.blend'
        config = self.config()
        config['materials'][0].update(base_color=mapping, uv_map='SurfaceUV')
        self.assertEqual(self.run_tool(config), 0)
        self.reopen()
        self.assertEqual(Path(bpy.data.images['RelativeExisting'].filepath), self.root / mapping['path'])
        for image in bpy.data.images:
            if image.source == 'FILE':
                self.assertTrue(Path(image.filepath).is_absolute())
                self.assertEqual(list(image.size), [4, 3])
        self.assertEqual(sha(self.source), self.source_hash)
        bpy.ops.wm.open_mainfile(filepath=str(self.source), use_scripts=False)
        self.assertEqual(bpy.data.images['RelativeExisting'].filepath, '//' + mapping['path'])

    def test_actual_jpeg_decode_is_supported(self):
        original = png(self.root / 'synthetic-gray.png')
        image = bpy.data.images.load(str(self.root / original['path']), check_existing=False)
        path = self.root / 'synthetic-gray.jpeg'
        settings = bpy.context.scene.render.image_settings
        settings.file_format = 'JPEG'
        settings.color_mode = 'RGB'
        image.save_render(str(path), scene=bpy.context.scene)
        settings.file_format = 'PNG'
        bpy.data.images.remove(image)
        config = self.config()
        config['materials'][0].update(base_color={'path': path.name, 'sha256': sha(path), 'size': [4, 3]}, uv_map='SurfaceUV')
        self.assertEqual(self.run_tool(config), 0)
        self.reopen()
        texture = next(n for n in bpy.data.materials['NewPaint'].node_tree.nodes if n.type == 'TEX_IMAGE')
        self.assertEqual(list(texture.image.size), [4, 3])
        self.assertEqual(texture.image.file_format, 'JPEG')

    def test_textured_target_without_uv_layer_is_rejected_without_unwrap(self):
        mesh = bpy.data.objects['Hull'].data
        mesh.uv_layers.remove(mesh.uv_layers['SurfaceUV'])
        self.save_source()
        config = self.config()
        config['materials'][0].update(base_color=png(self.root / 'synthetic-gray.png'), uv_map='SurfaceUV')
        self.assertEqual(self.run_tool(config), 2)
        self.assertEqual(len(bpy.data.objects['Hull'].data.uv_layers), 0)
        self.assertFalse(self.output.exists())
        self.assertEqual(sha(self.source), self.source_hash)

    def test_normal_convention_and_binding_policy_are_not_guessed(self):
        mapping = png(self.root / 'synthetic-normal.png', (128, 128, 255, 255))
        for convention in (None, '', True, 'opengl', 'DX', 'object_space'):
            config = self.config()
            config['materials'][0].update(normal={**mapping, 'convention': convention}, uv_map='SurfaceUV')
            with self.subTest(convention=convention), self.assertRaises(ValueError):
                self.tool.validate(config, self.spec_path)
        config = self.config()
        config['materials'][0].update(normal=mapping, uv_map='SurfaceUV')
        with self.assertRaises(ValueError):
            self.tool.validate(config, self.spec_path)
        for policy in ({}, {'append': False}, {'append': 1}, {'append': True, 'slot': 1}):
            config = self.config()
            config['bindings'][0] = {'object': 'Hull', 'material': 'NewPaint', **policy}
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                self.tool.validate(config, self.spec_path)

    def test_ambiguous_local_and_linked_object_name_is_rejected(self):
        library = self.root / 'library.blend'
        bpy.data.libraries.write(str(library), {bpy.data.objects['Hull']})
        with bpy.data.libraries.load(str(library), link=True) as (_, data):
            data.objects = ['Hull']
        bpy.context.scene.collection.objects.link(data.objects[0])
        self.assertEqual(len([o for o in bpy.data.objects if o.name == 'Hull']), 2)
        self.save_source()
        self.assertEqual(self.run_tool(), 2)
        self.assertFalse(self.output.exists())
        self.assertNotIn('NewPaint', bpy.data.materials)

    def test_script_execution_from_unrelated_directory_builds_real_snapshot(self):
        """run_path also exercises script-directory imports like Blender --python."""
        self.spec_path.write_text(json.dumps(self.config()))
        args = [str(MODULE), '--source', str(self.source), '--spec', str(self.spec_path),
                '--output', str(self.output), '--report', str(self.report)]
        launch = 'import runpy, sys; sys.argv = ' + repr(args) + '; runpy.run_path(sys.argv[0], run_name="__main__")'
        result = subprocess.run([sys.executable, '-c', launch], cwd=self.root, text=True,
                                capture_output=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sha(self.source), self.source_hash)
        self.reopen()
        self.assertEqual(bpy.data.objects['Hull'].material_slots[1].material.name, 'NewPaint')
        self.assertEqual(json.loads(self.report.read_text())['lineage']['output_sha256'], sha(self.output))

    def test_unfilled_distributed_template_is_rejected(self):
        template = MODULE.parent.parent / 'assets' / 'pbr-spec.json'
        with self.assertRaises(ValueError):
            self.tool.validate(json.loads(template.read_text()), template)

    def test_source_or_spec_changed_during_open_refuses_publication(self):
        for target in ('source', 'spec_path'):
            @bpy.app.handlers.persistent
            def alter_after_open(*_):
                path = getattr(self, target)
                with path.open('ab') as stream:
                    stream.write(b'\n')
            bpy.app.handlers.load_post.append(alter_after_open)
            try:
                with self.subTest(target=target):
                    self.assertEqual(self.run_tool(), 2)
                    self.assertFalse(self.output.exists())
                    self.assertFalse(self.report.exists())
            finally:
                if alter_after_open in bpy.app.handlers.load_post:
                    bpy.app.handlers.load_post.remove(alter_after_open)

    def test_rejects_malformed_schema_and_factors_before_opening_source(self):
        marker = bpy.data.objects.new('NotOpened', None)
        bpy.context.scene.collection.objects.link(marker)
        bad_specs = [[], None, {}, {'schema_version': 1, 'materials': [], 'bindings': []}]
        base = self.config()
        for value in (True, 0, 2, 1.0):
            bad = copy.deepcopy(base)
            bad['schema_version'] = value
            bad_specs.append(bad)
        for field in ('roughness', 'metallic'):
            for value in (True, None, float('nan'), float('inf'), -0.01, 1.01, '0.5', 10 ** 400):
                bad = copy.deepcopy(base)
                bad['materials'][0][field] = value
                bad_specs.append(bad)
        for value in ([0, 1, 0], [0, 0, 0, 2], [True, 0, 0, 1], [0, 0, float('nan'), 1], 'green'):
            bad = copy.deepcopy(base)
            bad['materials'][0]['base_color'] = value
            bad_specs.append(bad)
        for field in ('gloss', 'packed', 'displacement', 'parallax', 'normal_convention'):
            bad = copy.deepcopy(base)
            bad['materials'][0][field] = 'unsupported'
            bad_specs.append(bad)
        for value in ('', 'a' * 64, '\x00'):
            bad = copy.deepcopy(base)
            bad['materials'][0]['name'] = value
            bad_specs.append(bad)
        for value in (True, -1, 1.0):
            bad = copy.deepcopy(base)
            bad['bindings'][0]['slot'] = value
            bad_specs.append(bad)
        for bad in bad_specs:
            with self.subTest(spec=repr(bad)[:100]):
                self.assertEqual(self.run_tool(bad), 2)
                self.assertIn('NotOpened', bpy.data.objects)
                self.assertFalse(self.output.exists())
                self.assertFalse(self.report.exists())
        self.assertEqual(sha(self.source), self.source_hash)


if __name__ == '__main__':
    unittest.main()
