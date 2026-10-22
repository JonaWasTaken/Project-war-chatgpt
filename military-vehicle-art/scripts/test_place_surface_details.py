"""Synthetic real-bpy regressions; these tests do not establish asset fidelity."""
import contextlib
import copy
import hashlib
import io
import importlib.util
import json
import math
import os
from pathlib import Path
import tempfile
import unittest

try:
    import bpy
    from mathutils import Matrix, Vector
except ImportError:
    bpy = None

MODULE = Path(__file__).with_name('place_surface_details.py')


def spec():
    return {'schema_version': 1, 'collection': 'PlacedDetails',
            'master': {'object': 'BoltMaster', 'attachment_origin': [0, 0, 0],
                       'normal_axis': '+Z', 'tangent_axis': '+X'},
            'placements': [{'feature_id': 'panel-fastener-01', 'object_name': 'Bolt01',
                'target': 'Panel', 'ray': {'origin': [0, 0, 5], 'direction': [0, 0, -1],
                                          'max_distance': 10},
                'tangent': [1, 0, 0], 'offset': 0.01, 'rotation_degrees': 0,
                'scale': [1, 1, 1],
                'support': {'kind': 'authored', 'description': 'Synthetic authored test location'}}]}


@unittest.skipIf(bpy is None, 'requires actual bpy')
class SurfaceDetailTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), 'surface placement helper is not implemented')
        loader = importlib.util.spec_from_file_location('surface_detail_helper', MODULE)
        self.tool = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(self.tool)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.root = Path(self.tmp.name)

    def tearDown(self):
        if hasattr(self, 'tmp'):
            self.tmp.cleanup()

    def scene(self):
        bpy.ops.mesh.primitive_plane_add(size=4)
        panel = bpy.context.object
        panel.name = 'Panel'
        panel.location = (2, -3, 1)
        panel.rotation_euler = (.3, -.4, .2)
        panel.scale = (2, 1, .5)
        solid = panel.modifiers.new('StaticThickness', 'SOLIDIFY')
        solid.thickness = .2
        solid.offset = 1
        bpy.ops.mesh.primitive_cube_add(size=.2, location=(8, 8, 8))
        master = bpy.context.object
        master.name = 'BoltMaster'
        for vertex in master.data.vertices:
            vertex.co += Vector((.2, -.1, .4))
        master.data.uv_layers[0].name = 'MasterUV'
        base = bpy.data.materials.new('DataMaterial')
        override = bpy.data.materials.new('ObjectMaterial')
        master.data.materials.append(base)
        master.material_slots[0].link = 'OBJECT'
        master.material_slots[0].material = override
        bpy.context.view_layer.update()
        config = spec()
        config['master']['attachment_origin'] = [.2, -.1, .3]
        normal = (panel.matrix_world.to_3x3().inverted().transposed() @ Vector((0, 0, 1))).normalized()
        hit = panel.matrix_world @ Vector((.31, -.23, .2))
        tangent = (panel.matrix_world.to_3x3() @ Vector((1, 0, 0))).normalized()
        config['placements'][0].update(
            ray={'origin': list(hit+normal*3), 'direction': list(-normal*7), 'max_distance': 4},
            tangent=list(tangent+normal*.5), rotation_degrees=35, scale=[1.2, .8, 1.1])
        return config, hit, normal, tangent

    def test_evaluated_transformed_hit_frame_and_independent_master_material_ownership(self):
        config, hit, normal, tangent = self.scene()
        master = bpy.data.objects['BoltMaster']
        before = [list(v.co) for v in master.data.vertices]
        matrix_before = [list(row) for row in master.matrix_world]
        report = self.tool.place(config)
        json.dumps(report, allow_nan=False)
        row = report['placements'][0]
        self.assertEqual(row['feature_id'], 'panel-fastener-01')
        self.assertLess((Vector(row['hit_position'])-hit).length, 2e-5)
        self.assertLess((Vector(row['hit_normal'])-normal).length, 2e-5)
        self.assertAlmostEqual(row['distance'], 3, places=5)
        obj = bpy.data.objects['Bolt01']
        matrix = obj.matrix_world
        self.assertEqual(row['matrix_world'], [list(r) for r in matrix])
        anchor = matrix @ Vector(config['master']['attachment_origin'])
        self.assertLess((anchor-(hit+normal*.01)).length, 2e-5)
        x = (matrix.to_3x3() @ Vector((1, 0, 0))).normalized()
        z = (matrix.to_3x3() @ Vector((0, 0, 1))).normalized()
        expected_x = tangent*math.cos(math.radians(35)) + normal.cross(tangent)*math.sin(math.radians(35))
        self.assertLess((x-expected_x).length, 2e-5)
        self.assertLess((z-normal).length, 2e-5)
        self.assertEqual([list(v.co) for v in obj.data.vertices], before)
        self.assertIsNot(obj.data, master.data)
        self.assertEqual(obj.data.users, 1)
        self.assertEqual(obj.material_slots[0].link, 'OBJECT')
        self.assertEqual(obj.material_slots[0].material.name, 'ObjectMaterial')
        self.assertEqual(obj.data.materials[0].name, 'DataMaterial')
        self.assertEqual([u.name for u in obj.data.uv_layers], ['MasterUV'])
        obj.data.vertices[0].co.x += .5
        self.assertEqual([list(v.co) for v in master.data.vertices], before)
        self.assertEqual([list(r) for r in master.matrix_world], matrix_before)
        self.assertEqual(len(bpy.data.objects['Panel'].modifiers), 1)
        self.assertEqual(report['collision_tested'], False)
        self.assertEqual(report['collection'], 'PlacedDetails')

    def test_ray_direction_magnitude_does_not_change_hit_distance_or_frame(self):
        config, _, _, _ = self.scene()
        original = copy.deepcopy(config['placements'][0])
        config['placements'] = []
        for i, magnitude in enumerate((1, 1e-18, 1e-40, 1e5)):
            row = copy.deepcopy(original)
            row.update(feature_id=f'ray-{i}', object_name=f'RayBolt{i}')
            length = math.hypot(*original['ray']['direction'])
            row['ray']['direction'] = [v/length*magnitude for v in original['ray']['direction']]
            config['placements'].append(row)
        before = copy.deepcopy(config)
        report = self.tool.place(config)
        self.assertEqual(config, before)
        control = report['placements'][0]
        for row in report['placements']:
            self.assertLess((Vector(row['hit_position'])-Vector(control['hit_position'])).length, 2e-5)
            self.assertAlmostEqual(row['distance'], control['distance'], places=5)
            for actual, expected in zip(row['matrix_world'], control['matrix_world']):
                for a, b in zip(actual, expected):
                    self.assertAlmostEqual(a, b, places=5)
            self.assertIn(row['object'], bpy.data.objects)

    def test_tangent_magnitude_does_not_change_projected_tangent_or_placement_frame(self):
        config, _, _, _ = self.scene()
        original = copy.deepcopy(config['placements'][0])
        config['placements'] = []
        for i, magnitude in enumerate((1, 1e-18, 1e-40, 1e5)):
            row = copy.deepcopy(original)
            row.update(feature_id=f'tangent-{i}', object_name=f'TangentBolt{i}')
            length = math.hypot(*original['tangent'])
            row['tangent'] = [v/length*magnitude for v in original['tangent']]
            config['placements'].append(row)
        before = copy.deepcopy(config)
        report = self.tool.place(config)
        self.assertEqual(config, before)
        control = report['placements'][0]
        for row in report['placements']:
            self.assertLess((Vector(row['tangent'])-Vector(control['tangent'])).length, 2e-5)
            for actual, expected in zip(row['matrix_world'], control['matrix_world']):
                for a, b in zip(actual, expected):
                    self.assertAlmostEqual(a, b, places=5)
            self.assertIn(row['object'], bpy.data.objects)

    def test_preflight_rejects_entire_batch_without_creating_ids(self):
        cases = ('miss', 'range', 'parallel', 'hidden', 'hidden_render', 'master_hidden',
                 'missing_master', 'missing_target', 'target_is_master', 'owned_object',
                 'owned_mesh', 'owned_collection', 'owned_feature', 'parent', 'constraint',
                 'animation', 'shape_keys', 'nodes', 'master_modifier', 'master_rotation',
                 'negative_scale', 'zero_scale', 'delta', 'nonfinite_mesh',
                 'collapsed_offset', 'collapsed_master', 'collection_instance', 'object_dependency',
                 'excessive_subdivision', 'output_budget', 'hidden_faces',
                 'destination_collection_dependency')
        for case in cases:
            with self.subTest(case=case):
                bpy.ops.wm.read_factory_settings(use_empty=True)
                config, hit, normal, tangent = self.scene()
                master, panel = bpy.data.objects['BoltMaster'], bpy.data.objects['Panel']
                second = copy.deepcopy(config['placements'][0])
                second.update(feature_id='second', object_name='Bolt02')
                config['placements'].append(second)
                if case == 'miss': second['ray']['origin'] = [900, 900, 900]
                elif case == 'range': second['ray']['max_distance'] = .01
                elif case == 'parallel': second['tangent'] = list(normal)
                elif case == 'hidden': panel.hide_set(True)
                elif case == 'hidden_render': panel.hide_render = True
                elif case == 'master_hidden': master.hide_set(True)
                elif case == 'missing_master': config['master']['object'] = 'Missing'
                elif case == 'missing_target': second['target'] = 'Missing'
                elif case == 'target_is_master': second['target'] = 'BoltMaster'
                elif case == 'owned_object': bpy.data.objects.new('Bolt02', None)
                elif case == 'owned_mesh': bpy.data.meshes.new('Bolt02')
                elif case == 'owned_collection': bpy.data.collections.new('PlacedDetails')
                elif case == 'owned_feature': panel['surface_detail_feature_id'] = 'second'
                elif case == 'parent': panel.parent = master
                elif case == 'constraint': panel.constraints.new('COPY_LOCATION')
                elif case == 'animation': panel.keyframe_insert(data_path='location')
                elif case == 'shape_keys': panel.shape_key_add(name='Basis')
                elif case == 'nodes': panel.modifiers.new('Unsupported', 'NODES')
                elif case == 'master_modifier': master.modifiers.new('Unsupported', 'BEVEL')
                elif case == 'master_rotation': master.rotation_euler.x = .3
                elif case == 'negative_scale': panel.scale.x = -2
                elif case == 'zero_scale': panel.scale.x = 0
                elif case == 'delta': panel.delta_location.x = 1
                elif case == 'nonfinite_mesh': panel.data.vertices[0].co.x = float('nan')
                elif case == 'hidden_faces': panel.data.polygons[0].hide = True
                elif case == 'destination_collection_dependency':
                    group = bpy.data.node_groups.new('CollectionConsumer', 'GeometryNodeTree')
                    node = group.nodes.new('GeometryNodeCollectionInfo')
                    node.inputs['Collection'].default_value = bpy.context.scene.collection
                elif case == 'collapsed_offset': second['offset'] = 1e-15
                elif case == 'collapsed_master': second['scale'] = [1e-35]*3
                elif case == 'collection_instance':
                    isolated = bpy.data.collections.new('InstancedInputs')
                    bpy.context.scene.collection.children.link(isolated)
                    isolated.objects.link(panel)
                    instance = bpy.data.objects.new('LeakingInstance', None)
                    instance.instance_type = 'COLLECTION'
                    instance.instance_collection = isolated
                    bpy.context.scene.collection.objects.link(instance)
                elif case == 'object_dependency':
                    dependent = master.modifiers.new('ObjectDependent', 'BOOLEAN')
                    dependent.object = panel
                elif case == 'excessive_subdivision':
                    subdiv = panel.modifiers.new('Huge', 'SUBSURF')
                    subdiv.levels = 6
                elif case == 'output_budget':
                    config['placements'] = []
                    # 9600 vertex master * 256 exceeds the independent-copy budget.
                    mesh = bpy.data.meshes.new('BudgetMesh')
                    mesh.from_pydata([(i*.01, j*.01, .3) for i in range(120) for j in range(80)], [],
                        [(i*80+j, (i+1)*80+j, (i+1)*80+j+1, i*80+j+1)
                         for i in range(119) for j in range(79)])
                    master.data = mesh
                    for i in range(256):
                        row = copy.deepcopy(second)
                        row.update(feature_id=f'f{i}', object_name=f'Bolt{i}')
                        config['placements'].append(row)
                before = (set(bpy.data.objects.keys()), set(bpy.data.meshes.keys()), set(bpy.data.collections.keys()))
                with self.assertRaises(ValueError):
                    self.tool.place(config)
                after = (set(bpy.data.objects.keys()), set(bpy.data.meshes.keys()), set(bpy.data.collections.keys()))
                self.assertEqual(before, after)

    def test_curved_faceted_world_normal_and_preservation_report(self):
        config, _, _, _ = self.scene()
        old_panel = bpy.data.objects['Panel']
        bpy.data.objects.remove(old_panel, do_unlink=True)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=2)
        target = bpy.context.object
        target.name = 'Panel'
        target.location = (1, 2, -1)
        target.rotation_euler = (.2, .3, -.4)
        target.scale = (1.4, .7, 1.1)
        bpy.context.view_layer.update()
        target.data.calc_loop_triangles()
        tri = target.data.loop_triangles[75]
        points = [target.matrix_world @ target.data.vertices[i].co for i in tri.vertices]
        hit = sum(points, Vector())/3
        normal = (points[1]-points[0]).cross(points[2]-points[0]).normalized()
        tangent = (points[1]-points[0]).normalized()
        config['placements'][0].update(
            ray={'origin': list(hit+normal), 'direction': list(-normal), 'max_distance': 2},
            tangent=list(tangent), offset=0, rotation_degrees=0)
        signature = ([tuple(v.co) for v in target.data.vertices], [list(r) for r in target.matrix_world])
        report = self.tool.place(config)
        row = report['placements'][0]
        self.assertLess((Vector(row['hit_position'])-hit).length, 2e-5)
        self.assertLess((Vector(row['hit_normal'])-normal).length, 2e-5)
        self.assertEqual(row['normal_method'], 'evaluated_world_triangle_winding')
        self.assertEqual(signature, ([tuple(v.co) for v in target.data.vertices], [list(r) for r in target.matrix_world]))
        for check in report['preservation']:
            self.assertTrue(check['unchanged'])
            self.assertEqual(check['before_sha256'], check['after_sha256'])
        self.assertEqual({check['object'] for check in report['preservation']}, {'Panel', 'BoltMaster'})

    def cli_fixture(self):
        config, _, _, _ = self.scene()
        self.source = self.root/'source.blend'
        self.output = self.root/'new.blend'
        self.report = self.root/'new.json'
        self.spec_file = self.root/'placements.json'
        self.spec_file.write_text(json.dumps(config))
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        self.source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        return config

    def run_cli(self):
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            code = self.tool.main(['--source', str(self.source), '--spec', str(self.spec_file),
                                  '--output', str(self.output), '--report', str(self.report)])
        self.last_error = errors.getvalue()
        return code

    def test_cli_save_reopen_preserves_source_and_slots_and_refuses_existing_publication(self):
        self.cli_fixture()
        before = {name: self.tool.state_digest(bpy.data.objects[name]) for name in ('Panel', 'BoltMaster')}
        self.assertEqual(self.run_cli(), 0, self.last_error)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash)
        record = json.loads(self.report.read_text())
        self.assertEqual(record['status'], 'placed')
        self.assertEqual(record['lineage']['output_sha256'], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertFalse(bpy.context.preferences.filepaths.use_scripts_auto_execute)
        bpy.ops.wm.open_mainfile(filepath=str(self.output), use_scripts=False)
        self.assertEqual(before, {name: self.tool.state_digest(bpy.data.objects[name]) for name in before})
        placed = bpy.data.objects['Bolt01']
        self.assertEqual(placed.material_slots[0].link, 'OBJECT')
        self.assertEqual(placed.material_slots[0].material.name, 'ObjectMaterial')
        self.assertNotEqual(placed.data, bpy.data.objects['BoltMaster'].data)
        hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.output, self.report)]
        self.assertEqual(self.run_cli(), 2)
        self.assertIn('existing', self.last_error)
        self.assertEqual(hashes, [hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.output, self.report)])
        self.assertEqual(list(self.root.glob('*.blend1')), [])

    def test_cli_rejects_duplicate_json_and_invalid_schema_without_opening_source(self):
        self.cli_fixture()
        marker = bpy.data.objects.new('NotOpened', None)
        bpy.context.scene.collection.objects.link(marker)
        variants = [self.spec_file.read_text().replace('"offset": 0.01', '"offset": 0.01, "offset": 0.02'),
                    json.dumps(dict(spec(), placements=[])), '{"schema_version":NaN}']
        for raw in variants:
            self.spec_file.write_text(raw)
            self.assertEqual(self.run_cli(), 2)
            self.assertIn('NotOpened', bpy.data.objects)
            self.assertFalse(self.output.exists())
            self.assertFalse(self.report.exists())
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash)

    def test_cli_save_handler_races_are_exclusive_and_recheck_input_hashes(self):
        base = self.root
        for case in ('output_race', 'report_race', 'source_change', 'spec_change'):
            with self.subTest(case=case):
                bpy.ops.wm.read_factory_settings(use_empty=True)
                self.root = base/case
                self.root.mkdir()
                self.cli_fixture()
                @bpy.app.handlers.persistent
                def at_save(*unused):
                    if case == 'output_race': self.output.write_bytes(b'competitor output')
                    elif case == 'report_race': self.report.write_bytes(b'competitor report')
                    elif case == 'source_change': self.source.write_bytes(self.source.read_bytes()+b'changed')
                    elif case == 'spec_change': self.spec_file.write_text(self.spec_file.read_text()+' ')
                bpy.app.handlers.save_pre.append(at_save)
                try:
                    self.assertEqual(self.run_cli(), 2, self.last_error)
                    if case == 'output_race':
                        self.assertEqual(self.output.read_bytes(), b'competitor output')
                        self.assertFalse(self.report.exists())
                    elif case == 'report_race':
                        self.assertEqual(self.report.read_bytes(), b'competitor report')
                        self.assertFalse(self.output.exists())
                    else:
                        self.assertIn('changed', self.last_error)
                        self.assertFalse(self.output.exists())
                        self.assertFalse(self.report.exists())
                finally:
                    if at_save in bpy.app.handlers.save_pre:
                        bpy.app.handlers.save_pre.remove(at_save)
        self.root = base

    def test_cli_rejects_oversized_spec_before_open(self):
        self.cli_fixture()
        marker = bpy.data.objects.new('NotOpened', None)
        bpy.context.scene.collection.objects.link(marker)
        self.spec_file.write_text(' '*1048577)
        self.assertEqual(self.run_cli(), 2)
        self.assertIn('1048576', self.last_error)
        self.assertIn('NotOpened', bpy.data.objects)

    def test_cli_rejects_hardlink_alias_before_open(self):
        self.cli_fixture()
        marker = bpy.data.objects.new('NotOpened', None)
        bpy.context.scene.collection.objects.link(marker)
        self.spec_file.unlink()
        os.link(self.source, self.spec_file)
        self.assertEqual(self.run_cli(), 2)
        self.assertIn('hardlink', self.last_error)
        self.assertIn('NotOpened', bpy.data.objects)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.report.exists())

    def test_material_data_object_null_slots_and_multiple_copies_report_ownership(self):
        config, _, _, _ = self.scene()
        master = bpy.data.objects['BoltMaster']
        data_material = bpy.data.materials.new('SecondDataMaterial')
        master.data.materials.append(data_material)
        master.data.materials.append(data_material)
        master.material_slots[2].link = 'OBJECT'
        master.material_slots[2].material = None
        second = copy.deepcopy(config['placements'][0])
        second.update(feature_id='second', object_name='Bolt02')
        config['placements'].append(second)
        report = self.tool.place(config)
        for row in report['placements']:
            obj = bpy.data.objects[row['object']]
            self.assertEqual(row['material_slots'], [
                {'index': 0, 'link': 'OBJECT', 'material': 'ObjectMaterial'},
                {'index': 1, 'link': 'DATA', 'material': 'SecondDataMaterial'},
                {'index': 2, 'link': 'OBJECT', 'material': None}])
            self.assertFalse(row['mesh_shared'])
            self.assertTrue(row['material_datablocks_shared'])
            self.assertEqual([s.link for s in obj.material_slots], ['OBJECT', 'DATA', 'OBJECT'])
            self.assertIsNone(obj.material_slots[2].material)
            self.assertEqual(obj.data.materials[2].name, 'SecondDataMaterial')
        self.assertEqual(len({bpy.data.objects[n].data.as_pointer() for n in ('BoltMaster', 'Bolt01', 'Bolt02')}), 3)

    def test_validate_explicit_schema_rejects_empty_duplicate_nonfinite_collapsed(self):
        self.assertEqual(self.tool.validate(spec()), spec())
        bads = [None, {}, {'schema_version': 1, 'collection': 'x', 'master': {}, 'placements': []}]
        for path, values in [
            (('schema_version',), [True, 1.0, 2]),
            (('collection',), ['', None, 'x'*64]),
            (('master', 'normal_axis'), ['-Z', '+X', None]),
            (('master', 'attachment_origin'), [[0, float('inf'), 0], [0, 1e50, 0]]),
            (('placements',), [[], [spec()['placements'][0]]*257]),
            (('row', 'feature_id'), ['', None, 'x'*64]),
            (('row', 'target'), ['', True]),
            (('row', 'scale'), [[0, 1, 1], [1e-100, 1, 1], [True, 1, 1]]),
            (('row', 'offset'), [float('nan'), 1e-100, True]),
            (('row', 'tangent'), [[0, 0, 0], [1e-100, 0, 0], [1, 2]]),
            (('ray', 'direction'), [[0, 0, 0], [1e-100, 0, 0]]),
            (('ray', 'origin'), [[1e20, 0, 0]]),
            (('ray', 'max_distance'), [0, 1e-100, True]),
            (('support', 'kind'), ['detected', True]),
            (('support', 'description'), ['', None]),
        ]:
            for value in values:
                bad = spec()
                if path[0] == 'row':
                    part = bad['placements'][0]
                elif path[0] in ('ray', 'support'):
                    part = bad['placements'][0][path[0]]
                else:
                    part = bad
                    for key in path[:-1]:
                        part = part[key]
                part[path[-1]] = value
                bads.append(bad)
        for field in ('feature_id', 'object_name'):
            bad = spec()
            second = copy.deepcopy(bad['placements'][0])
            second.update(feature_id='other', object_name='OtherBolt')
            second[field] = bad['placements'][0][field]
            bad['placements'].append(second)
            bads.append(bad)
        bad = spec()
        bad['unexpected'] = 1
        bads.append(bad)
        for bad in bads:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.tool.validate(bad)


if __name__ == '__main__':
    unittest.main()
