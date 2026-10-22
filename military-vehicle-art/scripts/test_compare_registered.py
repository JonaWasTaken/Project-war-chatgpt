"""Producer/consumer tests; synthetic PNG fixtures are not real-vehicle evidence."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from PIL import Image

class RegisteredComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'renders').mkdir()
        (self.root/'model.blend').write_bytes(b'Synthetic lineage fixture, not an executable scene')
        image = Image.new('RGB', (32,24), 'black')
        for y in range(6,18):
            for x in range(8,24):
                image.putpixel((x,y), (255,255,255))
        for name in ('photo.png','reference-mask.png','renders/mask.png','renders/detail.png'):
            image.save(self.root/name)
        self.manifest = {'schema_version':1,'kind':'registered_camera_render',
                         'source':{'path':str(self.root/'model.blend'),'sha256':self.sha('model.blend')},
                         'camera':{'name':'SyntheticCamera','type':'PERSP',
                                   'matrix_world':[[1,0,0,0],[0,1,0,0],[0,0,1,4],[0,0,0,1]]},
                         'image_size':[32,24], 'registration_note':'Synthetic projection fixture only',
                         'artifacts':{'mask':{'path':'mask.png','sha256':self.sha('renders/mask.png')},
                                      'detail':{'path':'detail.png','sha256':self.sha('renders/detail.png')}}}
        self.reference = {'schema_version':1,
                          'reference':{'path':'photo.png','sha256':self.sha('photo.png'),
                                       'mask_path':'reference-mask.png','mask_sha256':self.sha('reference-mask.png'),
                                       'foreground':'light','source_note':'Synthetic reference; tool mechanics only'},
                          'registration':{'confirmed':True,'note':'Synthetic matching camera/crop; not a real tank'},
                          'features':[{'id':'synthetic-panel','visibility':'visible','assessment':'unverified',
                                       'region':[8,6,24,18],'note':'Fixture only; no automatic detail assessment'}]}
        self.save()

    def sha(self, name):
        return hashlib.sha256((self.root/name).read_bytes()).hexdigest()

    def save(self):
        (self.root/'renders/manifest.json').write_text(json.dumps(self.manifest))
        (self.root/'reference.json').write_text(json.dumps(self.reference))

    def run_pair(self):
        import compare_registered
        return compare_registered.compare(self.root/'renders/manifest.json', self.root/'reference.json',
                                          self.root, self.root/'comparison')

    def test_pairs_real_fingerprinted_files_without_manual_model_transcription(self):
        report = self.run_pair()
        self.assertEqual(report['metrics']['silhouette_iou'], 1)
        self.assertEqual(report['manual_feature_coverage']['unverified'],1)
        self.assertTrue((self.root/'comparison/comparison.html').is_file())
        pair = json.loads((self.root/'comparison/paired-spec.json').read_text())
        self.assertEqual(pair['model']['foreground'],'light')
        self.assertEqual(pair['model']['source_sha256'],self.sha('model.blend'))
        self.assertEqual(pair['model']['detail_sha256'],self.sha('renders/detail.png'))
        self.assertEqual(pair['registration']['render_manifest']['sha256'],self.sha('renders/manifest.json'))
        self.assertEqual(report['inputs']['model_detail']['path'],'renders/detail.png')

    def test_stale_source_manifest_images_and_reference_masks_fail_without_output(self):
        for name in ('model.blend','renders/mask.png','renders/detail.png','reference-mask.png'):
            before = (self.root/name).read_bytes()
            (self.root/name).write_bytes(before+b'stale')
            with self.subTest(name=name), self.assertRaises((ValueError,OSError)):
                self.run_pair()
            self.assertFalse((self.root/'comparison').exists())
            (self.root/name).write_bytes(before)

    def test_unconfirmed_registration_wrong_kind_size_and_conflicting_model_are_rejected(self):
        original_m, original_r = copy.deepcopy(self.manifest), copy.deepcopy(self.reference)
        cases = [('reference', {'registration':{'confirmed':False,'note':'Not registered'}}),
                 ('reference', {'model':{'path':'invented.png'}}),
                 ('manifest', {'kind':'orthographic_studio_render'}),
                 ('manifest', {'image_size':[31,24]}),
                 ('manifest', {'camera':{'name':'x','type':'PANO','matrix_world':[[1]*4]*4}})]
        for target, fields in cases:
            self.manifest, self.reference = copy.deepcopy(original_m), copy.deepcopy(original_r)
            getattr(self,target).update(fields)
            self.save()
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.run_pair()
            self.assertFalse((self.root/'comparison').exists())

    def test_traversal_symlink_escape_and_existing_output_are_refused(self):
        original = copy.deepcopy(self.manifest)
        for path in ('../../photo.png','/outside.png','../photo.png'):
            self.manifest = copy.deepcopy(original)
            self.manifest['artifacts']['mask']['path'] = path
            self.save()
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.run_pair()
        self.manifest = original
        self.save()
        target = self.root/'renders/real-mask.png'
        (self.root/'renders/mask.png').rename(target)
        (self.root/'renders/mask.png').symlink_to(target)
        with self.assertRaisesRegex(ValueError,'Symlink'):
            self.run_pair()
        self.assertFalse((self.root/'comparison').exists())
        (self.root/'renders/mask.png').unlink()
        target.rename(self.root/'renders/mask.png')
        (self.root/'comparison').mkdir()
        (self.root/'comparison/keep.txt').write_text('unchanged')
        with self.assertRaises(FileExistsError):
            self.run_pair()
        self.assertEqual((self.root/'comparison/keep.txt').read_text(),'unchanged')

    def test_in_job_reference_symlinks_are_refused_without_output(self):
        for key,target in (('path','photo.png'),('mask_path','reference-mask.png')):
            link=self.root/('symlink-'+target)
            link.symlink_to(self.root/target)
            self.reference['reference'][key]=link.name
            self.save()
            with self.subTest(key=key), self.assertRaisesRegex(ValueError,'Symlink'):
                self.run_pair()
            self.assertFalse((self.root/'comparison').exists())
            self.reference['reference'][key]=target
            link.unlink()

    def test_cli_success_and_refusal_are_machine_readable(self):
        import subprocess
        import sys
        import compare_registered
        command = [sys.executable, compare_registered.__file__, '--manifest',str(self.root/'renders/manifest.json'),
                   '--reference-spec',str(self.root/'reference.json'),'--root',str(self.root),
                   '--output',str(self.root/'comparison')]
        run = subprocess.run(command,text=True,capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(json.loads(run.stdout)['status'],'computed_not_acceptance')
        run = subprocess.run(command,text=True,capture_output=True)
        self.assertEqual(run.returncode,2)
        self.assertEqual(json.loads(run.stdout)['status'],'error')

if __name__ == '__main__':
    unittest.main()
