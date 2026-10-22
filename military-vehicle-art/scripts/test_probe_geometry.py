"""Real-bpy measured-geometry fixtures; synthetic, not reference evidence."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    import bpy
except ImportError:
    bpy = None

SCRIPT = Path(__file__).with_name('probe_geometry.py')


@unittest.skipIf(bpy is None, 'requires real Blender Python')
class GeometryProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'fixture.blend'
        self.specpath = self.root / 'spec.json'
        self.reportpath = self.root / 'report.json'
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.context.scene.name = 'Fixture'
        bpy.context.scene.unit_settings.system = 'METRIC'
        bpy.context.scene.unit_settings.scale_length = .25
        self.spec = {'schema_version': 1, 'scene': 'Fixture', 'view_layer': 'ViewLayer',
                     'evaluation_frame': 1, 'units': 'm', 'checks': []}

    def cube(self, name, location=(0,0,0), scale=(1,1,1)):
        bpy.ops.mesh.primitive_cube_add(size=2, location=location)
        obj = bpy.context.object
        obj.name = name
        obj.scale = scale
        return obj

    def empty(self, name, location=(0,0,0)):
        obj = bpy.data.objects.new(name, None)
        bpy.context.scene.collection.objects.link(obj)
        obj.location = location
        return obj

    def basis(self):
        return {'kind': 'design_brief', 'note': 'Synthetic fixture dimensions and allowed residuals only.',
                'sha256': hashlib.sha256(b'synthetic test brief').hexdigest()}

    def save(self):
        bpy.context.view_layer.update()
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        self.specpath.write_text(json.dumps(self.spec), encoding='utf-8')
        self.before = [p.read_bytes() for p in (self.source, self.specpath)]

    def invoke(self, expected=0):
        import probe_geometry
        code = probe_geometry.main(['--source',str(self.source), '--spec',str(self.specpath),
                                    '--report',str(self.reportpath)])
        self.assertEqual(code, expected)
        self.assertEqual([p.read_bytes() for p in (self.source,self.specpath)], self.before)
        return json.loads(self.reportpath.read_text()) if expected != 2 and self.reportpath.exists() else None

    def assertVector(self, actual, expected, places=5):
        for a,b in zip(actual,expected):
            self.assertAlmostEqual(a,b,places=places)

    def test_dimensions_uses_evaluated_vertices_in_rigid_frame_and_metres(self):
        body = self.cube('Body', (10,3,2), (2,1,.5))
        body.rotation_euler.z = math.pi/4
        array = body.modifiers.new('Actual evaluated extension', 'ARRAY')
        array.count = 2
        array.relative_offset_displace = (1,0,0)
        datum = self.empty('Datum', (10,3,2))
        datum.rotation_euler.z = math.pi/4
        self.spec['checks'] = [{'id':'size', 'type':'dimensions', 'objects':['Body'],
            'frame':{'kind':'object','object':'Datum'},
            'target':{'dimensions_m':[2, .5, .25], 'tolerance_m':[.00001]*3, 'basis':self.basis()}}]
        self.save()
        report = self.invoke()
        self.assertEqual(report['command'], 'probe-geometry')
        self.assertEqual(report['schema_version'], 1)
        self.assertEqual(report['source_sha256'], hashlib.sha256(self.before[0]).hexdigest())
        row = report['checks'][0]
        self.assertVector(row['dimensions_m'], [2,.5,.25])
        self.assertVector(row['bounds_min_m'], [-.5,-.25,-.125])
        self.assertVector(row['bounds_max_m'], [1.5,.25,.125])
        self.assertEqual(row['evaluated_vertices'],16)
        self.assertEqual(row['objects'],['Body'])
        metadata = {item['name']:item for item in report['evaluated_objects']}
        self.assertVector([metadata['Body']['matrix_world_bu'][i][3] for i in range(3)],[10,3,2])
        self.assertEqual(metadata['Body']['type'],'MESH')
        self.assertIn('Datum',metadata)
        self.assertEqual(report['evaluation']['blender_version'],bpy.app.version_string)
        self.assertEqual(row['status'], 'within-tolerances')
        self.assertTrue(report['limitations'])

    def test_datum_extracts_evaluated_vertex_and_object_axis_not_input_coordinates(self):
        obj = self.cube('Body',(10,3,2),(2,1,.5))
        obj.rotation_euler.z = math.pi/2
        datum = self.empty('Datum',(10,3,2))
        datum.rotation_euler.z = math.pi/2
        # Vertex 0 is (-1,-1,-1), transformed by actual evaluated matrix.
        self.spec['checks'] = [{'id':'corner', 'type':'datum',
            'landmark':{'object':'Body','point':'vertex','index':0}, 'axis':'X',
            'frame':{'kind':'object','object':'Datum'},
            'target':{'position_m':[-.5,-.25,-.125], 'position_tolerance_m':.00001,
                      'direction':[1,0,0], 'angle_tolerance_deg':.01, 'basis':self.basis()}},
            {'id':'origin', 'type':'datum','landmark':{'object':'Body','point':'origin'},
             'axis':'Y','frame':{'kind':'world'}}]
        self.save()
        rows = self.invoke()['checks']
        self.assertVector(rows[0]['position_m'],[-.5,-.25,-.125])
        self.assertVector(rows[0]['direction'],[1,0,0])
        self.assertAlmostEqual(rows[0]['comparison']['angle_error_deg'],0,places=5)
        self.assertEqual(rows[0]['status'],'within-tolerances')
        self.assertVector(rows[1]['position_m'],[2.5,.75,.5])
        self.assertVector(rows[1]['direction'],[-1,0,0])
        self.assertEqual(rows[1]['status'],'measured')

    def test_clearance_samples_true_transformed_gap_and_both_misses(self):
        from mathutils import Vector
        datum = self.empty('Datum',(10,3,2))
        datum.rotation_euler.z = math.pi/4
        bpy.context.view_layer.update()
        a = self.cube('A',datum.location,(2,2,.5))
        a.rotation_euler.z = math.pi/4
        b = self.cube('B',datum.matrix_world @ Vector((8,0,0)),(1,1,.5))
        b.rotation_euler.z = math.pi/4
        self.spec['checks'] = [{'id':'gap','type':'clearance','from_object':'A','to_object':'B',
            'frame':{'kind':'object','object':'Datum'}, 'max_distance_m':3, 'epsilon_m':.00001,
            'samples':[{'id':'center','origin_m':[0,0,0],'direction':[2,0,0]},
                       {'id':'miss-from','origin_m':[0,2,0],'direction':[1,0,0]},
                       {'id':'miss-to','origin_m':[0,.375,0],'direction':[1,0,0]}],
            'target':{'gap_m':1.25,'tolerance_m':.0001,'basis':self.basis()}}]
        self.save()
        row = self.invoke(expected=1)['checks'][0]
        self.assertEqual(row['status'],'incomplete')
        samples = row['samples']
        self.assertAlmostEqual(samples[0]['gap_m'],1.25,places=5)
        self.assertEqual(samples[0]['status'],'within-tolerances')
        self.assertVector(samples[0]['from_hit']['position_m'],[.5,0,0])
        self.assertVector(samples[0]['to_hit']['position_m'],[1.75,0,0])
        self.assertEqual(samples[1]['status'],'from-miss')
        self.assertIsNone(samples[1]['from_hit'])
        self.assertEqual(samples[2]['status'],'to-miss')
        self.assertIsNone(samples[2]['to_hit'])

    def test_thickness_uses_successive_shell_surfaces_not_outer_span_or_cavity(self):
        outer = self.cube('Shell',(10,3,2),(2,1,1))
        vertices = [tuple(v.co) for v in outer.data.vertices]
        faces = [tuple(p.vertices) for p in outer.data.polygons]
        vertices += [tuple(c*.8 for c in v) for v in vertices[:]]
        faces += [tuple(i+8 for i in reversed(p)) for p in faces[:]]
        mesh = bpy.data.meshes.new('Hollow mesh')
        mesh.from_pydata(vertices,[],faces)
        outer.data = mesh
        outer.rotation_euler.z = math.pi/4
        datum = self.empty('Datum',(10,3,2))
        datum.rotation_euler.z = math.pi/4
        self.spec['checks'] = [{'id':'wall','type':'thickness','object':'Shell',
            'frame':{'kind':'object','object':'Datum'},'max_distance_m':3,'epsilon_m':.00001,
            'samples':[{'id':'normal','origin_m':[-1,0,0],'direction':[1,0,0]},
                       {'id':'oblique','origin_m':[-1,-.05,0],'direction':[1,.1,0]},
                       {'id':'miss','origin_m':[-1,2,0],'direction':[1,0,0]}]}]
        self.save()
        samples = self.invoke(expected=1)['checks'][0]['samples']
        self.assertAlmostEqual(samples[0]['thickness_m'],.1,places=5)
        self.assertVector(samples[0]['entry_hit']['position_m'],[-.5,0,0])
        self.assertVector(samples[0]['exit_hit']['position_m'],[-.4,0,0])
        self.assertAlmostEqual(samples[1]['thickness_m'],.1*math.sqrt(1.01),places=5)
        self.assertEqual(samples[0]['status'],'measured')
        self.assertEqual(samples[2]['status'],'entry-miss')
        self.assertIsNone(samples[2]['thickness_m'])

    def test_duplicate_json_fields_are_rejected_before_blender_opens(self):
        self.cube('Body')
        self.spec['checks'] = [{'id':'size','type':'dimensions','objects':['Body'],'frame':{'kind':'world'}}]
        self.save()
        raw = self.specpath.read_text().replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1')
        self.specpath.write_text(raw)
        self.before[1] = raw.encode()
        self.assertIsNone(self.invoke(expected=2))
        self.assertFalse(self.reportpath.exists())

    def test_clearance_reports_intervening_source_surface_instead_of_false_gap_pass(self):
        a = self.cube('A')
        vertices = [tuple(v.co) for v in a.data.vertices]
        faces = [tuple(p.vertices) for p in a.data.polygons]
        vertices += [(x+5,y,z) for x,y,z in vertices[:]]
        faces += [tuple(i+8 for i in p) for p in faces[:]]
        mesh = bpy.data.meshes.new('Disconnected source lobes')
        mesh.from_pydata(vertices,[],faces)
        a.data = mesh
        self.cube('B',(10,0,0))
        self.spec['checks'] = [{'id':'gap','type':'clearance','from_object':'A','to_object':'B',
            'frame':{'kind':'world'},'max_distance_m':4,'epsilon_m':.00001,
            'samples':[{'id':'center','origin_m':[0,0,0],'direction':[1,0,0]}],
            'target':{'gap_m':2,'tolerance_m':.001,'basis':self.basis()}}]
        self.save()
        sample = self.invoke(expected=1)['checks'][0]['samples'][0]
        self.assertEqual(sample['status'],'source-obstructed')
        self.assertVector(sample['source_rehit']['position_m'],[1,0,0])
        self.assertNotIn('comparison',sample)

    def test_geometry_nodes_are_rejected_instead_of_silently_dropping_instances(self):
        obj = self.cube('Body')
        group = bpy.data.node_groups.new('Possibly instanced geometry','GeometryNodeTree')
        group.interface.new_socket(name='Geometry',in_out='INPUT',socket_type='NodeSocketGeometry')
        group.interface.new_socket(name='Geometry',in_out='OUTPUT',socket_type='NodeSocketGeometry')
        source = group.nodes.new('NodeGroupInput')
        sink = group.nodes.new('NodeGroupOutput')
        group.links.new(source.outputs['Geometry'],sink.inputs['Geometry'])
        obj.modifiers.new('GN','NODES').node_group = group
        self.spec['checks'] = [{'id':'size','type':'dimensions','objects':['Body'],'frame':{'kind':'world'}}]
        self.save()
        self.assertIsNone(self.invoke(expected=2))

    def test_total_ray_workload_is_bounded_across_checks(self):
        import copy
        import probe_geometry
        item = {'id':'wall','type':'thickness','object':'Body','frame':{'kind':'world'},
                'max_distance_m':1,'epsilon_m':.00001,
                'samples':[{'id':str(i),'origin_m':[0,0,0],'direction':[1,0,0]} for i in range(2049)]}
        other = copy.deepcopy(item)
        other['id'] = 'wall2'
        self.spec['checks'] = [item,other]
        with self.assertRaisesRegex(ValueError,'total sample'):
            probe_geometry.validate_spec(self.spec)

    def test_hidden_measurement_objects_are_rejected_as_unsupported_evaluation_scope(self):
        obj = self.cube('Body')
        obj.hide_set(True)
        self.spec['checks'] = [{'id':'size','type':'dimensions','objects':['Body'],'frame':{'kind':'world'}}]
        self.save()
        self.assertIsNone(self.invoke(expected=2))

    def test_evaluated_mesh_budget_is_global_not_reset_for_each_check(self):
        import probe_geometry
        from unittest.mock import patch
        self.cube('A')
        self.cube('B',(4,0,0))
        self.spec['checks'] = [{'id':name,'type':'dimensions','objects':[name],'frame':{'kind':'world'}} for name in ('A','B')]
        self.save()
        with patch.object(probe_geometry,'MAX_VERTICES',12):
            self.assertIsNone(self.invoke(expected=2))

    def test_json_publication_is_complete_atomic_and_exclusive_under_destination_race(self):
        import probe_geometry
        from unittest.mock import patch
        real_link = os.link
        def racing_link(source,target,**kwargs):
            self.assertEqual(json.loads(Path(source).read_text()),{'measured':42})
            self.assertFalse(Path(target).exists())
            Path(target).write_text('racing writer owns this file')
            return real_link(source,target,**kwargs)
        with patch.object(probe_geometry.os,'link',side_effect=racing_link):
            with self.assertRaises(FileExistsError):
                probe_geometry.publish_json(self.reportpath,{'measured':42})
        self.assertEqual(self.reportpath.read_text(),'racing writer owns this file')
        self.assertEqual(list(self.root.glob('.geometry-*')),[])
        self.reportpath.unlink()
        probe_geometry.publish_json(self.reportpath,{'measured':42})
        self.assertEqual(json.loads(self.reportpath.read_text()),{'measured':42})
        with self.assertRaises(FileExistsError):
            probe_geometry.publish_json(self.reportpath,{'measured':43})

    def test_child_of_vertex_instancer_is_rejected_instead_of_measuring_uninstanced_master(self):
        emitter = self.cube('Emitter')
        emitter.instance_type = 'VERTS'
        child = self.cube('Child',(0,0,2),(.1,.1,.1))
        child.parent = emitter
        self.spec['checks'] = [{'id':'size','type':'dimensions','objects':['Child'],'frame':{'kind':'world'}}]
        self.save()
        self.assertIsNone(self.invoke(expected=2))

    def test_schema_rejects_unknown_missing_vacuous_nonfinite_and_boolean_values(self):
        import copy
        import probe_geometry
        dims = {'id':'size','type':'dimensions','objects':['Body'],'frame':{'kind':'world'},
                'target':{'dimensions_m':[1,1,1],'tolerance_m':[.01]*3,'basis':self.basis()}}
        datum = {'id':'point','type':'datum','landmark':{'object':'Body','point':'vertex','index':0},
                 'axis':'X','frame':{'kind':'world'},
                 'target':{'position_m':[0,0,0],'position_tolerance_m':.01,'direction':[1,0,0],
                           'angle_tolerance_deg':1,'basis':self.basis()}}
        wall = {'id':'wall','type':'thickness','object':'Body','frame':{'kind':'world'},
                'max_distance_m':1,'epsilon_m':.00001,
                'samples':[{'id':'a','origin_m':[0,0,0],'direction':[1,0,0]}],
                'target':{'thickness_m':.1,'tolerance_m':.01,'basis':self.basis()}}
        gap = {**copy.deepcopy(wall),'id':'gap','type':'clearance','from_object':'Body','to_object':'Other'}
        del gap['object']
        gap['target']['gap_m'] = gap['target'].pop('thickness_m')
        self.spec['checks'] = [dims,datum,wall,gap]
        probe_geometry.validate_spec(self.spec)
        def at(data,path):
            for key in path:
                data = data[key]
            return data
        dictionaries = [(),('checks',0),('checks',0,'frame'),('checks',0,'target'),
                        ('checks',0,'target','basis'),('checks',1),('checks',1,'landmark'),
                        ('checks',1,'target'),('checks',2),('checks',2,'samples',0),
                        ('checks',2,'target'),('checks',3),('checks',3,'target')]
        for path in dictionaries:
            for operation in ('unknown','missing'):
                bad = copy.deepcopy(self.spec)
                node = at(bad,path)
                if operation == 'unknown':
                    node['invented'] = 1
                else:
                    del node[next(iter(node))]
                with self.subTest(path=path,operation=operation), self.assertRaises(ValueError):
                    probe_geometry.validate_spec(bad)
        mutations = [(('schema_version',),True),(('evaluation_frame',),True),(('units',),'mm'),
                     (('checks',),[]),(('checks',0,'objects'),[]),(('checks',0,'objects'),['Body','Body']),
                     (('checks',0,'target','dimensions_m',0),True),
                     (('checks',0,'target','tolerance_m',0),-.1),
                     (('checks',0,'target','basis','note'),' '),
                     (('checks',0,'target','basis','sha256'),'not-a-fingerprint'),
                     (('checks',1,'landmark','index'),True),(('checks',1,'axis'),'W'),
                     (('checks',1,'target','position_tolerance_m'),True),
                     (('checks',1,'target','angle_tolerance_deg'),181),
                     (('checks',1,'target','direction'),[0,0,0]),
                     (('checks',2,'samples'),[]),(('checks',2,'max_distance_m'),True),
                     (('checks',2,'epsilon_m'),0),(('checks',2,'epsilon_m'),2),
                     (('checks',2,'samples',0,'direction'),[0,0,0]),
                     (('checks',2,'samples',0,'origin_m',0),True),
                     (('checks',2,'target','thickness_m'),-.1),
                     (('checks',3,'to_object'),'Body')]
        for invalid in (float('nan'),float('inf'),-float('inf'),10**1000):
            mutations.append((('checks',2,'samples',0,'origin_m',0),invalid))
        for path,value in mutations:
            bad = copy.deepcopy(self.spec)
            at(bad,path[:-1])[path[-1]] = value
            with self.subTest(path=path,value=repr(value)), self.assertRaises(ValueError):
                probe_geometry.validate_spec(bad)
        duplicate = copy.deepcopy(self.spec)
        duplicate['checks'][2]['samples'] *= 2
        with self.assertRaises(ValueError):
            probe_geometry.validate_spec(duplicate)
        duplicate = copy.deepcopy(self.spec)
        duplicate['checks'] *= 2
        with self.assertRaises(ValueError):
            probe_geometry.validate_spec(duplicate)

    def test_cli_from_unrelated_cwd_preserves_inputs_and_refuses_existing_report(self):
        self.cube('Body',scale=(2,1,.5))
        self.spec['checks'] = [{'id':'size','type':'dimensions','objects':['Body'],'frame':{'kind':'world'}}]
        self.save()
        unrelated = self.root / 'unrelated'
        unrelated.mkdir()
        command = [sys.executable,str(SCRIPT),'--source',str(self.source),'--spec',str(self.specpath),'--report',str(self.reportpath)]
        environment = {**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}
        result = subprocess.run(command,cwd=unrelated,env=environment,text=True,capture_output=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        report = json.loads(self.reportpath.read_text())
        self.assertVector(report['checks'][0]['dimensions_m'],[1,.5,.25])
        self.assertEqual(report['spec_sha256'],hashlib.sha256(self.before[1]).hexdigest())
        encoded = self.reportpath.read_bytes()
        result = subprocess.run(command,cwd=unrelated,env=environment,text=True,capture_output=True,timeout=60)
        self.assertEqual(result.returncode,2,result.stdout+result.stderr)
        self.assertEqual(self.reportpath.read_bytes(),encoded)
        self.assertEqual([p.read_bytes() for p in (self.source,self.specpath)],self.before)

    def test_output_symlink_hardlink_and_input_aliases_are_not_overwritten(self):
        self.cube('Body')
        self.spec['checks'] = [{'id':'size','type':'dimensions','objects':['Body'],'frame':{'kind':'world'}}]
        self.save()
        for kind in ('symlink','dangling-symlink','hardlink','source-alias','spec-alias'):
            with self.subTest(kind=kind):
                if kind == 'symlink':
                    self.reportpath.symlink_to(self.source)
                elif kind == 'dangling-symlink':
                    self.reportpath.symlink_to(self.root/'missing')
                elif kind == 'hardlink':
                    os.link(self.source,self.reportpath)
                elif kind == 'source-alias':
                    self.reportpath = self.source
                else:
                    self.reportpath = self.specpath
                self.invoke(expected=2)
                if kind in ('symlink','dangling-symlink','hardlink'):
                    self.reportpath.unlink()
                self.reportpath = self.root/'report.json'

    def test_source_or_spec_changes_during_real_evaluation_prevent_publication(self):
        import probe_geometry
        from unittest.mock import patch
        self.cube('Body')
        self.spec['checks'] = [{'id':'size','type':'dimensions','objects':['Body'],'frame':{'kind':'world'}}]
        self.save()
        real_evaluate = probe_geometry.evaluate
        for index in (0,1):
            changed = (self.source,self.specpath)[index]
            def mutate(spec):
                result = real_evaluate(spec)
                with changed.open('ab') as stream:
                    stream.write(b'\n')
                return result
            with self.subTest(input=index), patch.object(probe_geometry,'evaluate',side_effect=mutate):
                result = probe_geometry.main(['--source',str(self.source),'--spec',str(self.specpath),'--report',str(self.reportpath)])
                self.assertEqual(result,2)
                self.assertFalse(self.reportpath.exists())
            changed.write_bytes(self.before[index])

    def test_named_frames_reject_scale_shear_and_reflection(self):
        from mathutils import Matrix
        self.cube('Body')
        self.empty('Datum')
        self.spec['checks'] = [{'id':'size','type':'dimensions','objects':['Body'],'frame':{'kind':'object','object':'Datum'}}]
        matrices = [Matrix.Diagonal((2,1,1,1)),Matrix.Diagonal((-1,1,1,1)),
                    Matrix(((1,.2,0,0),(0,1,0,0),(0,0,1,0),(0,0,0,1)))]
        for matrix in matrices:
            bpy.data.objects['Datum'].matrix_world = matrix
            self.save()
            with self.subTest(matrix=str(matrix)):
                self.assertIsNone(self.invoke(expected=2))

    def test_linked_and_local_same_name_are_ambiguous_not_silently_selected(self):
        obj = self.cube('Body')
        library = self.root/'library.blend'
        bpy.data.libraries.write(str(library),{obj})
        with bpy.data.libraries.load(str(library),link=True) as (source,target):
            target.objects = ['Body']
        bpy.context.scene.collection.objects.link(target.objects[0])
        self.assertEqual(len([o for o in bpy.data.objects if o.name=='Body']),2)
        self.spec['checks'] = [{'id':'size','type':'dimensions','objects':['Body'],'frame':{'kind':'world'}}]
        self.save()
        self.assertIsNone(self.invoke(expected=2))

    def test_open_surface_has_entry_but_no_exit_not_zero_thickness(self):
        mesh = bpy.data.meshes.new('OpenPlane')
        mesh.from_pydata([(0,-1,-1),(0,-1,1),(0,1,1),(0,1,-1)],[],[(0,1,2,3)])
        obj = bpy.data.objects.new('OpenPlane',mesh)
        bpy.context.scene.collection.objects.link(obj)
        self.spec['checks'] = [{'id':'wall','type':'thickness','object':'OpenPlane','frame':{'kind':'world'},
            'max_distance_m':1,'epsilon_m':.00001,
            'samples':[{'id':'single','origin_m':[-.5,0,0],'direction':[1,0,0]}]}]
        self.save()
        sample = self.invoke(expected=1)['checks'][0]['samples'][0]
        self.assertEqual(sample['status'],'exit-miss')
        self.assertIsNotNone(sample['entry_hit'])
        self.assertIsNone(sample['exit_hit'])
        self.assertIsNone(sample['thickness_m'])

    def test_reversed_seed_orientation_is_not_accepted_as_thickness_or_gap(self):
        self.cube('Body')
        self.cube('Other',(4,0,0))
        self.spec['checks'] = [
            {'id':'wall','type':'thickness','object':'Body','frame':{'kind':'world'},'max_distance_m':3,'epsilon_m':.00001,
             'samples':[{'id':'inside','origin_m':[0,0,0],'direction':[1,0,0]}]},
            {'id':'gap','type':'clearance','from_object':'Body','to_object':'Other','frame':{'kind':'world'},
             'max_distance_m':3,'epsilon_m':.00001,'samples':[{'id':'outside','origin_m':[-1,0,0],'direction':[1,0,0]}]}]
        self.save()
        rows = self.invoke(expected=1)['checks']
        self.assertEqual(rows[0]['samples'][0]['status'],'exit-miss')
        self.assertEqual(rows[1]['samples'][0]['status'],'source-obstructed')
        self.assertNotIn('comparison',rows[1]['samples'][0])

    def test_requested_animation_frame_and_evaluated_array_landmark_are_used(self):
        obj = self.cube('Body')
        obj.location.x = 0
        obj.keyframe_insert(data_path='location',frame=1)
        obj.location.x = 8
        obj.keyframe_insert(data_path='location',frame=5)
        modifier = obj.modifiers.new('Second actual part','ARRAY')
        modifier.count = 2
        modifier.relative_offset_displace = (1,0,0)
        self.spec['evaluation_frame'] = 5
        self.spec['checks'] = [{'id':'point','type':'datum','landmark':{'object':'Body','point':'vertex','index':8},
                              'axis':'X','frame':{'kind':'world'}}]
        self.save()
        report = self.invoke()
        self.assertEqual(report['evaluation']['frame'],5)
        self.assertVector(report['checks'][0]['position_m'],[2.25,-.25,-.25])

    def test_distributed_template_is_deliberately_unfilled_and_refused(self):
        import probe_geometry
        path = SCRIPT.parent.parent/'assets'/'geometry-probes.json'
        self.assertTrue(path.is_file(),'the unfilled template must be distributed')
        with self.assertRaises(ValueError):
            probe_geometry.read_spec(path)
        data = json.loads(path.read_text())
        self.assertEqual([row['type'] for row in data['checks']],['dimensions','datum','clearance','thickness'])
        self.assertIsNone(data['scene'])

    def test_symlink_input_or_output_ancestors_are_refused_without_dependency_retargeting(self):
        import probe_geometry
        self.cube('Body')
        self.spec['checks'] = [{'id':'size','type':'dimensions','objects':['Body'],'frame':{'kind':'world'}}]
        self.save()
        source_alias = self.root/'source-alias.blend'
        source_alias.symlink_to(self.source)
        spec_alias = self.root/'spec-alias.json'
        spec_alias.symlink_to(self.specpath)
        directory_alias = self.root/'directory-alias'
        directory_alias.symlink_to(self.root,target_is_directory=True)
        for source,spec,output in ((source_alias,self.specpath,self.reportpath),
                                   (self.source,spec_alias,self.reportpath),
                                   (self.source,self.specpath,directory_alias/'report.json')):
            with self.subTest(source=str(source),spec=str(spec),output=str(output)):
                code = probe_geometry.main(['--source',str(source),'--spec',str(spec),'--report',str(output)])
                self.assertEqual(code,2)
                self.assertFalse(self.reportpath.exists())
        self.assertEqual([p.read_bytes() for p in (self.source,self.specpath)],self.before)

    def test_each_check_type_executes_independently_and_reports_target_disagreement(self):
        self.cube('Body',scale=(2,1,.5))
        self.cube('Other',(8,0,0),scale=(1,1,.5))
        cases = [
            {'id':'size','type':'dimensions','objects':['Body'],
             'target':{'dimensions_m':[2,.5,.25],'tolerance_m':[0,0,0],'basis':self.basis()}},
            {'id':'point','type':'datum','landmark':{'object':'Body','point':'origin'},'axis':'X',
             'target':{'position_m':[0,1,0],'position_tolerance_m':.01,'direction':[0,1,0],
                       'angle_tolerance_deg':.5,'basis':self.basis()}},
            {'id':'gap','type':'clearance','from_object':'Body','to_object':'Other',
             'max_distance_m':3,'epsilon_m':.00001,'samples':[{'id':'a','origin_m':[0,0,0],'direction':[1,0,0]}],
             'target':{'gap_m':2,'tolerance_m':.01,'basis':self.basis()}},
            {'id':'wall','type':'thickness','object':'Body','max_distance_m':3,'epsilon_m':.00001,
             'samples':[{'id':'a','origin_m':[-1,0,0],'direction':[1,0,0]}],
             'target':{'thickness_m':2,'tolerance_m':.01,'basis':self.basis()}}]
        for check in cases:
            with self.subTest(kind=check['type']):
                check['frame'] = {'kind':'world'}
                self.spec['checks'] = [check]
                self.reportpath = self.root/(check['type']+'.json')
                self.save()
                report = self.invoke(expected=1)
                row = report['checks'][0]
                self.assertEqual(row['status'],'needs-correction')
                self.assertEqual(report['status'],'needs-correction')
                if check['type'] == 'datum':
                    self.assertAlmostEqual(row['comparison']['position_error_m'],1)
                    self.assertAlmostEqual(row['comparison']['angle_error_deg'],90)
                elif check['type'] == 'thickness':
                    self.assertAlmostEqual(row['samples'][0]['thickness_m'],1)
                elif check['type'] == 'clearance':
                    self.assertAlmostEqual(row['samples'][0]['gap_m'],1.25)

    def test_missing_scene_layer_name_vertex_and_empty_mesh_do_not_publish(self):
        import copy
        self.cube('Body')
        self.empty('EmptyDatum')
        mesh = bpy.data.meshes.new('EmptyMesh')
        empty = bpy.data.objects.new('EmptyMesh',mesh)
        bpy.context.scene.collection.objects.link(empty)
        baseline = {'id':'size','type':'dimensions','objects':['Body'],'frame':{'kind':'world'}}
        self.spec['checks'] = [baseline]
        cases = []
        for key,value in (('scene','Missing'),('view_layer','Missing')):
            bad = copy.deepcopy(self.spec)
            bad[key] = value
            cases.append(bad)
        for name in ('Missing','EmptyMesh','EmptyDatum'):
            bad = copy.deepcopy(self.spec)
            bad['checks'][0]['objects'] = [name]
            cases.append(bad)
        bad = copy.deepcopy(self.spec)
        bad['checks'] = [{'id':'point','type':'datum','landmark':{'object':'Body','point':'vertex','index':1000},
                          'axis':'X','frame':{'kind':'world'}}]
        cases.append(bad)
        for case in cases:
            self.spec = case
            self.save()
            self.assertIsNone(self.invoke(expected=2))
            self.assertFalse(self.reportpath.exists())
        self.spec = {'schema_version':1,'scene':'Fixture','view_layer':'ViewLayer','evaluation_frame':1,
                     'units':'m','checks':[baseline]}
        bpy.context.scene.unit_settings.system = 'NONE'
        self.save()
        self.assertIsNone(self.invoke(expected=2))

    def test_duplicate_local_and_linked_scene_names_are_ambiguous(self):
        library = self.root/'scene-library.blend'
        bpy.data.libraries.write(str(library),{bpy.context.scene})
        with bpy.data.libraries.load(str(library),link=True) as (source,target):
            target.scenes = ['Fixture']
        self.cube('Body')
        self.assertEqual(len([s for s in bpy.data.scenes if s.name=='Fixture']),2)
        self.spec['checks'] = [{'id':'point','type':'datum','landmark':{'object':'Body','point':'origin'},
                              'axis':'X','frame':{'kind':'world'}}]
        self.save()
        import probe_geometry
        with self.assertRaisesRegex(ValueError,'ambiguous.*scene'):
            probe_geometry.run(self.source,self.specpath,self.reportpath)

    def test_ray_values_that_overflow_or_underflow_blender_precision_are_refused(self):
        self.cube('Body')
        check = {'id':'wall','type':'thickness','object':'Body','frame':{'kind':'world'},
                 'max_distance_m':2,'epsilon_m':.00001,
                 'samples':[{'id':'sample','origin_m':[-1,0,0],'direction':[1,0,0]}]}
        import copy
        for field,value in (('origin_m',1e100),('max_distance_m',1e100),('epsilon_m',1e-100)):
            bad = copy.deepcopy(check)
            if field == 'origin_m':
                bad['samples'][0]['origin_m'][0] = value
            else:
                bad[field] = value
            self.spec['checks'] = [bad]
            self.reportpath = self.root/(field+'.json')
            self.save()
            with self.subTest(field=field):
                self.assertIsNone(self.invoke(expected=2))
                self.assertFalse(self.reportpath.exists())


if __name__ == '__main__':
    unittest.main()
