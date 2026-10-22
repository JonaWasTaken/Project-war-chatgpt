"""Offline real-bpy mechanics tests; no asset/aerodynamic accuracy claims."""
import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import bpy
import bmesh

HERE = Path(__file__).resolve().parent
MODULE = HERE / 'build_lifting_surface.py'


def example():
    return {'schema_version': 1, 'object_name': 'NewWing', 'collection': 'NewSurfaces',
            'airfoil': {'kind': 'naca4_vertical', 'samples': 17},
            'placement': {'origin': [0, 0, 0], 'rotation_degrees': [0, 0, 0]},
            'stations': [
                {'span': 0, 'leading_edge': [0, 0], 'chord': 2, 'twist_degrees': 0,
                 'profile': {'thickness': .12, 'camber': 0, 'camber_position': .4}},
                {'span': 4, 'leading_edge': [0, 0], 'chord': 2, 'twist_degrees': 0,
                 'profile': {'thickness': .12, 'camber': 0, 'camber_position': .4}}]}


def geometry(obj):
    return ([tuple(v.co) for v in obj.data.vertices],
            [tuple(p.vertices) for p in obj.data.polygons],
            [tuple(row) for row in obj.matrix_world])


class LiftingSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), 'lifting surface construction is not implemented')
        module = importlib.util.spec_from_file_location('lifting_helper', MODULE)
        self.tool = importlib.util.module_from_spec(module)
        module.loader.exec_module(self.tool)
        bpy.ops.wm.read_factory_settings(use_empty=True)

    def assert_solid(self, obj):
        bm = bmesh.new()
        try:
            bm.from_mesh(obj.data)
            self.assertTrue(all(e.is_manifold and e.is_contiguous for e in bm.edges))
            self.assertGreater(bm.calc_volume(signed=True), 0)
            self.assertEqual(len(bm.verts) - len(bm.edges) + len(bm.faces), 2)
            self.assertTrue(all(f.calc_area() > 0 for f in bm.faces))
            return bm.calc_volume(signed=True)
        finally:
            bm.free()

    def test_closed_generated_airfoil_actual_blender_positive_manifold(self):
        spec = example()
        valid = self.tool.validate(spec)
        self.assertEqual(valid['status'], 'valid')
        self.assertEqual(json.loads(json.dumps(valid)), valid)
        report = self.tool.build(spec)
        obj = bpy.data.objects[spec['object_name']]
        self.assertEqual(len(obj.data.vertices), 64)
        self.assertEqual(len(obj.data.polygons), 124)
        volume = self.assert_solid(obj)
        self.assertAlmostEqual(report['mesh']['volume_blender_units_cubed'], volume)
        self.assertEqual(report['mesh']['vertices'], 64)
        self.assertEqual(report['mesh']['triangles'], 124)
        self.assertEqual(report['status'], 'built')
        self.assertEqual(json.loads(json.dumps(report, allow_nan=False)), report)

    def test_sweep_taper_camber_real_twist_and_rigid_fin_placement(self):
        spec = example()
        spec['placement'] = {'origin': [3, 4, 5], 'rotation_degrees': [90, 0, 0]}
        spec['stations'][0]['profile']['camber'] = .02
        tip = spec['stations'][1]
        tip.update(leading_edge=[1.3, .4], chord=.8, twist_degrees=3)
        tip['profile'].update(camber=.03, camber_position=.3, thickness=.09)
        report = self.tool.build(spec)
        obj = bpy.data.objects[spec['object_name']]
        self.assert_solid(obj)
        bpy.context.view_layer.update()
        self.assertEqual(tuple(obj.data.vertices[32].co), tuple(map(self.tool.float32, (1.3, 4, .4))))
        end = obj.data.vertices[48].co
        theta = math.radians(3)
        self.assertAlmostEqual(end.x, 1.3+.8*math.cos(theta), places=6)
        self.assertAlmostEqual(end.z, .4-.8*math.sin(theta), places=6)
        world_tip = obj.matrix_world @ obj.data.vertices[32].co
        self.assertAlmostEqual(world_tip.z, 9, places=5)
        self.assertAlmostEqual(obj.matrix_world.determinant(), 1, places=5)
        self.assertAlmostEqual(report['segments'][0]['dihedral_degrees'], math.degrees(math.atan2(.4,4)))
        self.assertAlmostEqual(report['segments'][0]['sweep_degrees'], math.degrees(math.atan2(1.3,4)))
        upper, lower = obj.data.vertices[8].co, obj.data.vertices[24].co
        # x=.5: NACA mean line is .02/.6^2*(1-2*.4+2*.4*.5-.5^2).
        self.assertAlmostEqual((upper.z+lower.z)/2, 2*.02/.6**2*(1-.8+.4-.25), places=6)

    def explicit(self):
        spec = example()
        spec['airfoil'] = {'kind': 'explicit', 'x': [0, .2, .5, .8, 1]}
        for station in spec['stations']:
            station['profile'] = {'upper': [0, .08, .02, .015, 0],
                                  'lower': [0, -.03, -.01, -.01, 0]}
        return spec

    def test_explicit_corresponding_nonconvex_airfoil_not_convex_ring_loft(self):
        spec = self.explicit()
        spec['stations'][1].update(chord=.7, leading_edge=[1, .3], twist_degrees=-2)
        report = self.tool.build(spec)
        self.assert_solid(bpy.data.objects['NewWing'])
        self.assertEqual(report['mesh']['vertices'], 16)
        self.assertEqual(report['mesh']['triangles'], 28)
        self.assertEqual(self.tool.validate(spec)['status'], 'valid')

    def test_tiny_native_normal_degeneracy_is_refused_with_datablock_rollback(self):
        # Exact independently reviewed shape: valid relative conditioning and
        # manifold topology, but bpy 5.2.2 gives four cap normals (0,0,1).
        spec = {'schema_version': 1, 'object_name': 'AdversarialTinyConcave',
                'collection': 'AdversarialTinyConcaveCollection',
                'airfoil': {'kind': 'explicit', 'x': [0, 2e-5, .25, .6, .99998, 1]},
                'placement': {'origin': [0, 0, 0], 'rotation_degrees': [0, 0, 0]},
                'stations': [{'span': span, 'leading_edge': [0, 0], 'chord': 1e-4,
                              'twist_degrees': 0,
                              'profile': {'upper': [0, 1.1e-5, .05, -.1, 1.1e-5, 0],
                                          'lower': [0, 0, .04998, -.10002, 0, 0]}}
                             for span in (0, 1e-4)]}
        bpy.ops.mesh.primitive_cube_add()
        keep = bpy.context.object
        original = geometry(keep)
        before = [set(c.keys()) for c in (bpy.data.objects, bpy.data.meshes, bpy.data.collections)]
        self.assertEqual(self.tool.validate(spec)['status'], 'valid')
        with self.assertRaisesRegex(ValueError, 'native.*normal'):
            self.tool.build(spec)
        self.assertEqual(before, [set(c.keys()) for c in (bpy.data.objects, bpy.data.meshes, bpy.data.collections)])
        self.assertEqual(geometry(keep), original)

        # The same geometry at 100x is supported, with actual face and flat-cap
        # corner normals checked against independently computed double normals.
        control = copy.deepcopy(spec)
        for station in control['stations']:
            station['chord'] *= 100
            station['span'] *= 100
            station['leading_edge'] = [v*100 for v in station['leading_edge']]
        self.assertEqual(self.tool.build(control)['status'], 'built')
        obj = bpy.data.objects[control['object_name']]
        self.assert_solid(obj)
        for face in obj.data.polygons:
            a, b, c = [tuple(obj.data.vertices[i].co) for i in face.vertices]
            u, v = [[p[j]-a[j] for j in range(3)] for p in (b, c)]
            cross = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
            expected = [q/math.hypot(*cross) for q in cross]
            self.assertGreater(sum(x*y for x, y in zip(face.normal, expected)), .99999)
            if not face.use_smooth:
                for i in face.loop_indices:
                    actual = obj.data.corner_normals[i].vector
                    self.assertTrue(all(math.isfinite(q) for q in actual))
                    self.assertGreater(sum(x*y for x, y in zip(actual, expected)), .99999)

    def test_explicit_crossed_or_uncorresponding_or_open_profile_refused(self):
        for field, value in [('upper', [0, .08, -.02, .015, 0]),
                             ('upper', [0, .08, .02, .015]),
                             ('lower', [0, -.03, -.01, -.01, .01]),
                             ('upper', [0, .08, float('nan'), .015, 0]),
                             ('lower', [0, -.03, .02, -.01, 0])]:
            spec = self.explicit()
            spec['stations'][1]['profile'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.tool.build(spec)
            self.assertEqual(len(bpy.data.objects), 0)
        for xs in ([0,.5,.2,.8,1], [0,.2,.2,.8,1], [0,.2,.5,.8,.99]):
            spec = self.explicit()
            spec['airfoil']['x'] = xs
            with self.subTest(x=xs), self.assertRaises(ValueError):
                self.tool.validate(spec)

    def test_bounded_numeric_schema_and_float32_collapse_refused_before_creation(self):
        variants = [None, [], {}, example() | {'schema_version': True}, example() | {'unknown': 1}]
        for path, values in [
                (('airfoil','samples'), [True, 4, 66, 17.0]),
                (('object_name',), ['', True, 'é'*32, '\x00']),
                (('placement','origin'), [None, [0,0], [1e7,0,0], [True,0,0]]),
                (('placement','rotation_degrees'), [[0,0,361], [0,0,float('inf')]]),
                (('stations',0,'span'), [True, float('nan'), float('inf'), 10**400, -1]),
                (('stations',1,'span'), [0, -1, 1e-50]),
                (('stations',0,'chord'), [True, 0, -1, 1e-50, 1e5, '2']),
                (('stations',0,'leading_edge'), [[1e6,0], [0,1e6], [0,float('nan')], [0], None]),
                (('stations',0,'twist_degrees'), [True, -21, 21, '3', float('nan')]),
                (('stations',0,'profile','thickness'), [True, 0, .001, .401]),
                (('stations',0,'profile','camber'), [True, -.101, .101]),
                (('stations',0,'profile','camber_position'), [True, .09, .91])]:
            for value in values:
                spec = example()
                part = spec
                for key in path[:-1]:
                    part = part[key]
                part[path[-1]] = value
                variants.append(spec)
        for bad in variants:
            with self.subTest(spec=repr(bad)[:160]), self.assertRaises(ValueError):
                self.tool.validate(bad)
            self.assertEqual(len(bpy.data.objects), 0)
            self.assertEqual(len(bpy.data.meshes), 0)
        spec = example()
        spec['stations'] = spec['stations']*33
        with self.assertRaises(ValueError):
            self.tool.validate(spec)

    def test_twist_that_overturns_projected_airfoil_is_outside_supported_domain(self):
        spec = example()
        spec['airfoil']['samples'] = 65
        spec['stations'][0]['twist_degrees'] = 20
        with self.assertRaisesRegex(ValueError, 'projected|overturn'):
            self.tool.validate(spec)

    def test_between_station_crossing_is_rejected_not_just_ring_checked(self):
        spec = self.explicit()
        spec['airfoil']['x'] = [0,.25,.5,.75,1]
        for station, chord, twist, upper, lower in [
                (spec['stations'][0], 1.3903119087, -15.4324520783,
                 [0,-.3201388811,.3139487482,-.1014281686,0],
                 [0,-.3221388811,.3119487482,-.1034281686,0]),
                (spec['stations'][1], 2.8125650044, 17.6461647736,
                 [0,-.1690882935,.1130344620,.0965836317,0],
                 [0,-.1710882935,.1110344620,.0945836317,0])]:
            station.update(chord=chord, twist_degrees=twist, profile={'upper':upper,'lower':lower})
        spec['stations'][0]['leading_edge'] = [-.7858042168,.4757990851]
        spec['stations'][1].update(span=1, leading_edge=[-.0014832267,.5186330202])
        # Ordered simple endpoint rings nevertheless cross near y=.5, x=.55134.
        with self.assertRaisesRegex(ValueError, 'between|cross|separation'):
            self.tool.validate(spec)
        self.assertEqual(len(bpy.data.meshes), 0)

    def test_four_explicit_uv_islands_positive_area_and_seams(self):
        spec = example()
        middle = copy.deepcopy(spec['stations'][0])
        middle.update(span=1.7, chord=1.4, leading_edge=[.5,.2], twist_degrees=-2)
        spec['stations'].insert(1,middle)
        report = self.tool.build(spec)
        obj = bpy.data.objects['NewWing']
        self.assert_solid(obj)
        mesh = obj.data
        uv = mesh.uv_layers['LiftingSurfaceUV']
        self.assertEqual(len(uv.data), len(mesh.loops))
        for face in mesh.polygons:
            a,b,c = [uv.data[i].uv for i in face.loop_indices]
            area = abs((b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x))
            self.assertGreater(area, 1e-12)
            for p in (a,b,c):
                self.assertTrue(0 < p.x < 1 and 0 < p.y < 1)
        side_count = 4*16*2
        self.assertTrue(all(p.use_smooth for p in mesh.polygons[:side_count]))
        self.assertTrue(all(not p.use_smooth for p in mesh.polygons[side_count:]))
        self.assertGreater(sum(e.use_seam for e in mesh.edges), 0)
        self.assertEqual(report['uv']['islands'], ['upper','lower','root','tip'])
        self.assertFalse(report['uv']['texel_density_verified'])
        self.assertEqual(report['mesh']['closed_caps'], ['root','tip'])

    def test_world_float32_resolution_and_edit_mode_rejected(self):
        spec = example()
        spec['placement']['origin'] = [100000, 0, 100000]
        for station in spec['stations']:
            station['chord'] = .001
        with self.assertRaisesRegex(ValueError, 'placement|world|resolution|collapse'):
            self.tool.validate(spec)
        bpy.ops.mesh.primitive_cube_add()
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            with self.assertRaisesRegex(ValueError, 'mode'):
                self.tool.build(example())
            self.assertNotIn('NewWing', bpy.data.objects)
        finally:
            bpy.ops.object.mode_set(mode='OBJECT')

    def test_owned_object_mesh_collection_names_never_auto_suffix_or_mutate(self):
        for kind in ('object','mesh','collection'):
            bpy.ops.wm.read_factory_settings(use_empty=True)
            if kind == 'object':
                bpy.data.objects.new('NewWing',None)
            elif kind == 'mesh':
                bpy.data.meshes.new('NewWing')
            else:
                bpy.data.collections.new('NewSurfaces')
            before = [set(c.keys()) for c in (bpy.data.objects,bpy.data.meshes,bpy.data.collections)]
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'owned'):
                self.tool.build(example())
            self.assertEqual(before,[set(c.keys()) for c in (bpy.data.objects,bpy.data.meshes,bpy.data.collections)])

    def test_66_point_explicit_blunt_reference_section_preserves_endpoints(self):
        spec = self.explicit()
        xs = [(1-math.cos(math.pi*i/65))/2 for i in range(66)]
        spec['airfoil'] = {'kind':'explicit', 'x':xs, 'trailing_edge':'blunt'}
        for station in spec['stations']:
            station['profile'] = {'upper':[.12*math.sqrt(x)*(1-x)+.00126*x for x in xs],
                                  'lower':[-.12*math.sqrt(x)*(1-x)-.00126*x for x in xs]}
        report = self.tool.build(spec)
        obj = bpy.data.objects['NewWing']
        self.assert_solid(obj)
        self.assertEqual(report['mesh']['vertices'], 262)
        self.assertEqual(report['mesh']['triangles'], 520)
        self.assertAlmostEqual(obj.data.vertices[65].co.z, .00252, places=8)
        self.assertAlmostEqual(obj.data.vertices[130].co.z, -.00252, places=8)
        self.assertIn('trailing_edge',report['uv']['islands'])
        spec['stations'][1]['twist_degrees'] = 1
        with self.assertRaisesRegex(ValueError, 'blunt.*twist|twist.*blunt'):
            self.tool.validate(spec)

    def fixture(self):
        from PIL import Image
        tmp = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'])
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        texture = root/'keep.png'
        Image.new('RGB',(2,2),(20,40,80)).save(texture)
        bpy.ops.mesh.primitive_cube_add()
        keep = bpy.context.object
        keep.name = 'KeepSource'
        keep['editable_note'] = 'original'
        image = bpy.data.images.load(str(texture))
        image.name = 'KeepImage'
        image.use_fake_user = True
        image.filepath = '//keep.png'
        script = bpy.data.texts.new('not_to_execute.py')
        script.use_module = True
        script.write('import bpy\nbpy.context.scene["unexpected_autoexec"] = True\n')
        bpy.context.scene.unit_settings.system = 'METRIC'
        bpy.context.scene.unit_settings.scale_length = .01
        source = root/'source.blend'
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(source))
        original = geometry(keep)
        spec = root/'filled.json'
        spec.write_text(json.dumps(example()))
        (root/'published').mkdir()
        output, report = root/'published'/'new.blend', root/'published'/'report.json'
        return source,spec,output,report,texture,original

    def cli(self, source,spec,output,report):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            result = self.tool.main(['--source',str(source),'--spec',str(spec),
                                     '--output',str(output),'--report',str(report)])
        return result,errors.getvalue()

    def test_cli_snapshot_reopen_preserves_originals_dependencies_and_units(self):
        source,spec,output,report,texture,original = self.fixture()
        originals = {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (source,spec,texture)}
        result,error = self.cli(source,spec,output,report)
        self.assertEqual(result,0,error)
        data = json.loads(report.read_text())
        self.assertEqual(data['command'],'build-lifting-surface')
        self.assertEqual(data['lineage']['output_sha256'],hashlib.sha256(output.read_bytes()).hexdigest())
        for p,sha in originals.items():
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),sha)
        self.assertEqual(data['units']['lengths'],'source_blender_units')
        self.assertAlmostEqual(data['units']['scene_scale_length'],.01)
        self.assertTrue(data['dependencies']['unchanged'])
        self.assertIn(str(texture),[d['path'] for d in data['dependencies']['files']])
        bpy.ops.wm.open_mainfile(filepath=str(output),use_scripts=False)
        self.assert_solid(bpy.data.objects['NewWing'])
        self.assertEqual(geometry(bpy.data.objects['KeepSource']),original)
        self.assertEqual(bpy.data.objects['KeepSource']['editable_note'],'original')
        self.assertEqual(Path(bpy.path.abspath(bpy.data.images['KeepImage'].filepath)).resolve(),texture.resolve())
        self.assertNotIn('unexpected_autoexec',bpy.context.scene)
        self.assertFalse(bpy.context.preferences.filepaths.use_scripts_auto_execute)
        self.assertEqual(sorted(p.name for p in output.parent.iterdir()),['new.blend','report.json'])

    def test_failed_uv_creation_rolls_back_only_new_datablocks(self):
        bpy.ops.mesh.primitive_cube_add()
        keep = bpy.context.object
        before = [set(c.keys()) for c in (bpy.data.objects,bpy.data.meshes,bpy.data.collections)]
        original = geometry(keep)
        def injected_failure(mesh,spec):
            mesh.uv_layers.new(name='PartialUV')
            raise ValueError('injected real-mesh UV failure')
        self.tool._add_uv = injected_failure
        with self.assertRaisesRegex(ValueError,'injected'):
            self.tool.build(example())
        self.assertEqual(before,[set(c.keys()) for c in (bpy.data.objects,bpy.data.meshes,bpy.data.collections)])
        self.assertEqual(geometry(keep),original)

    def test_cli_duplicate_keys_and_invalid_specs_fail_before_source_open(self):
        source,spec,output,report,texture,original = self.fixture()
        marker = bpy.data.objects.new('NotOpened',None)
        bpy.context.scene.collection.objects.link(marker)
        for raw in [json.dumps(example()).replace('"samples": 17','"samples": 17, "samples": 19'),
                    json.dumps(example() | {'schema_version':True}), '{',
                    ' '*(1048576+1)]:
            spec.write_text(raw)
            result,error = self.cli(source,spec,output,report)
            self.assertEqual(result,2,error)
            self.assertIn('NotOpened',bpy.data.objects)
            self.assertFalse(output.exists())
            self.assertFalse(report.exists())

    def test_cli_existing_targets_path_aliases_and_missing_parent_refused(self):
        source,spec,output,report,texture,original = self.fixture()
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        output.write_bytes(b'owned')
        self.assertEqual(self.cli(source,spec,output,report)[0],2)
        self.assertEqual(output.read_bytes(),b'owned')
        output.unlink()
        report.write_text('owned report')
        self.assertEqual(self.cli(source,spec,output,report)[0],2)
        self.assertFalse(output.exists())
        report.unlink()
        self.assertEqual(self.cli(source,spec,source,report)[0],2)
        hardlink = source.parent/'alias.json'
        os.link(source,hardlink)
        self.assertEqual(self.cli(source,hardlink,output,report)[0],2)
        dangling = output.parent/'dangling.blend'
        dangling.symlink_to(output.parent/'missing')
        self.assertEqual(self.cli(source,spec,dangling,report)[0],2)
        self.assertTrue(dangling.is_symlink())
        self.assertEqual(self.cli(source,spec,output.parent/'absent'/'new.blend',report)[0],2)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),sha)

    def test_changed_source_spec_or_dependency_prevents_publication(self):
        for kind in ('source','spec','texture'):
            bpy.ops.wm.read_factory_settings(use_empty=True)
            source,spec,output,report,texture,original = self.fixture()
            target = {'source':source,'spec':spec,'texture':texture}[kind]
            real_build = self.tool.build
            def change_after_build(config):
                result = real_build(config)
                with target.open('ab') as stream:
                    stream.write(b'\nchanged')
                return result
            self.tool.build = change_after_build
            try:
                code,error = self.cli(source,spec,output,report)
                self.assertEqual(code,2,error)
                self.assertIn('changed',error)
                self.assertFalse(output.exists())
                self.assertFalse(report.exists())
            finally:
                self.tool.build = real_build

    def test_missing_external_dependency_refused_without_snapshot(self):
        source,spec,output,report,texture,original = self.fixture()
        texture.unlink()
        code,error = self.cli(source,spec,output,report)
        self.assertEqual(code,2,error)
        self.assertIn('dependency',error)
        self.assertFalse(output.exists())
        self.assertFalse(report.exists())

    def test_actual_subprocess_cli_and_double_dash_form(self):
        source,spec,output,report,texture,original = self.fixture()
        completed = subprocess.run([sys.executable,str(MODULE),'--','--source',str(source),
                                   '--spec',str(spec),'--output',str(output),'--report',str(report)],
                                  capture_output=True,text=True,timeout=120)
        self.assertEqual(completed.returncode,0,completed.stderr+completed.stdout)
        self.assertEqual(json.loads(report.read_text())['status'],'built')
        bpy.ops.wm.open_mainfile(filepath=str(output),use_scripts=False)
        self.assert_solid(bpy.data.objects['NewWing'])

    def test_float32_uv_collapse_refused_and_new_mesh_removed(self):
        spec = example()
        middle = copy.deepcopy(spec['stations'][0])
        middle['span'] = 1e-4
        spec['stations'].insert(1,middle)
        spec['stations'][-1]['span'] = 100000
        with self.assertRaisesRegex(ValueError,'UV|uv'):
            self.tool.build(spec)
        self.assertNotIn('NewWing',bpy.data.meshes)
        self.assertNotIn('NewWing',bpy.data.objects)

    def test_supported_generated_workload_boundary_is_real_manifold(self):
        spec = example()
        spec['airfoil']['samples'] = 65
        station = spec['stations'][0]
        spec['stations'] = [copy.deepcopy(station) | {'span':i*.1} for i in range(64)]
        report = self.tool.build(spec)
        self.assertEqual(report['mesh']['vertices'],8192)
        self.assertEqual(report['mesh']['triangles'],16380)
        self.assert_solid(bpy.data.objects['NewWing'])

    def test_linked_library_and_nested_texture_targets_survive_new_directory(self):
        from PIL import Image
        tmp = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'])
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        library_dir = root/'library'
        library_dir.mkdir()
        texture = library_dir/'nested.png'
        Image.new('RGB',(2,2),(1,2,3)).save(texture)
        bpy.ops.mesh.primitive_cube_add()
        part = bpy.context.object
        part.name = 'LinkedPart'
        mat = bpy.data.materials.new('LinkedMaterial')
        node = mat.node_tree.nodes.new('ShaderNodeTexImage')
        node.image = bpy.data.images.load(str(texture))
        node.image.filepath = '//nested.png'
        part.data.materials.append(mat)
        library = library_dir/'parts.blend'
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(library))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        with bpy.data.libraries.load(str(library),link=True) as (available,loaded):
            loaded.objects = ['LinkedPart']
        bpy.context.scene.collection.objects.link(loaded.objects[0])
        source = root/'source.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(source))
        originals = {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in (source,library,texture)}
        spec = root/'filled.json'
        spec.write_text(json.dumps(example()))
        (root/'new_directory').mkdir()
        output,report = root/'new_directory'/'new.blend',root/'new_directory'/'report.json'
        code,error = self.cli(source,spec,output,report)
        self.assertEqual(code,0,error)
        bpy.ops.wm.open_mainfile(filepath=str(output),use_scripts=False)
        linked = bpy.data.objects['LinkedPart']
        self.assertIsNotNone(linked.library)
        self.assertEqual(Path(bpy.path.abspath(linked.library.filepath)).resolve(),library)
        image = linked.data.materials[0].node_tree.nodes.get('Image Texture').image
        self.assertEqual(Path(bpy.path.abspath(image.filepath,library=image.library)).resolve(),texture)
        self.assert_solid(bpy.data.objects['NewWing'])
        for p,sha in originals.items():
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),sha)

    def test_late_publication_races_never_overwrite_and_report_failure_rolls_back(self):
        for kind in ('output','report'):
            bpy.ops.wm.read_factory_settings(use_empty=True)
            source,spec,output,report,texture,original = self.fixture()
            real_save = self.tool.save_snapshot
            def race(args,data):
                (args.output if kind == 'output' else args.report).write_text('race-created-owner')
                return real_save(args,data)
            self.tool.save_snapshot = race
            try:
                code,error = self.cli(source,spec,output,report)
                self.assertEqual(code,2,error)
                owned = output if kind == 'output' else report
                self.assertEqual(owned.read_text(),'race-created-owner')
                self.assertFalse((report if kind == 'output' else output).exists())
            finally:
                self.tool.save_snapshot = real_save

    def test_packaged_generated_example_builds_and_records_exact_editable_recipe(self):
        path = HERE.parent/'assets'/'lifting-surface.json'
        spec = json.loads(path.read_text())
        report = self.tool.build(spec)
        obj = bpy.data.objects[spec['object_name']]
        self.assert_solid(obj)
        self.assertEqual(json.loads(obj['construction_spec_json']),spec)
        self.assertEqual(obj['construction_tool'],'build_lifting_surface.v1')
        self.assertEqual(len(report['segments']),2)
        self.assertEqual(obj.parent,None)
        self.assertEqual(len(obj.modifiers),0)
        self.assertEqual(tuple(obj.scale),(1,1,1))

    def test_explicit_129_by_64_blunt_workload_boundary_is_manifold(self):
        spec = self.explicit()
        xs = [(1-math.cos(math.pi*i/128))/2 for i in range(129)]
        spec['airfoil'] = {'kind':'explicit','x':xs,'trailing_edge':'blunt'}
        section = {'upper':[.12*math.sqrt(x)*(1-x)+.00126*x for x in xs],
                   'lower':[-.12*math.sqrt(x)*(1-x)-.00126*x for x in xs]}
        spec['stations'] = [{'span':i*.1,'leading_edge':[0,0],'chord':2,
                             'twist_degrees':0,'profile':section} for i in range(64)]
        report = self.tool.build(spec)
        self.assertEqual(report['mesh']['vertices'],16448)
        self.assertEqual(report['mesh']['triangles'],32892)
        self.assert_solid(bpy.data.objects['NewWing'])


if __name__ == '__main__':
    unittest.main()
