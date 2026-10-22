"""Real Blender synthetic mechanics tests, not asset-quality evidence.

Run with official bpy Python: python -m unittest discover -s scripts
-p test_finish_asset.py -v . No installs, network, or user scenes are used.
"""
import copy
import contextlib
import io
import hashlib
import importlib.util
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

MODULE = Path(__file__).with_name('finish_asset.py')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def geometry(mesh):
    return ([tuple(v.co) for v in mesh.vertices], [tuple(e.vertices) for e in mesh.edges],
            [tuple(p.vertices) for p in mesh.polygons])


def uv_values(layer):
    return [tuple(item.uv) for item in layer.data]


@unittest.skipIf(bpy is None, 'requires real bpy')
class FinishTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), 'finishing helper has not been implemented')
        module = importlib.util.spec_from_file_location('finish_helper', MODULE)
        self.tool = importlib.util.module_from_spec(module)
        module.loader.exec_module(self.tool)
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.root = Path(self.tmp.name)
        self.source = self.root / 'synthetic-source.blend'
        self.output = self.root / 'synthetic-finished.blend'
        self.report = self.root / 'synthetic-report.json'
        self.spec_path = self.root / 'filled.json'
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.object
        obj.name = 'Cabinet'
        self.base_geometry = geometry(obj.data)
        keep = obj.data.uv_layers[0]
        keep.name = 'KeepUV'
        self.keep_uv = uv_values(keep)
        mat = bpy.data.materials.new('KeepMaterial')
        mat.diffuse_color = (.2, .3, .4, 1)
        obj.data.materials.append(mat)
        other = bpy.data.objects.new('Unselected', obj.data.copy())
        bpy.context.scene.collection.objects.link(other)
        other.location = (5, 0, 0)
        other.select_set(True)
        obj.select_set(False)
        bpy.context.view_layer.objects.active = other
        self.save_source()

    def tearDown(self):
        if hasattr(self, 'tmp'):
            self.tmp.cleanup()

    def save_source(self):
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        self.source_hash = sha(self.source)

    def config(self):
        return {'schema_version': 1, 'targets': [{'object': 'Cabinet', 'shared_mesh': 'reject',
            'uv': {'name': 'FinishUV', 'method': 'smart_project', 'angle_limit_degrees': 66,
                   'island_margin': .02},
            'bevel': {'name': 'EdgeFinish', 'width': .025, 'segments': 3,
                      'angle_degrees': 30, 'clamp_overlap': True},
            'shading': {'mode': 'smooth_by_angle', 'angle_degrees': 45}}]}

    def run_tool(self, config=...):
        self.spec_path.write_text(json.dumps(self.config() if config is ... else config))
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            result = self.tool.main(['--source', str(self.source), '--spec', str(self.spec_path),
                '--output', str(self.output), '--report', str(self.report)])
        self.last_error = errors.getvalue()
        return result

    def reopen(self):
        bpy.ops.wm.open_mainfile(filepath=str(self.output), use_scripts=False)

    def test_real_smart_uv_editable_bevel_snapshot_preserves_base_and_unselected(self):
        self.assertEqual(self.run_tool(), 0)
        self.assertEqual(sha(self.source), self.source_hash)
        report = json.loads(self.report.read_text())
        self.assertEqual(report['status'], 'finished')
        self.assertEqual(report['lineage']['output_sha256'], sha(self.output))
        row = report['targets'][0]
        self.assertTrue(row['base_geometry']['unchanged'])
        self.assertEqual(row['base_geometry']['before_sha256'], row['base_geometry']['after_sha256'])
        self.assertGreater(row['uv']['triangle_area_sum'], 0)
        self.assertEqual(row['uv']['zero_area_triangles'], 0)
        self.assertGreaterEqual(row['uv']['island_count'], 1)
        self.assertEqual(len(row['uv']['islands']), row['uv']['island_count'])
        self.assertFalse(row['uv']['overlap_tested'])
        self.assertFalse(row['uv']['texel_density_tested'])
        self.reopen()
        obj = bpy.data.objects['Cabinet']
        self.assertEqual(geometry(obj.data), self.base_geometry)
        self.assertEqual(uv_values(obj.data.uv_layers['KeepUV']), self.keep_uv)
        self.assertEqual(obj.data.uv_layers.active.name, 'KeepUV')
        points = uv_values(obj.data.uv_layers['FinishUV'])
        self.assertEqual(len(points), len(obj.data.loops))
        self.assertTrue(all(math.isfinite(v) for uv in points for v in uv))
        bounds = [[min(uv[i] for uv in points) for i in (0, 1)],
                  [max(uv[i] for uv in points) for i in (0, 1)]]
        self.assertEqual(row['uv']['bounds'], bounds)
        mod = obj.modifiers['EdgeFinish']
        self.assertEqual(mod.type, 'BEVEL')
        self.assertAlmostEqual(mod.width, .025)
        self.assertEqual(mod.segments, 3)
        self.assertAlmostEqual(mod.angle_limit, math.radians(30))
        self.assertEqual(mod.limit_method, 'ANGLE')
        self.assertTrue(mod.use_clamp_overlap)
        self.assertTrue(all(p.use_smooth for p in obj.data.polygons))
        self.assertTrue(all(e.use_edge_sharp for e in obj.data.edges))
        self.assertGreater(len(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data.polygons),
                           len(obj.data.polygons), 'bevel must affect evaluated geometry only')
        other = bpy.data.objects['Unselected']
        self.assertEqual(geometry(other.data), self.base_geometry)
        self.assertEqual([layer.name for layer in other.data.uv_layers], ['KeepUV'])
        self.assertEqual(len(other.modifiers), 0)
        self.assertEqual([s.material.name for s in obj.material_slots], ['KeepMaterial'])
        self.assertEqual([s.material.name for s in other.material_slots], ['KeepMaterial'])
        self.assertEqual(bpy.context.view_layer.objects.active, other)
        self.assertEqual([o.name for o in bpy.context.selected_objects], ['Unselected'])

    def test_strict_schema_rejects_malformed_values_before_source_open(self):
        marker = bpy.data.objects.new('NotOpened', None)
        bpy.context.scene.collection.objects.link(marker)
        variants = [None, [], {}, {'schema_version': 1, 'targets': []}]
        for field, values in (
                ('schema_version', [True, 1.0, 2]),
                ('targets', [None, True, {}, [self.config()['targets'][0]] * 129])):
            for value in values:
                bad = self.config()
                bad[field] = value
                variants.append(bad)
        for path, values in (
                (('object',), [None, '', True, 'x'*64, '\x00']),
                (('shared_mesh',), [None, True, 'copy', []]),
                (('uv', 'name'), [None, '', True, 'é'*32]),
                (('uv', 'method'), [None, True, 'unwrap', {}]),
                (('uv', 'angle_limit_degrees'), [None, True, 0, 90, '66', float('nan'), float('inf'), 10**400]),
                (('uv', 'island_margin'), [None, True, -.001, .101, float('nan')]),
                (('bevel', 'name'), [None, '', '\x00']),
                (('bevel', 'width'), [None, True, 0, -1, 1e-100, 1e7, float('nan'), float('inf'), 10**400]),
                (('bevel', 'segments'), [None, True, 3.0, 0, 33]),
                (('bevel', 'angle_degrees'), [None, True, -1, 181, float('nan')]),
                (('bevel', 'clamp_overlap'), [None, 0, 1, 'true']),
                (('shading', 'mode'), [None, True, 'auto', 'preserve']),
                (('shading', 'angle_degrees'), [None, True, 0, 181, float('inf')])):
            for value in values:
                bad = self.config()
                part = bad['targets'][0]
                for key in path[:-1]:
                    part = part[key]
                part[path[-1]] = value
                variants.append(bad)
        for path in ((), ('targets',), ('uv',), ('bevel',), ('shading',)):
            bad = self.config()
            part = bad if not path else bad['targets'][0]
            if path and path[0] != 'targets':
                part = part[path[0]]
            part['unknown'] = 1
            variants.append(bad)
        bad = self.config()
        bad['targets'].append(copy.deepcopy(bad['targets'][0]))
        variants.append(bad)
        bad = self.config()
        bad['targets'][0].update(uv=None, bevel=None, shading=None)
        variants.append(bad)
        for bad in variants:
            with self.subTest(spec=repr(bad)[:150]):
                self.assertEqual(self.run_tool(bad), 2)
                self.assertIn('NotOpened', bpy.data.objects)
                self.assertFalse(self.output.exists())
                self.assertFalse(self.report.exists())
        self.assertEqual(sha(self.source), self.source_hash)

    def test_duplicate_json_key_rejects_before_source_open(self):
        raw = json.dumps(self.config()).replace('"segments": 3', '"segments": 3, "segments": 4')
        self.spec_path.write_text(raw)
        marker = bpy.data.objects.new('NotOpened', None)
        bpy.context.scene.collection.objects.link(marker)
        self.assertEqual(self.tool.main(['--source', str(self.source), '--spec', str(self.spec_path),
            '--output', str(self.output), '--report', str(self.report)]), 2)
        self.assertIn('NotOpened', bpy.data.objects)
        self.assertFalse(self.output.exists())

    def test_whole_scope_preflight_rejects_conflicts_and_unsupported_scene_state(self):
        for kind in ('uv_conflict', 'attribute_conflict', 'modifier_conflict', 'missing', 'nonmesh',
                     'scale', 'delta_scale', 'parent', 'constraint', 'animation', 'shape_keys',
                     'vertex_group', 'nodes', 'hidden', 'rigid_body', 'edit_mode'):
            bpy.ops.wm.open_mainfile(filepath=str(self.source), use_scripts=False)
            obj = bpy.data.objects['Cabinet']
            config = self.config()
            if kind == 'uv_conflict':
                obj.data.uv_layers.new(name='FinishUV')
            elif kind == 'attribute_conflict':
                obj.data.attributes.new('FinishUV', 'FLOAT', 'POINT')
            elif kind == 'modifier_conflict':
                obj.modifiers.new('EdgeFinish', 'BEVEL')
            elif kind == 'missing':
                second = copy.deepcopy(config['targets'][0])
                second['object'] = 'NoSuchTarget'
                config['targets'].append(second)
            elif kind == 'nonmesh':
                config['targets'][0]['object'] = 'Empty'
                bpy.context.scene.collection.objects.link(bpy.data.objects.new('Empty', None))
            elif kind == 'scale':
                obj.scale = (2, 2, 2)
            elif kind == 'delta_scale':
                obj.delta_scale = (1, 2, 1)
            elif kind == 'parent':
                obj.parent = bpy.data.objects['Unselected']
            elif kind == 'constraint':
                obj.constraints.new('COPY_LOCATION')
            elif kind == 'animation':
                obj.keyframe_insert('location', frame=1)
            elif kind == 'shape_keys':
                obj.shape_key_add(name='Basis')
            elif kind == 'vertex_group':
                obj.vertex_groups.new(name='RigWeights')
            elif kind == 'nodes':
                obj.modifiers.new('ExistingNodes', 'NODES')
            elif kind == 'hidden':
                obj.hide_set(True)
            elif kind == 'rigid_body':
                bpy.context.view_layer.objects.active = obj
                obj.select_set(True)
                bpy.ops.rigidbody.object_add()
            elif kind == 'edit_mode':
                bpy.context.view_layer.objects.active = obj
                obj.select_set(True)
                bpy.ops.object.mode_set(mode='EDIT')
            before_uvs = [layer.name for layer in obj.data.uv_layers]
            before_mods = [mod.name for mod in obj.modifiers]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.tool.finish(config)
            self.assertEqual([layer.name for layer in obj.data.uv_layers], before_uvs)
            self.assertEqual([mod.name for mod in obj.modifiers], before_mods)
            self.assertEqual(sha(self.source), self.source_hash)
            if obj.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')

    def test_shared_mesh_policy_never_mutates_unselected_mesh_users(self):
        obj = bpy.data.objects['Cabinet']
        other = bpy.data.objects['Unselected']
        other.data = obj.data
        self.save_source()
        with self.assertRaisesRegex(ValueError, 'shared'):
            self.tool.finish(self.config())
        self.assertNotIn('FinishUV', obj.data.uv_layers)
        config = self.config()
        config['targets'][0]['shared_mesh'] = 'copy_for_target'
        self.assertEqual(self.run_tool(config), 0)
        self.reopen()
        obj, other = bpy.data.objects['Cabinet'], bpy.data.objects['Unselected']
        self.assertNotEqual(obj.data, other.data)
        self.assertIn('FinishUV', obj.data.uv_layers)
        self.assertNotIn('FinishUV', other.data.uv_layers)
        self.assertEqual(geometry(obj.data), self.base_geometry)
        self.assertEqual(geometry(other.data), self.base_geometry)
        self.assertEqual(uv_values(other.data.uv_layers['KeepUV']), self.keep_uv)
        self.assertEqual(len(other.modifiers), 0)
        self.assertTrue(json.loads(self.report.read_text())['targets'][0]['mesh_copied'])
        self.assertEqual(sha(self.source), self.source_hash)

    def test_source_spec_hardlink_alias_is_rejected_before_parsing_or_open(self):
        alias = self.root / 'hardlink.json'
        os.link(self.source, alias)
        self.spec_path = alias
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(self.tool.main(['--source', str(self.source), '--spec', str(alias),
                '--output', str(self.output), '--report', str(self.report)]), 2)
        self.assertIn('distinct', errors.getvalue())
        self.assertEqual(sha(self.source), self.source_hash)
        self.assertFalse(self.output.exists())

    def test_rejects_evaluated_dependency_users_outside_target_scope(self):
        other = bpy.data.objects['Unselected']
        dependent = other.modifiers.new('UnselectedBoolean', 'BOOLEAN')
        dependent.object = bpy.data.objects['Cabinet']
        with self.assertRaisesRegex(ValueError, 'depend'):
            self.tool.finish(self.config())
        self.assertNotIn('FinishUV', bpy.data.objects['Cabinet'].data.uv_layers)
        self.assertEqual(len(bpy.data.objects['Cabinet'].modifiers), 0)

    def test_collection_info_consumers_of_target_or_ancestor_refuse_before_edits(self):
        """Collection membership alone is safe; external collection evaluation is not."""
        for ancestor in (False, True):
            for consumed in (False, True):
                with self.subTest(ancestor=ancestor, consumed=consumed):
                    bpy.ops.wm.open_mainfile(filepath=str(self.source), use_scripts=False)
                    target = bpy.data.objects['Cabinet']
                    owner = bpy.data.collections.new('FinishScope')
                    parent = bpy.data.collections.new('FinishParent')
                    bpy.context.scene.collection.children.link(parent)
                    parent.children.link(owner)
                    for old in list(target.users_collection):
                        old.objects.unlink(target)
                    owner.objects.link(target)
                    other = bpy.data.objects['Unselected']
                    if consumed:
                        group = bpy.data.node_groups.new('ExternalCollectionConsumer', 'GeometryNodeTree')
                        group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
                        info = group.nodes.new('GeometryNodeCollectionInfo')
                        info.inputs['Collection'].default_value = parent if ancestor else owner
                        realize = group.nodes.new('GeometryNodeRealizeInstances')
                        output = group.nodes.new('NodeGroupOutput')
                        group.links.new(info.outputs['Instances'], realize.inputs['Geometry'])
                        group.links.new(realize.outputs['Geometry'], output.inputs['Geometry'])
                        other.modifiers.new('ExternalConsumer', 'NODES').node_group = group
                    bpy.context.view_layer.update()
                    depsgraph = bpy.context.evaluated_depsgraph_get()
                    before = geometry(other.evaluated_get(depsgraph).data)
                    if consumed:
                        self.assertEqual(len(before[2]), 6, 'consumer must actually evaluate the target cube')
                        with self.assertRaisesRegex(ValueError, 'depend'):
                            self.tool.finish(self.config())
                        self.assertNotIn('FinishUV', target.data.uv_layers)
                        self.assertEqual(len(target.modifiers), 0)
                        bpy.context.view_layer.update()
                        self.assertEqual(geometry(other.evaluated_get(bpy.context.evaluated_depsgraph_get()).data), before)
                    else:
                        self.tool.finish(self.config())
                        self.assertIn('FinishUV', target.data.uv_layers)

    def test_custom_normals_rejected_for_shading_without_edits(self):
        obj = bpy.data.objects['Cabinet']
        obj.data.normals_split_custom_set([(0, 0, 1)] * len(obj.data.loops))
        self.assertTrue(obj.data.has_custom_normals)
        with self.assertRaisesRegex(ValueError, 'custom normals'):
            self.tool.finish(self.config())
        self.assertNotIn('FinishUV', obj.data.uv_layers)

    def test_uv_projection_restores_hidden_selection_and_existing_uv_flags(self):
        obj = bpy.data.objects['Cabinet']
        mesh = obj.data
        second = mesh.uv_layers.new(name='LightmapKeep')
        second.active_render = True
        mesh.uv_layers.active_index = 0
        for index, item in enumerate(mesh.uv_layers['KeepUV'].data):
            item.pin_uv = index % 3 == 0
            if hasattr(item, 'select'):
                item.select = index % 2 == 0
                item.select_edge = index % 5 == 0
        for items in (mesh.vertices, mesh.edges, mesh.polygons):
            for index, item in enumerate(items):
                item.hide = index == 0
                item.select = index % 2 == 1
        flags = [[(item.hide, item.select) for item in items] for items in (mesh.vertices, mesh.edges, mesh.polygons)]
        uv_flags = [(item.pin_uv, getattr(item, 'select', None), getattr(item, 'select_edge', None)) for item in mesh.uv_layers['KeepUV'].data]
        second_values = uv_values(second)
        self.save_source()
        self.assertEqual(self.run_tool(), 0)
        self.reopen()
        mesh = bpy.data.objects['Cabinet'].data
        self.assertEqual([[(item.hide, item.select) for item in items] for items in (mesh.vertices, mesh.edges, mesh.polygons)], flags)
        self.assertEqual([(item.pin_uv, getattr(item, 'select', None), getattr(item, 'select_edge', None)) for item in mesh.uv_layers['KeepUV'].data], uv_flags)
        self.assertEqual(uv_values(mesh.uv_layers['LightmapKeep']), second_values)
        self.assertEqual(mesh.uv_layers.active.name, 'KeepUV')
        self.assertTrue(mesh.uv_layers['LightmapKeep'].active_render)
        self.assertFalse(mesh.uv_layers['FinishUV'].active_render)

    def test_uv_only_bevel_only_and_shading_only_operations_are_independent(self):
        for operation in ('uv', 'bevel', 'shading'):
            bpy.ops.wm.open_mainfile(filepath=str(self.source), use_scripts=False)
            config = self.config()
            row = config['targets'][0]
            for field in ('uv', 'bevel', 'shading'):
                if field != operation:
                    row[field] = None
            result = self.tool.finish(config)['targets'][0]
            obj = bpy.data.objects['Cabinet']
            self.assertEqual(geometry(obj.data), self.base_geometry)
            self.assertEqual('FinishUV' in obj.data.uv_layers, operation == 'uv')
            self.assertEqual('EdgeFinish' in obj.modifiers, operation == 'bevel')
            self.assertEqual(uv_values(obj.data.uv_layers['KeepUV']), self.keep_uv)
            self.assertEqual(result['uv'] is not None, operation == 'uv')

    def test_flat_smooth_and_angle_shading_have_bounded_explicit_effects(self):
        for shading in ({'mode': 'flat'}, {'mode': 'smooth'},
                        {'mode': 'smooth_by_angle', 'angle_degrees': 120}):
            bpy.ops.wm.open_mainfile(filepath=str(self.source), use_scripts=False)
            obj = bpy.data.objects['Cabinet']
            for face in obj.data.polygons:
                face.use_smooth = True
            for edge in obj.data.edges:
                edge.use_edge_sharp = True
            config = self.config()
            config['targets'][0].update(uv=None, bevel=None, shading=shading)
            self.tool.finish(config)
            self.assertTrue(all(face.use_smooth == (shading['mode'] != 'flat') for face in obj.data.polygons))
            self.assertTrue(all(edge.use_edge_sharp == (shading['mode'] != 'smooth_by_angle') for edge in obj.data.edges))

    def test_existing_modifiers_and_material_properties_are_preserved(self):
        obj = bpy.data.objects['Cabinet']
        keep = obj.modifiers.new('KeepModifier', 'BEVEL')
        keep.width = .004
        keep.segments = 2
        self.save_source()
        self.assertEqual(self.run_tool(), 0)
        self.reopen()
        obj = bpy.data.objects['Cabinet']
        self.assertEqual([mod.name for mod in obj.modifiers], ['KeepModifier', 'EdgeFinish'])
        self.assertAlmostEqual(obj.modifiers['KeepModifier'].width, .004)
        self.assertEqual(obj.modifiers['KeepModifier'].segments, 2)
        self.assertEqual(tuple(round(v, 3) for v in bpy.data.materials['KeepMaterial'].diffuse_color), (.2, .3, .4, 1))

    def test_uv_report_rejects_empty_zero_area_and_nonfinite_coordinates(self):
        mesh = bpy.data.objects['Cabinet'].data
        layer = mesh.uv_layers['KeepUV']
        for item in layer.data:
            item.uv = (0, 0)
        with self.assertRaisesRegex(ValueError, 'usable UV area'):
            self.tool.uv_report(mesh, layer)
        layer.data[0].uv = (float('nan'), 0)
        with self.assertRaisesRegex(ValueError, 'nonfinite'):
            self.tool.uv_report(mesh, layer)
        empty = bpy.data.meshes.new('EmptyMesh')
        empty_layer = empty.uv_layers.new(name='EmptyUV')
        with self.assertRaisesRegex(ValueError, 'empty'):
            self.tool.uv_report(empty, empty_layer)

    def test_island_reporting_is_bounded_and_does_not_certify_overlapping_uvs(self):
        mesh = bpy.data.meshes.new('SyntheticOverlappingUVs')
        vertices, faces = [], []
        for index in range(300):
            start = len(vertices)
            vertices.extend([(index*2, 0, 0), (index*2+1, 0, 0), (index*2, 1, 0)])
            faces.append((start, start+1, start+2))
        mesh.from_pydata(vertices, [], faces)
        layer = mesh.uv_layers.new(name='OverlappingUV')
        for index, item in enumerate(layer.data):
            item.uv = [(0, 0), (1, 0), (0, 1)][index % 3]
        report = self.tool.uv_report(mesh, layer)
        self.assertEqual(report['island_count'], 300)
        self.assertEqual(len(report['islands']), 256)
        self.assertEqual(report['islands_omitted'], 44)
        self.assertEqual(report['bounds'], [[0, 0], [1, 1]])
        self.assertAlmostEqual(report['triangle_area_sum'], 150)
        self.assertFalse(report['overlap_tested'])
        self.assertFalse(report['texel_density_tested'])

    def test_cli_help_and_blender_style_runpy_work_from_unrelated_cwd(self):
        for launch in ([sys.executable, str(MODULE), '--help'],
                       [sys.executable, '-c', 'import runpy,sys; sys.argv='+repr(['blender', '--background', '--python', str(MODULE), '--', '--help'])+'; runpy.run_path('+repr(str(MODULE))+',run_name="__main__")']):
            result = subprocess.run(launch, cwd=self.root, capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('--source', result.stdout)
            self.assertIn('--report', result.stdout)
        self.spec_path.write_text(json.dumps(self.config()))
        args = ['blender', '--background', '--disable-autoexec', '--python', str(MODULE), '--',
            '--source', str(self.source), '--spec', str(self.spec_path), '--output', str(self.output), '--report', str(self.report)]
        launch = 'import runpy,sys; sys.argv='+repr(args)+'; runpy.run_path('+repr(str(MODULE))+',run_name="__main__")'
        result = subprocess.run([sys.executable, '-c', launch], cwd=self.root, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(sha(self.source), self.source_hash)
        self.reopen()
        self.assertIn('FinishUV', bpy.data.objects['Cabinet'].data.uv_layers)
        self.assertEqual(json.loads(self.report.read_text())['lineage']['output_sha256'], sha(self.output))

    def test_linked_overridden_and_ambiguous_named_targets_reject_without_edits(self):
        library = self.root / 'synthetic-library.blend'
        bpy.data.libraries.write(str(library), {bpy.data.objects['Cabinet']})
        for kind in ('linked', 'override', 'ambiguous'):
            bpy.ops.wm.open_mainfile(filepath=str(self.source), use_scripts=False)
            if kind != 'ambiguous':
                bpy.data.objects.remove(bpy.data.objects['Cabinet'], do_unlink=True)
            with bpy.data.libraries.load(str(library), link=True) as (_, data):
                data.objects = ['Cabinet']
            linked = data.objects[0]
            bpy.context.scene.collection.objects.link(linked)
            config = self.config()
            if kind == 'override':
                override = linked.override_create(remap_local_usages=True)
                self.assertIsNotNone(override.override_library)
                override.name = 'CabinetOverride'
                config['targets'][0]['object'] = override.name
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.tool.finish(config)
            self.assertTrue(all('FinishUV' not in obj.data.uv_layers for obj in bpy.data.objects if obj.type == 'MESH'))
        self.assertEqual(sha(self.source), self.source_hash)

    def test_existing_targets_symlinks_and_output_aliases_are_never_overwritten(self):
        for path in (self.output, self.report):
            path.write_bytes(b'keep exactly')
            self.assertEqual(self.run_tool(), 2)
            self.assertEqual(path.read_bytes(), b'keep exactly')
            path.unlink()
        self.output.symlink_to(self.root / 'absent.blend')
        self.assertEqual(self.run_tool(), 2)
        self.assertTrue(self.output.is_symlink())
        self.output.unlink()
        self.output.symlink_to(self.source)
        self.assertEqual(self.run_tool(), 2)
        self.output.unlink()
        self.spec_path.write_text(json.dumps(self.config()))
        self.assertEqual(self.tool.main(['--source', str(self.source), '--spec', str(self.spec_path),
            '--output', str(self.source), '--report', str(self.report)]), 2)
        self.assertEqual(self.tool.main(['--source', str(self.source), '--spec', str(self.spec_path),
            '--output', str(self.output), '--report', str(self.output)]), 2)
        self.assertEqual(sha(self.source), self.source_hash)
        self.assertFalse(self.report.exists())

    def test_publication_races_do_not_overwrite_or_publish_partial_pairs(self):
        for destination in (self.output, self.report):
            @bpy.app.handlers.persistent
            def create_raced_target(*_):
                destination.write_bytes(b'race winner')
            bpy.app.handlers.load_post.append(create_raced_target)
            try:
                self.assertEqual(self.run_tool(), 2)
                self.assertEqual(destination.read_bytes(), b'race winner')
                other = self.report if destination == self.output else self.output
                self.assertFalse(other.exists())
            finally:
                bpy.app.handlers.load_post.remove(create_raced_target)
                if destination.exists():
                    destination.unlink()
        self.assertEqual(sha(self.source), self.source_hash)

    def test_changed_source_or_spec_refuses_publication(self):
        for name in ('source', 'spec_path'):
            @bpy.app.handlers.persistent
            def alter_after_open(*_):
                with getattr(self, name).open('ab') as stream:
                    stream.write(b'\n')
            bpy.app.handlers.load_post.append(alter_after_open)
            try:
                self.assertEqual(self.run_tool(), 2)
                self.assertFalse(self.output.exists())
                self.assertFalse(self.report.exists())
            finally:
                bpy.app.handlers.load_post.remove(alter_after_open)

    def test_relocated_snapshot_resolves_existing_relative_dependencies(self):
        from PIL import Image
        texture = self.root / 'synthetic-image.png'
        Image.new('RGB', (2, 2), (120, 120, 120)).save(texture)
        image = bpy.data.images.load(str(texture), check_existing=False)
        image.name = 'KeepImage'
        image.filepath = '//' + texture.name
        image.use_fake_user = True
        self.save_source()
        relocated = self.root / 'relocated'
        relocated.mkdir()
        self.output = relocated / 'finished.blend'
        self.assertEqual(self.run_tool(), 0)
        self.reopen()
        self.assertEqual(Path(bpy.data.images['KeepImage'].filepath), texture)
        self.assertEqual(list(bpy.data.images['KeepImage'].size), [2, 2])
        self.assertEqual(sha(self.source), self.source_hash)
        bpy.ops.wm.open_mainfile(filepath=str(self.source), use_scripts=False)
        self.assertEqual(bpy.data.images['KeepImage'].filepath, '//' + texture.name)

    def test_finished_snapshot_feeds_explicit_pbr_uv_and_registered_cpu_render(self):
        """Synthetic mechanics chain; not photographic registration or visual approval."""
        from PIL import Image
        from mathutils import Vector
        import build_pbr
        import render_registered
        collection = bpy.data.collections.new('SyntheticProduct')
        bpy.context.scene.collection.children.link(collection)
        obj = bpy.data.objects['Cabinet']
        collection.objects.link(obj)
        bpy.context.scene.collection.objects.unlink(obj)
        scene = bpy.context.scene
        camera = bpy.data.objects.new('SyntheticCamera', bpy.data.cameras.new('SyntheticCamera'))
        scene.collection.objects.link(camera)
        camera.location = (3, -4, 3)
        camera.rotation_euler = (-camera.location).to_track_quat('-Z', 'Y').to_euler()
        camera.data.type = 'ORTHO'
        camera.data.ortho_scale = 3.6
        scene.camera = camera
        sun = bpy.data.objects.new('SyntheticSun', bpy.data.lights.new('SyntheticSun', 'SUN'))
        scene.collection.objects.link(sun)
        sun.rotation_euler = Vector((1, -2, 3)).to_track_quat('Z', 'Y').to_euler()
        sun.data.energy = 2
        scene.render.resolution_x = scene.render.resolution_y = 32
        scene.render.resolution_percentage = 100
        self.save_source()
        self.assertEqual(self.run_tool(), 0)
        finished_hash = sha(self.output)
        texture = self.root / 'synthetic-red.png'
        Image.new('RGB', (4, 4), (220, 35, 20)).save(texture)
        pbr_spec = self.root / 'pbr.json'
        pbr_spec.write_text(json.dumps({'schema_version': 1, 'materials': [{'name': 'SyntheticRed',
            'base_color': {'path': texture.name, 'sha256': sha(texture), 'size': [4, 4]},
            'roughness': .65, 'metallic': 0, 'uv_map': 'FinishUV'}],
            'bindings': [{'object': 'Cabinet', 'material': 'SyntheticRed', 'slot': 0}]}))
        shaded = self.root / 'synthetic-shaded.blend'
        self.assertEqual(build_pbr.main(['--source', str(self.output), '--spec', str(pbr_spec),
            '--output', str(shaded), '--report', str(self.root / 'pbr-report.json')]), 0)
        bpy.ops.wm.open_mainfile(filepath=str(shaded), use_scripts=False)
        nodes = bpy.data.materials['SyntheticRed'].node_tree.nodes
        self.assertEqual(next(n for n in nodes if n.type == 'UVMAP').uv_map, 'FinishUV')
        render_spec = self.root / 'registered.json'
        render_spec.write_text(json.dumps({'schema_version': 1, 'camera': 'SyntheticCamera',
            'collection': 'SyntheticProduct', 'resolution': [32, 32], 'samples': 2,
            'registration_note': 'Synthetic fixed camera mechanics fixture; no photo registration or artistic approval.'}))
        rendered = self.root / 'synthetic-registered-render'
        self.assertEqual(render_registered.main(['--source', str(shaded), '--spec', str(render_spec),
            '--output', str(rendered)]), 0)
        manifest = json.loads((rendered / 'render-manifest.json').read_text())
        self.assertEqual(manifest['mesh_instances'], 1)
        self.assertEqual(manifest['source']['sha256'], sha(shaded))
        self.assertEqual(manifest['render_engine'], 'CYCLES CPU')
        detail = Image.open(rendered / 'detail.png').convert('RGB')
        r, g, b = detail.getpixel((16, 16))
        self.assertGreater(r, g*2)
        self.assertGreater(r, b*2)
        self.assertGreater(Image.open(rendered / 'mask.png').convert('L').getextrema()[1], 0)
        self.assertEqual(sha(self.source), self.source_hash)
        self.assertEqual(sha(self.output), finished_hash)
        print('SYNTHETIC_FINISH_PBR_REGISTERED_RENDER=' + json.dumps({'center_rgb': [r, g, b],
            'mesh_instances': manifest['mesh_instances'], 'size': list(detail.size), 'engine': manifest['render_engine']}))

    def test_report_records_actual_editable_bevel_settings_and_uv_controls(self):
        config = self.config()
        config['targets'][0]['bevel'].update(width=.03123456789, clamp_overlap=False, segments=5)
        self.assertEqual(self.run_tool(config), 0)
        report = json.loads(self.report.read_text())['targets'][0]
        self.reopen()
        mod = bpy.data.objects['Cabinet'].modifiers['EdgeFinish']
        self.assertEqual(report['bevel']['width'], mod.width)
        self.assertEqual(report['bevel']['segments'], mod.segments)
        self.assertEqual(report['bevel']['angle_degrees'], math.degrees(mod.angle_limit))
        self.assertEqual(report['bevel']['clamp_overlap'], mod.use_clamp_overlap)
        self.assertEqual(report['bevel']['offset_type'], 'OFFSET')
        self.assertEqual(report['bevel']['applied'], False)
        self.assertEqual(report['uv']['method'], 'smart_project')
        self.assertEqual(report['uv']['controls']['island_margin'], .02)
        self.assertEqual(report['uv']['controls']['margin_method'], 'SCALED')

    def test_nonmanifold_uv_edge_fan_is_rejected_before_editing(self):
        mesh = bpy.data.objects['Cabinet'].data
        mesh.clear_geometry()
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (0, -1, 0)], [],
                         [(0, 1, 2), (1, 0, 3), (0, 1, 4)])
        before = geometry(mesh)
        with self.assertRaisesRegex(ValueError, 'nonmanifold'):
            self.tool.finish(self.config())
        self.assertEqual(geometry(mesh), before)
        self.assertNotIn('FinishUV', mesh.uv_layers)

    def test_distributed_template_is_deliberately_unfilled_and_rejected(self):
        template = MODULE.parent.parent / 'assets' / 'finish-spec.json'
        self.assertTrue(template.is_file(), 'unfilled finishing template has not been provided')
        with self.assertRaises(ValueError):
            self.tool.validate(json.loads(template.read_text()))

    def test_loose_vertex_count_cannot_bypass_mesh_execution_bounds(self):
        mesh = bpy.data.objects['Cabinet'].data
        mesh.vertices.add(400000)
        with self.assertRaisesRegex(ValueError, 'vertices'):
            self.tool.finish(self.config())
        self.assertNotIn('FinishUV', mesh.uv_layers)

    def test_new_projection_does_not_inherit_existing_uv_pins(self):
        for item in bpy.data.objects['Cabinet'].data.uv_layers['KeepUV'].data:
            item.pin_uv = True
        self.save_source()
        self.assertEqual(self.run_tool(), 0)
        self.reopen()
        layers = bpy.data.objects['Cabinet'].data.uv_layers
        self.assertTrue(all(item.pin_uv for item in layers['KeepUV'].data))
        self.assertFalse(any(item.pin_uv for item in layers['FinishUV'].data))

    def test_target_without_any_uv_gets_new_active_usable_projection(self):
        mesh = bpy.data.objects['Cabinet'].data
        mesh.uv_layers.remove(mesh.uv_layers['KeepUV'])
        self.save_source()
        self.assertEqual(self.run_tool(), 0)
        self.reopen()
        mesh = bpy.data.objects['Cabinet'].data
        self.assertEqual([layer.name for layer in mesh.uv_layers], ['FinishUV'])
        self.assertEqual(mesh.uv_layers.active.name, 'FinishUV')
        self.assertTrue(mesh.uv_layers.active.active_render)
        report = json.loads(self.report.read_text())['targets'][0]['uv']
        self.assertGreater(report['triangle_area_sum'], 1e-12)

    def test_uv_only_preserves_existing_custom_corner_normals(self):
        mesh = bpy.data.objects['Cabinet'].data
        mesh.normals_split_custom_set([(0, 0, 1)] * len(mesh.loops))
        normals = [tuple(item.vector) for item in mesh.corner_normals]
        config = self.config()
        config['targets'][0].update(bevel=None, shading=None)
        self.tool.finish(config)
        self.assertTrue(mesh.has_custom_normals)
        self.assertEqual([tuple(item.vector) for item in mesh.corner_normals], normals)

    def test_collection_instance_dependency_rejects_without_edits(self):
        collection = bpy.data.collections.new('InstancedSource')
        bpy.context.scene.collection.children.link(collection)
        collection.objects.link(bpy.data.objects['Cabinet'])
        instance = bpy.data.objects.new('UnselectedInstance', None)
        bpy.context.scene.collection.objects.link(instance)
        instance.instance_type = 'COLLECTION'
        instance.instance_collection = collection
        with self.assertRaisesRegex(ValueError, 'depend'):
            self.tool.finish(self.config())
        self.assertNotIn('FinishUV', bpy.data.objects['Cabinet'].data.uv_layers)

    def test_spec_changed_during_validation_is_not_misattributed_in_lineage(self):
        """Inject a deterministic real file race, without mocking Blender or validation."""
        original = self.tool.validate
        calls = 0
        def racing_validate(spec):
            nonlocal calls
            result = original(spec)
            calls += 1
            if calls == 1:
                with self.spec_path.open('a') as stream:
                    stream.write('\n')
            return result
        self.tool.validate = racing_validate
        self.assertEqual(self.run_tool(), 2)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.report.exists())
        self.assertEqual(sha(self.source), self.source_hash)


if __name__ == '__main__':
    unittest.main()
