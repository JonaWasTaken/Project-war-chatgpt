"""Real-bpy tests; run with uv run --python 3.13 --with bpy python this_file."""
import importlib.util
import math
from pathlib import Path
import sys
import hashlib
import json
import os
import subprocess
import tempfile
import unittest

import bpy

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def module():
    path = HERE / 'build_track.py'
    if not path.exists():
        raise AssertionError('build_track.py does not yet implement the assembly builder')
    spec = importlib.util.spec_from_file_location('build_track', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def example():
    return {'schema_version': 1,
            'master': {'object': 'ApprovedLink', 'approved': True, 'approval_note': 'Synthetic test master inspected.'},
            'collection': 'NewBelt', 'prefix': 'BeltLink',
            'path': {'x': 1.5, 'yz': [[-2, 0], [2, 0], [2, 2], [-2, 2]]},
            'count': 12, 'phase': 0.0}


def master():
    # A beveled-profile prism, not the builder supplying a fallback cube.
    yz = [(-.18, -.04), (.18, -.04), (.2, .02), (.12, .07), (-.12, .07), (-.2, .02)]
    zmid = (.07 - .04) / 2
    verts = [(x, y, z-zmid) for x in (-.3, .3) for y, z in yz]
    n = len(yz)
    faces = [list(reversed(range(n))), list(range(n, 2*n))]
    faces += [(i, (i+1) % n, (i+1) % n+n, i+n) for i in range(n)]
    mesh = bpy.data.meshes.new('PreparedLinkMesh')
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new('ApprovedLink', mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = (10, 20, 30)  # Geometry must use mesh-local coordinates, not this placement.
    bpy.context.view_layer.update()
    return obj


class TrackTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.master = master()

    def test_real_belt_shared_mesh_and_frames_both_windings(self):
        build = module()
        spec = example()
        original = self.master.matrix_world.copy()
        original_coords = [tuple(v.co) for v in self.master.data.vertices]
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                s = example()
                if reverse:
                    s['path']['yz'].reverse()
                    s['prefix'] = 'ReverseLink'
                    s['collection'] = 'ReverseBelt'
                report = build.build_track(s)
                links = list(bpy.data.collections[s['collection']].objects)
                self.assertEqual(len(links), s['count'])
                self.assertEqual(len(report['links']), s['count'])
                center = (0, 1)
                for entry in report['links']:
                    obj = bpy.data.objects[entry['name']]
                    self.assertIs(obj.data, self.master.data)
                    matrix = obj.matrix_world
                    self.assertAlmostEqual(matrix.determinant(), 1, places=5)
                    self.assertAlmostEqual(matrix.translation.x, 1.5)
                    for axis in range(3):
                        self.assertAlmostEqual(matrix.col[1][axis], entry['tangent'][axis], places=5)
                        self.assertAlmostEqual(matrix.col[2][axis], entry['normal'][axis], places=5)
                    p, normal = entry['position'], entry['normal']
                    self.assertGreater((p[1]-center[0])*normal[1] + (p[2]-center[1])*normal[2], 0)
                self.assertAlmostEqual(report['path_length'], 12)
                self.assertAlmostEqual(report['actual_pitch'], 1)
                self.assertEqual(len(report['neighbor_chord_distances']), 12)
                self.assertAlmostEqual(report['closure_center_spacing'], report['neighbor_chord_distances'][-1])
                self.assertIn('not a collision test', report['limitations'])
        self.assertEqual(self.master.matrix_world, original)
        self.assertEqual([tuple(v.co) for v in self.master.data.vertices], original_coords)

    def test_malformed_paths_rejected_without_new_objects(self):
        build = module()
        bad = [[], [[0, 0], [1, 0], [0, 1]],
               [[0, 0], [2, 0], [2, 1], [0, 0]],
               [[0, 0], [2, 2], [0, 2], [2, 0]],
               [[0, 0], [2, 0], [2, 0], [0, 2]],
               [[0, 0], [2, 0], [1, 0], [1, 2], [0, 2]],
               [[0, 0], [2, 0], [2, float('nan')], [0, 2]],
               [[0, 0], [True, 0], [2, 2], [0, 2]],
               [[0, 0, 0], [2, 0], [2, 2], [0, 2]],
               [[0, 0], [1e-50, 0], [1, 1], [0, 1]],
               [[1e10, 0], [1e10+1, 0], [1e10+1, 2], [1e10, 2]]]
        for path in bad:
            with self.subTest(path=path):
                spec = example()
                spec['path']['yz'] = path
                with self.assertRaises(ValueError):
                    build.build_track(spec)
                self.assertEqual(len(bpy.data.objects), 1)
                self.assertNotIn('NewBelt', bpy.data.collections)

    def test_schema_count_phase_pitch_validation(self):
        build = module()
        for field, value in [('count', True), ('count', 3), ('count', 10001), ('count', 4.5),
                             ('phase', -0.1), ('phase', 1), ('phase', float('inf')),
                             ('schema_version', True), ('unknown', 1)]:
            with self.subTest(field=field, value=value):
                spec = example()
                spec[field] = value
                with self.assertRaises(ValueError):
                    build.build_track(spec)
        for extra in ({'requested_pitch': 1}, {'max_pitch_error': .1},
                      {'requested_pitch': 2, 'max_pitch_error': .1},
                      {'requested_pitch': 1, 'max_pitch_error': -1}):
            with self.subTest(extra=extra):
                spec = example() | extra
                with self.assertRaises(ValueError):
                    build.build_track(spec)
        report = build.build_track(example() | {'requested_pitch': 1, 'max_pitch_error': 0})
        self.assertEqual(report['pitch_error'], 0)

    def test_links_on_long_straight_runs_do_not_tilt_toward_remote_corners(self):
        build = module()
        s = example()
        s['path']['yz'] = [[-5,0],[5,0],[5,2],[-5,2]]
        s['count'] = 48
        report = build.build_track(s)
        straight = [entry for entry in report['links'] if entry['segment'] == 0 and -4 < entry['position'][1] < 4]
        self.assertTrue(straight)
        for entry in straight:
            self.assertAlmostEqual(entry['tangent'][1],1,places=6)
            self.assertAlmostEqual(entry['tangent'][2],0,places=6)

    def test_concave_loop_and_continuous_corner_frame(self):
        build = module()
        s = example()
        s['path']['yz'] = [[0, 0], [4, 0], [4, 2], [2, 1], [0, 2]]
        self.assertEqual(len(build.build_track(s)['links']), 12)
        # Samples just before/at/after square corner converge to the same bisector.
        vectors = []
        for index, phase in enumerate((0, 1e-7, 1-1e-7)):
            s = example()
            s['prefix'], s['collection'] = f'Phase{index}', f'Collection{index}'
            s['phase'] = phase
            r = build.build_track(s)
            entry = r['links'][0] if phase < .5 else r['links'][-1]
            vectors.append(entry['tangent'])
        self.assertLess(math.dist(vectors[0], vectors[1]), 1e-5)
        self.assertLess(math.dist(vectors[0], vectors[2]), 1e-5)

    def test_unapproved_or_unprepared_master_refused(self):
        build = module()
        changes = [
            ('unapproved', lambda o: None),
            ('missing', lambda o: None),
            ('scale', lambda o: setattr(o, 'scale', (2, 1, 1))),
            ('negative_scale', lambda o: setattr(o, 'scale', (-1, 1, 1))),
            ('rotation', lambda o: setattr(o, 'rotation_euler', (0, 0, .3))),
            ('delta', lambda o: setattr(o, 'delta_location', (1, 0, 0))),
            ('modifier', lambda o: o.modifiers.new('Unapplied', 'BEVEL')),
            ('constraint', lambda o: o.constraints.new('COPY_LOCATION')),
            ('animation', lambda o: o.animation_data_create()),
            ('mesh_animation', lambda o: o.data.animation_data_create()),
            ('shape_keys', lambda o: o.shape_key_add(name='Basis')),
            ('vertex_groups', lambda o: o.vertex_groups.new(name='Deform')),
            ('parent', lambda o: setattr(o, 'parent', bpy.data.objects.new('Parent', None))),
            ('offset_origin', lambda o: [setattr(v.co, 'y', v.co.y+1) for v in o.data.vertices]),
            ('flat_mesh', lambda o: [setattr(v.co, 'z', 0) for v in o.data.vertices]),
            ('nonfinite_mesh', lambda o: setattr(o.data.vertices[0].co, 'x', float('nan'))),
            ('instancing', lambda o: setattr(o, 'instance_type', 'FACES')),
        ]
        for label, change in changes:
            with self.subTest(state=label):
                self.setUp()
                change(self.master)
                s = example()
                if label == 'unapproved':
                    s['master']['approved'] = False
                if label == 'missing':
                    s['master']['object'] = 'AbsentMaster'
                with self.assertRaises(ValueError):
                    build.build_track(s)
                self.assertNotIn('NewBelt', bpy.data.collections)

    def test_names_are_preflighted_without_partial_construction(self):
        build = module()
        for kind in ('collection', 'last_link', 'long_prefix'):
            with self.subTest(kind=kind):
                self.setUp()
                s = example()
                if kind == 'collection':
                    bpy.data.collections.new(s['collection'])
                elif kind == 'last_link':
                    bpy.data.objects.new('BeltLink_00011', None)
                else:
                    s['prefix'] = 'é' * 30
                before = set(bpy.data.objects)
                with self.assertRaises(ValueError):
                    build.build_track(s)
                self.assertEqual(before, set(bpy.data.objects))

    def test_float32_center_collapse_rejected_before_creation(self):
        s = example()
        s['path']['yz'] = [[1e8, 0], [1e8+16, 0], [1e8+16, 2], [1e8, 2]]
        s['count'] = 100
        with self.assertRaises(ValueError):
            module().build_track(s)
        self.assertNotIn('NewBelt', bpy.data.collections)

    def test_long_link_is_diagnostic_not_a_fake_collision_pass(self):
        for v in self.master.data.vertices:
            v.co.y *= 20
        s = example()
        r = module().build_track(s)
        self.assertAlmostEqual(r['master']['local_extents'][1], 8, places=5)
        self.assertLess(r['diagnostics']['min_neighbor_chord_over_link_length'], 1)
        self.assertTrue(any('link length' in w for w in r['warnings']))
        self.assertTrue(any('corner' in w for w in r['warnings']))
        self.assertEqual(len(r['diagnostics']['corner_turn_degrees']), 4)
        self.assertNotIn('collision_pass', r)

    def _cli(self, source, spec, output, report):
        return subprocess.run([sys.executable, str(HERE/'build_track.py'), '--source', str(source),
                               '--spec', str(spec), '--output', str(output), '--report', str(report)],
                              capture_output=True, text=True, timeout=120,
                              env=os.environ | {'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1'})

    def test_pbr_producer_master_material_override_survives_track_build(self):
        import build_pbr
        with tempfile.TemporaryDirectory(prefix='pbr-track-', dir=os.environ.get('TMPDIR')) as tmp:
            root = Path(tmp)
            source, material_source, output = root/'source.blend', root/'materials.blend', root/'belt.blend'
            image = bpy.data.images.new('SyntheticColorFixture',width=2,height=2)
            image.pixels = [.15,.4,.12,1]*4
            image.filepath_raw = str(root/'synthetic-color.png')
            image.file_format = 'PNG'
            image.save()
            self.master.data.materials.append(bpy.data.materials.new('OriginalMeshMaterial'))
            self.master.data.uv_layers.new(name='ProductionUV')
            bpy.ops.wm.save_as_mainfile(filepath=str(source),check_existing=False)
            original_bytes = source.read_bytes()
            material_spec = {'schema_version':1,'materials':[{'name':'SyntheticPBRFromActualProducer',
                'uv_map':'ProductionUV','base_color':{'path':'synthetic-color.png',
                'sha256':hashlib.sha256((root/'synthetic-color.png').read_bytes()).hexdigest(),'size':[2,2]},
                'roughness':.6,'metallic':0}],
                'bindings':[{'object':'ApprovedLink','material':'SyntheticPBRFromActualProducer','slot':0}]}
            (root/'pbr.json').write_text(json.dumps(material_spec))
            self.assertEqual(build_pbr.main(['--source',str(source),'--spec',str(root/'pbr.json'),
                '--output',str(material_source),'--report',str(root/'materials.json')]),0)
            (root/'track.json').write_text(json.dumps(example()))
            self.assertEqual(module().main(['--source',str(material_source),'--spec',str(root/'track.json'),
                '--output',str(output),'--report',str(root/'belt.json')]),0)
            self.assertEqual(source.read_bytes(),original_bytes)
            bpy.ops.wm.open_mainfile(filepath=str(output),use_scripts=False)
            master = bpy.data.objects['ApprovedLink']
            self.assertEqual(master.data.materials[0].name,'OriginalMeshMaterial')
            for obj in bpy.data.collections['NewBelt'].objects:
                self.assertIs(obj.data,master.data)
                self.assertEqual(obj.material_slots[0].link,'OBJECT')
                self.assertEqual(obj.material_slots[0].material.name,'SyntheticPBRFromActualProducer')
                self.assertTrue(any(n.type=='TEX_IMAGE' for n in obj.material_slots[0].material.node_tree.nodes))

    def test_cli_snapshot_reload_lineage_and_relative_dependencies(self):
        with tempfile.TemporaryDirectory(prefix='track-builder-', dir=os.environ.get('TMPDIR')) as tmp:
            root = Path(tmp)
            original, moved = root/'original', root/'moved'
            original.mkdir()
            moved.mkdir()
            source, spec = original/'source.blend', root/'spec.json'
            output, report = moved/'belt.blend', moved/'belt.json'
            mesh = self.master.data
            uv = mesh.uv_layers.new(name='ProductionUV')
            for index, item in enumerate(uv.data):
                item.uv = (index/len(uv.data), (index % 3)/3)
            for face in mesh.polygons:
                face.use_smooth = True
            mesh.normals_split_custom_set([(0, 0, 1)]*len(mesh.loops))
            material = bpy.data.materials.new('PaintWithTexture')
            if bpy.app.version < (5, 0, 0):
                material.use_nodes = True
            mesh.materials.append(material)
            texture = bpy.data.images.new('ActualExternalTexture', width=2, height=2)
            texture.filepath_raw = str(original/'texture.png')
            texture.file_format = 'PNG'
            texture.save()
            texture.filepath = '//texture.png'
            material.node_tree.nodes.new('ShaderNodeTexImage').image = texture
            external = bpy.data.objects.new('ExternalLibraryObject', None)
            bpy.data.libraries.write(str(original/'linked.blend'), {external})
            bpy.data.objects.remove(external)
            with bpy.data.libraries.load(str(original/'linked.blend'), link=True) as (src, dst):
                dst.objects = ['ExternalLibraryObject']
            bpy.context.scene.collection.objects.link(dst.objects[0])
            dst.objects[0].library.filepath = '//linked.blend'
            sentinel = bpy.data.objects.new('ExistingSentinel', None)
            bpy.context.scene.collection.objects.link(sentinel)
            sentinel.location = (9, 8, 7)
            bpy.ops.wm.save_as_mainfile(filepath=str(source), check_existing=False)
            spec.write_text(json.dumps(example()), encoding='utf8')
            source_bytes = source.read_bytes()
            before_uv = [tuple(item.uv) for item in uv.data]
            before_normals = [tuple(item.vector) for item in mesh.corner_normals]
            before_coords = [tuple(v.co) for v in mesh.vertices]
            result = self._cli(source, spec, output, report)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertTrue(output.is_file(), 'CLI did not save its requested .blend')
            self.assertTrue(report.is_file(), 'CLI did not save its requested report')
            self.assertEqual(source.read_bytes(), source_bytes)
            r = json.loads(report.read_text())
            self.assertEqual(r['lineage']['source_sha256'], hashlib.sha256(source_bytes).hexdigest())
            self.assertEqual(r['lineage']['spec_sha256'], hashlib.sha256(spec.read_bytes()).hexdigest())
            self.assertEqual(r['lineage']['output_sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
            bpy.ops.wm.open_mainfile(filepath=str(output), load_ui=False, use_scripts=False)
            prepared = bpy.data.objects['ApprovedLink']
            links = list(bpy.data.collections['NewBelt'].objects)
            self.assertEqual(len(links), 12)
            self.assertTrue(all(o.data is prepared.data for o in links))
            self.assertTrue(prepared.data.has_custom_normals)
            self.assertEqual([tuple(v.co) for v in prepared.data.vertices], before_coords)
            self.assertEqual([tuple(item.uv) for item in prepared.data.uv_layers['ProductionUV'].data], before_uv)
            self.assertEqual([tuple(item.vector) for item in prepared.data.corner_normals], before_normals)
            self.assertEqual(links[0].data.materials[0].name, 'PaintWithTexture')
            self.assertEqual(tuple(bpy.data.objects['ExistingSentinel'].location), (9, 8, 7))
            self.assertEqual(tuple(prepared.location), (10, 20, 30))
            self.assertEqual(Path(bpy.path.abspath(bpy.data.images['ActualExternalTexture'].filepath)).resolve(), (original/'texture.png').resolve())
            self.assertEqual(Path(bpy.path.abspath(next(iter(bpy.data.libraries)).filepath)).resolve(), (original/'linked.blend').resolve())
            for entry in r['links']:
                obj = bpy.data.objects[entry['name']]
                self.assertAlmostEqual(obj.matrix_world.determinant(), 1, places=5)
                self.assertLess(math.dist(obj.matrix_world.translation, entry['position']), 1e-6)
                for i in range(4):
                    for j in range(4):
                        self.assertAlmostEqual(obj.matrix_world[i][j], entry['frame'][i][j], places=5)

    def test_cli_rejects_overwrite_alias_and_failed_build_without_files(self):
        with tempfile.TemporaryDirectory(prefix='track-reject-', dir=os.environ.get('TMPDIR')) as tmp:
            root = Path(tmp)
            source, spec = root/'source.blend', root/'spec.json'
            output, report = root/'new.blend', root/'new.json'
            bpy.ops.wm.save_as_mainfile(filepath=str(source), check_existing=False)
            spec.write_text(json.dumps(example()), encoding='utf8')
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            for kind in ('output', 'report', 'source_alias', 'symlink', 'invalid_spec', 'bad_master'):
                with self.subTest(kind=kind):
                    target = output
                    s = example()
                    if kind == 'output':
                        output.write_text('do not overwrite', encoding='utf8')
                    if kind == 'report':
                        report.write_text('do not overwrite', encoding='utf8')
                    if kind == 'source_alias':
                        target = source
                    if kind == 'symlink':
                        output.symlink_to(source)
                    if kind == 'invalid_spec':
                        s['path']['yz'][1] = s['path']['yz'][0]
                    if kind == 'bad_master':
                        s['master']['object'] = 'DoesNotExist'
                    spec.write_text(json.dumps(s), encoding='utf8')
                    result = self._cli(source, spec, target, report)
                    self.assertNotEqual(result.returncode, 0, result.stdout+result.stderr)
                    self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)
                    if kind == 'output':
                        self.assertEqual(output.read_text(), 'do not overwrite')
                    elif kind == 'report':
                        self.assertEqual(report.read_text(), 'do not overwrite')
                    elif kind != 'symlink':
                        self.assertFalse(output.exists())
                    if kind != 'report':
                        self.assertFalse(report.exists())
                    if output.exists() or output.is_symlink():
                        output.unlink()
                    if report.exists():
                        report.unlink()

    def test_linked_master_refused(self):
        build = module()
        with tempfile.TemporaryDirectory(prefix='track-library-', dir=os.environ.get('TMPDIR')) as tmp:
            path = Path(tmp)/'library.blend'
            bpy.data.libraries.write(str(path), {self.master})
            bpy.data.objects.remove(self.master, do_unlink=True)
            with bpy.data.libraries.load(str(path), link=True) as (src, dst):
                dst.objects = ['ApprovedLink']
            bpy.context.scene.collection.objects.link(dst.objects[0])
            with self.assertRaises(ValueError):
                build.build_track(example())
            self.assertNotIn('NewBelt', bpy.data.collections)

    def test_float32_transformed_link_thickness_collapse_refused(self):
        s = example()
        # Centers remain distinct, but an actual .11-thick master vanishes at this Z offset.
        s['path']['yz'] = [[-100, 1e8], [100, 1e8], [100, 1e8+32], [-100, 1e8+32]]
        s['count'] = 4
        s['phase'] = .5
        with self.assertRaises(ValueError):
            module().build_track(s)
        self.assertNotIn('NewBelt', bpy.data.collections)

    def test_compensating_rotations_not_a_prepared_master(self):
        self.master.rotation_euler.z = .3
        self.master.delta_rotation_euler.z = -.3
        with self.assertRaises(ValueError):
            module().build_track(example())

    def test_template_is_unapproved_and_filled_fictional_loop_builds(self):
        s = json.loads((HERE.parent/'assets'/'track-spec.json').read_text())
        self.assertIs(s['master']['approved'], False)
        with self.assertRaises(ValueError):
            module().build_track(s)
        s['master'] = example()['master']
        r = module().build_track(s)
        self.assertEqual(len(r['links']), s['count'])
        self.assertTrue(all(bpy.data.objects[e['name']].data is self.master.data for e in r['links']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
