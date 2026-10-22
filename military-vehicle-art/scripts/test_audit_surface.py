"""Synthetic real-bpy/Pillow mechanics; not photorealism certification."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import bpy
from PIL import Image

MODULE = Path(__file__).with_name('audit_surface.py')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class SurfaceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), 'surface audit is not implemented')
        loader = importlib.util.spec_from_file_location('surface_tool', MODULE)
        self.tool = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(self.tool)
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'])
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source.blend'
        self.spec_path = self.root / 'filled.json'
        self.report = self.root / 'report.json'
        self.image = self.root / 'map.png'
        Image.new('RGB', (100, 100), (80, 80, 80)).save(self.image)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)],
                  [[(0, 0), (1, 0), (0, 1)]])
        self.save()

    def tearDown(self):
        if hasattr(self, 'tmp'):
            self.tmp.cleanup()

    def mesh(self, vertices, faces, uvs, materials=None):
        old = bpy.data.objects.get('Panel')
        if old:
            bpy.data.objects.remove(old, do_unlink=True)
        mesh = bpy.data.meshes.new('PanelMesh')
        mesh.from_pydata(vertices, [], faces)
        obj = bpy.data.objects.new('Panel', mesh)
        bpy.context.scene.collection.objects.link(obj)
        layer = mesh.uv_layers.new(name='AuditUV')
        for face, points in zip(mesh.polygons, uvs):
            for loop, uv in zip(face.loop_indices, points):
                layer.data[loop].uv = uv
        mat = bpy.data.materials.get('Paint') or bpy.data.materials.new('Paint')
        mesh.materials.append(mat)
        if materials:
            mesh.materials.append(bpy.data.materials.new('Other'))
            for face, material in zip(mesh.polygons, materials):
                face.material_index = material
        return obj

    def save(self):
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        self.source_hash = sha(self.source)

    def config(self):
        return {'schema_version': 1, 'meters_per_blender_unit': 1,
                'limits': {'triangles': 1000, 'overlap_pairs': 10000, 'seam_samples': 10000},
                'overlap': {'scope': 'within_object_material_region', 'area_epsilon': 1e-12},
                'seams': {'samples_per_edge': 8, 'inset_fraction': 0.001,
                          'discontinuity_threshold': 0.1},
                'targets': [{'object': 'Panel', 'uv_map': 'AuditUV', 'regions': [
                    {'material': 'Paint', 'uv_policy': 'single_1001', 'texture': {
                        'path': 'map.png', 'sha256': sha(self.image), 'size': [100, 100],
                        'role': 'color', 'color_space': 'srgb', 'wrap': 'clamp'}}]}]}

    def run_tool(self, spec=...):
        self.spec_path.write_text(json.dumps(self.config() if spec is ... else spec))
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            rc = self.tool.main(['--source', str(self.source), '--spec', str(self.spec_path),
                                 '--report', str(self.report)])
        self.last_error = errors.getvalue()
        return rc

    def data(self):
        return json.loads(self.report.read_text())

    def region(self):
        return self.data()['targets'][0]['regions'][0]

    def test_png16_rgb_maps_are_refused_before_silent_pillow_truncation(self):
        import struct,zlib
        def chunk(kind,data):
            return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        raw=(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,16,2,0,0,0))+
             chunk(b'IDAT',zlib.compress(b'\x00'+b'\x80\x01'*3))+chunk(b'IEND',b''))
        self.image.write_bytes(raw)
        with Image.open(self.image) as decoded:self.assertEqual(decoded.mode,'RGB')
        spec=self.config();spec['targets'][0]['regions'][0]['texture']['size']=[1,1]
        self.assertEqual(self.run_tool(spec),2,'unsupported 16-bit data was silently audited as 8-bit')
        self.assertIn('8-bit',self.last_error)
        self.assertFalse(self.report.exists())
        self.assertEqual(sha(self.source),self.source_hash)

    def test_density_analytic_evaluated_world_scale_and_source_preserved(self):
        obj = bpy.data.objects['Panel']
        obj.scale = (2, 2, 1)
        self.save()
        spec = self.config()
        spec['meters_per_blender_unit'] = 0.5
        self.assertEqual(self.run_tool(spec), 0, self.last_error)
        report = self.data()
        self.assertEqual(report['schema_version'], 1)
        self.assertEqual(report['command'], 'audit-surface')
        self.assertEqual(report['source_sha256'], self.source_hash)
        self.assertEqual(sha(self.source), self.source_hash)
        density = self.region()['density']
        self.assertEqual(density['status'], 'measured')
        self.assertAlmostEqual(density['world_area_m2'], 0.5)
        self.assertAlmostEqual(density['effective_texels_per_meter'], 100)
        self.assertAlmostEqual(density['triangles'][0]['texels_per_meter'], 100)
        self.assertEqual(report['targets'][0]['density']['effective_texels_per_meter'], 100)
        self.assertEqual(self.region()['texture']['sha256'], sha(self.image))
        self.assertEqual(self.region()['texture']['actual_size'], [100, 100])
        self.assertFalse(report['shader_graph_equivalence_verified'])

    def test_triangle_mapping_measures_distortion_not_quality_score(self):
        self.mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 1, 2)],
                  [[(0, 0), (1, 0), (0, 0.5)]])
        self.save()
        self.assertEqual(self.run_tool(), 0, self.last_error)
        stretch = self.region()['stretch']
        self.assertEqual(stretch['status'], 'measured')
        tri = stretch['triangles'][0]
        self.assertAlmostEqual(tri['texel_singular_values_per_meter'][0], 100)
        self.assertAlmostEqual(tri['texel_singular_values_per_meter'][1], 50)
        self.assertAlmostEqual(tri['texel_anisotropy'], 2)
        self.assertAlmostEqual(tri['uv_anisotropy'], 2)
        self.assertFalse(tri['uv_mirrored'])
        self.assertNotIn('score', stretch)

    def test_ill_conditioned_nonzero_uv_mapping_preserves_area_determinant(self):
        import math
        u,delta=2.0**-40,2.0**-63
        self.mesh([(0,0,0),(1,0,0),(1,1,0)],[(0,1,2)],
                  [[(0,0),(1,1),(u,u+delta)]])
        self.save()
        self.assertEqual(self.run_tool(),0,self.last_error)
        tri=self.region()['stretch']['triangles'][0]
        for key,factor in [('uv_singular_values_per_meter',1),('texel_singular_values_per_meter',10000)]:
            high,low=tri[key]
            self.assertTrue(math.isfinite(high) and math.isfinite(low) and low>0)
            self.assertAlmostEqual(high*low/(delta*factor),1,places=12)
        self.assertTrue(math.isfinite(tri['uv_anisotropy']))
        self.assertEqual(sha(self.source),self.source_hash)

    def test_non_square_map_distinguishes_uv_and_texel_anisotropy(self):
        Image.new('RGB', (200, 100), (20, 20, 20)).save(self.image)
        spec = self.config()
        spec['targets'][0]['regions'][0]['texture']['size'] = [200, 100]
        self.assertEqual(self.run_tool(spec), 0, self.last_error)
        tri = self.region()['stretch']['triangles'][0]
        self.assertAlmostEqual(tri['uv_anisotropy'], 1)
        self.assertAlmostEqual(tri['texel_anisotropy'], 2)

    def test_geometric_overlap_detects_containment_partial_and_reversed_winding(self):
        cases = [([(0, 0), (1, 0), (0, 1)], 0.5),
                 ([(0, 1), (1, 0), (0, 0)], 0.5),
                 ([(0.25, 0), (1, 0), (0.25, 0.75)], 0.28125),
                 ([(1, 0), (1, 1), (0, 1)], 0)]
        for second, expected in cases:
            with self.subTest(second=second):
                self.mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0),
                           (2, 0, 0), (3, 0, 0), (2, 1, 0)],
                          [(0, 1, 2), (3, 4, 5)],
                          [[(0, 0), (1, 0), (0, 1)], second])
                self.save()
                self.report.unlink(missing_ok=True)
                self.assertEqual(self.run_tool(), 0, self.last_error)
                result = self.region()['overlap']
                self.assertEqual(result['status'], 'measured')
                self.assertEqual(result['triangle_pairs'], 1)
                self.assertAlmostEqual(result['pairwise_intersection_area_sum_uv2'], expected)
                self.assertEqual(result['positive_area_pairs'], int(expected > 0))
                self.assertEqual(result['method'], 'convex_triangle_clipping_float64')

    def test_adjacent_shared_mesh_edge_is_not_overlap(self):
        self.mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)],
                  [(0, 1, 2), (1, 3, 2)],
                  [[(0, 0), (1, 0), (0, 1)], [(1, 0), (1, 1), (0, 1)]])
        self.save()
        self.assertEqual(self.run_tool(), 0, self.last_error)
        self.assertEqual(self.region()['overlap']['positive_area_pairs'], 0)
        self.assertEqual(self.region()['overlap']['pairwise_intersection_area_sum_uv2'], 0)

    def split_panel(self, materials=None):
        self.mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)],
                  [(0, 1, 2), (1, 3, 2)],
                  [[(0.1, 0.1), (0.4, 0.1), (0.1, 0.4)],
                   [(0.6, 0.1), (0.9, 0.4), (0.6, 0.4)]], materials)
        self.save()

    def test_actual_pixel_seam_continuity_and_discontinuity(self):
        self.split_panel()
        for discontinuous in (False, True):
            with self.subTest(discontinuous=discontinuous):
                image = Image.new('RGB', (100, 100), (0, 0, 0))
                if discontinuous:
                    image.paste((255, 255, 255), (50, 0, 100, 100))
                image.save(self.image)
                self.report.unlink(missing_ok=True)
                self.assertEqual(self.run_tool(), 0, self.last_error)
                seams = self.region()['seams']
                self.assertEqual(seams['status'], 'sampled')
                self.assertEqual(seams['sample_count'], 8)
                self.assertEqual(seams['uv_split_edges'], 1)
                self.assertAlmostEqual(seams['max_delta'], float(discontinuous))
                self.assertEqual(seams['discontinuous_edges'], int(discontinuous))
                self.assertEqual(seams['comparison_space'], 'linear_rgb')
                self.assertGreater(seams['max_world_sample_spacing_m'], 0)
                self.assertGreater(seams['edges'][0]['pixel_sample_spacing'][0], 0)

    def test_intended_material_boundary_is_excluded(self):
        self.split_panel([0, 1])
        self.assertEqual(self.run_tool(), 0, self.last_error)
        result = self.region()['seams']
        self.assertEqual(result['sample_count'], 0)
        self.assertEqual(result['excluded_material_boundaries'], 1)
        self.assertEqual(result['status'], 'not_applicable_no_uv_split_edges')

    def test_tangent_normals_are_not_judged_by_rgb_seam_delta(self):
        self.split_panel()
        spec = self.config()
        spec['targets'][0]['regions'][0]['texture'].update(role='tangent_normal', color_space='data')
        self.assertEqual(self.run_tool(spec), 0, self.last_error)
        result = self.region()['seams']
        self.assertEqual(result['status'], 'unsupported_tangent_normal')
        self.assertEqual(result['sample_count'], 0)
        self.assertIsNone(result['max_delta'])

    def test_strict_schema_rejects_unknown_numeric_and_empty_declarations_before_open(self):
        marker = bpy.data.objects.new('NotOpened', None)
        bpy.context.scene.collection.objects.link(marker)
        variants = [None, [], {}, {'schema_version': 1}]
        for path, values in [
            (('schema_version',), [True, 1.0, 2]),
            (('meters_per_blender_unit',), [True, 0, -1, '1', float('nan'), float('inf'), 10**400]),
            (('targets',), [[], {}, [self.config()['targets'][0]]*17]),
            (('limits', 'triangles'), [True, 0, 20001, 2.5]),
            (('limits', 'overlap_pairs'), [True, 0, 2000001]),
            (('limits', 'seam_samples'), [True, 0, 1000001]),
            (('overlap', 'scope'), ['all', None]),
            (('overlap', 'area_epsilon'), [True, -1, 1, float('nan')]),
            (('seams', 'samples_per_edge'), [True, 0, 129, 2.5]),
            (('seams', 'inset_fraction'), [True, -1, 0.1]),
            (('seams', 'discontinuity_threshold'), [True, -1, 2]),
            (('targets', 0, 'object'), ['', None, 'x'*64]),
            (('targets', 0, 'uv_map'), ['', True]),
            (('targets', 0, 'regions'), [[], None]),
            (('targets', 0, 'regions', 0, 'material'), ['', None]),
            (('targets', 0, 'regions', 0, 'uv_policy'), ['guess', None]),
            (('targets', 0, 'regions', 0, 'texture', 'path'), ['', True, '../map.png']),
            (('targets', 0, 'regions', 0, 'texture', 'sha256'), ['x'*64, 'A'*64, None]),
            (('targets', 0, 'regions', 0, 'texture', 'size'), [[True, 100], [0, 1], [20000, 20000], [1], '100']),
            (('targets', 0, 'regions', 0, 'texture', 'role'), ['unknown']),
            (('targets', 0, 'regions', 0, 'texture', 'color_space'), ['guess', 'data']),
            (('targets', 0, 'regions', 0, 'texture', 'wrap'), ['extend', None])]:
            for value in values:
                bad = self.config()
                part = bad
                for key in path[:-1]:
                    part = part[key]
                part[path[-1]] = value
                variants.append(bad)
        for path in [(), ('limits',), ('overlap',), ('seams',), ('targets', 0),
                     ('targets', 0, 'regions', 0), ('targets', 0, 'regions', 0, 'texture')]:
            bad = self.config()
            part = bad
            for key in path:
                part = part[key]
            part['unknown'] = 1
            variants.append(bad)
        bad = self.config()
        bad['targets'].append(copy.deepcopy(bad['targets'][0]))
        variants.append(bad)
        bad = self.config()
        bad['targets'][0]['regions'] *= 2
        variants.append(bad)
        for bad in variants:
            with self.subTest(spec=repr(bad)[:180]):
                self.report.unlink(missing_ok=True)
                self.assertEqual(self.run_tool(bad), 2, self.last_error)
                self.assertIn('NotOpened', bpy.data.objects)
                self.assertFalse(self.report.exists())
        self.assertEqual(sha(self.source), self.source_hash)

    def test_duplicate_keys_and_unfilled_template_are_rejected(self):
        raw = json.dumps(self.config()).replace('"role": "color"', '"role": "color", "role": "color"')
        self.spec_path.write_text(raw)
        self.assertEqual(self.tool.main(['--source', str(self.source), '--spec', str(self.spec_path),
                                         '--report', str(self.report)]), 2)
        self.assertFalse(self.report.exists())
        template = MODULE.parent.parent / 'assets' / 'surface-audit.json'
        self.assertTrue(template.is_file(), 'unfilled surface template is missing')
        self.assertEqual(self.run_tool(json.loads(template.read_text())), 2)

    def test_map_hash_dimensions_mode_and_signature_are_verified(self):
        for kind in ('hash', 'size', 'mode', 'signature'):
            with self.subTest(kind=kind):
                Image.new('RGB', (100, 100)).save(self.image)
                spec = self.config()
                if kind == 'hash':
                    spec['targets'][0]['regions'][0]['texture']['sha256'] = '0'*64
                elif kind == 'size':
                    spec['targets'][0]['regions'][0]['texture']['size'] = [101, 100]
                elif kind == 'mode':
                    Image.new('P', (100, 100)).save(self.image)
                else:
                    Image.new('RGB', (100, 100)).save(self.image, format='JPEG')
                if kind in ('mode', 'signature'):
                    spec['targets'][0]['regions'][0]['texture']['sha256'] = sha(self.image)
                self.report.unlink(missing_ok=True)
                self.assertEqual(self.run_tool(spec), 2, self.last_error)
                self.assertFalse(self.report.exists())

    def test_existing_reports_aliases_and_symlink_components_reject_before_source_open(self):
        self.spec_path.write_text(json.dumps(self.config()))
        marker = bpy.data.objects.new('NotOpened', None)
        bpy.context.scene.collection.objects.link(marker)
        symsource, symspec, symmap = [self.root / n for n in ('source-link.blend', 'spec-link.json', 'map-link.png')]
        symsource.symlink_to(self.source)
        symspec.symlink_to(self.spec_path)
        symmap.symlink_to(self.image)
        symdir = self.root / 'linked-dir'
        symdir.symlink_to(self.root, target_is_directory=True)
        self.report.write_text('KEEP')
        for source, spec, output in [(self.source, self.spec_path, self.report),
                                     (symsource, self.spec_path, self.root/'r1.json'),
                                     (self.source, symspec, self.root/'r2.json'),
                                     (self.source, self.spec_path, symdir/'r3.json'),
                                     (self.source, self.spec_path, self.source)]:
            with self.subTest(source=source, spec=spec, report=output):
                self.assertEqual(self.tool.main(['--source', str(source), '--spec', str(spec),
                                                 '--report', str(output)]), 2)
                self.assertIn('NotOpened', bpy.data.objects)
        self.assertEqual(self.report.read_text(), 'KEEP')
        self.report.unlink()
        spec = self.config()
        spec['targets'][0]['regions'][0]['texture']['path'] = symmap.name
        self.assertEqual(self.run_tool(spec), 2)
        self.assertIn('NotOpened', bpy.data.objects)
        self.assertFalse(self.report.exists())
        hardmap = self.root/'hard-source.png'
        os.link(self.source, hardmap)
        spec = self.config()
        spec['targets'][0]['regions'][0]['texture'].update(path=hardmap.name, sha256=sha(hardmap))
        self.assertEqual(self.run_tool(spec), 2)
        self.assertIn('alias', self.last_error.lower())
        self.assertEqual(sha(self.source), self.source_hash)

    def test_changed_inputs_and_competing_report_prevent_publication(self):
        original = self.tool.audit
        for changed in ('source', 'spec', 'map', 'report'):
            with self.subTest(changed=changed):
                self.report.unlink(missing_ok=True)
                def mutate(*args, **kwargs):
                    result = original(*args, **kwargs)
                    path = {'source': self.source, 'spec': self.spec_path,
                            'map': self.image, 'report': self.report}[changed]
                    if changed == 'report':
                        path.write_text('COMPETING')
                    else:
                        with path.open('ab') as stream:
                            stream.write(b' ')
                    return result
                self.tool.audit = mutate
                self.assertEqual(self.run_tool(), 2, self.last_error)
                if changed == 'report':
                    self.assertEqual(self.report.read_text(), 'COMPETING')
                else:
                    self.assertFalse(self.report.exists())
        self.tool.audit = original

    def test_triangle_pair_and_sample_workloads_are_bounded(self):
        self.split_panel()
        for field, maximum in [('triangles', 1), ('seam_samples', 7)]:
            spec = self.config()
            spec['limits'][field] = maximum
            with self.subTest(field=field):
                self.report.unlink(missing_ok=True)
                self.assertEqual(self.run_tool(spec), 2, self.last_error)
                self.assertIn('workload', self.last_error)
                self.assertFalse(self.report.exists())
        self.mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0), (2, 0, 0)],
                  [(0, 1, 2), (1, 3, 2), (1, 4, 3)],
                  [[(0, 0), (1, 0), (0, 1)], [(1, 0), (1, 1), (0, 1)],
                   [(0, 0), (1, 0), (0, 1)]])
        self.save()
        spec = self.config()
        spec['limits']['overlap_pairs'] = 2
        self.assertEqual(self.run_tool(spec), 2, self.last_error)
        self.assertFalse(self.report.exists())

    def test_out_of_tile_has_explicit_unsupported_and_repeat_policy(self):
        self.split_panel()
        for item in bpy.data.objects['Panel'].data.uv_layers['AuditUV'].data:
            item.uv.x += 2
        self.save()
        self.assertEqual(self.run_tool(), 0, self.last_error)
        row = self.region()
        for system in ('density', 'stretch', 'overlap', 'seams'):
            self.assertEqual(row[system]['status'], 'unsupported_outside_1001')
        self.assertEqual(self.data()['targets'][0]['density']['status'], 'unsupported_incomplete_regions')
        self.report.unlink()
        spec = self.config()
        spec['targets'][0]['regions'][0]['uv_policy'] = 'repeat_unwrapped'
        spec['targets'][0]['regions'][0]['texture']['wrap'] = 'repeat'
        self.assertEqual(self.run_tool(spec), 0, self.last_error)
        self.assertEqual(self.region()['density']['status'], 'measured')
        self.assertEqual(self.region()['stretch']['status'], 'measured')
        self.assertEqual(self.region()['seams']['status'], 'sampled')
        self.assertEqual(self.region()['overlap']['status'], 'unsupported_periodic_domain')
        self.assertFalse(self.region()['overlap']['periodic_overlap_tested'])

    def test_degenerate_empty_missing_and_nonfinite_checks_never_pass(self):
        baseline = self.source.read_bytes()
        for kind in ('world_degenerate', 'uv_degenerate', 'missing_object', 'missing_uv', 'empty_region', 'uv_nonfinite'):
            with self.subTest(kind=kind):
                self.source.write_bytes(baseline)
                bpy.ops.wm.open_mainfile(filepath=str(self.source), use_scripts=False)
                obj = bpy.data.objects['Panel']
                spec = self.config()
                if kind == 'world_degenerate':
                    obj.scale.z = 0
                    obj.scale.y = 0
                elif kind == 'uv_degenerate':
                    for item in obj.data.uv_layers['AuditUV'].data:
                        item.uv = (0, 0)
                elif kind == 'missing_object':
                    spec['targets'][0]['object'] = 'Missing'
                elif kind == 'missing_uv':
                    spec['targets'][0]['uv_map'] = 'Missing'
                elif kind == 'empty_region':
                    spec['targets'][0]['regions'][0]['material'] = 'Missing'
                else:
                    obj.data.uv_layers['AuditUV'].data[0].uv.x = float('nan')
                self.save()
                self.report.unlink(missing_ok=True)
                self.assertEqual(self.run_tool(spec), 2, self.last_error)
                self.assertFalse(self.report.exists())

    def test_density_is_translation_invariant_not_float32_world_position_difference(self):
        bpy.data.objects['Panel'].location = (100000000, 100000000, 0)
        self.save()
        self.assertEqual(self.run_tool(), 0, self.last_error)
        self.assertAlmostEqual(self.region()['density']['world_area_m2'], 0.5)
        self.assertAlmostEqual(self.region()['density']['effective_texels_per_meter'], 100)

    def test_parent_shear_and_live_modifier_are_evaluated_without_applying(self):
        from math import pi
        obj = bpy.data.objects['Panel']
        parent = bpy.data.objects.new('Parent', None)
        bpy.context.scene.collection.objects.link(parent)
        parent.scale = (2, 3, 1)
        obj.parent = parent
        obj.rotation_euler.z = pi/4
        modifier = obj.modifiers.new('Subdivide', 'SUBSURF')
        modifier.subdivision_type = 'SIMPLE'
        modifier.levels = 1
        self.save()
        self.assertEqual(self.run_tool(), 0, self.last_error)
        self.assertGreater(self.data()['targets'][0]['evaluated_triangles'], 1)
        self.assertAlmostEqual(self.region()['density']['world_area_m2'], 3, places=6)
        self.assertAlmostEqual(self.region()['density']['effective_texels_per_meter'], (5000/3)**0.5, places=5)
        self.assertEqual(sha(self.source), self.source_hash)
        obj = bpy.data.objects['Panel']
        self.assertEqual(len(obj.data.polygons), 1)
        self.assertEqual(len(obj.modifiers), 1)

    def test_finish_asset_producer_and_real_cli(self):
        loader = importlib.util.spec_from_file_location('finish_surface_producer', MODULE.with_name('finish_asset.py'))
        producer = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(producer)
        finish_spec = self.root/'finish.json'
        finish_spec.write_text(json.dumps({'schema_version': 1, 'targets': [
            {'object': 'Panel', 'shared_mesh': 'reject', 'uv': {
                'name': 'ProducedUV', 'method': 'smart_project', 'angle_limit_degrees': 66,
                'island_margin': 0.02}, 'bevel': None, 'shading': None}]}))
        finished = self.root/'finished.blend'
        finish_report = self.root/'finish-report.json'
        self.assertEqual(producer.main(['--source', str(self.source), '--spec', str(finish_spec),
            '--output', str(finished), '--report', str(finish_report)]), 0)
        before = sha(finished)
        spec = self.config()
        spec['targets'][0]['uv_map'] = 'ProducedUV'
        self.spec_path.write_text(json.dumps(spec))
        result = subprocess.run([sys.executable, str(MODULE), '--source', str(finished),
            '--spec', str(self.spec_path), '--report', str(self.report)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(self.region()['density']['status'], 'measured')
        self.assertEqual(self.region()['stretch']['status'], 'measured')
        self.assertEqual(sha(finished), before)
        self.assertEqual(sha(self.source), self.source_hash)
        self.assertEqual(self.data()['source_sha256'], before)

    def test_seam_spacing_reports_actual_inset_sample_track_and_record_bounds(self):
        self.split_panel()
        self.assertEqual(self.run_tool(), 0, self.last_error)
        seams = self.region()['seams']
        expected = 2**0.5/8*(1-0.001)
        self.assertAlmostEqual(seams['max_world_sample_spacing_m'], expected)
        self.assertAlmostEqual(seams['edges'][0]['world_sample_spacing_m'], expected)

    def test_overlap_records_are_bounded_without_truncating_totals(self):
        n = 24
        vertices = [(3*i+x, y, 0) for i in range(n) for x, y in ((0, 0), (1, 0), (0, 1))]
        faces = [(3*i, 3*i+1, 3*i+2) for i in range(n)]
        self.mesh(vertices, faces, [[(0, 0), (1, 0), (0, 1)]]*n)
        self.save()
        self.assertEqual(self.run_tool(), 0, self.last_error)
        result = self.region()['overlap']
        count = n*(n-1)//2
        self.assertEqual(result['triangle_pairs'], count)
        self.assertEqual(result['positive_area_pairs'], count)
        self.assertEqual(result['pairwise_intersection_area_sum_uv2'], count*0.5)
        self.assertEqual(len(result['intersections']), 256)
        self.assertEqual(result['intersections_omitted'], count-256)
        self.assertEqual(self.data()['workload']['overlap_pairs'], count)

    def test_nonmanifold_edges_and_continuous_uv_are_not_vacuous_seam_passes(self):
        self.assertEqual(self.run_tool(), 0, self.last_error)
        self.assertEqual(self.region()['seams']['status'], 'not_applicable_no_uv_split_edges')
        self.assertIsNone(self.region()['seams']['max_delta'])
        self.report.unlink()
        self.mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1)],
                  [(0, 1, 2), (1, 0, 3), (0, 1, 4)],
                  [[(0, 0), (1, 0), (0, 1)]]*3)
        self.save()
        self.assertEqual(self.run_tool(), 0, self.last_error)
        self.assertEqual(self.region()['seams']['status'], 'unsupported_nonmanifold_edges')
        self.assertEqual(self.region()['seams']['excluded_nonmanifold_edges'], 1)
        self.assertEqual(self.region()['seams']['sample_count'], 0)

    def test_animated_png_is_not_silently_audited_as_one_static_map(self):
        first = Image.new('RGB', (100, 100), (0, 0, 0))
        second = Image.new('RGB', (100, 100), (255, 255, 255))
        first.save(self.image, save_all=True, append_images=[second], duration=100, loop=0)
        self.assertEqual(self.run_tool(), 2, self.last_error)
        self.assertFalse(self.report.exists())

    def test_workload_limits_are_global_across_distinct_objects(self):
        self.split_panel()
        other = bpy.data.objects.new('OtherPanel', bpy.data.objects['Panel'].data)
        bpy.context.scene.collection.objects.link(other)
        self.save()
        for field, limit in [('triangles', 2), ('overlap_pairs', 1), ('seam_samples', 8)]:
            with self.subTest(field=field):
                spec = self.config()
                second = copy.deepcopy(spec['targets'][0])
                second['object'] = 'OtherPanel'
                spec['targets'].append(second)
                spec['limits'][field] = limit
                self.assertEqual(self.run_tool(spec), 2, self.last_error)
                self.assertIn('workload', self.last_error)
                self.assertFalse(self.report.exists())
        self.assertEqual(sha(self.source), self.source_hash)

    def test_sampling_color_decode_wrap_orientation_and_scalar_channel(self):
        image = Image.new('RGB', (2, 2))
        image.putdata([(128, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255)])
        mapping = self.config()['targets'][0]['regions'][0]['texture']
        sample = self.tool.pixel_sample(image, (0.25, 0.75), mapping)
        self.assertAlmostEqual(sample[0], ((128/255+0.055)/1.055)**2.4)
        self.assertAlmostEqual(sample[1], 0)
        mapping['wrap'] = 'repeat'
        self.assertEqual(self.tool.pixel_sample(image, (1.25, -0.25), mapping), sample)
        mapping.update(role='scalar', color_space='data')
        self.assertEqual(self.tool.pixel_sample(image, (0.25, 0.75), mapping), [128/255])
        mapping.update(role='color', color_space='linear', wrap='clamp')
        self.assertEqual(self.tool.pixel_sample(image, (-1, 2), mapping), [128/255, 0, 0])


if __name__ == '__main__':
    unittest.main()
