"""Synthetic mechanics tests only; fixtures are NOT photographic fidelity evidence."""
import copy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import tempfile
import unittest

from PIL import Image
import numpy as np


class ContourTests(unittest.TestCase):
    def test_exact_bidirectional_distances_match_independent_bruteforce_oracle(self):
        self.assertIsNotNone(importlib.util.find_spec('compare_fidelity'), 'contour comparison is not implemented')
        import compare_fidelity as f
        def boundary(mask):
            h, w = mask.shape
            return [(y, x) for y in range(h) for x in range(w) if mask[y, x] and any(
                yy < 0 or yy >= h or xx < 0 or xx >= w or not mask[yy, xx]
                for yy, xx in ((y-1,x),(y+1,x),(y,x-1),(y,x+1)))]
        def oracle(a, b):
            return sorted(min(math.hypot(y-v, x-u) for v, u in b) for y, x in a)
        def stats(values):
            p = (len(values)-1)*.95
            lo = int(p)
            hi = math.ceil(p)
            return {'mean_px':sum(values)/len(values),
                    'p95_px':values[lo]+(p-lo)*(values[hi]-values[lo]), 'max_px':max(values)}
        single = np.zeros((7, 9), dtype=bool); single[1, 2] = True
        diagonal = np.zeros_like(single); diagonal[4, 6] = True
        full = np.ones_like(single)
        shifted = np.zeros_like(single); shifted[1:5, 3:8] = True
        ring = np.ones_like(single); ring[2:5, 2:6] = False
        for a, b in ((single, diagonal), (full, single), (ring, full), (shifted, ring), (full, full)):
            with self.subTest(a=int(a.sum()), b=int(b.sum())):
                result = f.contour_distances(a, b)
                ab, ba = oracle(boundary(a), boundary(b)), oracle(boundary(b), boundary(a))
                self.assertEqual(result['boundary_counts'], [len(ab), len(ba)])
                for name, values in (('model_to_reference', ab), ('reference_to_model', ba), ('pooled', sorted(ab+ba))):
                    for key, expected in stats(values).items():
                        self.assertAlmostEqual(result[name][key], expected, places=12)
        self.assertEqual(f.contour_distances(single, diagonal)['pooled']['max_px'], 5.0)

    def test_contour_rejects_empty_nonbinary_mismatched_and_unbounded_work(self):
        import compare_fidelity as f
        a = np.ones((3, 4), dtype=bool)
        for bad in (np.zeros_like(a), a.astype(float), np.ones((4, 3), dtype=bool), np.array(True)):
            with self.subTest(shape=bad.shape), self.assertRaises(ValueError):
                f.contour_distances(a, bad)
        from unittest.mock import patch
        with patch.object(f, 'MAX_CONTOUR_PAIRS', 2), self.assertRaisesRegex(ValueError, 'workload'):
            f.contour_distances(a, a)


class AppearanceTests(unittest.TestCase):
    def test_known_rgb_patches_use_signed_linear_srgb_and_d65_delta_e76(self):
        import compare_fidelity as f
        self.assertTrue(hasattr(f, 'appearance_statistics'), 'appearance comparison is not implemented')
        reference = np.array([[[0,0,0], [255,255,255], [255,0,0], [0,255,0]]], dtype=np.uint8)
        model = np.array([[[255,255,255], [0,0,0], [0,255,0], [128,128,128]]], dtype=np.uint8)
        region = np.array([[True, True, True, False]])
        result = f.appearance_statistics(model, reference, region)
        # Independent scalar implementation, not production transform imports.
        def linear(channel):
            c = channel / 255
            return c/12.92 if c <= .04045 else ((c+.055)/1.055)**2.4
        def lab(rgb):
            r, g, b = map(linear, rgb)
            xyz = ((.4124564*r+.3575761*g+.1804375*b)/.95047,
                   .2126729*r+.7151522*g+.0721750*b,
                   (.0193339*r+.1191920*g+.9503041*b)/1.08883)
            x, y, z = (v**(1/3) if v > (6/29)**3 else v/(3*(6/29)**2)+4/29 for v in xyz)
            return (116*y-16, 500*(x-y), 200*(y-z))
        errors = [math.dist(lab(m),lab(r)) for m,r in zip(model[0,:3],reference[0,:3])]
        self.assertEqual(result['pixels'], 3)
        self.assertAlmostEqual(result['delta_e76']['mean'], sum(errors)/3, places=10)
        self.assertAlmostEqual(result['delta_e76']['max'], max(errors), places=10)
        self.assertAlmostEqual(errors[0], 100, places=4)
        self.assertAlmostEqual(errors[2], 170.565242, places=5)
        self.assertEqual(result['encoded_srgb']['signed_mean'], [-1/3,1/3,0])
        self.assertEqual(result['linear_srgb']['signed_mean'], [-1/3,1/3,0])
        # Middle-grey patch proves the transfer function is applied, not just RGB.
        grey = np.array([[[128,128,128]]], dtype=np.uint8)
        black = np.zeros_like(grey)
        actual = f.appearance_statistics(grey,black,np.array([[True]]))
        self.assertAlmostEqual(actual['linear_srgb']['signed_mean'][0], linear(128), places=14)
        self.assertAlmostEqual(actual['delta_e76']['mean'], math.dist(lab([128]*3),lab([0]*3)), places=10)


class FileComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'render').mkdir()
        (self.root/'source.blend').write_bytes(b'Synthetic non-executable lineage fixture only')
        self.mask = np.zeros((12,16), dtype=np.uint8); self.mask[2:10,3:13] = 255
        self.region = np.zeros_like(self.mask); self.region[4:8,5:11] = 255
        for name in ('render/mask.png','reference-mask.png'):
            Image.fromarray(self.mask).save(self.root/name)
        Image.fromarray(self.region).save(self.root/'region.png')
        Image.new('RGB',(16,12),(128,128,128)).save(self.root/'render/detail.png')
        Image.new('RGB',(16,12),(64,64,64)).save(self.root/'reference.png')
        self.manifest = {'schema_version':1,'kind':'registered_camera_render',
            'source': {'path':str(self.root/'source.blend'),'sha256':self.sha('source.blend')},
            'camera':{'name':'SyntheticCamera','type':'PERSP','matrix_world':[[1,0,0,0],[0,1,0,0],[0,0,1,4],[0,0,0,1]]},
            'registration_note':'Synthetic aligned camera fixture, not a real object.', 'image_size':[16,12],
            'artifacts':{role:{'path':name,'sha256':self.sha('render/'+name)} for role,name in
                         (('mask','mask.png'),('detail','detail.png'))}}
        self.spec = {'schema_version':1,'view':{'id':'side','role':'fit'},
            'reference':{'path':'reference.png','sha256':self.sha('reference.png'),
                'mask_path':'reference-mask.png','mask_sha256':self.sha('reference-mask.png'),
                'foreground':'light','source_note':'Synthetic independently stored fixture; NOT photographic evidence.'},
            'evidence':{'kind':'synthetic_test','independent':False},
            'registration':{'confirmed':True,'note':'Synthetic exact crop and aligned pixel coordinates only.'},
            'appearance':{'color_encoding':'srgb','controlled_lighting':False,'calibrated':False,
                          'note':'Synthetic encoded image values; no physical material claim.'},
            'regions':[{'id':'panel','mask_path':'region.png','mask_sha256':self.sha('region.png')}]}
        self.save()

    def sha(self, name):
        return hashlib.sha256((self.root/name).read_bytes()).hexdigest()

    def save(self):
        (self.root/'render/render-manifest.json').write_text(json.dumps(self.manifest))
        (self.root/'spec.json').write_text(json.dumps(self.spec))

    def compare(self, output='result'):
        import compare_fidelity as f
        self.assertTrue(hasattr(f, 'compare'), 'manifest-backed compare is not implemented')
        return f.compare(self.root/'render/render-manifest.json', self.root/'spec.json',self.root,self.root/output)

    def test_manifest_comparison_uses_actual_files_and_keeps_evidence_declarations(self):
        report = self.compare()
        self.assertEqual(report['schema_version'],1)
        self.assertEqual(report['command'],'compare-fidelity')
        self.assertEqual(report['source_sha256'],self.sha('source.blend'))
        self.assertEqual(report['metrics']['contour']['pooled']['max_px'],0)
        region = report['metrics']['regions']['panel']
        self.assertEqual(region['pixels'],24)
        self.assertAlmostEqual(region['encoded_srgb']['signed_mean'][0],64/255)
        self.assertEqual(report['reference_evidence']['kind'],'synthetic_test')
        self.assertFalse(report['appearance_declaration']['controlled_lighting'])
        for key,name in (('render_manifest','render/render-manifest.json'), ('spec','spec.json'),
                         ('model_image','render/detail.png'), ('region:panel','region.png')):
            self.assertEqual(report['inputs'][key],{'path':name,'sha256':self.sha(name)})
        self.assertEqual(json.loads((self.root/'result/report.json').read_text()),report)
        self.assertEqual(report['diagnostic_status'],'computed_not_acceptance')
        with self.assertRaises(FileExistsError):
            self.compare()

    def test_independent_reference_cannot_alias_render_image_or_self_mask(self):
        self.spec['evidence'] = {'kind':'independent_photo','independent':True}
        self.spec['reference']['source_note'] = 'Declared independent photographic reference; synthetic test of rejection only.'
        original = copy.deepcopy(self.spec)
        for key, hashkey, path in (('path','sha256','render/detail.png'),('mask_path','mask_sha256','render/mask.png')):
            self.spec = copy.deepcopy(original)
            self.spec['reference'][key] = path
            self.spec['reference'][hashkey] = self.sha(path)
            self.save()
            with self.subTest(key=key), self.assertRaisesRegex(ValueError,'independent|alias'):
                self.compare()
            self.assertFalse((self.root/'result').exists())
        self.spec = copy.deepcopy(original)
        (self.root/'photo-hardlink.png').hardlink_to(self.root/'render/detail.png')
        self.spec['reference'].update(path='photo-hardlink.png',sha256=self.sha('photo-hardlink.png'))
        self.save()
        with self.assertRaisesRegex(ValueError,'independent|alias'):
            self.compare()

    def test_duplicate_region_masks_are_not_independent_region_measurements(self):
        self.spec['regions'].append({**self.spec['regions'][0],'id':'renamed-panel'})
        self.save()
        with self.assertRaisesRegex(ValueError,'duplicate region'):
            self.compare()

    def test_full_frame_dark_reference_and_full_frame_model_are_valid_boundaries(self):
        Image.new('L',(16,12),255).save(self.root/'render/mask.png')
        Image.new('L',(16,12),0).save(self.root/'reference-mask.png')
        self.spec['reference'].update(foreground='dark',mask_sha256=self.sha('reference-mask.png'))
        self.manifest['artifacts']['mask']['sha256'] = self.sha('render/mask.png')
        self.save()
        report = self.compare()
        self.assertEqual(report['metrics']['contour']['pooled']['max_px'],0)
        self.assertEqual(report['metrics']['contour']['boundary_counts'],[52,52])

    def test_cli_compare_aggregate_and_error_are_json(self):
        import subprocess
        import sys
        import compare_fidelity as f
        command = [sys.executable,f.__file__,'compare','--manifest',str(self.root/'render/render-manifest.json'),
                   '--spec',str(self.root/'spec.json'),'--root',str(self.root),'--output',str(self.root/'cli-result')]
        run = subprocess.run(command,text=True,capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertTrue(run.stdout.strip(),'compare CLI is not implemented')
        self.assertEqual(json.loads(run.stdout)['diagnostic_status'],'computed_not_acceptance')
        run = subprocess.run(command,text=True,capture_output=True)
        self.assertEqual(run.returncode,2)
        self.assertEqual(json.loads(run.stdout)['status'],'error')
        self.make_two_views()
        run = subprocess.run([sys.executable,f.__file__,'aggregate','--spec',str(self.root/'aggregate.json'),
                              '--root',str(self.root),'--output',str(self.root/'cli-aggregate')],text=True,capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(json.loads(run.stdout)['threshold_status'],'exceeded')

    def test_expected_hashes_must_not_be_null(self):
        original_spec, original_manifest = copy.deepcopy(self.spec), copy.deepcopy(self.manifest)
        for target in ('source','detail','reference','reference_mask','region'):
            self.spec, self.manifest = copy.deepcopy(original_spec), copy.deepcopy(original_manifest)
            if target == 'source':
                self.manifest['source']['sha256'] = None
            elif target == 'detail':
                self.manifest['artifacts']['detail']['sha256'] = None
            elif target == 'reference':
                self.spec['reference']['sha256'] = None
            elif target == 'reference_mask':
                self.spec['reference']['mask_sha256'] = None
            else:
                self.spec['regions'][0]['mask_sha256'] = None
            self.save()
            with self.subTest(target=target), self.assertRaisesRegex(ValueError,'fingerprint'):
                self.compare('hash-'+target)
            self.assertFalse((self.root/('hash-'+target)).exists())

    def test_mask_and_image_encoding_rejects_transparency_icc_and_high_bit_depth(self):
        import io
        import struct
        import zlib
        import compare_fidelity as f
        original = (self.root/'reference.png').read_bytes()
        for mode, options in (('RGBA',{}),('RGB',{'icc_profile':b'Synthetic unsupported ICC'})):
            image = Image.new(mode,(16,12),(20,30,40,127) if mode == 'RGBA' else (20,30,40))
            image.save(self.root/'reference.png',**options)
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError,'transparent|ICC'):
                f.image_array((self.root/'reference.png').read_bytes())
        # Construct a real 16-bit RGB PNG; Pillow would silently decode it as RGB8.
        def chunk(kind, data):
            return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        png = (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,16,2,0,0,0))+
               chunk(b'IDAT',zlib.compress(b'\x00'+b'\x80\x01'*3))+chunk(b'IEND',b''))
        self.assertEqual(Image.open(io.BytesIO(png)).mode,'RGB')
        with self.assertRaisesRegex(ValueError,'8-bit|bit depth'):
            f.image_array(png)
        (self.root/'reference.png').write_bytes(original)

    def test_schema_types_nonfinite_duplicates_paths_empty_and_workload_rejected(self):
        import compare_fidelity as f
        from unittest.mock import patch
        original = copy.deepcopy(self.spec)
        mutations = [(('schema_version',),True),(('registration','confirmed'),1),
            (('appearance','calibrated'),1),(('appearance','controlled_lighting'),'false'),
            (('reference','path'),''),(('reference','path'),'../reference.png'),
            (('reference','path'),'/outside.png'),(('reference','path'),False),
            (('reference','sha256'),'A'*64),(('reference','source_note'),''),
            (('regions',),[]),(('evidence','kind'),'unknown'),(('view','role'),'all'),
            (('regions',),[original['regions'][0],original['regions'][0]])]
        for index,(path,value) in enumerate(mutations):
            self.spec = copy.deepcopy(original)
            item = self.spec
            for key in path[:-1]: item = item[key]
            item[path[-1]] = value
            self.save()
            with self.subTest(path=path,value=value), self.assertRaises((ValueError,OSError)):
                self.compare('invalid-'+str(index))
        self.spec = original; self.save()
        for text in ('{"schema_version":1,"schema_version":1}', '{"n":NaN}', '{"n":Infinity}', '{"n":1e999}'):
            (self.root/'spec.json').write_text(text)
            with self.subTest(text=text),self.assertRaises(ValueError): self.compare('bad-json')
        self.save()
        for constant,limit in (('MAX_READ_BYTES',1),('MAX_JSON_BYTES',1),('MAX_PIXELS',10),('MAX_IMAGE_BYTES',1),('MAX_SOURCE_BYTES',1)):
            with self.subTest(constant=constant),patch.object(f,constant,limit),self.assertRaises(ValueError):
                # Runtime limits are applied at their callers, not default argument capture.
                self.compare('work-'+constant)
        link = self.root/'reference-link.png'; link.symlink_to(self.root/'reference.png')
        self.spec['reference']['path'] = link.name; self.save()
        with self.assertRaisesRegex(ValueError,'symlink'): self.compare('symlink-result')

    def test_fingerprints_checked_before_and_after_compute_without_publication(self):
        import compare_fidelity as f
        from unittest.mock import patch
        for name in ('source.blend','render/mask.png','render/detail.png','reference.png','reference-mask.png','region.png'):
            original = (self.root/name).read_bytes()
            (self.root/name).write_bytes(original+b'changed')
            with self.subTest(stale=name), self.assertRaisesRegex(ValueError,'stale'):
                self.compare()
            self.assertFalse((self.root/'result').exists())
            (self.root/name).write_bytes(original)
        original_function = f.appearance_statistics
        def mutate(*args):
            result = original_function(*args)
            (self.root/'reference.png').write_bytes(b'Changed after pixel computation')
            return result
        with patch.object(f,'appearance_statistics',side_effect=mutate),self.assertRaisesRegex(ValueError,'changed during'):
            self.compare()
        self.assertFalse((self.root/'result').exists())

    def test_atomic_exclusive_publication_losing_race_keeps_competing_directory(self):
        import compare_fidelity as f
        from unittest.mock import patch
        original = f.publish_directory
        def race(stage, output):
            output.mkdir()
            (output/'keep.txt').write_text('competitor owns this')
            original(stage,output)
        with patch.object(f,'publish_directory',side_effect=race),self.assertRaises(FileExistsError):
            self.compare()
        self.assertEqual((self.root/'result/keep.txt').read_text(),'competitor owns this')
        self.assertFalse((self.root/'result/report.json').exists())

    def make_two_views(self):
        first = self.compare('side-result')
        self.spec['view'] = {'id':'rear','role':'held_out'}
        self.manifest['camera']['matrix_world'][0][3] = 2
        self.manifest['camera']['name'] = 'SyntheticRearCamera'
        # A second actual renderer-artifact directory; not a renamed first report.
        (self.root/'rear-render').mkdir()
        for name in ('mask.png','detail.png'):
            (self.root/'rear-render'/name).write_bytes((self.root/'render'/name).read_bytes())
        Image.new('RGB',(16,12),(255,255,255)).save(self.root/'rear-render/detail.png')
        self.manifest['artifacts']['detail']['sha256'] = self.sha('rear-render/detail.png')
        (self.root/'rear-render/render-manifest.json').write_text(json.dumps(self.manifest))
        (self.root/'rear-spec.json').write_text(json.dumps(self.spec))
        import compare_fidelity as f
        second = f.compare(self.root/'rear-render/render-manifest.json',self.root/'rear-spec.json',self.root,self.root/'rear-result')
        self.aggregate_spec = {'schema_version':1,'purpose':'synthetic_test',
            'required_views':[{'id':'side','role':'fit'},{'id':'rear','role':'held_out'}],
            'reports':[{'path':name,'sha256':self.sha(name)} for name in ('side-result/report.json','rear-result/report.json')],
            'limits':{'contour_p95_px':0,'contour_max_px':0,'region_delta_e76_mean':50,'region_delta_e76_max':50}}
        (self.root/'aggregate.json').write_text(json.dumps(self.aggregate_spec))
        return first, second

    def aggregate(self, output='aggregate-result'):
        import compare_fidelity as f
        self.assertTrue(hasattr(f,'aggregate'),'source-bound aggregation is not implemented')
        return f.aggregate(self.root/'aggregate.json',self.root,self.root/output)

    def test_source_bound_aggregate_retains_worst_held_out_view_failure(self):
        self.make_two_views()
        report = self.aggregate()
        self.assertEqual(report['command'],'aggregate-fidelity')
        self.assertEqual(report['source_sha256'],self.sha('source.blend'))
        self.assertEqual(report['threshold_status'],'exceeded')
        self.assertEqual(report['roles']['fit']['threshold_status'],'not_exceeded')
        self.assertEqual(report['roles']['held_out']['threshold_status'],'exceeded')
        self.assertEqual(report['worst']['region_delta_e76_mean']['view_id'],'rear')
        self.assertEqual(report['worst']['region_delta_e76_mean']['role'],'held_out')
        self.assertEqual(report['worst']['region_delta_e76_mean']['region_id'],'panel')
        self.assertEqual(len(report['views']),2)
        self.assertTrue(report['views'][1]['failures'])
        self.assertEqual(json.loads((self.root/'aggregate-result/report.json').read_text()),report)
    def test_deliberately_unfilled_template_is_refused_without_output(self):
        template = Path(__file__).resolve().parents[1]/'assets/fidelity-comparison.json'
        self.assertTrue(template.is_file(),'comparison template is not implemented')
        (self.root/'unfilled.json').write_bytes(template.read_bytes())
        import compare_fidelity as f
        with self.assertRaises(ValueError):
            f.compare(self.root/'render/render-manifest.json',self.root/'unfilled.json',self.root,self.root/'unfilled-result')
        self.assertFalse((self.root/'unfilled-result').exists())

    def test_camera_numeric_fields_reject_bools_and_unknown_fields(self):
        original = copy.deepcopy(self.manifest)
        for index,(key,value) in enumerate((('lens_mm',True),('lens_mm',float('nan')),('ortho_scale',0),('lens_mm','50'),('unrecognized_projection',20))):
            self.manifest = copy.deepcopy(original)
            self.manifest['camera'][key] = value
            self.save()
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                self.compare('invalid-camera-'+str(index))

    def test_duplicate_region_pixels_reencoded_as_different_png_are_rejected(self):
        from PIL.PngImagePlugin import PngInfo
        info = PngInfo(); info.add_text('note','Identical synthetic mask stored in different bytes')
        Image.fromarray(self.region).save(self.root/'duplicate-region.png',pnginfo=info)
        self.assertNotEqual(self.sha('region.png'),self.sha('duplicate-region.png'))
        self.spec['regions'].append({'id':'duplicate','mask_path':'duplicate-region.png','mask_sha256':self.sha('duplicate-region.png')})
        self.save()
        with self.assertRaisesRegex(ValueError,'duplicate region'):
            self.compare()

    def test_aggregate_rejects_duplicate_missing_role_invalid_and_synthetic_reference_review(self):
        self.make_two_views()
        original = copy.deepcopy(self.aggregate_spec)
        mutations = [('reports',[original['reports'][0],original['reports'][0]]),
            ('reports',original['reports'][:1]),('required_views',[original['required_views'][0]]*2),
            ('required_views',[{'id':'side','role':'fit'},{'id':'rear','role':'check'}]),
            ('required_views',[{'id':'side','role':'fit'},{'id':'missing','role':'held_out'}]),
            ('required_views',[]),('schema_version',True),('purpose','reference_review'),
            ('limits',{**original['limits'],'contour_max_px':True}),
            ('limits',{**original['limits'],'contour_max_px':float('nan')}),
            ('limits',{**original['limits'],'region_delta_e76_max':-1}),
            ('reports',[{**original['reports'][0],'sha256':None},original['reports'][1]])]
        for i,(key,value) in enumerate(mutations):
            spec = copy.deepcopy(original); spec[key] = value
            (self.root/'aggregate.json').write_text(json.dumps(spec))
            with self.subTest(key=key,value=value),self.assertRaises((ValueError,OSError)):
                self.aggregate('invalid-aggregate-'+str(i))
            self.assertFalse((self.root/('invalid-aggregate-'+str(i))).exists())

    def test_aggregate_rejects_stale_every_bound_input_and_edited_scores(self):
        self.make_two_views()
        for name in ('source.blend','side-result/report.json','spec.json','render/render-manifest.json',
                     'render/mask.png','render/detail.png','reference.png','reference-mask.png','region.png'):
            before = (self.root/name).read_bytes()
            (self.root/name).write_bytes(before+b'stale')
            with self.subTest(name=name),self.assertRaises((ValueError,OSError)):
                self.aggregate()
            self.assertFalse((self.root/'aggregate-result').exists())
            (self.root/name).write_bytes(before)
        report = json.loads((self.root/'rear-result/report.json').read_text())
        report['metrics']['regions']['panel']['delta_e76']['max'] = 0
        (self.root/'rear-result/report.json').write_text(json.dumps(report))
        self.aggregate_spec['reports'][1]['sha256'] = self.sha('rear-result/report.json')
        (self.root/'aggregate.json').write_text(json.dumps(self.aggregate_spec))
        with self.assertRaisesRegex(ValueError,'recomputed'):
            self.aggregate()

    def test_aggregate_rejects_legitimate_outputs_from_mixed_sources(self):
        self.make_two_views()
        (self.root/'other.blend').write_bytes(b'Another synthetic saved source, not an actual Blender file')
        self.manifest['source'] = {'path':'other.blend','sha256':self.sha('other.blend')}
        (self.root/'rear-render/render-manifest.json').write_text(json.dumps(self.manifest))
        import compare_fidelity as f
        f.compare(self.root/'rear-render/render-manifest.json',self.root/'rear-spec.json',self.root,self.root/'other-result')
        self.aggregate_spec['reports'][1] = {'path':'other-result/report.json','sha256':self.sha('other-result/report.json')}
        (self.root/'aggregate.json').write_text(json.dumps(self.aggregate_spec))
        with self.assertRaisesRegex(ValueError,'mixed-source'):
            self.aggregate()

    def test_aggregate_rejects_same_camera_relabelled_as_a_second_view(self):
        self.make_two_views()
        original = json.loads((self.root/'render/render-manifest.json').read_text())
        self.manifest['camera'] = original['camera']
        self.manifest['camera']['name'] = 'RenamedButSameProjection'
        (self.root/'rear-render/render-manifest.json').write_text(json.dumps(self.manifest))
        import compare_fidelity as f
        f.compare(self.root/'rear-render/render-manifest.json',self.root/'rear-spec.json',self.root,self.root/'same-camera-result')
        self.aggregate_spec['reports'][1] = {'path':'same-camera-result/report.json','sha256':self.sha('same-camera-result/report.json')}
        (self.root/'aggregate.json').write_text(json.dumps(self.aggregate_spec))
        with self.assertRaisesRegex(ValueError,'duplicate camera'):
            self.aggregate()

    def test_aggregate_duplicate_camera_identity_uses_numeric_values_not_json_spelling(self):
        self.make_two_views()
        original=json.loads((self.root/'render/render-manifest.json').read_text())['camera']
        import compare_fidelity as f
        for label in ('signed-zero','integer-float'):
            camera=copy.deepcopy(original);camera['name']='NumericallyIdenticalCamera'
            if label=='signed-zero':camera['matrix_world'][0][1]=-0.0
            else:camera['matrix_world']=[[float(v) for v in row] for row in camera['matrix_world']]
            self.assertEqual({k:v for k,v in camera.items() if k!='name'},
                             {k:v for k,v in original.items() if k!='name'})
            self.manifest['camera']=camera
            (self.root/'rear-render/render-manifest.json').write_text(json.dumps(self.manifest))
            output='numeric-camera-'+label
            f.compare(self.root/'rear-render/render-manifest.json',self.root/'rear-spec.json',self.root,self.root/output)
            path=output+'/report.json'
            self.aggregate_spec['reports'][1]={'path':path,'sha256':self.sha(path)}
            (self.root/'aggregate.json').write_text(json.dumps(self.aggregate_spec))
            with self.subTest(label=label),self.assertRaisesRegex(ValueError,'duplicate camera'):
                self.aggregate('aggregate-'+label)
            self.assertFalse((self.root/('aggregate-'+label)).exists())

    def test_aggregate_checks_bound_files_after_recomputation(self):
        self.make_two_views()
        import compare_fidelity as f
        from unittest.mock import patch
        original = f.evaluate
        count = 0
        def mutate(*args):
            nonlocal count
            result = original(*args); count += 1
            if count == 2:
                (self.root/'source.blend').write_bytes(b'Changed while aggregating')
            return result
        with patch.object(f,'evaluate',side_effect=mutate),self.assertRaisesRegex(ValueError,'changed during'):
            self.aggregate()
        self.assertFalse((self.root/'aggregate-result').exists())

    def test_report_preserves_actual_render_camera_and_registration_note(self):
        report = self.compare()
        self.assertIn('render_camera',report,'camera binding must remain directly inspectable')
        self.assertEqual(report['render_camera'],self.manifest['camera'])
        self.assertEqual(report['renderer_registration_note'],self.manifest['registration_note'])


if __name__ == '__main__':
    unittest.main()
