"""Image diagnostic tests on labelled synthetic masks, not real reconstruction accuracy."""
import importlib.util
from pathlib import Path
import unittest

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None
SCRIPT = Path(__file__).with_name('reference_match.py')


def tools():
    spec = importlib.util.spec_from_file_location('reference_match', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipIf(Image is None, 'Pillow unavailable')
class MaskMetricTests(unittest.TestCase):
    def test_equal_and_different_masks_have_scoped_metrics(self):
        self.assertTrue(SCRIPT.exists(), 'reference-match tool is not implemented')
        m = tools()
        a = Image.new('L', (32, 32), 0)
        ImageDraw.Draw(a).rectangle((8, 8, 23, 23), fill=255)
        same = m.mask_metrics(a, a)
        self.assertEqual(same['silhouette_iou'], 1)
        self.assertEqual(same['mean_boundary_manhattan_px'], 0)
        b = Image.new('L', (32, 32), 0)
        ImageDraw.Draw(b).rectangle((12, 8, 27, 23), fill=255)
        shifted = m.mask_metrics(a, b)
        expected_intersection = sum(bool(x and y) for x, y in zip(a.tobytes(), b.tobytes()))
        expected_union = sum(bool(x or y) for x, y in zip(a.tobytes(), b.tobytes()))
        self.assertAlmostEqual(shifted['silhouette_iou'], expected_intersection/expected_union)
        self.assertGreater(shifted['mean_boundary_manhattan_px'], 0)
        with self.assertRaises(ValueError):
            m.mask_metrics(a, Image.new('L', (32, 32), 0))
        with self.assertRaises(ValueError):
            m.mask_metrics(a, Image.new('L', (16, 16), 255))


import hashlib
import json
import os
import tempfile
import copy


@unittest.skipIf(Image is None, 'Pillow unavailable')
class ReferenceReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        Image.new('RGB', (32, 32), '#777777').save(self.root/'photo.png')
        mask = Image.new('L', (32, 32), 0)
        ImageDraw.Draw(mask).rectangle((8, 8, 23, 23), fill=255)
        mask.save(self.root/'reference-mask.png')
        mask.point(lambda v: 255-v).save(self.root/'model-mask.png')
        Image.new('RGB', (32, 32), '#666666').save(self.root/'detail.png')
        (self.root/'source.blend').write_bytes(b'Synthetic source fixture, not artwork')
        sha = lambda p: hashlib.sha256((self.root/p).read_bytes()).hexdigest()
        self.spec = {'schema_version': 1,
                     'reference': {'path': 'photo.png', 'sha256': sha('photo.png'),
                                   'mask_path': 'reference-mask.png', 'mask_sha256': sha('reference-mask.png'),
                                   'foreground': 'light', 'source_note': 'Synthetic image fixture'},
                     'model': {'path': 'model-mask.png', 'sha256': sha('model-mask.png'),
                               'foreground': 'dark', 'source_path': 'source.blend', 'source_sha256': sha('source.blend'),
                               'detail_path': 'detail.png', 'detail_sha256': sha('detail.png')},
                     'registration': {'confirmed': True, 'note': 'Synthetic identical projection; not camera calibration'},
                     'features': [{'id': 'body', 'visibility': 'visible', 'assessment': 'unverified',
                                   'region': [8, 8, 24, 24], 'note': 'Synthetic example, manual assessment pending'}]}

    def test_report_produces_real_overlay_and_scoped_manual_coverage(self):
        m = tools()
        self.assertTrue(hasattr(m, 'evaluate'), 'report pipeline is not implemented')
        report = m.evaluate(self.spec, self.root, self.root/'output')
        self.assertEqual(report['metrics']['silhouette_iou'], 1)
        self.assertEqual(report['manual_feature_coverage']['unverified'], 1)
        self.assertIn('NOT', report['limitation'])
        self.assertTrue((self.root/'output/report.json').is_file())
        self.assertTrue((self.root/'output/comparison.html').is_file())
        with Image.open(self.root/'output/overlay.png') as overlay:
            self.assertEqual(overlay.size, (32, 32))
        self.assertEqual(hashlib.sha256((self.root/'source.blend').read_bytes()).hexdigest(), self.spec['model']['source_sha256'])
        with self.assertRaises(FileExistsError):
            m.evaluate(self.spec, self.root, self.root/'output')

    def test_invalid_or_unaligned_spec_does_not_create_output(self):
        m = tools()
        self.assertTrue(hasattr(m, 'evaluate'), 'report pipeline is not implemented')
        mutations = [('schema_version', True), ('features', []),
                     ('registration', {'confirmed': False, 'note': 'not aligned'}),
                     ('registration', {'confirmed': True, 'note': ''})]
        for i, (key, value) in enumerate(mutations):
            spec = copy.deepcopy(self.spec)
            spec[key] = value
            output = self.root/('invalid-'+str(i))
            with self.subTest(key=key), self.assertRaises(ValueError):
                m.evaluate(spec, self.root, output)
            self.assertFalse(output.exists())

    def test_stale_inputs_are_rejected(self):
        m = tools()
        self.assertTrue(hasattr(m, 'evaluate'), 'report pipeline is not implemented')
        for field, hash_field in [('path', 'sha256'), ('mask_path', 'mask_sha256')]:
            spec = copy.deepcopy(self.spec)
            spec['reference'][hash_field] = '0'*64
            with self.subTest(field=field), self.assertRaises(ValueError):
                m.evaluate(spec, self.root, self.root/'stale')
        spec = copy.deepcopy(self.spec)
        spec['model']['source_sha256'] = '0'*64
        with self.assertRaises(ValueError):
            m.evaluate(spec, self.root, self.root/'stale-source')

    def test_feature_labels_and_regions_are_validated(self):
        m = tools()
        self.assertTrue(hasattr(m, 'evaluate'), 'report pipeline is not implemented')
        for features in [self.spec['features']*2,
                         [dict(self.spec['features'][0], region=[0, 0, 99, 99])],
                         [dict(self.spec['features'][0], visibility='occluded', assessment='match')],
                         [dict(self.spec['features'][0], note='')]]:
            spec = copy.deepcopy(self.spec)
            spec['features'] = features
            with self.subTest(features=features), self.assertRaises(ValueError):
                m.evaluate(spec, self.root, self.root/'features')

    def test_escape_paths_and_output_outside_job_are_rejected(self):
        m = tools()
        self.assertTrue(hasattr(m, 'evaluate'), 'report pipeline is not implemented')
        for raw in ['../photo.png', '/etc/passwd', 'C:\\photo.png']:
            spec = copy.deepcopy(self.spec)
            spec['reference']['path'] = raw
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                m.evaluate(spec, self.root, self.root/'escape')
        with self.assertRaises(ValueError):
            m.evaluate(self.spec, self.root, self.root.parent/'outside-reference-report')
        (self.root/'escape-link').symlink_to(self.root.parent)
        spec = copy.deepcopy(self.spec)
        spec['reference']['path'] = 'escape-link/photo.png'
        with self.assertRaises(ValueError):
            m.evaluate(spec, self.root, self.root/'escape')

    def test_cli_writes_report_and_escapes_labels(self):
        import subprocess
        import sys
        self.spec['features'][0]['id'] = '<script>alert(1)</script>'
        self.spec['reference']['source_note'] = '<img src=https://example.invalid>'
        path = self.root/'spec.json'
        path.write_text(json.dumps(self.spec))
        result = subprocess.run([sys.executable, str(SCRIPT), str(path), '--root', str(self.root),
                                 '--output', str(self.root/'cli-output')], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        document = (self.root/'cli-output/comparison.html').read_text()
        self.assertIn('&lt;script&gt;', document)
        self.assertNotIn('<script>', document)
        self.assertIn('data:image/png;base64,', document)
        self.assertIn('computed_not_acceptance', result.stdout)

    def test_overlay_uses_same_four_neighbour_edges_as_metrics(self):
        m = tools()
        for name, hole in [('full', False), ('diagonal', True)]:
            Image.new('RGB', (8, 8), '#777777').save(self.root/'photo.png')
            Image.new('RGB', (8, 8), '#666666').save(self.root/'detail.png')
            mask = Image.new('L', (8, 8), 255)
            if hole:
                mask.putpixel((2, 2), 0)
            mask.save(self.root/'reference-mask.png')
            mask.point(lambda v: 255-v).save(self.root/'model-mask.png')
            spec = copy.deepcopy(self.spec)
            for row, pathkey, hashkey in [(spec['reference'], 'path', 'sha256'),
                                          (spec['reference'], 'mask_path', 'mask_sha256'),
                                          (spec['model'], 'path', 'sha256'),
                                          (spec['model'], 'detail_path', 'detail_sha256')]:
                row[hashkey] = hashlib.sha256((self.root/row[pathkey]).read_bytes()).hexdigest()
            spec['features'][0]['region'] = [0, 0, 8, 8]
            m.evaluate(spec, self.root, self.root/name)
            with Image.open(self.root/name/'overlay.png') as overlay:
                self.assertEqual(overlay.getpixel((0, 0)), (255, 255, 255), 'image exterior must be background')
                if hole:
                    self.assertEqual(overlay.getpixel((3, 3)), (119, 119, 119), 'diagonal-only adjacency is not a cardinal boundary')
                else:
                    expected = sum(x in (0, 7) or y in (0, 7) for x in range(8) for y in range(8))
                    raw = overlay.tobytes()
                    self.assertEqual(sum(raw[i:i+3] == b'\xff\xff\xff' for i in range(0, len(raw), 3)), expected)

    def test_mask_dimensions_and_alpha_are_not_silently_changed(self):
        m = tools()
        self.assertTrue(hasattr(m, 'evaluate'), 'report pipeline is not implemented')
        Image.new('RGBA', (32, 32), (255, 255, 255, 0)).save(self.root/'reference-mask.png')
        self.spec['reference']['mask_sha256'] = hashlib.sha256((self.root/'reference-mask.png').read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            m.evaluate(self.spec, self.root, self.root/'alpha')
        Image.new('L', (16, 16), 255).save(self.root/'reference-mask.png')
        self.spec['reference']['mask_sha256'] = hashlib.sha256((self.root/'reference-mask.png').read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            m.evaluate(self.spec, self.root, self.root/'size')


if __name__ == '__main__':
    unittest.main()
