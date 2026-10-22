"""Record-integrity tests with synthetic evidence; not artwork tests."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('check_review.py')
CATEGORIES = ('silhouette', 'proportions', 'fit', 'shading', 'materials', 'readability', 'motion', 'regression')


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        # This is explicitly a synthetic non-image fixture, not a generated render.
        (self.root / 'side.png').write_bytes(b'SYNTHETIC UNIT TEST EVIDENCE')
        (self.root / 'source.blend').write_bytes(b'SYNTHETIC SOURCE FIXTURE, NOT A BLENDER FILE')
        self.record = {
            'schema_version': 2, 'gate': 'blockout', 'model_version': 'v001',
            'required_views': ['side'], 'motion_required': False,
            'source': {'path': 'source.blend', 'version': 'v001',
                       'sha256': hashlib.sha256((self.root / 'source.blend').read_bytes()).hexdigest()},
            'evidence': [{'path': 'side.png', 'kind': 'render', 'version': 'v001',
                          'view': 'side', 'inspected': True,
                          'finding': 'Synthetic fixture observation for record validation.',
                          'sha256': hashlib.sha256((self.root / 'side.png').read_bytes()).hexdigest()}],
            'coverage': {key: {'status': 'pass', 'reason': 'Fixture check only.',
                              'evidence_paths': ['side.png']} for key in CATEGORIES},
            'defects': [],
            'approval': {'status': 'approved', 'reference': 'Fixture user turn',
                         'scope': 'blockout v001', 'model_version': 'v001', 'gate': 'blockout'},
        }

    def run_record(self):
        path = self.root / 'review.json'
        path.write_text(json.dumps(self.record), encoding='utf-8')
        return subprocess.run([sys.executable, str(SCRIPT), str(path), '--root', str(self.root)],
                              capture_output=True, text=True, timeout=10)

    def test_ready_record_has_explicit_limited_claim(self):
        result = self.run_record()
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['status'], 'record-ready')
        self.assertIn('artistic', output['limitation'].lower())

    def test_pending_approval_cannot_pass_blockout(self):
        self.record['approval']['status'] = 'pending'
        result = self.run_record()
        self.assertEqual(result.returncode, 1)
        self.assertIn('approval', result.stdout.lower())

    def test_incomplete_or_contradictory_records_never_pass(self):
        import copy
        mutations = {
            'no_evidence': lambda r: r.update(evidence=[]),
            'missing_file': lambda r: r['evidence'][0].update(path='missing.png'),
            'empty_file': lambda r: r['evidence'][0].update(path='empty.png'),
            'stale_version': lambda r: r['evidence'][0].update(version='v000'),
            'not_inspected': lambda r: r['evidence'][0].update(inspected=False),
            'string_inspected': lambda r: r['evidence'][0].update(inspected='true'),
            'empty_finding': lambda r: r['evidence'][0].update(finding=' '),
            'missing_view': lambda r: r['evidence'][0].pop('view'),
            'artifact_only': lambda r: r['evidence'][0].update(kind='artifact'),
            'absolute_path': lambda r: r['evidence'][0].update(path=str(self.root / 'side.png')),
            'path_escape': lambda r: r['evidence'][0].update(path='../outside.png'),
            'missing_coverage': lambda r: r['coverage'].pop('proportions'),
            'blocked_check': lambda r: r['coverage']['shading'].update(status='blocked'),
            'failed_check': lambda r: r['coverage']['fit'].update(status='fail'),
            'unknown_check': lambda r: r['coverage']['fit'].update(status='great'),
            'no_reason': lambda r: r['coverage']['fit'].update(reason=''),
            'unlinked_coverage': lambda r: r['coverage']['fit'].update(evidence_paths=['other.png']),
            'no_coverage_evidence': lambda r: r['coverage']['fit'].update(evidence_paths=[]),
            'no_approval_reference': lambda r: r['approval'].update(reference=''),
            'open_blocker': lambda r: r.update(defects=[{'id':'D1','severity':'blocker','state':'open','description':'Bad silhouette'}]),
            'accepted_blocker': lambda r: r.update(defects=[{'id':'D1','severity':'blocker','state':'accepted','description':'Bad silhouette','acceptance_reference':'fixture'}]),
            'open_important': lambda r: r.update(defects=[{'id':'D1','severity':'important','state':'open','description':'Wrong turret'}]),
            'fixed_without_recheck': lambda r: r.update(defects=[{'id':'D1','severity':'important','state':'fixed','description':'Wrong turret'}]),
            'accepted_without_reference': lambda r: r.update(defects=[{'id':'D1','severity':'important','state':'accepted','description':'Wrong turret'}]),
            'unknown_defect_state': lambda r: r.update(defects=[{'id':'D1','severity':'important','state':'maybe','description':'Wrong turret'}]),
            'bad_evidence_type': lambda r: r.update(evidence='image.png'),
            'bad_coverage_type': lambda r: r.update(coverage=[]),
            'bad_defects_type': lambda r: r.update(defects=None),
        }
        (self.root / 'empty.png').touch()
        original = copy.deepcopy(self.record)
        for name, mutation in mutations.items():
            with self.subTest(name=name):
                self.record = copy.deepcopy(original)
                mutation(self.record)
                result = self.run_record()
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertTrue(json.loads(result.stdout)['errors'])

    def test_stale_approval_does_not_authorize_current_version(self):
        self.record['approval']['model_version'] = 'v000'
        self.assertEqual(self.run_record().returncode, 1)

    def test_required_gate_checks_cannot_be_marked_not_applicable(self):
        self.record['coverage']['silhouette'] = {'status': 'na', 'reason': 'Skip it'}
        self.assertEqual(self.run_record().returncode, 1)

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as outside:
            target = Path(outside) / 'outside.png'
            target.write_bytes(b'SYNTHETIC OUTSIDE FIXTURE')
            try:
                (self.root / 'linked.png').symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest('Symlinks unavailable on this system')
            self.record['evidence'][0]['path'] = 'linked.png'
            self.assertEqual(self.run_record().returncode, 1)

    def test_fixed_defect_requires_and_accepts_a_recheck_record(self):
        self.record['defects'] = [{'id': 'D1', 'severity': 'blocker', 'state': 'fixed',
                                  'description': 'Fixture defect', 'recheck_evidence': 'side.png'}]
        self.assertEqual(self.run_record().returncode, 0)

    def test_malformed_json_returns_input_error(self):
        path = self.root / 'malformed.json'
        path.write_text('{', encoding='utf-8')
        result = subprocess.run([sys.executable, str(SCRIPT), str(path), '--root', str(self.root)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['status'], 'input-error')

    def test_changed_evidence_bytes_are_rejected_even_with_same_filename(self):
        (self.root / 'side.png').write_bytes(b'CHANGED SYNTHETIC FIXTURE')
        self.assertEqual(self.run_record().returncode, 1)

    def test_changed_source_bytes_are_rejected_even_with_same_version_label(self):
        (self.root / 'source.blend').write_bytes(b'CHANGED SYNTHETIC SOURCE')
        self.assertEqual(self.run_record().returncode, 1)

    def test_source_version_mismatch_is_rejected(self):
        self.record['source']['version'] = 'v000'
        self.assertEqual(self.run_record().returncode, 1)

    def test_invalid_digest_is_rejected(self):
        self.record['evidence'][0]['sha256'] = 'not-a-digest'
        self.assertEqual(self.run_record().returncode, 1)

    def test_missing_required_view_blocks_readiness(self):
        self.record['required_views'].append('front')
        self.assertEqual(self.run_record().returncode, 1)

    def test_required_motion_cannot_be_waived_at_delivery(self):
        self.record['gate'] = 'delivery'
        self.record['approval']['gate'] = 'delivery'
        self.record['motion_required'] = True
        self.record['coverage']['motion'] = {'status': 'na', 'reason': 'Skipped'}
        self.assertEqual(self.run_record().returncode, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
