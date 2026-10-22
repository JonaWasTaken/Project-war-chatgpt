"""Offline real-bpy reconstruction integration tests; scratch files only."""
import copy
import contextlib
import errno
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

try:
    import bpy
except ImportError:
    bpy = None

MODULE = Path(__file__).with_name('reconstruct_vehicle.py')

@unittest.skipIf(bpy is None, 'requires real bpy; run uv run --python 3.13 --with bpy python -m unittest discover -s scripts -p test_reconstruct_vehicle.py -v')
class ReconstructionTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), 'reconstruction implementation does not exist')
        spec = importlib.util.spec_from_file_location('reconstruction', MODULE)
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.root = Path(self.tmp.name)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.source = self.root / 'source.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        self.source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()

    def tearDown(self):
        if hasattr(self, 'tmp'):
            self.tmp.cleanup()

    def loft_spec(self):
        labels = ['bottom_left', 'bottom_right', 'shoulder_right', 'top_right', 'top_left', 'shoulder_left']
        rings = [[[-2, 0], [2, 0], [2, 1], [1, 2], [-1, 2], [-2, 1]],
                 [[-1.5, .2], [1.5, .2], [1.5, 1.2], [.8, 1.8], [-.8, 1.8], [-1.5, 1.2]]]
        return {'schema_version': 1, 'object_name': 'ReconHull', 'collection': 'Reconstruction',
                'sections': [{'y': y, 'labels': list(labels), 'xz': ring} for y, ring in zip([-3, 4], rings)]}

    def run_tool(self, mode, config):
        spec = self.root / (mode + '.json')
        spec.write_text(json.dumps(config))
        return self.tool.main([mode, '--source', str(self.source), '--spec', str(spec),
                               '--output', str(self.root / 'result.blend'), '--report', str(self.root / 'report.json')])

    def test_loft_builds_capped_profile_preserving_source(self):
        self.assertEqual(self.run_tool('loft', self.loft_spec()), 0)
        report = json.loads((self.root / 'report.json').read_text())
        self.assertEqual(report['status'], 'built')
        self.assertEqual(report['mesh']['vertices'], 12)
        self.assertEqual(report['mesh']['faces'], 8)
        self.assertEqual(report['mesh']['bounds'], [[-2.0, -3.0, 0.0], [2.0, 4.0, 2.0]])
        self.assertGreater(report['mesh']['volume'], 0)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash)
        bpy.ops.wm.open_mainfile(filepath=str(self.root / 'result.blend'), use_scripts=False)
        obj = bpy.data.objects['ReconHull']
        self.assertEqual(len(obj.data.vertices), 12)
        edges = {}
        for face in obj.data.polygons:
            ids = list(face.vertices)
            for a, b in zip(ids, ids[1:] + ids[:1]):
                key = tuple(sorted((a,b)))
                edges[key] = edges.get(key, 0) + 1
        self.assertTrue(all(count == 2 for count in edges.values()))
        self.assertEqual(len(obj.data.polygons[0].vertices), 6)

    @unittest.skipUnless(os.name == 'posix', 'requires POSIX RLIMIT_FSIZE')
    def test_kernel_report_short_write_removes_own_report_and_snapshot(self):
        import resource
        import signal
        from unittest.mock import patch

        # Real file dependency and read-only inputs; no save/write replacement.
        asset = self.root / 'asset.png'
        image = bpy.data.images.new('SourceAsset', width=16, height=16)
        image.filepath_raw = str(asset)
        image.file_format = 'PNG'
        image.save()
        image.filepath = '//asset.png'
        image.use_fake_user = True
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        spec = self.root / 'loft.json'
        spec.write_text(json.dumps(self.loft_spec()))
        protected = (self.source, spec, asset)
        originals = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
        for p in protected:
            p.chmod(0o444)
        published = self.root / 'published'
        published.mkdir()
        output, report = published / 'new.blend', published / 'report.json'
        original_open = Path.open
        old_limit = resource.getrlimit(resource.RLIMIT_FSIZE)
        old_handler = signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        report_opened = []

        def limit_report_open(path, *args, **kwargs):
            stream = original_open(path, *args, **kwargs)
            if path == report and args and args[0] == 'x':
                # The kernel allows one byte then raises EFBIG on write/close,
                # only after the genuine bpy staging save has completed.
                resource.setrlimit(resource.RLIMIT_FSIZE, (1, old_limit[1]))
                report_opened.append(True)
            return stream

        errors = io.StringIO()
        try:
            with patch.object(Path, 'open', limit_report_open), contextlib.redirect_stderr(errors):
                code = self.tool.main(['loft', '--source', str(self.source), '--spec', str(spec),
                                       '--output', str(output), '--report', str(report)])
        finally:
            resource.setrlimit(resource.RLIMIT_FSIZE, old_limit)
            signal.signal(signal.SIGXFSZ, old_handler)
        self.assertEqual(code, 2, errors.getvalue())
        self.assertEqual(report_opened, [True])
        self.assertIn(f'[Errno {errno.EFBIG}]', json.loads(errors.getvalue())['error'])
        for p, sha in originals.items():
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), sha)
            self.assertEqual(p.stat().st_mode & 0o777, 0o444)
        self.assertFalse(output.exists())
        self.assertFalse(report.exists(), f'partial report left: {report.read_bytes() if report.exists() else None!r}')
        self.assertEqual(list(published.iterdir()), [])

    def test_late_publication_races_preserve_existing_targets(self):
        from unittest.mock import patch

        spec = self.root / 'loft.json'
        spec.write_text(json.dumps(self.loft_spec()))
        spec_hash = hashlib.sha256(spec.read_bytes()).hexdigest()
        original_link = os.link
        for kind in ('output', 'report'):
            published = self.root / kind
            published.mkdir()
            output, report = published / 'new.blend', published / 'report.json'
            owned = output if kind == 'output' else report

            def race_link(source, target, *args, **kwargs):
                if Path(target) == output:
                    # Real competing file after preflight and staging, before
                    # publication/exclusive report open; never replace writes.
                    owned.write_bytes(b'race-created-owner')
                return original_link(source, target, *args, **kwargs)

            errors = io.StringIO()
            with self.subTest(kind=kind):
                with patch.object(os, 'link', race_link), contextlib.redirect_stderr(errors):
                    code = self.tool.main(['loft', '--source', str(self.source), '--spec', str(spec),
                                           '--output', str(output), '--report', str(report)])
                self.assertEqual(code, 2, errors.getvalue())
                self.assertEqual(owned.read_bytes(), b'race-created-owner')
                self.assertFalse((report if kind == 'output' else output).exists())
                self.assertEqual(list(published.iterdir()), [owned])
                self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash)
                self.assertEqual(hashlib.sha256(spec.read_bytes()).hexdigest(), spec_hash)

    def test_loft_rejects_invalid_profiles(self):
        base = self.loft_spec()
        cases = []
        for value in (True, float('nan'), float('inf')):
            bad = copy.deepcopy(base)
            bad['sections'][0]['xz'][0][0] = value
            cases.append(bad)
        for change in ('crossing', 'flat', 'winding', 'labels', 'stations', 'count', 'twist'):
            bad = copy.deepcopy(base)
            if change == 'crossing':
                bad['sections'][0]['xz'][1], bad['sections'][0]['xz'][4] = bad['sections'][0]['xz'][4], bad['sections'][0]['xz'][1]
            elif change == 'flat':
                bad['sections'][0]['xz'] = [[i, 0] for i in range(6)]
            elif change == 'winding':
                bad['sections'][1]['xz'].reverse()
            elif change == 'labels':
                bad['sections'][1]['labels'][0] = 'other'
            elif change == 'stations':
                bad['sections'][1]['y'] = -3
            elif change == 'count':
                bad['sections'][1]['xz'].pop()
            else:
                bad['sections'][1]['xz'] = bad['sections'][1]['xz'][3:] + bad['sections'][1]['xz'][:3]
            cases.append(bad)
        for i, bad in enumerate(cases):
            with self.subTest(case=i):
                self.assertEqual(self.run_tool('loft', bad), 2)
                self.assertFalse((self.root / 'result.blend').exists())
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash)

    def test_paths_and_existing_names_are_not_overwritten(self):
        spec_path = self.root / 'loft.json'
        spec_path.write_text(json.dumps(self.loft_spec()))
        args = ['loft', '--source', str(self.source), '--spec', str(spec_path), '--output',
                str(self.source), '--report', str(self.root / 'report.json')]
        self.assertEqual(self.tool.main(args), 2)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash)
        for filename in ('result.blend', 'report.json'):
            target = self.root / filename
            target.write_bytes(b'keep me')
            self.assertEqual(self.run_tool('loft', self.loft_spec()), 2)
            self.assertEqual(target.read_bytes(), b'keep me')
            target.unlink()
        for kind in ('object', 'collection', 'mesh'):
            bpy.ops.wm.read_factory_settings(use_empty=True)
            if kind == 'object':
                obj = bpy.data.objects.new('ReconHull', None)
                bpy.context.scene.collection.objects.link(obj)
            elif kind == 'collection':
                collection = bpy.data.collections.new('Reconstruction')
                bpy.context.scene.collection.children.link(collection)
            else:
                bpy.data.meshes.new('ReconHull').use_fake_user = True
            bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
            before = hashlib.sha256(self.source.read_bytes()).hexdigest()
            self.assertEqual(self.run_tool('loft', self.loft_spec()), 2)
            self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before)
            self.assertFalse((self.root / 'result.blend').exists())

    def camera_fixture(self):
        from mathutils import Vector
        from bpy_extras.object_utils import world_to_camera_view
        scene = bpy.context.scene
        scene.render.resolution_x = 960
        scene.render.resolution_y = 720
        scene.render.resolution_percentage = 100
        scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1
        camera = bpy.data.objects.new('PhotoCamera', bpy.data.cameras.new('PhotoCamera'))
        scene.collection.objects.link(camera)
        scene.camera = camera
        camera.data.type = 'PERSP'
        camera.data.lens = 50
        camera.location = (8, -12, 7)
        camera.rotation_euler = (Vector((0,0,1))-camera.location).to_track_quat('-Z', 'Y').to_euler()
        bpy.context.view_layer.update()
        self.known_matrix = camera.matrix_world.copy()
        points = [(-2,-3,0),(2,-3,0),(-2,3,0),(2,3,0),(-1,-2,2),(1,2,3),(-1,2,2),(1,-2,3)]
        landmarks = []
        for i, point in enumerate(points):
            obj = bpy.data.objects.new('Landmark_%d' % i, None)
            scene.collection.objects.link(obj)
            obj.location = point
            bpy.context.view_layer.update()
            p = world_to_camera_view(scene, camera, obj.matrix_world.translation)
            landmarks.append({'object': obj.name, 'role': 'fit' if i < 6 else 'holdout',
                              'pixel': [p.x*960, (1-p.y)*720]})
        bpy.ops.mesh.primitive_cube_add(location=(0, 0, 1))
        bpy.context.object.name = 'UntouchedMesh'
        bpy.context.object.hide_render = True
        self.mesh_points = [tuple(v.co) for v in bpy.context.object.data.vertices]
        image = bpy.data.images.new('SyntheticPhoto', width=960, height=720)
        photo = self.root / 'synthetic-photo.png'
        image.filepath_raw = str(photo)
        image.file_format = 'PNG'
        image.save()
        bpy.data.images.remove(image)
        camera.location += Vector((.4,-.3,.2))
        for i, delta in enumerate((.015,-.02,.015)):
            camera.rotation_euler[i] += delta
        bpy.context.view_layer.update()
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        self.source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        return {'schema_version': 1, 'camera': 'PhotoCamera',
                'photo': {'path': str(photo), 'sha256': hashlib.sha256(photo.read_bytes()).hexdigest(), 'size': [960,720]},
                'lens': {'mode': 'fixed', 'millimeters': 50}, 'landmarks': landmarks,
                'solver': {'max_iterations': 100, 'fit_rms_limit_px': .1, 'holdout_rms_limit_px': .1}}

    def test_real_fit_report_connects_to_controller_without_transcription(self):
        import vehicle_job as job
        config = self.camera_fixture()
        root = self.root / 'job'
        job.init_job(root, self.source)
        self.assertEqual(self.tool.main(['prepare-source', '--source', str(self.source),
                          '--output', str(root/'work/source-v001.blend'),
                          '--report', str(root/'source-preparation.json')]), 0)
        photo = root / 'reference.png'
        photo.write_bytes(Path(config['photo']['path']).read_bytes())
        config['photo']['path'] = str(photo)
        fingerprint = lambda p: {'path': p, 'sha256': hashlib.sha256((root/p).read_bytes()).hexdigest()}
        references = {'schema_version': 1,
                      'images': [{**fingerprint('reference.png'), 'view': 'synthetic perspective', 'description': 'Calibration fixture, not real vehicle evidence'}],
                      'features': [{'id': 'calibration', 'basis': 'observed', 'description': 'Synthetic projected points',
                                    'uncertainty': 'Synthetic test only', 'reference_paths': ['reference.png']}],
                      'checks': [{'name': 'fixture identity', 'status': 'pass', 'reason': 'Synthetic test only', 'reference_paths': ['reference.png']}]}
        (root/'references.json').write_text(json.dumps(references))
        job.advance(root, 'references', 'work/source-v001.blend', references='references.json')
        (root/'fit-spec.json').write_text(json.dumps(config))
        self.assertEqual(self.tool.main(['fit-camera', '--source', str(root/'work/source-v001.blend'),
                          '--spec', str(root/'fit-spec.json'), '--output', str(root/'work/fitted.blend'),
                          '--report', str(root/'fit-report.json')]), 0)
        record = {'model_version': 'synthetic-v002', 'source': fingerprint('work/fitted.blend')}
        record['registration'] = {'mode': 'reconstruction_fit_report', 'model_version': record['model_version'],
                                  'source_sha256': record['source']['sha256'], 'reference_paths': ['reference.png'],
                                  'fit_report': fingerprint('fit-report.json'), 'metrics_report': fingerprint('fit-report.json'),
                                  'diagnostic_scope': 'Synthetic sparse reprojection only', 'metrics_finding': 'Synthetic mechanics test, no visual approval'}
        with job.locked(root) as locked_root:
            files = {}
            job.registration_files(locked_root, job.load_verified(locked_root), record, files)
            self.assertIn('fit-report.json', files)
        self.assertEqual(job.status(root)['stage'], 'blockout')  # No invented blockout approval.

    def test_camera_fit_recovers_known_pose_and_preserves_geometry(self):
        spec = self.camera_fixture()
        self.assertEqual(self.run_tool('fit-camera', spec), 0)
        report = json.loads((self.root / 'report.json').read_text())
        self.assertEqual(report['status'], 'converged')
        self.assertEqual(report['evidence']['kind'], 'sparse_photo_reprojection_not_mesh_accuracy')
        self.assertLess(report['reprojection']['fit']['rms_px'], .1)
        self.assertLess(report['reprojection']['holdout']['rms_px'], .1)
        self.assertEqual(len(report['reprojection']['landmarks']), 8)
        self.assertTrue(report['acceptance']['passed'])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash)
        bpy.ops.wm.open_mainfile(filepath=str(self.root / 'result.blend'), use_scripts=False)
        camera = bpy.data.objects['PhotoCamera']
        self.assertLess(max(abs(camera.matrix_world[i][j]-self.known_matrix[i][j]) for i in range(4) for j in range(4)), .002)
        self.assertEqual([tuple(v.co) for v in bpy.data.objects['UntouchedMesh'].data.vertices], self.mesh_points)
        self.assertTrue(bpy.data.objects['UntouchedMesh'].hide_render)
        for i, row in enumerate(report['reprojection']['landmarks']):
            self.assertEqual(row['world'], list(bpy.data.objects['Landmark_%d' % i].matrix_world.translation))
            self.assertEqual(row['observed_pixel'], spec['landmarks'][i]['pixel'])

    def test_holdouts_do_not_drive_fit_and_bad_holdout_is_not_accepted(self):
        spec = self.camera_fixture()
        self.assertEqual(self.run_tool('fit-camera', spec), 0)
        before = json.loads((self.root / 'report.json').read_text())
        (self.root / 'result.blend').unlink()
        (self.root / 'report.json').unlink()
        for row in spec['landmarks']:
            if row['role'] == 'holdout':
                row['pixel'][0] += 20
                row['pixel'][1] -= 15
        self.assertEqual(self.run_tool('fit-camera', spec), 3)
        after = json.loads((self.root / 'report.json').read_text())
        self.assertEqual(before['camera']['final_matrix_world'], after['camera']['final_matrix_world'])
        self.assertEqual(after['status'], 'converged')
        self.assertFalse(after['acceptance']['passed'])
        self.assertGreater(after['reprojection']['holdout']['rms_px'], 24)
        self.assertLess(after['reprojection']['fit']['rms_px'], .1)

    def test_nonconverged_fit_reports_diagnostics_without_snapshot(self):
        spec = self.camera_fixture()
        spec['solver']['max_iterations'] = 1
        self.assertEqual(self.run_tool('fit-camera', spec), 2)
        self.assertFalse((self.root / 'result.blend').exists())
        report = json.loads((self.root / 'report.json').read_text())
        self.assertEqual(report['status'], 'nonconverged')
        self.assertFalse(report['acceptance']['passed'])
        self.assertFalse(report['solver']['converged'])
        self.assertEqual(report['lineage']['source_sha256'], self.source_hash)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash)

    def test_camera_rejects_malformed_correspondences_and_photo_metadata(self):
        base = self.camera_fixture()
        cases = []
        for key, value in [('schema_version', True), ('landmarks', []), ('camera', 'MissingCamera')]:
            bad = copy.deepcopy(base)
            bad[key] = value
            cases.append(bad)
        for change in ('hash', 'size', 'missing', 'duplicate', 'role', 'holdouts', 'nan', 'bool', 'lens', 'iterations'):
            bad = copy.deepcopy(base)
            if change == 'hash': bad['photo']['sha256'] = '0'*64
            elif change == 'size': bad['photo']['size'] = [960, 719]
            elif change == 'missing': bad['landmarks'][0]['object'] = 'NotPresent'
            elif change == 'duplicate': bad['landmarks'][1]['object'] = bad['landmarks'][0]['object']
            elif change == 'role': bad['landmarks'][0]['role'] = 'maybe'
            elif change == 'holdouts': bad['landmarks'][-1]['role'] = 'fit'
            elif change == 'nan': bad['landmarks'][0]['pixel'][0] = float('nan')
            elif change == 'bool': bad['landmarks'][0]['pixel'][0] = True
            elif change == 'lens': bad['lens']['mode'] = 'bounded'
            elif change == 'iterations': bad['solver']['max_iterations'] = True
            cases.append(bad)
        for i, bad in enumerate(cases):
            with self.subTest(case=i):
                self.assertEqual(self.run_tool('fit-camera', bad), 2)
                self.assertFalse((self.root / 'result.blend').exists())
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash)

    def test_camera_rejects_behind_points_and_unsupported_rigs(self):
        from mathutils import Vector
        spec = self.camera_fixture()
        original = self.source.read_bytes()
        for change in ('behind', 'parent', 'constraint', 'ortho', 'coplanar', 'shared_location'):
            with self.subTest(case=change):
                self.source.write_bytes(original)
                bpy.ops.wm.open_mainfile(filepath=str(self.source), use_scripts=False)
                camera = bpy.data.objects['PhotoCamera']
                if change == 'behind':
                    bpy.data.objects['Landmark_0'].location = camera.matrix_world @ Vector((0,0,1))
                elif change == 'parent': camera.parent = bpy.data.objects['Landmark_0']
                elif change == 'constraint': camera.constraints.new('COPY_LOCATION')
                elif change == 'ortho': camera.data.type = 'ORTHO'
                elif change == 'shared_location': bpy.data.objects['Landmark_0'].location = bpy.data.objects['Landmark_1'].location
                else:
                    for row in spec['landmarks']:
                        bpy.data.objects[row['object']].location.z = 0
                bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
                before = hashlib.sha256(self.source.read_bytes()).hexdigest()
                self.assertEqual(self.run_tool('fit-camera', spec), 2)
                self.assertFalse((self.root / 'result.blend').exists())
                self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before)

    def test_camera_fit_refuses_camera_dependent_hidden_geometry(self):
        spec = self.camera_fixture()
        mesh = bpy.data.objects['UntouchedMesh']
        mesh.parent = bpy.data.objects['PhotoCamera']
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        self.assertEqual(self.run_tool('fit-camera', spec), 2)
        self.assertFalse((self.root / 'result.blend').exists())

    def test_prepare_source_preserves_relative_image_target_without_geometry_changes(self):
        asset = self.root / 'asset.png'
        image = bpy.data.images.new('SourceAsset', width=16, height=16)
        image.filepath_raw = str(asset)
        image.file_format = 'PNG'
        image.save()
        image.filepath = '//asset.png'
        image.use_fake_user = True
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        before = self.tool.digest(self.source)
        original_geometry = self.tool.geometry_signature(None)
        moved = self.root / 'job' / 'work'
        moved.mkdir(parents=True)
        output, report = moved/'source-v001.blend', moved.parent/'source-preparation.json'
        self.assertEqual(self.tool.main(['prepare-source', '--source', str(self.source),
                                        '--output', str(output), '--report', str(report)]), 0)
        details = json.loads(report.read_text())
        self.assertEqual(details['status'], 'prepared')
        self.assertTrue(details['dependency_paths_absolute'])
        self.assertEqual(details['lineage']['source_sha256'], before)
        self.assertEqual(self.tool.digest(self.source), before)
        bpy.ops.wm.open_mainfile(filepath=str(output), use_scripts=False)
        self.assertEqual(Path(bpy.path.abspath(bpy.data.images['SourceAsset'].filepath)).resolve(), asset)
        self.assertEqual(self.tool.geometry_signature(None), original_geometry)
        self.assertEqual(self.tool.main(['prepare-source', '--source', str(self.source),
                                        '--output', str(output), '--report', str(report)]), 2)

    def test_prepare_source_keeps_relative_linked_library_target(self):
        library = self.root/'library.blend'
        mesh = bpy.data.meshes.new('LinkedFixtureMesh')
        bpy.data.libraries.write(str(library), {mesh})
        bpy.data.meshes.remove(mesh)
        with bpy.data.libraries.load(str(library), link=True) as (available, loaded):
            loaded.meshes = ['LinkedFixtureMesh']
        linked = bpy.data.meshes['LinkedFixtureMesh']
        obj = bpy.data.objects.new('LinkedFixtureObject', linked)
        bpy.context.scene.collection.objects.link(obj)
        linked.library.filepath = '//library.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        before = self.tool.digest(library)
        moved = self.root/'moved'
        moved.mkdir()
        output = moved/'prepared.blend'
        self.assertEqual(self.tool.main(['prepare-source', '--source', str(self.source),
                          '--output', str(output), '--report', str(moved/'prepare.json')]), 0)
        bpy.ops.wm.open_mainfile(filepath=str(output), use_scripts=False)
        self.assertEqual(Path(bpy.data.meshes['LinkedFixtureMesh'].library.filepath).resolve(), library)
        self.assertEqual(self.tool.digest(library), before)

    def test_snapshot_preserves_external_relative_asset_lineage(self):
        asset = self.root / 'asset.png'
        image = bpy.data.images.new('SourceAsset', width=16, height=16)
        image.filepath_raw = str(asset)
        image.file_format = 'PNG'
        image.save()
        image.filepath = '//asset.png'
        image.use_fake_user = True
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        self.source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        spec = self.root / 'loft.json'
        spec.write_text(json.dumps(self.loft_spec()))
        folder = self.root / 'elsewhere'
        folder.mkdir()
        output, report = folder / 'result.blend', folder / 'report.json'
        self.assertEqual(self.tool.main(['loft', '--source', str(self.source), '--spec', str(spec),
                         '--output', str(output), '--report', str(report)]), 0)
        bpy.ops.wm.open_mainfile(filepath=str(output), use_scripts=False)
        self.assertEqual(Path(bpy.path.abspath(bpy.data.images['SourceAsset'].filepath)).resolve(), asset)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash)

    def test_loft_rejects_float32_collapse_and_unsupported_numeric_magnitude(self):
        for value in (10**400, 1e40):
            bad = self.loft_spec()
            bad['sections'][0]['xz'][0][0] = value
            with self.subTest(value=str(value)):
                self.assertEqual(self.run_tool('loft', bad), 2)
                self.assertFalse((self.root / 'result.blend').exists())
        bad = self.loft_spec()
        for station in bad['sections']:
            station['y'] = 1e8 + (station['y'] + 3)*.0001
        self.assertEqual(self.run_tool('loft', bad), 2)
        self.assertFalse((self.root / 'result.blend').exists())

    def test_real_cli_executes_loft_and_refuses_reuse(self):
        import subprocess
        import sys
        config = self.root / 'cli-loft.json'
        config.write_text(json.dumps(self.loft_spec()))
        output, report = self.root / 'cli.blend', self.root / 'cli-report.json'
        command = [sys.executable, str(MODULE), 'loft', '--source', str(self.source),
                   '--spec', str(config), '--output', str(output), '--report', str(report)]
        completed = subprocess.run(command, text=True, capture_output=True, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        before = hashlib.sha256(output.read_bytes()).hexdigest()
        completed = subprocess.run(command, text=True, capture_output=True, timeout=60)
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertIn('refusing existing output', completed.stderr)
        self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), before)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash)

    def test_noisy_fit_stops_at_stationarity_not_zero_error(self):
        spec = self.camera_fixture()
        noise = [(.3, -.2), (-.2, .4), (.4,.2), (-.3,-.2), (.1,-.4), (-.2,.3)]
        for row, delta in zip(spec['landmarks'], noise):
            row['pixel'] = [p+d for p,d in zip(row['pixel'], delta)]
        spec['solver']['fit_rms_limit_px'] = 2
        spec['solver']['holdout_rms_limit_px'] = 2
        self.assertEqual(self.run_tool('fit-camera', spec), 0)
        report = json.loads((self.root / 'report.json').read_text())
        self.assertTrue(report['solver']['converged'])
        self.assertGreater(report['reprojection']['fit']['rms_px'], .05)
        self.assertLess(report['reprojection']['fit']['rms_px'], 1)
        self.assertLess(report['reprojection']['holdout']['rms_px'], 2)

    def test_example_loft_is_executable_but_camera_template_is_unfilled(self):
        assets = MODULE.parent.parent / 'assets'
        self.assertEqual(self.run_tool('loft', json.loads((assets / 'loft-spec.json').read_text())), 0)
        report = json.loads((self.root / 'report.json').read_text())
        self.assertEqual(report['mesh']['vertices'], 24)
        self.assertEqual(report['mesh']['faces'], 20)
        with self.assertRaises(ValueError):
            self.tool.validate_camera_spec(json.loads((assets / 'camera-fit-spec.json').read_text()), assets / 'camera-fit-spec.json')

    def test_loft_rejects_between_sample_fold_in_correspondence(self):
        a = [[3.272304761313064, 3.1649799638172973], [-0.0012461786731521626, -0.5890320337631433], [314.7072312439082, 119.52177735065891]]
        b = [[0.3646959078725973, -0.21705808050923112], [-0.02997252721791858, 0.0007634898350300635], [5.744555570169752, -4.301372383872443]]
        bad = self.loft_spec()
        for section, ring in zip(bad['sections'], [a,b]):
            section['xz'] = ring
            section['labels'] = ['corner_a', 'corner_b', 'corner_c']
        # Both endpoint rings and quarter samples are convex. Near t=.953 the
        # interpolated ring reverses winding: checking only samples misses it.
        self.assertEqual(self.run_tool('loft', bad), 2)
        self.assertFalse((self.root / 'result.blend').exists())

if __name__ == '__main__':
    unittest.main()
