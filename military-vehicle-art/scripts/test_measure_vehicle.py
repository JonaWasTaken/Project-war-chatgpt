"""Numerical checks with synthetic coordinates, not Blender/artwork tests."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('measure_vehicle.py')


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.landmarks = {
            'schema_version': 1, 'model_version': 'v1', 'reference_version': 'r1',
            'view': 'side', 'alignment_confirmed': True,
            'alignment_note': 'Synthetic frames intentionally share projection and crop.',
            'reference_size': [100, 100], 'model_size': [200, 200],
            'tolerance_px': 5, 'tolerance_basis': 'Synthetic test threshold, not a recommended default.',
            'landmarks': [
                {'id': 'nose', 'reference_px': [10, 20], 'model_px': [26, 48]},
                {'id': 'tail', 'reference_px': [90, 20], 'model_px': [180, 40]},
            ],
        }

    def run_input(self, command, payload):
        path = self.root / 'input.json'
        path.write_text(json.dumps(payload), encoding='utf-8')
        result = subprocess.run([sys.executable, str(SCRIPT), command, str(path)],
                                capture_output=True, text=True, timeout=10)
        return result, json.loads(result.stdout) if result.stdout else {}

    def test_landmark_errors_use_reference_pixel_space(self):
        result, report = self.run_input('landmarks', self.landmarks)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report['status'], 'within-tolerances')
        self.assertAlmostEqual(report['landmarks'][0]['error_px'], 5.0)
        self.assertEqual(report['landmarks'][1]['error_px'], 0.0)
        self.assertIn('artistic', report['limitation'])

    def test_assembly_dimensions_and_attachment_gaps_are_checked(self):
        payload = {
            'schema_version': 1, 'model_version': 'v1', 'units': 'm',
            'coordinate_frame': 'approved vehicle frame', 'tolerance_basis': 'Synthetic fixture only.',
            'assemblies': [
                {'id': 'hull', 'measured_dimensions': [6.03, 3, 2],
                 'target_dimensions': [6, 3, 2], 'dimension_tolerance': [0.02, 0.02, 0.02]},
                {'id': 'turret', 'measured_dimensions': [2, 2, 1]},
            ],
            'attachments': [{'id': 'ring', 'from_assembly': 'hull', 'to_assembly': 'turret',
                             'from_position': [0, 0, 2], 'to_position': [0, 0, 2.1],
                             'expected_gap': 0, 'tolerance': 0.01}],
            'ratios': [{'id': 'width-height', 'numerator': {'assembly': 'hull', 'axis': 1},
                        'denominator': {'assembly': 'hull', 'axis': 2},
                        'target_ratio': 1.5, 'relative_tolerance': 0.01}],
        }
        result, report = self.run_input('assemblies', payload)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(report['status'], 'needs-correction')
        self.assertEqual(report['checks_failed'], 2)
        gap = next(row for row in report['checks'] if row['id'] == 'attachment:ring')
        self.assertAlmostEqual(gap['actual'], 0.1)

    def test_decimal_boundary_does_not_fail_due_to_roundoff(self):
        payload = {'schema_version': 1, 'model_version': 'v1', 'units': 'm',
                   'coordinate_frame': 'frame', 'tolerance_basis': 'Synthetic boundary fixture',
                   'assemblies': [{'id': 'body', 'measured_dimensions': [1.1, 1, 1],
                                   'target_dimensions': [1, 1, 1],
                                   'dimension_tolerance': [0.1, 0, 0]}]}
        result, report = self.run_input('assemblies', payload)
        self.assertEqual(result.returncode, 0, report)

    def test_landmark_drift_is_reported_not_fitted_away(self):
        self.landmarks['landmarks'][0]['model_px'] = [40, 40]
        result, report = self.run_input('landmarks', self.landmarks)
        self.assertEqual(result.returncode, 1, report)
        self.assertEqual(report['landmarks'][0]['error_px'], 10)

    def test_unaligned_frames_are_rejected(self):
        self.landmarks['alignment_confirmed'] = False
        result, report = self.run_input('landmarks', self.landmarks)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(report['status'], 'input-error')

    def test_invalid_landmark_inputs_are_rejected(self):
        import copy
        original = copy.deepcopy(self.landmarks)
        mutations = {
            'aspect': lambda d: d.update(model_size=[200, 100]),
            'zero_size': lambda d: d.update(reference_size=[0, 100]),
            'negative_tolerance': lambda d: d.update(tolerance_px=-1),
            'nan': lambda d: d.update(tolerance_px=float('nan')),
            'infinity': lambda d: d.update(tolerance_px=float('inf')),
            'boolean_number': lambda d: d.update(tolerance_px=True),
            'no_threshold_basis': lambda d: d.update(tolerance_basis=''),
            'no_points': lambda d: d.update(landmarks=[]),
            'outside_frame': lambda d: d['landmarks'][0].update(reference_px=[101, 20]),
            'duplicate_id': lambda d: d['landmarks'][1].update(id='nose'),
            'missing_reference': lambda d: d.pop('reference_version'),
            'string_confirmation': lambda d: d.update(alignment_confirmed='true'),
        }
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                payload = copy.deepcopy(original)
                mutation(payload)
                result, report = self.run_input('landmarks', payload)
                self.assertEqual(result.returncode, 2, report)
                self.assertEqual(report['status'], 'input-error')

    def test_measurements_without_acceptance_checks_are_not_a_pass(self):
        payload = {'schema_version': 1, 'model_version': 'v1', 'units': 'm',
                   'coordinate_frame': 'frame', 'tolerance_basis': 'Unknown dimensions',
                   'assemblies': [{'id': 'body', 'measured_dimensions': [1, 1, 1]}]}
        result, report = self.run_input('assemblies', payload)
        self.assertEqual(result.returncode, 2, report)

    def test_exact_assembly_dimensions_pass_without_default_thresholds(self):
        payload = {'schema_version': 1, 'model_version': 'v1', 'units': 'm',
                   'coordinate_frame': 'frame', 'tolerance_basis': 'Exact synthetic fixture',
                   'assemblies': [{'id': 'body', 'measured_dimensions': [6, 3, 2],
                                   'target_dimensions': [6, 3, 2],
                                   'dimension_tolerance': [0, 0, 0]}]}
        result, report = self.run_input('assemblies', payload)
        self.assertEqual(result.returncode, 0, report)
        self.assertEqual(report['checks_failed'], 0)

    def test_ratio_only_check_does_not_require_invented_world_dimensions(self):
        payload = {'schema_version': 1, 'model_version': 'v1', 'units': 'model-units',
                   'coordinate_frame': 'frame', 'tolerance_basis': 'Synthetic ratio fixture',
                   'assemblies': [{'id': 'body', 'measured_dimensions': [6, 3, 2]}],
                   'ratios': [{'id': 'shape', 'numerator': {'assembly': 'body', 'axis': 0},
                               'denominator': {'assembly': 'body', 'axis': 1},
                               'target_ratio': 2, 'relative_tolerance': 0}]}
        result, report = self.run_input('assemblies', payload)
        self.assertEqual(result.returncode, 0, report)
        self.assertEqual(report['checks'][0]['actual'], 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
