"""Real Blender integration tests on labelled synthetic geometry, not vehicle art."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

try:
    import bpy
except ImportError:
    bpy = None

SCRIPT = Path(__file__).with_name('blender_vehicle_tools.py')


@unittest.skipIf(bpy is None, 'Blender Python unavailable')
class BlenderIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        collection = bpy.data.collections.new('Vehicle')
        bpy.context.scene.collection.children.link(collection)
        bpy.ops.mesh.primitive_cube_add(size=2)
        cube = bpy.context.object
        for c in list(cube.users_collection):
            c.objects.unlink(cube)
        collection.objects.link(cube)
        cube.name = 'SyntheticBody'
        cube.modifiers.new('Test bevel', 'BEVEL').width = 0.05
        self.source = self.root / 'synthetic.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        spec = importlib.util.spec_from_file_location('vehicle_tools', SCRIPT)
        self.tools = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tools)

    def test_cli_opens_actual_source_and_refuses_overwrite(self):
        import subprocess
        import sys
        output = self.root / 'audit.json'
        args = [sys.executable, str(SCRIPT), 'audit', '--blend', str(self.source),
                '--collection', 'Vehicle', '--output', str(output)]
        result = subprocess.run(args, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(output.exists(), 'CLI did not produce audit')
        self.assertEqual(json.loads(output.read_text())['source_sha256'], self.digest)
        result = subprocess.run(args, capture_output=True, text=True, timeout=90)
        self.assertNotEqual(result.returncode, 0, 'must not overwrite previous evidence')
        args[-1] = str(self.source)
        result = subprocess.run(args, capture_output=True, text=True, timeout=90)
        self.assertNotEqual(result.returncode, 0, 'must not overwrite source')
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.digest)

    def test_review_renders_modes_previews_and_reuses_locked_frame(self):
        self.assertTrue(hasattr(self.tools, 'render_review'), 'review renderer is not implemented')
        cfg = {'schema_version': 1, 'collection': 'Vehicle', 'resolution': [64, 64],
               'samples': 2, 'modes': ['clay', 'material', 'silhouette'],
               'preview_frame_heights': [32], 'views': [{'name': 'three_quarter', 'direction': [1, 1, 0.7]}],
               'frame': None, 'exposure': 0, 'world_strength': 0.35}
        first = self.tools.render_review(cfg, self.source, self.root / 'review-a')
        self.assertEqual(len(first['images']), 6)
        self.assertEqual(first.get('tool_sha256'), hashlib.sha256(SCRIPT.read_bytes()).hexdigest())
        for row in first['images']:
            path = self.root / 'review-a' / row['path']
            self.assertTrue(path.is_file())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row['sha256'])
        lock = json.loads((self.root / 'review-a' / 'rig-lock.json').read_text())
        self.assertIsNotNone(lock['frame'])
        second = self.tools.render_review(lock, self.source, self.root / 'review-b')
        self.assertEqual(first['rig_sha256'], second['rig_sha256'])
        self.assertEqual(first['camera_matrices'], second['camera_matrices'])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.digest)
        with self.assertRaises(FileExistsError):
            self.tools.render_review(lock, self.source, self.root / 'review-a')

    def test_render_cli_writes_manifest(self):
        import subprocess
        import sys
        cfg = {'schema_version': 1, 'collection': 'Vehicle', 'resolution': [32, 32],
               'samples': 1, 'modes': ['silhouette'], 'preview_frame_heights': [],
               'views': [{'name': 'top', 'direction': [0, 0, 1]}],
               'frame': None, 'exposure': 0, 'world_strength': 0.35}
        path = self.root / 'rig.json'
        path.write_text(json.dumps(cfg))
        result = subprocess.run([sys.executable, str(SCRIPT), 'render', '--blend', str(self.source),
                                 '--config', str(path), '--output', str(self.root / 'cli-review')],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / 'cli-review/render-manifest.json').is_file())

    def test_initial_framing_fits_each_view_then_locks(self):
        bpy.data.objects['SyntheticBody'].scale = (1, 3, 1)
        bpy.context.view_layer.update()
        cfg = {'schema_version': 1, 'collection': 'Vehicle', 'resolution': [32, 32],
               'samples': 1, 'modes': ['silhouette'], 'preview_frame_heights': [],
               'views': [{'name': 'front', 'direction': [0, 1, 0]},
                         {'name': 'side', 'direction': [1, 0, 0]}],
               'frame': None, 'exposure': 0, 'world_strength': 0.35}
        self.tools.render_review(cfg, self.source, self.root / 'framed')
        lock = json.loads((self.root / 'framed/rig-lock.json').read_text())
        self.assertIn('ortho_scale', lock['views'][0], 'each view needs its own locked framing')
        self.assertLess(lock['views'][0]['ortho_scale'], lock['views'][1]['ortho_scale'])

    def test_locked_view_reports_clipping_without_refitting(self):
        cfg = {'schema_version': 1, 'collection': 'Vehicle', 'resolution': [32, 32],
               'samples': 1, 'modes': ['silhouette'], 'preview_frame_heights': [],
               'views': [{'name': 'front', 'direction': [0, 1, 0], 'ortho_scale': 1}],
               'frame': {'center': [0, 0, 0], 'extent': 100}, 'exposure': 0, 'world_strength': 0.35}
        result = self.tools.render_review(cfg, self.source, self.root / 'clipped')
        self.assertEqual(result.get('bounds_outside_locked_views'), ['front'])
        lock = json.loads((self.root / 'clipped/rig-lock.json').read_text())
        self.assertEqual(lock['views'][0]['ortho_scale'], 1)

    def test_nonsquare_framing_contains_projected_bounds(self):
        from bpy_extras.object_utils import world_to_camera_view
        from mathutils import Matrix, Vector
        from itertools import product
        for width, height in [(128, 64), (64, 128)]:
            cfg = {'schema_version': 1, 'collection': 'Vehicle', 'resolution': [width, height],
                   'samples': 1, 'modes': ['silhouette'], 'preview_frame_heights': [],
                   'views': [{'name': 'front', 'direction': [0, 1, 0]}],
                   'frame': None, 'exposure': 0, 'world_strength': 0.35}
            directory = self.root / ('aspect-'+str(width))
            report = self.tools.render_review(cfg, self.source, directory)
            lock = json.loads((directory / 'rig-lock.json').read_text())
            scene = bpy.data.scenes.new('ProjectionCheck')
            scene.render.resolution_x, scene.render.resolution_y = width, height
            data = bpy.data.cameras.new('ProjectionCheck')
            camera = bpy.data.objects.new('ProjectionCheck', data)
            scene.collection.objects.link(camera)
            data.type = 'ORTHO'
            data.sensor_fit = report.get('camera_sensor_fit', 'AUTO')
            data.ortho_scale = lock['views'][0]['ortho_scale']
            camera.matrix_world = Matrix(report['camera_matrices']['front'])
            for corner in product([-1, 1], repeat=3):
                point = world_to_camera_view(scene, camera, Vector(corner))
                self.assertTrue(0 <= point.x <= 1 and 0 <= point.y <= 1,
                                'projected bounds clipped at aspect '+str((width, height))+': '+str(point))
            bpy.data.scenes.remove(scene)
            bpy.data.objects.remove(camera, do_unlink=True)
            bpy.data.cameras.remove(data)

    def test_external_instancer_does_not_contaminate_selected_collection(self):
        external = bpy.data.objects.new('UnrelatedInstancer', None)
        external.instance_type = 'COLLECTION'
        external.instance_collection = bpy.data.collections['Vehicle']
        external.location.x = 100
        bpy.context.scene.collection.objects.link(external)
        bpy.context.view_layer.update()
        report = self.tools.audit_scene('Vehicle', self.source)
        self.assertEqual(report['evaluated_totals']['instances'], 1)
        self.assertLess(report['bounds_world']['max'][0], 2)
        # Selecting the actual instancer must still include its generated cube.
        group = bpy.data.collections.new('InstancerSelection')
        bpy.context.scene.collection.children.link(group)
        group.objects.link(external)
        report = self.tools.audit_scene('InstancerSelection', self.source)
        self.assertEqual(report['evaluated_totals']['instances'], 1)
        self.assertGreater(report['bounds_world']['min'][0], 98)

    def test_excluded_child_is_not_reenabled_in_review_scene(self):
        child = bpy.data.collections.new('HiddenAlternative')
        bpy.data.collections['Vehicle'].children.link(child)
        mesh = bpy.data.meshes.new('AlternativeMesh')
        mesh.from_pydata([(20, 0, 0), (21, 0, 0), (20, 0, 1)], [], [(0, 1, 2)])
        hidden = bpy.data.objects.new('ExcludedPart', mesh)
        child.objects.link(hidden)
        bpy.context.view_layer.layer_collection.children['Vehicle'].children[child.name].exclude = True
        bpy.context.view_layer.update()
        self.assertEqual(self.tools.audit_scene('Vehicle', self.source)['evaluated_totals']['instances'], 1)
        rendered_names = []
        def capture(scene, *unused):
            rendered_names.extend(o.name for o in scene.objects)
        bpy.app.handlers.render_pre.append(capture)
        self.addCleanup(lambda: bpy.app.handlers.render_pre.remove(capture))
        cfg = {'schema_version': 1, 'collection': 'Vehicle', 'resolution': [32, 32],
               'samples': 1, 'modes': ['silhouette'], 'preview_frame_heights': [],
               'views': [{'name': 'front', 'direction': [0, 1, 0]}],
               'frame': None, 'exposure': 0, 'world_strength': 0.35}
        self.tools.render_review(cfg, self.source, self.root / 'excluded-check')
        self.assertIn('SyntheticBody', rendered_names)
        self.assertNotIn('ExcludedPart', rendered_names, 'review scene must not reactivate excluded geometry')

    def test_audit_uses_evaluated_geometry_without_saving_source(self):
        self.assertTrue(hasattr(self.tools, 'audit_scene'), 'scene audit is not implemented')
        report = self.tools.audit_scene('Vehicle', self.source)
        self.assertGreater(report['evaluated_totals']['triangles'], 12)
        self.assertEqual(report['objects'][0]['name'], 'SyntheticBody')
        self.assertIn('no_material', report['objects'][0]['warnings'])
        self.assertEqual(report['source_sha256'], self.digest)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.digest)
        self.assertIn('not', report['limitations'])
        with self.assertRaises(ValueError):
            self.tools.audit_scene('DoesNotExist', self.source)
        empty = bpy.data.collections.new('Empty')
        bpy.context.scene.collection.children.link(empty)
        with self.assertRaises(ValueError):
            self.tools.audit_scene('Empty', self.source)


if __name__ == '__main__':
    unittest.main()
