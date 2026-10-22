"""Real bpy construction mechanics tests; no visual/engineering certification."""
import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import tempfile
import unittest

import bpy
import bmesh

MODULE = Path(__file__).with_name('build_components.py')


def lathe():
    return {'kind': 'lathe', 'object_name': 'Shade', 'mesh_name': 'ShadeMesh',
            'origin': [0, 0, 0], 'segments': 32, 'mode': 'open_surface',
            'profile': [[1, 0], [.5, 1]], 'smooth_angle_degrees': 35}


def tube():
    return {'kind': 'tube', 'object_name': 'Handle', 'mesh_name': 'HandleMesh',
            'origin': [0, 0, 0], 'segments': 16, 'radius': .05,
            'path': [[0, 0, 0], [0, 0, .5], [.1, .05, 1], [.3, .2, 1.5]],
            'frame_up': [1, 0, 0], 'caps': 'flat'}


def spec(*rows):
    return {'schema_version': 1, 'collection': 'BuiltComponents', 'components': list(rows or [lathe()])}


def inspect(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    result = {'boundary': sum(e.is_boundary for e in bm.edges),
              'manifold': all(e.is_manifold for e in bm.edges),
              'volume': bm.calc_volume(signed=True),
              'consistent': all(e.is_contiguous for e in bm.edges if e.is_manifold)}
    bm.free()
    mesh.calc_loop_triangles()
    uv = mesh.uv_layers['ComponentUV']
    areas = []
    for tri in mesh.loop_triangles:
        a, b, c = [uv.data[i].uv for i in tri.loops]
        areas.append(abs((b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x))/2)
    result['uv_areas'] = areas
    return result


class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), 'component construction has not been implemented')
        definition = importlib.util.spec_from_file_location('component_builders', MODULE)
        self.tool = importlib.util.module_from_spec(definition)
        definition.loader.exec_module(self.tool)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ['TMPDIR'])
        self.root = Path(self.tmp.name)

    def tearDown(self):
        if hasattr(self, 'tmp'):
            self.tmp.cleanup()

    def test_curved_sides_use_smooth_shading_while_flat_tube_caps_stay_flat(self):
        self.tool.build(spec(lathe(),tube()))
        self.assertTrue(all(p.use_smooth for p in bpy.data.objects['Shade'].data.polygons))
        mesh=bpy.data.objects['Handle'].data
        side_count=(len(tube()['path'])-1)*tube()['segments']
        self.assertTrue(all(p.use_smooth for p in mesh.polygons[:side_count]))
        self.assertTrue(all(not p.use_smooth for p in mesh.polygons[side_count:]))
    def test_open_revolved_surface_has_intentional_boundary_outward_normals_and_uv_seam(self):
        config = spec()
        before = copy.deepcopy(config)
        report = self.tool.build(config)
        self.assertEqual(config, before)
        mesh = bpy.data.objects['Shade'].data
        measured = inspect(mesh)
        self.assertEqual(measured['boundary'], 64)
        self.assertTrue(measured['consistent'])
        self.assertGreater(min(measured['uv_areas']), 1e-6)
        self.assertTrue(all(p.normal.x*p.center.x + p.normal.y*p.center.y > 0 for p in mesh.polygons))
        self.assertEqual(sum(e.use_seam for e in mesh.edges), 65)
        values = [d.uv.x for d in mesh.uv_layers['ComponentUV'].data]
        self.assertEqual((min(values), max(values)), (0, 1))
        self.assertFalse(report['components'][0]['closed'])
        self.assertFalse(report['self_intersection_tested'])
        self.assertEqual(len(bpy.data.collections['BuiltComponents'].objects), 1)

    def test_strict_schema_and_workloads_are_rejected_without_scene_or_input_changes(self):
        self.assertTrue(callable(getattr(self.tool, 'validate', None)), 'strict validation is missing')
        cases = [None, [], {}, spec(*[lathe()]*33)]
        for field, values in [('schema_version', [True, 1.0, 2]), ('collection', ['', 'x'*64, '\x00', True]),
                              ('components', [[], {}, None])]:
            for value in values:
                config = spec()
                config[field] = value
                cases.append(config)
        for field, values in [('kind', ['loft', None, True]), ('object_name', ['', 'é'*32, None]),
                              ('mesh_name', ['', '\x00', 1]), ('segments', [True, 7, 129, 32.0]),
                              ('mode', ['closed', None]), ('smooth_angle_degrees', [True, 0, 181, float('inf')]),
                              ('origin', [[0, 0], [True, 0, 0], [1e5, 0, 0], [float('nan'), 0, 0]]),
                              ('profile', [[], [[1, 0]], [[1, 0]]*513, [[True, 0], [1, 1]], [[1, 0, 0], [1, 1]],
                                           [[1e-7, 0], [1, 1]], [[1e5, 0], [1, 1]], [[1, 0], [1, 10**400]]])]:
            for value in values:
                row = lathe()
                row[field] = value
                cases.append(spec(row))
        for config in [spec(), spec()]:
            if config is not None:
                config['unexpected'] = True
            cases.append(config)
        for config in cases:
            with self.subTest(config=repr(config)[:150]):
                before = repr(config)
                with self.assertRaises(ValueError):
                    self.tool.build(config)
                self.assertEqual(repr(config), before)
                self.assertEqual(len(bpy.data.objects), 0)
                self.assertEqual(len(bpy.data.meshes), 0)
                self.assertEqual(len(bpy.data.collections), 0)
        good = spec()
        self.assertIs(self.tool.validate(good), good)

    def test_lathe_refuses_crossed_touching_clockwise_collapsed_or_unsupported_axis_profiles(self):
        cases = [lathe() for _ in range(9)]
        cases[0]['profile'] = [[1, 1], [.5, 0]]
        cases[1]['profile'] = [[1, 0], [.5, 0]]
        cases[2]['profile'] = [[0, 0], [.5, 1]]
        cases[3].update(mode='closed_solid', profile=[[1, 0], [2, 1], [1, 1], [2, 0]])
        cases[4].update(mode='closed_solid', profile=[[1, 0], [1, 1], [2, 1], [2, 0]])
        cases[5].update(mode='closed_solid', profile=[[0, 0], [1, 0], [0, 1], [1, 2]])
        cases[6].update(mode='closed_solid', profile=[[1, 0], [2, 0], [2, 1], [1, 0]])
        cases[7]['profile'] = [[1, 9999], [1, 9999.0002]]
        cases[8].update(mode='closed_solid', profile=[[1, 0], [2, 0]])
        for row in cases:
            with self.subTest(row=row):
                with self.assertRaises(ValueError):
                    self.tool.build(spec(row))
                self.assertEqual(len(bpy.data.objects), 0)
                self.assertEqual(len(bpy.data.meshes), 0)
                self.assertEqual(len(bpy.data.collections), 0)

    def test_flat_capped_tube_is_manifold_positive_volume_with_separate_cap_uvs(self):
        self.assertTrue(callable(getattr(self.tool, 'routed', None)), 'tube construction is missing')
        row = tube()
        row['path'] = [[0, 0, 0], [0, 0, 2]]
        self.tool.build(spec(row))
        mesh = bpy.data.objects['Handle'].data
        measured = inspect(mesh)
        self.assertTrue(measured['manifold'])
        self.assertTrue(measured['consistent'])
        self.assertAlmostEqual(measured['volume'], 16*math.sin(2*math.pi/16)*.05**2, places=8)
        self.assertGreater(min(measured['uv_areas']), 1e-6)
        self.assertEqual(sum(e.use_seam for e in mesh.edges), 33)
        self.assertTrue(all(not p.use_smooth for p in mesh.polygons[16:]))
        self.assertTrue(all(p.normal.z < -.99 for p in mesh.polygons[16:32]))
        self.assertTrue(all(p.normal.z > .99 for p in mesh.polygons[32:]))
        caps = [tuple(mesh.uv_layers['ComponentUV'].data[i].uv) for p in mesh.polygons[16:] for i in p.loop_indices]
        self.assertTrue(all(1.09 < u < 2.91 for u, v in caps))

    def test_curved_uncapped_tube_transports_frames_without_twist_flips_and_uses_arc_length_uvs(self):
        from mathutils import Vector
        row = tube()
        row['caps'] = 'none'
        row['path'] = [[0, 0, 0], [0, 0, .5], [1e-8, 0, 1], [.12, .08, 1.5], [.4, .3, 2]]
        config = spec(row)
        before = copy.deepcopy(config)
        report = self.tool.build(config)
        self.assertEqual(config, before)
        mesh = bpy.data.objects['Handle'].data
        measured = inspect(mesh)
        self.assertEqual(measured['boundary'], 32)
        self.assertGreater(min(measured['uv_areas']), 1e-6)
        path = [Vector(p) for p in row['path']]
        directions = [(b-a).normalized() for a, b in zip(path, path[1:])]
        tangents = [directions[0]]+[(a+b).normalized() for a, b in zip(directions, directions[1:])]+[directions[-1]]
        normals = []
        for i, point in enumerate(path):
            ring = mesh.vertices[i*16:(i+1)*16]
            for vertex in ring:
                delta = vertex.co-point
                self.assertAlmostEqual(delta.length, .05, places=6)
                self.assertAlmostEqual(delta.dot(tangents[i]), 0, places=6)
            normals.append((ring[0].co-point).normalized())
        for i in range(1, len(normals)):
            transported = tangents[i-1].rotation_difference(tangents[i]) @ normals[i-1]
            self.assertGreater(transported.dot(normals[i]), .99999)
        lengths = [math.dist(a, b) for a, b in zip(row['path'], row['path'][1:])]
        uv = mesh.uv_layers['ComponentUV']
        self.assertAlmostEqual(uv.data[2].uv.y, lengths[0]/sum(lengths), places=6)
        self.assertEqual(report['components'][0]['boundary_edges'], 32)
        self.assertEqual(report['components'][0]['frame_method'], 'parallel_transport_bisector_tangents')

    def test_tube_refuses_unsafe_sampling_radius_reversal_near_contact_and_bad_frames(self):
        cases = []
        for field, values in [('radius', [True, 0, -1, 1e-7, 1001, float('nan'), .3]),
                              ('caps', [True, 'round', None]), ('frame_up', [[0, 0, 0], [0, 0, 1], [1e-8, 0, 1], [1, 0]]),
                              ('path', [None, [], [[0, 0, 0]], [[0, 0, 0]]*513,
                                        [[0, 0, 0], [0, 0, 0]], [[0, 0, 0], [0, 0, 1], [0, 0, 0]],
                                        [[0, 0, 0], [0, 0, 1], [1, 0, 1]],
                                        [[0, 0, 0], [0, 0, 1], [float('inf'), 0, 2]],
                                        [[0, 0, 0], [0, 0, 1], [True, 0, 2]],
                                        [[0, 0, 9999], [0, 0, 9999.0002]]])]:
            for value in values:
                row = tube()
                row[field] = value
                cases.append(row)
        # Gentle near-closed circle: local bends are acceptable; distant arms are too close.
        row = tube()
        row.update(radius=.05, path=[[math.sin(i*math.pi/12), 0, 1-math.cos(i*math.pi/12)] for i in range(25)])
        cases.append(row)
        for row in cases:
            with self.subTest(row=repr(row)[:180]):
                with self.assertRaises(ValueError):
                    self.tool.build(spec(row))
                self.assertEqual(len(bpy.data.objects), 0)
                self.assertEqual(len(bpy.data.meshes), 0)
                self.assertEqual(len(bpy.data.collections), 0)

    def test_all_names_are_explicit_unique_new_and_preflighted_before_scene_changes(self):
        for namespace, value in [('objects', 'Shade'), ('meshes', 'ShadeMesh'), ('collections', 'BuiltComponents')]:
            bpy.ops.wm.read_factory_settings(use_empty=True)
            if namespace == 'objects':
                bpy.data.objects.new(value, None)
            else:
                getattr(bpy.data, namespace).new(value)
            before = {n: tuple(x.name for x in getattr(bpy.data, n)) for n in ('objects', 'meshes', 'collections')}
            with self.subTest(namespace=namespace), self.assertRaises(ValueError):
                self.tool.build(spec())
            self.assertEqual(before, {n: tuple(x.name for x in getattr(bpy.data, n)) for n in before})
        bpy.ops.wm.read_factory_settings(use_empty=True)
        for field in ('object_name', 'mesh_name'):
            second = tube()
            second[field] = lathe()[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.tool.build(spec(lathe(), second))
            self.assertEqual(len(bpy.data.objects), 0)
        row = tube()
        row['radius'] = 0
        with self.assertRaises(ValueError):
            self.tool.build(spec(lathe(), row))
        self.assertEqual(len(bpy.data.objects), 0)

    def test_float32_generated_collapse_rolls_back_whole_batch_without_touching_existing_scene(self):
        keep = bpy.data.objects.new('Existing', None)
        bpy.context.scene.collection.objects.link(keep)
        keep.select_set(True)
        bpy.context.view_layer.objects.active = keep
        for use_origin in (False, True):
            row = tube()
            row.update(radius=.0001, path=[[0, 0, 0], [0, 0, 1]])
            if use_origin:
                row['origin'] = [9999, 0, 0]
            else:
                row['path'] = [[9999, 0, 0], [9999, 0, 1]]
            with self.subTest(origin=use_origin), self.assertRaises(ValueError):
                self.tool.build(spec(lathe(), row))
            self.assertEqual([o.name for o in bpy.data.objects], ['Existing'])
            self.assertEqual(len(bpy.data.meshes), 0)
            self.assertEqual(len(bpy.data.collections), 0)
            self.assertEqual(bpy.context.view_layer.objects.active, keep)
            self.assertEqual([o.name for o in bpy.context.selected_objects], ['Existing'])

    def test_distinct_world_vertices_with_collapsed_cap_triangles_roll_back_whole_batch(self):
        keep = bpy.data.objects.new('Existing', None)
        bpy.context.scene.collection.objects.link(keep)
        keep.select_set(True)
        bpy.context.view_layer.objects.active = keep
        row = tube()
        row.update(radius=.0001, path=[[0, 0, 0], [1, 0, 0]],
                   frame_up=[0, 1, 2], origin=[0, 0, 9999])
        from mathutils import Matrix, Vector
        vertices = self.tool.routed(row)[0]
        world = [Matrix.Translation(row['origin']) @ Vector(p) for p in vertices]
        self.assertEqual(len({tuple(p) for p in world}), len(vertices))
        self.assertEqual({p.z for p in world}, {9999})
        config = spec(lathe(), row)
        before = copy.deepcopy(config)
        with self.assertRaisesRegex(ValueError, 'world.*triangle'):
            self.tool.build(config)
        self.assertEqual(config, before)
        self.assertEqual([o.name for o in bpy.data.objects], ['Existing'])
        self.assertEqual(len(bpy.data.meshes), 0)
        self.assertEqual(len(bpy.data.collections), 0)
        self.assertEqual(bpy.context.view_layer.objects.active, keep)
        self.assertEqual([o.name for o in bpy.context.selected_objects], ['Existing'])

    def test_nondegenerate_world_triangles_with_zero_closed_volume_roll_back_whole_batch(self):
        from mathutils import Matrix
        row = lathe()
        row.update(mode='closed_solid', segments=16, origin=[0, 0, 9999],
                   profile=[[.9, 0], [1, 0], [.99, .0002], [.89, .0002]])
        probe = bpy.data.meshes.new('PrecisionProbe')
        try:
            self.tool.fill_mesh(probe, row, self.tool.revolved(row))
            probe.calc_loop_triangles()
            world = [Matrix.Translation(row['origin']) @ v.co for v in probe.vertices]
            self.assertEqual(len({tuple(p) for p in world}), len(world))
            self.assertEqual({p.z for p in world}, {9999})
            areas = [(world[t.vertices[1]]-world[t.vertices[0]]).cross(
                world[t.vertices[2]]-world[t.vertices[0]]).length/2 for t in probe.loop_triangles]
            self.assertGreater(min(areas), 1e-16)
        finally:
            bpy.data.meshes.remove(probe)
        with self.assertRaisesRegex(ValueError, 'world.*volume'):
            self.tool.build(spec(tube(), row))
        self.assertEqual(len(bpy.data.meshes), 0)
        self.assertEqual(len(bpy.data.objects), 0)
        self.assertEqual(len(bpy.data.collections), 0)

    def test_mesh_evidence_measures_real_mesh_and_refuses_inverted_or_degenerate_uv_surfaces(self):
        report = self.tool.build(spec(tube()))
        self.assertIn('signed_volume', report['components'][0], 'measured mesh evidence is missing')
        mesh = bpy.data.objects['Handle'].data
        row = report['components'][0]
        measured = inspect(mesh)
        self.assertAlmostEqual(row['signed_volume'], measured['volume'], places=8)
        self.assertTrue(row['winding_consistent'])
        self.assertEqual(row['vertices'], len(mesh.vertices))
        self.assertEqual(row['faces'], len(mesh.polygons))
        self.assertGreater(row['minimum_triangle_area'], 0)
        self.assertAlmostEqual(row['minimum_uv_triangle_area'], min(measured['uv_areas']))
        bm = bmesh.new()
        bm.from_mesh(mesh)
        bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
        bm.to_mesh(mesh)
        bm.free()
        mesh.update()
        with self.assertRaises(ValueError):
            self.tool.mesh_evidence(mesh, True, 16)
        for item in mesh.uv_layers['ComponentUV'].data:
            item.uv = (0, 0)
        with self.assertRaises(ValueError):
            self.tool.mesh_evidence(mesh, False, 16)

    def test_cli_new_snapshot_reopens_real_meshes_preserving_source_and_relative_dependencies(self):
        self.assertTrue(callable(getattr(self.tool, 'main', None)), 'source-backed CLI is missing')
        for name in ('source', 'output', 'library', 'textures'):
            (self.root/name).mkdir()
        library = self.root/'library'/'linked.blend'
        bpy.ops.mesh.primitive_cube_add()
        bpy.context.object.name = 'LinkedPart'
        bpy.ops.wm.save_as_mainfile(filepath=str(library))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add()
        keep = bpy.context.object
        keep.name = 'KeepOriginal'
        baseline = [tuple(v.co) for v in keep.data.vertices]
        image = bpy.data.images.new('KeepImage', width=2, height=2)
        image.pixels[:] = [.2, .4, .6, 1]*4
        texture = self.root/'textures'/'keep.png'
        image.filepath_raw = str(texture)
        image.file_format = 'PNG'
        image.save()
        image.filepath = '//../textures/keep.png'
        mat = bpy.data.materials.new('KeepMaterial')

        mat.node_tree.nodes.new('ShaderNodeTexImage').image = image
        keep.data.materials.append(mat)
        with bpy.data.libraries.load(str(library), link=True) as (available, requested):
            requested.objects = ['LinkedPart']
        linked = requested.objects[0]
        bpy.context.scene.collection.objects.link(linked)
        linked.select_set(False)
        linked.library.filepath = '//../library/linked.blend'
        source = self.root/'source'/'original.blend'
        output = self.root/'output'/'built.blend'
        report_path = self.root/'output'/'report.json'
        spec_path = self.root/'filled.json'
        config = spec(lathe(), tube())
        spec_path.write_text(json.dumps(config))
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(source))
        hashes = {p: self.tool.digest(p) for p in (source, spec_path, texture, library)}
        code = self.tool.main(['--source', str(source), '--spec', str(spec_path), '--output', str(output), '--report', str(report_path)])
        self.assertEqual(code, 0)
        self.assertEqual(hashes, {p: self.tool.digest(p) for p in hashes})
        report = json.loads(report_path.read_text())
        self.assertEqual(report['command'], 'build-components')
        self.assertEqual(report['status'], 'built')
        self.assertEqual(report['lineage']['output_sha256'], self.tool.digest(output))
        self.assertEqual(report['lineage']['source_sha256'], hashes[source])
        self.assertEqual(report['lineage']['spec_sha256'], hashes[spec_path])
        self.assertEqual(report['input_checks'], ['validated', 'opened', 'built', 'before_publication'])
        bpy.ops.wm.open_mainfile(filepath=str(output), use_scripts=False)
        self.assertEqual([tuple(v.co) for v in bpy.data.objects['KeepOriginal'].data.vertices], baseline)
        self.assertEqual(bpy.context.view_layer.objects.active.name, 'KeepOriginal')
        self.assertEqual([o.name for o in bpy.context.selected_objects], ['KeepOriginal'])
        self.assertEqual(Path(bpy.path.abspath(bpy.data.images['KeepImage'].filepath)).resolve(), texture.resolve())
        self.assertEqual(Path(bpy.path.abspath(bpy.data.objects['LinkedPart'].library.filepath)).resolve(), library.resolve())
        self.assertTrue(texture.exists())
        self.assertEqual(inspect(bpy.data.objects['Shade'].data)['boundary'], 64)
        self.assertTrue(inspect(bpy.data.objects['Handle'].data)['manifold'])
        self.assertFalse(list(self.root.rglob('*.blend1')))

    def cli_fixture(self):
        source = self.root/'source.blend'
        spec_path = self.root/'spec.json'
        output = self.root/'output.blend'
        report = self.root/'report.json'
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(source))
        spec_path.write_text(json.dumps(spec()))
        args = ['--source', str(source), '--spec', str(spec_path), '--output', str(output), '--report', str(report)]
        return source, spec_path, output, report, args

    def test_duplicate_json_keys_and_oversized_specs_fail_before_opening_source(self):
        source, spec_path, output, report, args = self.cli_fixture()
        marker = bpy.data.objects.new('NotOpened', None)
        bpy.context.scene.collection.objects.link(marker)
        for payload in ('{"schema_version":1,'+json.dumps(spec())[1:],
                        json.dumps(spec()).replace('"segments": 32', '"segments": 16, "segments": 32'),
                        ' '*2_000_001):
            spec_path.write_text(payload)
            with contextlib.redirect_stderr(io.StringIO()):
                code = self.tool.main(args)
            self.assertEqual(code, 2)
            self.assertIn('NotOpened', bpy.data.objects)
            self.assertFalse(output.exists())
            self.assertFalse(report.exists())

    def test_input_changes_during_each_stage_refuse_publication_including_real_snapshot_save(self):
        source, spec_path, output, report, args = self.cli_fixture()
        original_source, original_spec = source.read_bytes(), spec_path.read_bytes()
        for stage in ('validate', 'open', 'build', 'save_snapshot'):
            bpy.ops.wm.read_factory_settings(use_empty=True)
            output.unlink(missing_ok=True)
            report.unlink(missing_ok=True)
            source.write_bytes(original_source)
            spec_path.write_bytes(original_spec)
            @bpy.app.handlers.persistent
            def mutate(*unused):
                spec_path.write_bytes(original_spec+b'\n')
            original = None
            if stage == 'open':
                bpy.app.handlers.load_post.append(mutate)
            else:
                original = getattr(self.tool, stage)
                def action(*arguments, _original=original, **kwargs):
                    result = _original(*arguments, **kwargs)
                    mutate()
                    return result
                setattr(self.tool, stage, action)
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    code = self.tool.main(args)
            finally:
                if stage == 'open':
                    if mutate in bpy.app.handlers.load_post:
                        bpy.app.handlers.load_post.remove(mutate)
                else:
                    setattr(self.tool, stage, original)
            with self.subTest(stage=stage):
                self.assertEqual(code, 2)
                self.assertFalse(output.exists())
                self.assertFalse(report.exists())
                self.assertEqual(source.read_bytes(), original_source)

    def test_edit_mode_source_is_refused_before_creating_any_data(self):
        bpy.ops.mesh.primitive_cube_add()
        keep = bpy.context.object
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            with self.assertRaises(ValueError):
                self.tool.build(spec())
            self.assertEqual(bpy.context.mode, 'EDIT_MESH')
            self.assertEqual([o.name for o in bpy.data.objects], [keep.name])
            self.assertEqual(len(bpy.data.collections), 0)
        finally:
            bpy.ops.object.mode_set(mode='OBJECT')

    def test_segment_distance_reject_filter_handles_nearly_parallel_interior_crossing(self):
        distance = self.tool.segment_distance([0, 0, 0], [10000, 0, 0], [0, .0002, 0], [10000, -.0002, 0])
        self.assertAlmostEqual(distance, 0, places=10)
        self.assertAlmostEqual(self.tool.segment_distance([0,0,0], [1,0,0], [.5,-1,2], [.5,1,2]), 2)
        self.assertAlmostEqual(self.tool.segment_distance([0,0,0], [1,0,0], [0,3,0], [1,3,0]), 3)
        self.assertAlmostEqual(self.tool.segment_distance([0,0,0], [1,0,0], [3,0,0], [4,0,0]), 2)

    def test_exclusive_cli_refuses_existing_paths_aliases_and_late_publication_races(self):
        source, spec_path, output, report, args = self.cli_fixture()
        original_hash = self.tool.digest(source)
        for target in (output, report):
            target.write_text('keep')
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(self.tool.main(args), 2)
            self.assertEqual(target.read_text(), 'keep')
            target.unlink()
        original_save = self.tool.save_snapshot
        for target in (output, report):
            bpy.ops.wm.read_factory_settings(use_empty=True)
            def race(*arguments, _target=target, **kwargs):
                result = original_save(*arguments, **kwargs)
                _target.write_text('race-owner')
                return result
            self.tool.save_snapshot = race
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(self.tool.main(args), 2)
            finally:
                self.tool.save_snapshot = original_save
            self.assertEqual(target.read_text(), 'race-owner')
            if target == report:
                self.assertFalse(output.exists())
            else:
                self.assertFalse(report.exists())
            target.unlink()
        alias = self.root/'hardlink.json'
        os.link(source, alias)
        aliased = args.copy()
        aliased[3] = str(alias)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.tool.main(aliased), 2)
        self.assertEqual(self.tool.digest(source), original_hash)

    def test_low_volume_mesh_rejection_cleans_up_all_temporary_meshes(self):
        row = lathe()
        row.update(segments=8, mode='closed_solid', profile=[[0,0], [.000101,0], [0,.000101]])
        with self.assertRaisesRegex(ValueError, 'volume'):
            self.tool.build(spec(tube(), row))
        self.assertEqual(len(bpy.data.meshes), 0)
        self.assertEqual(len(bpy.data.objects), 0)
        self.assertEqual(len(bpy.data.collections), 0)

    def test_combined_workload_limit_and_root_collection_name_are_not_bypassed(self):
        rows = []
        for i in range(4):
            row = lathe()
            row.update(object_name='Shape'+str(i), mesh_name='ShapeMesh'+str(i), segments=128,
                       profile=[[1,z] for z in range(512)])
            rows.append(row)
        with self.assertRaisesRegex(ValueError, 'workload'):
            self.tool.validate(spec(*rows))
        config = spec()
        config['collection'] = bpy.context.scene.collection.name
        with self.assertRaisesRegex(ValueError, 'collection'):
            self.tool.build(config)

    def test_shipped_template_is_explicitly_incomplete_not_a_silent_default_design(self):
        template = MODULE.parent.parent/'assets'/'component-builders.json'
        self.assertTrue(template.is_file(), 'component template is missing')
        config = json.loads(template.read_text())
        self.assertIsNone(config['collection'])
        self.assertEqual({row['kind'] for row in config['components']}, {'lathe', 'tube'})
        with self.assertRaises(ValueError):
            self.tool.validate(config)

    def test_report_declares_unmeasured_collision_engineering_and_texture_claims_false(self):
        report = self.tool.build(spec(lathe(), tube()))
        self.assertIs(report.get('collision_with_scene_tested'), False)
        self.assertIs(report.get('physical_engineering_validated'), False)
        self.assertIs(report.get('uv_overlap_tested'), False)
        self.assertIs(report.get('texel_density_tested'), False)
        self.assertIn('not', report.get('limitations', '').lower())
        self.assertEqual(report['components'][0]['uv_name'], 'ComponentUV')
        self.assertEqual(report['components'][1]['seam_edges'], sum(e.use_seam for e in bpy.data.objects['Handle'].data.edges))

    def test_malformed_utf8_and_excessively_nested_json_return_error_without_opening_source(self):
        source, spec_path, output, report, args = self.cli_fixture()
        marker = bpy.data.objects.new('NotOpened', None)
        bpy.context.scene.collection.objects.link(marker)
        for payload in (b'\xff', b'['*1500+b'0'+b']'*1500):
            spec_path.write_bytes(payload)
            with contextlib.redirect_stderr(io.StringIO()):
                code = self.tool.main(args)
            self.assertEqual(code, 2)
            self.assertIn('NotOpened', bpy.data.objects)
            self.assertFalse(output.exists())
            self.assertFalse(report.exists())

    def test_source_tampering_during_construction_refuses_snapshot(self):
        source, spec_path, output, report, args = self.cli_fixture()
        original = source.read_bytes()
        original_build = self.tool.build
        def tamper(config):
            result = original_build(config)
            source.write_bytes(original+b'external-change')
            return result
        self.tool.build = tamper
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(self.tool.main(args), 2)
        finally:
            self.tool.build = original_build
        self.assertFalse(output.exists())
        self.assertFalse(report.exists())

    def test_axis_terminated_solid_has_single_poles_nonzero_uv_triangles_and_positive_volume(self):
        row = lathe()
        row.update(mode='closed_solid', profile=[[0, 0], [1, 0], [1, 2], [0, 2]])
        self.tool.build(spec(row))
        mesh = bpy.data.objects['Shade'].data
        measured = inspect(mesh)
        self.assertTrue(measured['manifold'])
        self.assertTrue(measured['consistent'])
        self.assertEqual(len(mesh.vertices), 66)
        self.assertAlmostEqual(measured['volume'], 32*math.sin(2*math.pi/32), places=6)
        self.assertGreater(min(measured['uv_areas']), 1e-6)
        bottom = [p for p in mesh.polygons if p.center.z < .001]
        top = [p for p in mesh.polygons if p.center.z > 1.999]
        self.assertTrue(all(p.normal.z < -.99 for p in bottom))
        self.assertTrue(all(p.normal.z > .99 for p in top))

    def test_closed_hollow_profile_keeps_air_space_manifold_positive_volume_and_inner_normals(self):
        row = lathe()
        row.update(mode='closed_solid', profile=[[.9, 0], [1, 0], [.55, 1], [.45, 1]])
        report = self.tool.build(spec(row))
        mesh = bpy.data.objects['Shade'].data
        measured = inspect(mesh)
        self.assertTrue(measured['manifold'])
        self.assertTrue(measured['consistent'])
        expected = .5*32*math.sin(2*math.pi/32)*(1+.55+.55**2-(.9**2+.9*.45+.45**2))/3
        self.assertAlmostEqual(measured['volume'], expected, places=6)
        self.assertTrue(report['components'][0]['closed'])
        self.assertEqual(sum(e.use_seam for e in mesh.edges), 36)
        self.assertGreater(min(measured['uv_areas']), 1e-6)
        inner = mesh.polygons[-1]
        self.assertLess(inner.normal.x*inner.center.x + inner.normal.y*inner.center.y, 0)


if __name__ == '__main__':
    unittest.main()
