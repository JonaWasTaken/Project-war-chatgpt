"""Real file/PNG CLI fixtures; these are not Blender or artwork-quality evidence."""
import base64
import copy
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

SCRIPT = Path(__file__).with_name('compare_reviews.py')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def png(width, height, rgb):
    def chunk(name, payload):
        return (struct.pack('>I', len(payload)) + name + payload +
                struct.pack('>I', zlib.crc32(name + payload) & 0xffffffff))
    scanlines = b''.join(b'\x00' + bytes(rgb) * width for _ in range(height))
    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(scanlines)) + chunk(b'IEND', b''))


class Tags(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class CompareReviewsTests(unittest.TestCase):
    def setUp(self):
        scratch = os.environ.get('TMPDIR')
        self.temp = tempfile.TemporaryDirectory(prefix='compare-reviews-', dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifests = []
        self.paths = []
        for side, rgb in [('before', (40, 50, 60)), ('after', (60, 50, 40))]:
            directory = self.root / side
            directory.mkdir()
            source = self.root / (side + '.blend')
            source.write_bytes(b'fixture source bytes, not an executable blend: ' + side.encode())
            rig = (b'{"schema_version":1,"fixture":"locked rig",'
                   b'"views":[{"name":"front","ortho_scale":4.0}]}\n')
            (directory / 'rig-lock.json').write_bytes(rig)
            images = []
            for width, height in [(8, 6), (4, 3)]:
                name = 'front-clay-%s.png' % height
                data = png(width, height, rgb)
                (directory / name).write_bytes(data)
                images.append({'view': 'front', 'mode': 'clay', 'path': name,
                               'frame_size': [width, height], 'sha256': sha(data)})
            manifest = {
                'schema_version': 1, 'source_path': str(source),
                'source_sha256': sha(source.read_bytes()), 'rig_sha256': sha(rig),
                'tool_sha256': sha(b'fixture renderer recipe version one'),
                'blender_version': '5.2.2 LTS', 'render_engine': 'CYCLES CPU', 'frame': 1,
                'camera_matrices': {'front': [[1.0, 0.0, 0.0, 0.0],
                                             [0.0, 1.0, 0.0, 0.0],
                                             [0.0, 0.0, 1.0, 0.0],
                                             [0.0, 0.0, 0.0, 1.0]]},
                'images': images,
            }
            path = directory / 'render-manifest.json'
            self.manifests.append(manifest)
            self.paths.append(path)
        self.output = self.root / 'comparison.html'
        self.save()

    def save(self):
        for path, manifest in zip(self.paths, self.manifests):
            path.write_text(json.dumps(manifest), encoding='utf-8')

    def run_cli(self, output=None, save=True):
        if save:
            self.save()
        return subprocess.run([sys.executable, str(SCRIPT), str(self.paths[0]),
                               str(self.paths[1]), '--output', str(output or self.output)],
                              capture_output=True, text=True)

    def assert_rejected(self, message, output=None):
        result = self.run_cli(output)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message.lower(), result.stderr.lower())
        self.assertNotIn('Traceback', result.stderr)
        if output is None:
            self.assertFalse(self.output.exists())

    def test_valid_pair_embeds_exact_pngs_and_native_previews_without_network(self):
        originals = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.output.read_text(encoding='utf-8')
        tags = Tags(text).tags
        images = [attrs for tag, attrs in tags if tag == 'img']
        self.assertEqual(len(images), 4)
        expected = sorted((path.parent / row['path']).read_bytes()
                          for path, manifest in zip(self.paths, self.manifests)
                          for row in manifest['images'])
        actual = sorted(base64.b64decode(attrs['src'].removeprefix('data:image/png;base64,'))
                        for attrs in images)
        self.assertEqual(expected, actual)
        self.assertEqual(sum('preview' in attrs.get('class', '') for attrs in images), 2)
        self.assertTrue(all(attrs.get('width') and attrs.get('height') for attrs in images))
        self.assertIn('max-width', text)
        self.assertIn('Before', text)
        self.assertIn('After', text)
        self.assertIn('not an aesthetic', text)
        for manifest in self.manifests:
            self.assertIn(manifest['source_sha256'], text)
        self.assertFalse(any(tag in ('script', 'link', 'iframe', 'object') for tag, _ in tags))
        self.assertFalse(any('src' in attrs and not attrs['src'].startswith('data:image/png;base64,')
                             for _, attrs in tags))
        for path, data in originals.items():
            self.assertEqual(path.read_bytes(), data, str(path))

    def test_stale_source_is_rejected_on_either_side(self):
        for manifest in self.manifests:
            source = Path(manifest['source_path'])
            original = source.read_bytes()
            source.write_bytes(original + b'changed')
            self.assert_rejected('source_sha256')
            source.write_bytes(original)

    def test_source_must_be_an_existing_absolute_file(self):
        original = self.manifests[1]['source_path']
        for value in ['relative.blend', str(self.root / 'missing.blend'), str(self.root)]:
            with self.subTest(value=value):
                self.manifests[1]['source_path'] = value
                self.assert_rejected('source')
        self.manifests[1]['source_path'] = original

    def test_schema_version_is_strict_on_both_sides(self):
        for manifest in self.manifests:
            for value in [2, True, 1.0, '1', None]:
                with self.subTest(value=value):
                    manifest['schema_version'] = value
                    self.assert_rejected('schema_version')
            manifest['schema_version'] = 1

    def test_rig_file_digest_is_verified_on_both_sides(self):
        for path in self.paths:
            rig = path.parent / 'rig-lock.json'
            original = rig.read_bytes()
            rig.write_bytes(original + b' ')
            self.assert_rejected('rig_sha256')
            rig.write_bytes(original)

    def test_different_rig_rejected_even_with_updated_digest(self):
        rig = self.paths[1].parent / 'rig-lock.json'
        rig.write_bytes(b'{"schema_version":1,"fixture":"different rig"}\n')
        self.manifests[1]['rig_sha256'] = sha(rig.read_bytes())
        self.assert_rejected('rig')

    def test_missing_rig_is_rejected(self):
        (self.paths[0].parent / 'rig-lock.json').unlink()
        self.assert_rejected('rig-lock.json')

    def test_controlled_metadata_must_match(self):
        for field, value in [('frame', 2), ('render_engine', 'CYCLES GPU'),
                             ('blender_version', '5.2.3 LTS')]:
            original = self.manifests[1][field]
            with self.subTest(field=field):
                self.manifests[1][field] = value
                self.assert_rejected(field)
            self.manifests[1][field] = original

    def test_camera_matrices_must_match_exactly(self):
        self.manifests[1]['camera_matrices']['front'][0][3] = 0.0000001
        self.assert_rejected('camera_matrices')

    def test_equal_but_invalid_controlled_metadata_is_rejected(self):
        baseline = copy.deepcopy(self.manifests)
        for field, value in [('frame', True), ('frame', 1.0), ('frame', None),
                             ('render_engine', ''), ('render_engine', 1),
                             ('blender_version', ''), ('blender_version', None),
                             ('camera_matrices', {}), ('camera_matrices', {'front': [[1]]}),
                             ('camera_matrices', {'front': [[True] * 4] * 4}),
                             ('camera_matrices', {'front': [[float('nan')] * 4] * 4})]:
            with self.subTest(field=field, value=value):
                self.manifests = copy.deepcopy(baseline)
                for manifest in self.manifests:
                    manifest[field] = value
                self.assert_rejected(field)
        self.manifests = baseline

    def test_sha256_fields_have_strict_format(self):
        baseline = copy.deepcopy(self.manifests)
        for field in ['source_sha256', 'rig_sha256', 'tool_sha256']:
            for value in ['', 'z' * 64, None, 7]:
                with self.subTest(field=field, value=value):
                    self.manifests = copy.deepcopy(baseline)
                    self.manifests[0][field] = value
                    self.assert_rejected(field)

    def test_stale_images_are_rejected_on_either_side(self):
        for path, manifest in zip(self.paths, self.manifests):
            image = path.parent / manifest['images'][0]['path']
            original = image.read_bytes()
            image.write_bytes(original + b'stale bytes')
            self.assert_rejected('sha256')
            image.write_bytes(original)

    def test_empty_or_nonlist_images_are_rejected(self):
        baseline = copy.deepcopy(self.manifests)
        for value in [[], {}, None, 'images']:
            with self.subTest(value=value):
                self.manifests = copy.deepcopy(baseline)
                for manifest in self.manifests:
                    manifest['images'] = value
                self.assert_rejected('images')

    def test_duplicate_pairs_are_rejected_on_either_side(self):
        for manifest in self.manifests:
            manifest['images'].append(copy.deepcopy(manifest['images'][0]))
            self.assert_rejected('duplicate')
            manifest['images'].pop()

    def test_pair_sets_must_match_including_previews(self):
        self.manifests[1]['images'].pop()
        self.assert_rejected('pair')

    def test_pair_order_does_not_matter(self):
        self.manifests[1]['images'].reverse()
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_image_dimensions_must_match_png_header_despite_updated_digest(self):
        row = self.manifests[1]['images'][0]
        image = self.paths[1].parent / row['path']
        image.write_bytes(png(7, 6, (0, 0, 0)))
        row['sha256'] = sha(image.read_bytes())
        self.assert_rejected('dimensions')

    def test_invalid_png_headers_are_rejected_despite_updated_digest(self):
        row = self.manifests[0]['images'][0]
        image = self.paths[0].parent / row['path']
        original = image.read_bytes()
        invalid = [b'not png', original[:24], b'notapng!' + original[8:],
                   original[:12] + b'IDAT' + original[16:],
                   original[:8] + struct.pack('>I', 12) + original[12:],
                   original[:29] + b'\x00\x00\x00\x00' + original[33:]]
        for data in invalid:
            with self.subTest(header=data[:33]):
                image.write_bytes(data)
                row['sha256'] = sha(data)
                self.assert_rejected('PNG')

    def test_invalid_image_rows_are_rejected_usefully(self):
        original = copy.deepcopy(self.manifests[0]['images'][0])
        invalid = [(None, 'images'), ({}, 'view')]
        for field, value in [('view', ''), ('view', 1), ('mode', None),
                             ('frame_size', []), ('frame_size', [8, True]),
                             ('frame_size', [0, 6]), ('frame_size', [8.0, 6]),
                             ('frame_size', [8, 6, 1]), ('sha256', 'bad')]:
            row = copy.deepcopy(original)
            row[field] = value
            invalid.append((row, field))
        for row, message in invalid:
            with self.subTest(row=row):
                self.manifests[0]['images'][0] = row
                self.assert_rejected(message)

    def test_each_image_view_needs_a_camera_matrix(self):
        for manifest in self.manifests:
            manifest['images'][0]['view'] = 'unrecorded-camera'
        self.assert_rejected('camera_matrices')

    def test_image_paths_reject_absolute_traversal_and_windows_escapes(self):
        row = self.manifests[0]['images'][0]
        original = row['path']
        candidates = ['../before/' + original, '/absolute.png', 'C:\\escape.png',
                      'C:escape.png', '\\\\server\\escape.png', '..\\before\\' + original,
                      './' + original, '', None, 2, 'bad\x00.png']
        for value in candidates:
            with self.subTest(path=value):
                row['path'] = value
                self.assert_rejected('image path')

    def make_symlink(self, link, target):
        try:
            link.symlink_to(target, target_is_directory=target.is_dir())
        except (OSError, NotImplementedError) as exc:
            self.skipTest('symlinks unavailable: %s' % exc)

    def test_symlink_image_escape_is_rejected(self):
        row = self.manifests[0]['images'][0]
        outside = self.root / 'outside.png'
        image = self.paths[0].parent / row['path']
        outside.write_bytes(image.read_bytes())
        image.unlink()
        self.make_symlink(image, outside)
        self.assert_rejected('image path')

    def test_symlink_directory_escape_is_rejected(self):
        directory = self.paths[0].parent
        self.make_symlink(directory / 'escape', self.paths[1].parent)
        self.manifests[0]['images'][0] = copy.deepcopy(self.manifests[1]['images'][0])
        self.manifests[0]['images'][0]['path'] = 'escape/' + self.manifests[1]['images'][0]['path']
        self.assert_rejected('image path')

    def test_safe_nested_and_internal_symlink_paths_are_allowed(self):
        row = self.manifests[0]['images'][0]
        directory = self.paths[0].parent
        nested = directory / 'nested'
        nested.mkdir()
        original = directory / row['path']
        relocated = nested / row['path']
        original.rename(relocated)
        self.make_symlink(original, relocated)
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.output.unlink()
        row['path'] = 'nested/' + relocated.name
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_output_and_all_inputs_are_never_overwritten(self):
        self.output.write_bytes(b'existing output marker')
        targets = [self.output, *self.paths,
                   *(Path(manifest['source_path']) for manifest in self.manifests),
                   *(path.parent / 'rig-lock.json' for path in self.paths),
                   *(path.parent / row['path'] for path, manifest in zip(self.paths, self.manifests)
                     for row in manifest['images'])]
        originals = {target: target.read_bytes() for target in targets}
        for target in targets:
            with self.subTest(output=target):
                self.assert_rejected('output', output=target)
                self.assertEqual(target.read_bytes(), originals[target])

    def test_output_symlink_is_refused_even_when_target_does_not_exist(self):
        target = self.root / 'new-target.html'
        self.make_symlink(self.output, target)
        self.assert_rejected('output', output=self.output)
        self.assertTrue(self.output.is_symlink())
        self.assertFalse(target.exists())

    def test_output_symlink_cannot_overwrite_source(self):
        source = Path(self.manifests[0]['source_path'])
        original = source.read_bytes()
        self.make_symlink(self.output, source)
        self.assert_rejected('output', output=self.output)
        self.assertEqual(source.read_bytes(), original)

    def test_html_escapes_all_manifest_labels(self):
        attack = '\"><script>alert("x")</script><img src="https://example.invalid/x" onerror="bad">&'
        for manifest in self.manifests:
            manifest['blender_version'] = attack
            manifest['render_engine'] = attack
            manifest['camera_matrices'][attack] = manifest['camera_matrices'].pop('front')
            for row in manifest['images']:
                row['view'] = attack
                row['mode'] = attack
        # Ampersands and apostrophes are portable filename characters.
        for manifest in self.manifests:
            source = Path(manifest['source_path'])
            renamed = source.with_name(source.stem + "&'" + source.suffix)
            source.rename(renamed)
            manifest['source_path'] = str(renamed)
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        document = self.output.read_text(encoding='utf-8')
        self.assertIn('&lt;script&gt;', document)
        self.assertIn('&quot;', document)
        self.assertIn('&amp;&#x27;', document)
        tags = Tags(document).tags
        self.assertFalse(any(tag == 'script' for tag, _ in tags))
        self.assertEqual(sum(tag == 'img' for tag, _ in tags), 4)
        self.assertFalse(any(key.startswith('on') for _, attrs in tags for key in attrs))

    def test_duplicate_json_keys_are_rejected(self):
        serialized = self.paths[0].read_text(encoding='utf-8')
        self.paths[0].write_text(serialized.replace('"schema_version": 1',
                                                   '"schema_version": 1, "schema_version": 1'),
                                 encoding='utf-8')
        result = self.run_cli(save=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('duplicate', result.stderr.lower())
        self.assertFalse(self.output.exists())

    def test_invalid_json_and_nonobject_manifests_have_clean_errors(self):
        for data in [b'{', b'[]', b'null', b'\xff']:
            with self.subTest(data=data):
                self.paths[1].write_bytes(data)
                result = self.run_cli(save=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr.strip())
                self.assertNotIn('Traceback', result.stderr)
                self.assertFalse(self.output.exists())

    def test_missing_manifest_has_a_clean_error(self):
        self.paths[1].unlink()
        result = self.run_cli(save=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('render-manifest.json', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertFalse(self.output.exists())

    def test_missing_or_directory_image_has_a_clean_error(self):
        image = self.paths[1].parent / self.manifests[1]['images'][0]['path']
        image.unlink()
        self.assert_rejected('image path')
        image.mkdir()
        self.assert_rejected('image path')

    def test_identical_reviews_are_valid_without_claiming_improvement(self):
        self.paths[1] = self.paths[0]
        self.manifests[1] = self.manifests[0]
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        document = self.output.read_text(encoding='utf-8')
        self.assertNotIn('improved', document.lower())
        self.assertNotIn('score:', document.lower())

    def test_tool_digest_is_required_on_both_sides(self):
        for manifest in self.manifests:
            original = manifest.pop('tool_sha256')
            self.assert_rejected('tool_sha256')
            manifest['tool_sha256'] = original

    def test_tool_digest_must_match_to_prevent_recipe_changes(self):
        self.manifests[1]['tool_sha256'] = sha(b'changed renderer lighting recipe')
        self.assert_rejected('tool_sha256')

    def test_changed_ortho_scale_is_rejected_even_with_updated_rig_digest(self):
        rig = self.paths[1].parent / 'rig-lock.json'
        config = json.loads(rig.read_text(encoding='utf-8'))
        config['views'][0]['ortho_scale'] = 4.25
        rig.write_text(json.dumps(config), encoding='utf-8')
        self.manifests[1]['rig_sha256'] = sha(rig.read_bytes())
        self.assert_rejected('rig_sha256')

    def test_pair_modes_must_match(self):
        self.manifests[1]['images'][0]['mode'] = 'silhouette'
        self.assert_rejected('pair')


if __name__ == '__main__':
    unittest.main()
