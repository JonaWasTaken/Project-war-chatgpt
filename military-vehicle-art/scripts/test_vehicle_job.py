#!/usr/bin/env python3
"""Filesystem mechanics plus optional real Blender integration; fixtures stay in TMPDIR."""
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


class VehicleJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / 'user.blend'
        self.source.write_bytes(b'BLENDER-v300 source fixture, not an executable blend scene')
        self.root = self.base / 'job'

    def module(self):
        try:
            return importlib.import_module('vehicle_job')
        except ModuleNotFoundError:
            self.fail('vehicle_job controller is not implemented')

    def test_init_does_not_offer_unprepared_relocated_source(self):
        job = self.module()
        job.init_job(self.root, self.source)
        self.assertFalse((self.root/'work/source-v001.blend').exists())
        manifest = self.reference_fixture()
        (self.root/'work/source-v001.blend').write_bytes(self.source.read_bytes())
        with self.assertRaisesRegex(ValueError, 'preparation|Missing'):
            job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)
        self.assertEqual(job.status(self.root)['stage'], 'references')

    def test_preparation_requires_exact_recorded_source_origin(self):
        job = self.started()
        state = json.loads((self.root / '.vehicle-job/state.json').read_text())
        report = json.loads((self.root / 'source-preparation.json').read_text())
        for origin in (None, '', 'user.blend', str(self.root / '.vehicle-job/baseline.blend'), str(self.base / 'copied.blend')):
            with self.subTest(origin=origin):
                report['lineage']['source'] = origin
                self.write_json('source-preparation.json', report)
                with self.assertRaisesRegex(ValueError, 'origin'):
                    job.preparation_files(self.root, state, 'work/source-v001.blend',
                                          {'work/source-v001.blend': self.source.read_bytes()})
        report['lineage']['source'] = str(self.source.resolve())
        self.write_json('source-preparation.json', report)
        job.preparation_files(self.root, state, 'work/source-v001.blend',
                              {'work/source-v001.blend': self.source.read_bytes()})

    @unittest.skipUnless(importlib.util.find_spec('bpy') and importlib.util.find_spec('PIL'),
                         'Actual bpy/Pillow runtime unavailable')
    def test_real_preparation_from_archival_baseline_is_rejected_then_original_succeeds(self):
        """Equal .blend bytes do not mean equal // dependency origins."""
        import bpy
        from PIL import Image
        import reconstruct_vehicle
        job = self.module()
        original = self.base / 'original'
        original.mkdir()
        texture = original / 'texture.png'
        Image.new('RGB', (4, 4), (60, 90, 120)).save(texture)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add()
        image = bpy.data.images.load(str(texture))
        image.name = 'RelativeOriginFixture'
        image.filepath = '//texture.png'
        image.use_fake_user = True
        self.source = original / 'source.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        initial_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        state = job.init_job(self.root, self.source)
        baseline = self.root / state['baseline']['path']
        wrong_output = self.root / 'work/source-v001.blend'
        wrong_report = self.root / 'wrong-origin-preparation.json'
        self.assertEqual(reconstruct_vehicle.main(['prepare-source', '--source', str(baseline),
            '--output', str(wrong_output), '--report', str(wrong_report)]), 0)
        (self.root / 'source-preparation.json').write_bytes(wrong_report.read_bytes())
        refs = self.reference_fixture()
        bpy.ops.wm.open_mainfile(filepath=str(wrong_output), use_scripts=False)
        wrong_texture = Path(bpy.data.images['RelativeOriginFixture'].filepath)
        self.assertNotEqual(wrong_texture, texture)
        self.assertFalse(wrong_texture.exists())
        with self.assertRaisesRegex(ValueError, 'origin'):
            job.advance(self.root, 'references', 'work/source-v001.blend', references=refs)
        self.assertEqual(job.status(self.root)['stage'], 'references')
        correct_output = self.root / 'work/source-v002.blend'
        correct_report = self.root / 'correct-origin-preparation.json'
        self.assertEqual(reconstruct_vehicle.main(['prepare-source', '--source', str(self.source),
            '--output', str(correct_output), '--report', str(correct_report)]), 0)
        # Only replace an unaccepted candidate; preserve both actual producer reports.
        (self.root / 'source-preparation.json').write_bytes(correct_report.read_bytes())
        result = job.advance(self.root, 'references', 'work/source-v002.blend', references=refs)
        self.assertEqual(result['stage'], 'blockout')
        bpy.ops.wm.open_mainfile(filepath=str(correct_output), use_scripts=False)
        self.assertEqual(Path(bpy.data.images['RelativeOriginFixture'].filepath), texture)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), initial_hash)

    def test_init_copies_baseline_without_mutating_input(self):
        job = self.module()
        before = self.source.read_bytes()
        job.init_job(self.root, self.source, 'existing')
        state = json.loads((self.root / '.vehicle-job/state.json').read_text())
        baseline = self.root / state['baseline']['path']
        self.assertEqual(baseline.read_bytes(), before)
        self.assertEqual(state['baseline']['sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse(baseline.stat().st_mode & 0o222)
        self.assertEqual(job.status(self.root)['stage'], 'references')
        self.assertTrue(job.status(self.root)['unmet_checks'])
        with self.assertRaises((ValueError, FileExistsError)):
            job.init_job(self.root, self.source, 'existing')

    def started(self):
        job = self.module()
        job.init_job(self.root, self.source)
        self.prepared_fixture()
        return job

    def prepared_fixture(self):
        # Documentary fixture only. Real bpy preparation is independently integration-tested.
        (self.root/'work/source-v001.blend').write_bytes(self.source.read_bytes())
        value = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.write_json('source-preparation.json', {'schema_version': 1, 'command': 'prepare-source',
                        'status': 'prepared', 'dependency_paths_absolute': True,
                        'lineage': {'source': str(self.source.resolve()), 'source_sha256': value, 'output_sha256': value},
                        'geometry_preservation': {'unchanged': True, 'before_sha256': 'a'*64, 'after_sha256': 'a'*64}})

    def write_json(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value))
        return path

    def fingerprint(self, path):
        return {'path': path, 'sha256': hashlib.sha256((self.root / path).read_bytes()).hexdigest()}

    def reference_fixture(self):
        import struct
        import zlib
        def chunk(kind, data):
            return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
        image = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
                 + chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00')) + chunk(b'IEND', b''))
        (self.root / 'reference.png').write_bytes(image)
        return self.write_json('references.json', {
            'schema_version': 1,
            'images': [{**self.fingerprint('reference.png'), 'view': 'side', 'description': 'Fixture image'}],
            'features': [{'id': 'hull', 'basis': 'observed', 'description': 'One visible fixture pixel',
                          'reference_paths': ['reference.png'], 'uncertainty': 'Fixture only'}],
            'checks': [{'name': 'reference coverage', 'status': 'pass', 'reason': 'Fixture only',
                        'reference_paths': ['reference.png']}]
        })

    def test_reference_gate_snapshots_then_advances_exactly_once(self):
        job = self.started()
        manifest = self.reference_fixture()
        result = job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)
        self.assertEqual(result['stage'], 'blockout')
        state = json.loads((self.root / '.vehicle-job/state.json').read_text())
        self.assertEqual(len(state['history']), 1)
        self.assertTrue(list((self.root / '.vehicle-job/history').rglob('*.blend')))
        self.assertEqual(job.status(self.root)['stage'], 'blockout')
        with self.assertRaisesRegex(ValueError, 'stage'):
            job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)

    def test_missing_reference_config_and_empty_checks_do_not_advance(self):
        job = self.started()
        with self.assertRaises(ValueError):
            job.advance(self.root, 'references', 'work/source-v001.blend', references='missing.json')
        manifest = self.reference_fixture()
        data = json.loads((self.root / manifest).read_text())
        data['checks'] = []
        self.write_json(manifest, data)
        with self.assertRaisesRegex(ValueError, 'checks'):
            job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)
        self.assertEqual(job.status(self.root)['stage'], 'references')

    def at_blockout(self):
        job = self.started()
        manifest = self.reference_fixture()
        job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)
        return job

    def review_fixture(self, gate='blockout', version='v002'):
        source = f'work/source-{version}.blend'
        (self.root / source).write_bytes(self.source.read_bytes() + version.encode())
        image = f'{gate}-{version}.png'
        (self.root / image).write_bytes((self.root / 'reference.png').read_bytes())
        record = {
            'schema_version': 2, 'gate': gate, 'model_version': version,
            'source': {**self.fingerprint(source), 'version': version},
            'required_views': ['side'], 'motion_required': False,
            'evidence': [{**self.fingerprint(image), 'version': version, 'kind': 'render',
                          'inspected': True, 'view': 'side', 'finding': 'Fixture inspection, not production evidence'}],
            'coverage': {name: {'status': 'pass', 'reason': 'Fixture assertion', 'evidence_paths': [image]}
                         for name in ('silhouette', 'proportions', 'fit', 'shading', 'materials',
                                      'readability', 'motion', 'regression')},
            'defects': [],
            'approval': {'status': 'approved', 'gate': gate, 'model_version': version,
                         'reference': 'fixture authorization', 'scope': 'fixture only'},
        }
        if gate == 'blockout':
            metrics = self.write_json('metrics.json', {'actual_diagnostic': {'triangles': 12}})
            camera = self.write_json('camera.json', {
                'model_version': version, 'source_sha256': record['source']['sha256'],
                'projection': 'ORTHO', 'ortho_scale': 1, 'image_size': [1, 1],
                'matrix_world': [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 3], [0, 0, 0, 1]],
            })
            landmarks = self.write_json('landmarks.json', {
                'schema_version': 1, 'model_version': version, 'reference_version': 'reference-fixture',
                'view': 'side', 'alignment_note': 'Fixture projection/crop agreed', 'alignment_confirmed': True,
                'reference_size': [1, 1], 'model_size': [1, 1], 'tolerance_px': 0.1,
                'tolerance_basis': 'Test fixture tolerance only',
                'landmarks': [{'id': 'pixel', 'reference_px': [0, 0], 'model_px': [0, 0]}],
            })
            record['registration'] = {
                'mode': 'measured_camera_fit', 'model_version': version,
                'source_sha256': record['source']['sha256'], 'reference_paths': ['reference.png'],
                'diagnostic_scope': 'Fixture-only geometry metric; not aesthetic approval',
                'metrics_finding': '12 test fixture triangles, not a production score',
                'metrics_report': self.fingerprint(metrics), 'camera_report': self.fingerprint(camera),
                'landmarks': self.fingerprint(landmarks),
            }
        review = self.write_json(f'{gate}-{version}-review.json', record)
        return source, review, record

    def reconstruction_report_fixture(self, record):
        # Synthetic producer-format fixture; never real calibration evidence.
        rows = [{'object': f'p{i}', 'role': 'fit' if i < 4 else 'holdout',
                 'observed_pixel': [0, 0], 'projected_pixel': [0, 0],
                 'world': [i, i % 2, i % 3], 'error_px': 0} for i in range(6)]
        report = {'schema_version': 1, 'command': 'fit-camera', 'status': 'converged',
                  'lineage': {'output_sha256': record['source']['sha256']},
                  'photo': {'sha256': self.fingerprint('reference.png')['sha256'], 'size': [1, 1]},
                  'solver': {'converged': True, 'holdouts_used_in_objective': False},
                  'geometry_preservation': {'unchanged': True, 'before_sha256': 'a'*64, 'after_sha256': 'a'*64},
                  'acceptance': {'passed': True, 'fit_rms_limit_px': 1, 'holdout_rms_limit_px': 1},
                  'reprojection': {'fit': {'count': 4, 'rms_px': 0}, 'holdout': {'count': 2, 'rms_px': 0},
                                   'landmarks': rows}}
        registration = record['registration']
        registration['mode'] = 'reconstruction_fit_report'
        registration.pop('camera_report')
        registration.pop('landmarks')
        self.write_json('fit-report.json', report)
        registration['fit_report'] = self.fingerprint('fit-report.json')
        return report

    def test_controller_accepts_current_reconstruction_producer_report_directly(self):
        job = self.at_blockout()
        source, review, record = self.review_fixture()
        self.reconstruction_report_fixture(record)
        self.write_json(review, record)
        self.assertEqual(job.advance(self.root, 'blockout', source, review=review)['stage'], 'assemblies')

    def test_direct_fit_rejects_stale_rejected_overfit_or_inconsistent_reports(self):
        import copy
        job = self.at_blockout()
        source, review, record = self.review_fixture()
        original = self.reconstruction_report_fixture(record)
        cases = []
        for field in ('lineage', 'solver', 'geometry_preservation', 'photo', 'acceptance', 'reprojection'):
            broken = copy.deepcopy(original)
            broken[field] = []
            cases.append(broken)
        for field, key, value in [('lineage', 'output_sha256', '0'*64), ('photo', 'sha256', '0'*64),
                                  ('solver', 'converged', False), ('solver', 'holdouts_used_in_objective', True),
                                  ('acceptance', 'passed', False), ('geometry_preservation', 'unchanged', False)]:
            broken = copy.deepcopy(original)
            broken[field][key] = value
            cases.append(broken)
        for role in ('fit', 'holdout'):
            broken = copy.deepcopy(original)
            broken['reprojection'][role] = []
            cases.append(broken)
        broken = copy.deepcopy(original)
        broken['reprojection']['landmarks'][-1]['projected_pixel'] = [10, 10]
        cases.append(broken)
        broken = copy.deepcopy(original)
        broken['reprojection']['landmarks'][-1]['object'] = 'p0'
        cases.append(broken)
        for index, broken in enumerate(cases):
            self.write_json('fit-report.json', broken)
            record['registration']['fit_report'] = self.fingerprint('fit-report.json')
            self.write_json(review, record)
            with self.subTest(case=index), self.assertRaises(ValueError):
                job.advance(self.root, 'blockout', source, review=review)
        self.assertEqual(job.status(self.root)['stage'], 'blockout')

    def test_review_gate_uses_existing_validator_and_cannot_skip(self):
        job = self.at_blockout()
        source, review, record = self.review_fixture()
        with self.assertRaisesRegex(ValueError, 'stage'):
            job.advance(self.root, 'assemblies', source, review=review)
        self.assertEqual(job.advance(self.root, 'blockout', source, review=review)['stage'], 'assemblies')
        for gate, version in [('assemblies', 'v003'), ('materials', 'v004'), ('delivery', 'v005')]:
            source, review, record = self.review_fixture(gate, version)
            job.advance(self.root, gate, source, review=review)
        self.assertEqual(job.status(self.root)['stage'], 'complete')

    def test_review_missing_pending_stale_or_wrong_source_rejected(self):
        job = self.at_blockout()
        source, review, record = self.review_fixture()
        with self.assertRaises(ValueError):
            job.advance(self.root, 'blockout', source, review='missing-review.json')
        for field, value in [('approval', {**record['approval'], 'status': 'pending'}),
                             ('source', {**record['source'], 'sha256': '0' * 64}),
                             ('gate', 'materials')]:
            broken = {**record, field: value}
            self.write_json(review, broken)
            with self.subTest(field=field), self.assertRaises(ValueError):
                job.advance(self.root, 'blockout', source, review=review)
        self.write_json(review, record)
        with self.assertRaisesRegex(ValueError, 'source'):
            job.advance(self.root, 'blockout', 'work/source-v001.blend', review=review)
        self.assertEqual(job.status(self.root)['stage'], 'blockout')

    def test_registration_cannot_be_missing_empty_stale_or_outside_tolerance(self):
        job = self.at_blockout()
        source, review, record = self.review_fixture()
        for registration in (None, {}, {**record['registration'], 'source_sha256': '0' * 64}):
            self.write_json(review, {**record, 'registration': registration})
            with self.subTest(registration=registration), self.assertRaises(ValueError):
                job.advance(self.root, 'blockout', source, review=review)
        points = json.loads((self.root / 'landmarks.json').read_text())
        points['landmarks'][0]['model_px'] = [1, 1]
        self.write_json('landmarks.json', points)
        record['registration']['landmarks'] = self.fingerprint('landmarks.json')
        self.write_json(review, record)
        with self.assertRaisesRegex(ValueError, 'tolerance'):
            job.advance(self.root, 'blockout', source, review=review)

    def test_explicit_orthographic_authorization_is_an_alternative_not_implicit(self):
        job = self.at_blockout()
        source, review, record = self.review_fixture()
        registration = record['registration']
        registration['mode'] = 'orthographic_approved'
        registration.pop('landmarks')
        registration.pop('camera_report')
        registration['orthographic_reason'] = 'Fixture image explicitly accepted as orthographic'
        registration['approval'] = {'status': 'pending'}
        self.write_json(review, record)
        with self.assertRaises(ValueError):
            job.advance(self.root, 'blockout', source, review=review)
        registration['approval'] = {'status': 'approved', 'gate': 'registration', 'model_version': 'v002',
                                    'reference': 'fixture explicit orthographic decision', 'scope': 'reference.png side projection'}
        self.write_json(review, record)
        self.assertEqual(job.advance(self.root, 'blockout', source, review=review)['stage'], 'assemblies')

    def test_status_reports_candidate_problems_and_cli_is_executable(self):
        import subprocess
        import sys
        job = self.at_blockout()
        source, review, record = self.review_fixture()
        state_path = self.root / '.vehicle-job/state.json'
        before = state_path.read_bytes()
        result = job.status(self.root, source=source, review=review)
        self.assertEqual(result['unmet_checks'], [])
        self.assertTrue(any('advance' in command for command in result['commands']))
        record['approval']['status'] = 'pending'
        self.write_json(review, record)
        self.assertTrue(job.status(self.root, source=source, review=review)['unmet_checks'])
        execution = subprocess.run([sys.executable, job.__file__, 'next', '--job', str(self.root),
                                    '--source', source, '--review', review], capture_output=True, text=True)
        self.assertEqual(execution.returncode, 0, execution.stderr)
        output = json.loads(execution.stdout)
        self.assertEqual(output['stage'], 'blockout')
        self.assertTrue(output['instructions'])
        self.assertEqual(state_path.read_bytes(), before)

    def authorization_fixture(self, intent='reconstruction'):
        # Synthetic authorization MECHANICS only: not actual user consent or a production brief.
        manifest = self.reference_fixture()
        references = json.loads((self.root / manifest).read_text())
        references['intent'] = intent
        (self.root / 'brief.md').write_text('SYNTHETIC MECHANICS FIXTURE: ' + intent + '; not a user brief.')
        (self.root / 'concept-decision.txt').write_text('SYNTHETIC approved concept fixture; NOT user consent.')
        authorization = {
            'schema_version': 1, 'intent': intent,
            'objective': 'create_original' if intent == 'original_design' else 'reconstruct_real_subject',
            'baseline_sha256': hashlib.sha256(self.source.read_bytes()).hexdigest(),
            'brief': self.fingerprint('brief.md'),
            'reference_images': [self.fingerprint('reference.png')],
            'approval': {'status': 'approved', 'gate': 'concept', 'reference': 'SYNTHETIC decision only',
                         'scope': 'Synthetic fixture concept, never user consent',
                         'evidence': self.fingerprint('concept-decision.txt')},
        }
        if intent == 'original_design':
            authorization['originality_statement'] = 'Synthetic fictional product, not a real-subject reconstruction.'
        self.write_json('design-authorization.json', authorization)
        references['authorization'] = self.fingerprint('design-authorization.json')
        self.write_json(manifest, references)
        return manifest, references, authorization

    def test_new_route_requires_then_accepts_explicit_concept_evidence(self):
        job = self.module()
        job.init_job(self.root, self.source, 'new')
        self.prepared_fixture()
        manifest = self.reference_fixture()
        with self.assertRaises(ValueError):
            job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)
        manifest, references, authorization = self.authorization_fixture()
        candidate = job.status(self.root, source='work/source-v001.blend', references=manifest)
        self.assertEqual(candidate['unmet_checks'], [])
        self.assertTrue(any('advance' in command for command in candidate['commands']))
        result = job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)
        self.assertEqual(result['stage'], 'blockout')
        self.assertEqual(result['intent'], 'reconstruction')
        state = json.loads((self.root / '.vehicle-job/state.json').read_text())
        captured = json.loads((self.root / state['history'][0]['path']).read_text())
        self.assertTrue({'brief.md', 'concept-decision.txt', 'design-authorization.json'} <=
                        {row['path'] for row in captured['files']})
        # New production start still uses real-subject reconstruction registration by default.
        source, review, record = self.review_fixture()
        self.assertEqual(job.advance(self.root, 'blockout', source, review=review)['stage'], 'assemblies')

    def design_review_fixture(self):
        # Synthetic mechanics only. This is NOT evidence of real design acceptance.
        source, review, record = self.review_fixture()
        record['intent'] = 'original_design'
        references = json.loads((self.root / 'references.json').read_text())
        metrics = json.loads((self.root / 'metrics.json').read_text())
        metrics['source_sha256'] = record['source']['sha256']
        self.write_json('metrics.json', metrics)
        (self.root / 'design-decision.txt').write_text('SYNTHETIC design-review decision; NOT user consent.')
        registration = record['registration']
        registration.pop('camera_report')
        registration.pop('landmarks')
        registration.update({
            'mode': 'design_review', 'metrics_report': self.fingerprint('metrics.json'),
            'accepted_design': references['authorization'],
            'design_checks': [{'requirement': 'Synthetic brief: fictional product outline', 'status': 'pass',
                               'finding': 'Synthetic inspection only, never a production quality score',
                               'evidence_paths': [record['evidence'][0]['path']]}],
            'approval': {'status': 'approved', 'gate': 'design_review', 'model_version': record['model_version'],
                         'source_sha256': record['source']['sha256'],
                         'accepted_design_sha256': references['authorization']['sha256'],
                         'reference': 'SYNTHETIC mechanics decision', 'scope': 'Synthetic fictional product fixture',
                         'evidence': self.fingerprint('design-decision.txt')},
        })
        self.write_json(review, record)
        return source, review, record

    def test_original_design_cli_route_reviews_the_accepted_design_without_photo_fit(self):
        import subprocess
        import sys
        job = self.module()
        initialized = subprocess.run([sys.executable, job.__file__, 'init', '--job', str(self.root),
                                      '--source', str(self.source), '--route', 'new', '--intent', 'original_design'],
                                     capture_output=True, text=True)
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.assertEqual(json.loads(initialized.stdout)['intent'], 'original_design')
        self.prepared_fixture()
        manifest, references, authorization = self.authorization_fixture('original_design')
        job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)
        source, review, record = self.design_review_fixture()
        candidate = job.status(self.root, source=source, review=review)
        self.assertEqual(candidate['unmet_checks'], [])
        self.assertIn('design_review', ' '.join(candidate['instructions']))
        self.assertFalse(any('landmarks' in command for command in candidate['commands']))
        result = job.advance(self.root, 'blockout', source, review=review)
        self.assertEqual(result['stage'], 'assemblies')
        for gate, version in [('assemblies', 'v003'), ('materials', 'v004'), ('delivery', 'v005')]:
            source, review, record = self.review_fixture(gate, version)
            job.advance(self.root, gate, source, review=review)
        self.assertEqual(job.status(self.root)['stage'], 'complete')

    def original_at_blockout(self, route='new'):
        job = self.module()
        job.init_job(self.root, self.source, route, intent='original_design')
        self.prepared_fixture()
        manifest, references, authorization = self.authorization_fixture('original_design')
        job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)
        return job

    def test_original_authorization_requires_explicit_original_brief_not_reconstruction_relabel(self):
        import copy
        job = self.module()
        job.init_job(self.root, self.source, 'existing', intent='original_design')
        self.prepared_fixture()
        manifest, references, original = self.authorization_fixture('original_design')
        cases = []
        for field, value in [('originality_statement', ''), ('objective', 'reconstruct_real_subject'),
                             ('intent', 'reconstruction'), ('baseline_sha256', '0'*64),
                             ('brief', {}), ('reference_images', [])]:
            cases.append({**original, field: value})
        for field, value in [('status', 'pending'), ('gate', 'blockout'), ('evidence', {}), ('scope', '')]:
            broken = copy.deepcopy(original)
            broken['approval'][field] = value
            cases.append(broken)
        for broken in cases:
            self.write_json('design-authorization.json', broken)
            references['authorization'] = self.fingerprint('design-authorization.json')
            self.write_json(manifest, references)
            self.assertTrue(job.status(self.root, source='work/source-v001.blend',
                                       references=manifest)['unmet_checks'], broken)
            with self.subTest(authorization=broken), self.assertRaises(ValueError):
                job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)
        self.assertEqual(job.status(self.root)['stage'], 'references')

    def test_design_review_rejects_reconstruction_photo_fit_disguised_as_design_diagnostics(self):
        job = self.original_at_blockout()
        source, review, record = self.design_review_fixture()
        metrics = json.loads((self.root / 'metrics.json').read_text())
        metrics['command'] = 'fit-camera'
        self.write_json('metrics.json', metrics)
        record['registration']['metrics_report'] = self.fingerprint('metrics.json')
        self.write_json(review, record)
        self.assertTrue(job.status(self.root, source=source, review=review)['unmet_checks'])
        with self.assertRaisesRegex(ValueError, 'reconstruction|photo'):
            job.advance(self.root, 'blockout', source, review=review)
        metrics.pop('command')
        self.write_json('metrics.json', metrics)
        record['registration']['metrics_report'] = self.fingerprint('metrics.json')
        for key in ('fit_report', 'camera_report', 'landmarks', 'orthographic_reason'):
            record['registration'][key] = {'disguised_reconstruction_fixture': True}
            self.write_json(review, record)
            self.assertTrue(job.status(self.root, source=source, review=review)['unmet_checks'], key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                job.advance(self.root, 'blockout', source, review=review)
            record['registration'].pop(key)
        self.assertEqual(job.status(self.root)['stage'], 'blockout')

    def test_review_cannot_change_the_locked_job_intent(self):
        job = self.at_blockout()
        source, review, record = self.review_fixture()
        record['intent'] = 'original_design'
        self.write_json(review, record)
        self.assertTrue(job.status(self.root, source=source, review=review)['unmet_checks'])
        with self.assertRaisesRegex(ValueError, 'intent'):
            job.advance(self.root, 'blockout', source, review=review)

    def test_history_intent_is_checked_even_after_its_manifest_is_rehashed(self):
        job = self.original_at_blockout()
        state_path = self.root / '.vehicle-job/state.json'
        state = json.loads(state_path.read_text())
        manifest_path = self.root / state['history'][0]['path']
        manifest = json.loads(manifest_path.read_text())
        manifest['intent'] = 'reconstruction'
        manifest_path.chmod(0o600)
        manifest_path.write_text(json.dumps(manifest))
        state['history'][0]['sha256'] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, 'intent'):
            job.status(self.root)

    def test_design_review_rejects_stale_diagnostics_design_checks_and_approval(self):
        import copy
        job = self.original_at_blockout(route='existing')
        source, review, record = self.design_review_fixture()
        registration = record['registration']
        cases = []
        for field, value in [('accepted_design', self.fingerprint('brief.md')), ('design_checks', []),
                             ('source_sha256', '0'*64), ('mode', 'measured_camera_fit')]:
            cases.append({**registration, field: value})
        for field, value in [('source_sha256', '0'*64), ('accepted_design_sha256', '0'*64),
                             ('status', 'pending'), ('evidence', {}), ('model_version', 'old')]:
            broken = copy.deepcopy(registration)
            broken['approval'][field] = value
            cases.append(broken)
        for field, value in [('status', 'blocked'), ('finding', ''), ('requirement', ''),
                             ('evidence_paths', ['reference.png'])]:
            broken = copy.deepcopy(registration)
            broken['design_checks'][0][field] = value
            cases.append(broken)
        for broken in cases:
            self.write_json(review, {**record, 'registration': broken})
            self.assertTrue(job.status(self.root, source=source, review=review)['unmet_checks'], broken)
            with self.assertRaises(ValueError):
                job.advance(self.root, 'blockout', source, review=review)
        for metric in ({'triangles': 12}, {'source_sha256': '0'*64}, {},
                       {'source_sha256': record['source']['sha256'], 'lineage': {'output_sha256': '0'*64}},
                       {'source_sha256': None, 'lineage': {'output_sha256': record['source']['sha256']}}):
            self.write_json('metrics.json', metric)
            registration['metrics_report'] = self.fingerprint('metrics.json')
            self.write_json(review, record)
            self.assertTrue(job.status(self.root, source=source, review=review)['unmet_checks'], metric)
            with self.subTest(metric=metric), self.assertRaises(ValueError):
                job.advance(self.root, 'blockout', source, review=review)
        # Output lineage is accepted directly for real producers that report saved output bytes.
        self.write_json('metrics.json', {'lineage': {'output_sha256': record['source']['sha256']}})
        registration['metrics_report'] = self.fingerprint('metrics.json')
        self.write_json(review, record)
        self.assertEqual(job.advance(self.root, 'blockout', source, review=review)['stage'], 'assemblies')

    def test_new_route_preparation_authorization_paths_and_image_bindings_are_not_optional(self):
        import copy
        job = self.module()
        job.init_job(self.root, self.source, 'new')
        manifest, references, authorization = self.authorization_fixture()
        (self.root / 'work/source-v001.blend').write_bytes(self.source.read_bytes())
        with self.assertRaises(ValueError):
            job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)
        self.prepared_fixture()
        original = copy.deepcopy(authorization)
        for images in ([], [self.fingerprint('brief.md')],
                       [self.fingerprint('reference.png'), self.fingerprint('reference.png')]):
            self.write_json('design-authorization.json', {**original, 'reference_images': images})
            references['authorization'] = self.fingerprint('design-authorization.json')
            self.write_json(manifest, references)
            with self.subTest(images=images), self.assertRaises(ValueError):
                job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)
        (self.root / 'brief-link.md').symlink_to(self.root / 'brief.md')
        for raw in ('../user.blend', str(self.source), '.vehicle-job/baseline.blend', 'brief-link.md'):
            self.write_json('design-authorization.json', {**original, 'brief': {'path': raw, 'sha256': '0'*64}})
            references['authorization'] = self.fingerprint('design-authorization.json')
            self.write_json(manifest, references)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)

    def test_accepted_original_brief_consent_and_images_remain_immutable(self):
        job = self.original_at_blockout()
        for raw in ('brief.md', 'concept-decision.txt', 'design-authorization.json', 'reference.png', 'references.json'):
            target = self.root / raw
            before = target.read_bytes()
            target.write_bytes(before + b'changed')
            with self.subTest(path=raw), self.assertRaises(ValueError):
                job.status(self.root)
            target.write_bytes(before)
        self.assertTrue(job.status(self.root)['history_verified'])

    def test_failed_reconstruction_cannot_switch_to_original_design_in_place(self):
        job = self.at_blockout()
        source, review, record = self.review_fixture()
        measurements = json.loads((self.root / 'landmarks.json').read_text())
        measurements['landmarks'][0]['model_px'] = [1, 1]
        self.write_json('landmarks.json', measurements)
        record['registration']['landmarks'] = self.fingerprint('landmarks.json')
        self.write_json(review, record)
        with self.assertRaisesRegex(ValueError, 'tolerance'):
            job.advance(self.root, 'blockout', source, review=review)
        record['registration']['mode'] = 'design_review'
        self.write_json(review, record)
        with self.assertRaisesRegex(ValueError, 'Registration mode'):
            job.advance(self.root, 'blockout', source, review=review)
        state_path = self.root / '.vehicle-job/state.json'
        state = json.loads(state_path.read_text())
        self.assertNotIn('intent', state)  # Actual legacy/default layout stays reconstruction.
        state['intent'] = 'original_design'
        state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, 'Genesis'):
            job.status(self.root)

    def test_shipped_design_templates_are_deliberately_unfilled_and_do_not_authorize(self):
        import shutil
        job = self.module()
        assets = Path(job.__file__).parent.parent / 'assets'
        for name in ('design-authorization.json', 'design-review-registration.json'):
            self.assertTrue((assets / name).is_file(), 'Missing documentary template: ' + name)
        job.init_job(self.root, self.source, 'new', intent='original_design')
        self.prepared_fixture()
        manifest, references, authorization = self.authorization_fixture('original_design')
        shutil.copyfile(assets / 'design-authorization.json', self.root / 'unfilled-authorization.json')
        references['authorization'] = self.fingerprint('unfilled-authorization.json')
        self.write_json(manifest, references)
        with self.assertRaises(ValueError):
            job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)
        references['authorization'] = self.fingerprint('design-authorization.json')
        self.write_json(manifest, references)
        job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)
        source, review, record = self.design_review_fixture()
        record['registration'] = json.loads((assets / 'design-review-registration.json').read_text())
        self.write_json(review, record)
        with self.assertRaises(ValueError):
            job.advance(self.root, 'blockout', source, review=review)

    def test_pre_intent_schema_one_history_stays_usable_without_migration(self):
        job = self.at_blockout()
        state_path = self.root / '.vehicle-job/state.json'
        state = json.loads(state_path.read_text())
        manifest_path = self.root / state['history'][0]['path']
        manifest = json.loads(manifest_path.read_text())
        manifest.pop('intent')
        manifest_path.chmod(0o600)
        manifest_path.write_text(json.dumps(manifest))
        state['history'][0]['sha256'] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        state_path.write_text(json.dumps(state))
        self.assertEqual(job.status(self.root)['intent'], 'reconstruction')
        source, review, record = self.review_fixture()
        self.assertEqual(job.advance(self.root, 'blockout', source, review=review)['stage'], 'assemblies')

    @unittest.skipUnless(importlib.util.find_spec('bpy') and importlib.util.find_spec('PIL'),
                         'Actual bpy/Pillow runtime unavailable; mechanics suite needs only stdlib')
    def test_real_blender_original_design_producers_connect_to_controller(self):
        # Real preparation/audit/render bytes; design approvals/findings are EXPLICITLY SYNTHETIC
        # mechanics fixtures. This test is never evidence of real user consent or art quality.
        import bpy
        from PIL import Image, ImageDraw
        import reconstruct_vehicle
        import shutil
        import subprocess
        import sys
        job = self.module()
        bpy.ops.wm.read_factory_settings(use_empty=True)
        collection = bpy.data.collections.new('SyntheticProduct')
        bpy.context.scene.collection.children.link(collection)
        bpy.ops.mesh.primitive_cube_add(size=2)
        cube = bpy.context.object
        for old in list(cube.users_collection):
            old.objects.unlink(cube)
        collection.objects.link(cube)
        cube.name = 'SyntheticFictionalProduct'
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        original_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        job.init_job(self.root, self.source, 'new', intent='original_design')
        self.assertEqual(reconstruct_vehicle.main([
            'prepare-source', '--source', str(self.source),
            '--output', str(self.root / 'work/source-v001.blend'),
            '--report', str(self.root / 'source-preparation.json')]), 0)
        manifest, references, authorization = self.authorization_fixture('original_design')
        concept = Image.new('RGB', (64, 64), 'white')
        ImageDraw.Draw(concept).rectangle((16, 16, 48, 48), fill='gray', outline='black')
        concept.save(self.root / 'reference.png')
        references['images'][0].update(self.fingerprint('reference.png'))
        references['images'][0]['description'] = 'Synthetic fictional cube product concept drawing, not a photo.'
        references['features'][0]['description'] = 'Synthetic original cube concept square profile.'
        authorization['reference_images'] = [self.fingerprint('reference.png')]
        self.write_json('design-authorization.json', authorization)
        references['authorization'] = self.fingerprint('design-authorization.json')
        self.write_json(manifest, references)
        job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)
        source, review, record = self.design_review_fixture()
        shutil.copyfile(self.root / 'work/source-v001.blend', self.root / source)
        record['source'].update(self.fingerprint(source))
        scripts = Path(job.__file__).parent
        self.write_json('integration-rig.json', {
            'schema_version': 1, 'collection': 'SyntheticProduct', 'resolution': [64, 64],
            'samples': 1, 'modes': ['silhouette'], 'preview_frame_heights': [],
            'views': [{'name': 'side', 'direction': [1, 0, 0]}],
            'frame': None, 'exposure': 0, 'world_strength': 0.35})
        for action, arguments in [('audit', ['--collection', 'SyntheticProduct', '--output', str(self.root / 'actual-audit.json')]),
                                  ('render', ['--config', str(self.root / 'integration-rig.json'),
                                              '--output', str(self.root / 'actual-renders')])]:
            result = subprocess.run([sys.executable, str(scripts / 'blender_vehicle_tools.py'), action,
                                     '--blend', str(self.root / source), *arguments],
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        actual_image = 'actual-renders/side-silhouette.png'
        record['evidence'][0].update(self.fingerprint(actual_image))
        for check in record['coverage'].values():
            check['evidence_paths'] = [actual_image]
        registration = record['registration']
        registration['source_sha256'] = record['source']['sha256']
        registration['metrics_report'] = self.fingerprint('actual-audit.json')
        registration['diagnostic_scope'] = 'Actual evaluated mesh audit, not aesthetic inspection or quality proof.'
        registration['metrics_finding'] = 'Actual audit reports 12 triangles; synthetic mechanics only.'
        registration['design_checks'][0]['evidence_paths'] = [actual_image]
        registration['approval']['source_sha256'] = record['source']['sha256']
        self.write_json(review, record)
        self.assertEqual(job.status(self.root, source=source, review=review)['unmet_checks'], [])
        self.assertEqual(job.advance(self.root, 'blockout', source, review=review)['stage'], 'assemblies')
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), original_hash)
        self.assertEqual(json.loads((self.root / 'actual-audit.json').read_text())['evaluated_totals']['triangles'], 12)

    def test_tampered_history_manifest_snapshot_or_earlier_evidence_blocks_status(self):
        job = self.at_blockout()
        state = json.loads((self.root / '.vehicle-job/state.json').read_text())
        manifest_path = self.root / state['history'][0]['path']
        manifest = json.loads(manifest_path.read_text())
        targets = [self.root / 'reference.png', manifest_path, self.root / manifest['files'][0]['snapshot'],
                   self.root / '.vehicle-job/baseline.blend', self.root / 'work/source-v001.blend']
        for target in targets:
            before = target.read_bytes()
            target.chmod(0o600)
            target.write_bytes(before + b'tamper')
            with self.subTest(target=target), self.assertRaises(ValueError):
                job.status(self.root)
            target.write_bytes(before)
        self.assertTrue(job.status(self.root)['history_verified'])

    def test_path_traversal_absolute_paths_and_symlinks_are_refused(self):
        job = self.started()
        manifest = self.reference_fixture()
        outside = self.base / 'outside.png'
        outside.write_bytes((self.root / 'reference.png').read_bytes())
        for raw in ('../user.blend', str(self.source), 'work/../../user.blend',
                    'C:\\outside.blend', '.vehicle-job/baseline.blend'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                job.advance(self.root, 'references', raw, references=manifest)
        (self.root / 'escape.png').symlink_to(outside)
        (self.root / 'local-link.png').symlink_to(self.root / 'reference.png')
        record = json.loads((self.root / manifest).read_text())
        for raw in ('escape.png', 'local-link.png'):
            bad = {**record, 'images': [{**record['images'][0], 'path': raw}]}
            self.write_json(manifest, bad)
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'Symlink'):
                job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)
        self.assertEqual(outside.read_bytes(), (self.root / 'reference.png').read_bytes())

    def test_renamed_text_is_not_an_image(self):
        job = self.started()
        manifest = self.reference_fixture()
        (self.root / 'reference.png').write_text('not a real image')
        record = json.loads((self.root / manifest).read_text())
        record['images'][0].update(self.fingerprint('reference.png'))
        self.write_json(manifest, record)
        with self.assertRaisesRegex(ValueError, 'actual supported'):
            job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)

    def test_concurrent_write_refused_and_failed_state_publish_is_atomic(self):
        from unittest.mock import patch
        job = self.started()
        manifest = self.reference_fixture()
        state_path = self.root / '.vehicle-job/state.json'
        original = state_path.read_bytes()
        lock = self.root / '.vehicle-job/lock'
        lock.write_text('another writer')
        with self.assertRaisesRegex(ValueError, 'locked'):
            job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)
        self.assertEqual(lock.read_text(), 'another writer')
        lock.unlink()
        real_replace = os.replace
        def fail_state_publish(source, destination):
            if Path(destination) == state_path:
                raise OSError('injected atomic replacement failure')
            return real_replace(source, destination)
        with patch.object(job.os, 'replace', side_effect=fail_state_publish):
            with self.assertRaisesRegex(OSError, 'injected'):
                job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)
        self.assertEqual(state_path.read_bytes(), original)
        self.assertFalse(lock.exists())
        self.assertEqual(list((self.root / '.vehicle-job/history').iterdir()), [])
        self.assertEqual(job.status(self.root)['stage'], 'references')

    def test_empty_metrics_or_unmeasured_camera_report_does_not_count(self):
        job = self.at_blockout()
        source, review, record = self.review_fixture()
        original_metrics = (self.root / 'metrics.json').read_bytes()
        self.write_json('metrics.json', {})
        record['registration']['metrics_report'] = self.fingerprint('metrics.json')
        self.write_json(review, record)
        with self.assertRaisesRegex(ValueError, 'Metrics report'):
            job.advance(self.root, 'blockout', source, review=review)
        (self.root / 'metrics.json').write_bytes(original_metrics)
        record['registration']['metrics_report'] = self.fingerprint('metrics.json')
        self.write_json('camera.json', {'unmeasured': True})
        record['registration']['camera_report'] = self.fingerprint('camera.json')
        self.write_json(review, record)
        with self.assertRaisesRegex(ValueError, 'camera'):
            job.advance(self.root, 'blockout', source, review=review)

    def test_review_checks_are_not_replaced_by_documentary_registration(self):
        job = self.at_blockout()
        source, review, record = self.review_fixture()
        record['coverage']['silhouette']['status'] = 'blocked'
        self.write_json(review, record)
        with self.assertRaisesRegex(ValueError, 'silhouette'):
            job.advance(self.root, 'blockout', source, review=review)
        self.assertEqual(job.status(self.root)['stage'], 'blockout')

    def test_missing_or_changed_historical_evidence_never_allows_later_gate(self):
        job = self.at_blockout()
        source, review, record = self.review_fixture()
        (self.root / 'reference.png').unlink()
        with self.assertRaisesRegex(ValueError, 'reference.png'):
            job.advance(self.root, 'blockout', source, review=review)

    def test_real_cli_init_record_and_blocked_review_exit_codes(self):
        import subprocess
        import sys
        job = self.module()
        executable = [sys.executable, job.__file__]
        initialized = subprocess.run(executable + ['init', '--job', str(self.root), '--source', str(self.source),
                                                   '--route', 'existing'], capture_output=True, text=True)
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.assertEqual(json.loads(initialized.stdout)['stage'], 'references')
        self.prepared_fixture()
        self.reference_fixture()
        recorded = subprocess.run(executable + ['record', '--job', str(self.root), '--stage', 'references',
                                                '--source', 'work/source-v001.blend', '--references', 'references.json'],
                                   capture_output=True, text=True)
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        self.assertEqual(json.loads(recorded.stdout)['stage'], 'blockout')
        failed = subprocess.run(executable + ['advance', '--job', str(self.root), '--stage', 'blockout',
                                              '--source', 'work/source-v001.blend', '--review', 'missing.json'],
                                 capture_output=True, text=True)
        self.assertEqual(failed.returncode, 2)
        self.assertEqual(json.loads(failed.stdout)['status'], 'blocked')
        self.assertEqual(job.status(self.root)['stage'], 'blockout')

    def test_interrupted_after_atomic_replace_keeps_committed_history_intact(self):
        from unittest.mock import patch
        job = self.started()
        manifest = self.reference_fixture()
        state_path = self.root / '.vehicle-job/state.json'
        real_replace = os.replace
        def replace_then_interrupt(source, destination):
            real_replace(source, destination)
            if Path(destination) == state_path:
                raise OSError('injected interruption AFTER atomic replacement')
        with patch.object(job.os, 'replace', side_effect=replace_then_interrupt):
            with self.assertRaisesRegex(OSError, 'AFTER'):
                job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)
        self.assertEqual(job.status(self.root)['stage'], 'blockout')
        self.assertTrue(job.status(self.root)['history_verified'])

    def test_reference_ledger_and_schema_must_be_explicit(self):
        job = self.started()
        manifest = self.reference_fixture()
        record = json.loads((self.root / manifest).read_text())
        for change in ({'schema_version': True}, {'features': []},
                       {'features': [{**record['features'][0], 'basis': 'guessed'}]}):
            self.write_json(manifest, {**record, **change})
            with self.subTest(change=change), self.assertRaises(ValueError):
                job.advance(self.root, 'references', 'work/source-v001.blend', references=manifest)

    def test_digest_chain_rejects_rehashed_but_unlinked_manifest(self):
        job = self.at_blockout()
        state_path = self.root / '.vehicle-job/state.json'
        state = json.loads(state_path.read_text())
        manifest_path = self.root / state['history'][0]['path']
        manifest = json.loads(manifest_path.read_text())
        manifest['previous'] = '0' * 64
        manifest_path.chmod(0o600)
        manifest_path.write_text(json.dumps(manifest))
        state['history'][0]['sha256'] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, 'chain'):
            job.status(self.root)

    def test_render_fingerprint_and_current_approval_cannot_be_stale(self):
        job = self.at_blockout()
        source, review, record = self.review_fixture()
        for change in ({'approval': {**record['approval'], 'model_version': 'older'}},
                       {'approval': {**record['approval'], 'gate': 'delivery'}},
                       {'evidence': [{**record['evidence'][0], 'sha256': '0' * 64}]}):
            self.write_json(review, {**record, **change})
            with self.subTest(change=change), self.assertRaises(ValueError):
                job.advance(self.root, 'blockout', source, review=review)


if __name__ == '__main__':
    unittest.main()
