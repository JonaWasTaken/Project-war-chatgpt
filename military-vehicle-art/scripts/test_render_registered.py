"""Real offscreen CPU Cycles tests; synthetic fixtures, never reference evidence."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    import bpy
    import numpy as np
except ImportError:
    bpy = None

SCRIPT = Path(__file__).with_name('render_registered.py')


@unittest.skipIf(bpy is None, 'requires real Blender Python')
class RegisteredRenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.scene = bpy.context.scene
        self.collection = bpy.data.collections.new('Subject')
        self.scene.collection.children.link(self.collection)
        self.body = self.plane('Body', (-.6, .15, 0), .25, self.collection)
        material = bpy.data.materials.new('Red emission')
        if bpy.app.version < (5, 0, 0):
            material.use_nodes = True
        tree = material.node_tree
        tree.nodes.clear()
        node = tree.nodes.new('ShaderNodeEmission')
        node.inputs['Color'].default_value = (1, 0, 0, 1)
        out = tree.nodes.new('ShaderNodeOutputMaterial')
        tree.links.new(node.outputs[0], out.inputs['Surface'])
        self.body.data.materials.append(material)
        data = bpy.data.cameras.new('Registered')
        self.camera = bpy.data.objects.new('Registered', data)
        self.scene.collection.objects.link(self.camera)
        self.camera.location = (.1, -.1, 5)
        data.lens = 42
        data.sensor_fit = 'HORIZONTAL'
        data.shift_x = .08
        data.shift_y = -.06
        self.scene.camera = self.camera
        self.scene.render.resolution_x = 96
        self.scene.render.resolution_y = 64
        self.scene.render.resolution_percentage = 100
        self.spec = dict(schema_version=1, camera='Registered', collection='Subject',
                         resolution=[96, 64], samples=2,
                         registration_note='Synthetic fixture: known camera, full frame, no photo calibration claim.')
        self.source = self.root / 'fixture.blend'
        self.specpath = self.root / 'spec.json'
        self.output = self.root / 'render'

    def plane(self, name, center, radius, collection):
        x, y, z = center
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata([(x-radius,y-radius,z), (x+radius,y-radius,z),
                          (x+radius,y+radius,z), (x-radius,y+radius,z)], [], [(0,1,2,3)])
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        return obj

    def save(self):
        bpy.context.view_layer.update()
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        self.sourcehash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.specpath.write_text(json.dumps(self.spec))

    def invoke(self, subprocess_cli=False):
        args = ['--source', str(self.source), '--spec', str(self.specpath), '--output', str(self.output)]
        if subprocess_cli:
            result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                                    text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            import render_registered
            self.assertEqual(render_registered.main(args), 0)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.sourcehash)
        return json.loads((self.output / 'render-manifest.json').read_text())

    def pixels(self, name):
        image = bpy.data.images.load(str(self.output / name), check_existing=False)
        try:
            self.assertEqual(list(image.size), self.spec['resolution'])
            return np.array(image.pixels[:]).reshape((image.size[1],image.size[0],4))
        finally:
            bpy.data.images.remove(image)

    def projected(self, point):
        from bpy_extras.object_utils import world_to_camera_view
        from mathutils import Vector
        p = world_to_camera_view(bpy.context.scene, bpy.data.objects['Registered'], Vector(point))
        return int(p.x*96), int(p.y*64)

    def test_object_material_override_is_used_in_detail_render(self):
        override = bpy.data.materials.new('ObjectOverrideGreen')
        if override.node_tree is None:
            override.use_nodes=True
        override.node_tree.nodes.clear()
        emit = override.node_tree.nodes.new('ShaderNodeEmission')
        emit.inputs['Color'].default_value=(0,1,0,1)
        output = override.node_tree.nodes.new('ShaderNodeOutputMaterial')
        override.node_tree.links.new(emit.outputs[0],output.inputs['Surface'])
        self.body.material_slots[0].link='OBJECT'
        self.body.material_slots[0].material=override
        self.save()
        self.invoke()
        x,y=self.projected((-.6,.15,0))
        red,green,blue,alpha=self.pixels('detail.png')[y,x]
        self.assertGreater(green,red+.4)

    def test_camera_hidden_collection_instancer_stays_hidden(self):
        master=bpy.data.collections.new('CameraHiddenMaster')
        self.plane('InstancedPart',(.65,.4,0),.22,master)
        emitter=bpy.data.objects.new('CameraHiddenEmitter',None)
        emitter.instance_type='COLLECTION'
        emitter.instance_collection=master
        emitter.visible_camera=False
        self.collection.objects.link(emitter)
        self.save()
        report=self.invoke()
        self.assertEqual(report['mesh_instances'],1)
        x,y=self.projected((.65,.4,0))
        self.assertEqual(self.pixels('mask.png')[y,x,0],0)

    def test_render_hidden_vertex_emitter_does_not_become_foreground(self):
        self.body.instance_type='VERTS'
        self.body.show_instancer_for_render=False
        child=self.plane('RepeatedChild',(0,0,0),.04,self.collection)
        child.parent=self.body
        self.save()
        self.invoke()
        x,y=self.projected((-.6,.15,0))
        self.assertEqual(self.pixels('mask.png')[y,x,0],0)

    def test_vertex_instanced_child_source_is_not_an_extra_mesh(self):
        self.body.instance_type='VERTS'
        self.body.show_instancer_for_render=False
        child=self.plane('RepeatedChild',(0,0,0),.04,self.collection)
        child.parent=self.body
        self.save()
        report=self.invoke()
        self.assertEqual(report['mesh_instances'],4)
        x,y=self.projected((0,0,0))
        self.assertEqual(self.pixels('mask.png')[y,x,0],0)

    def test_viewport_hidden_render_visible_vertex_emitter_is_refused(self):
        self.body.instance_type='VERTS'
        self.body.show_instancer_for_viewport=False
        self.body.show_instancer_for_render=True
        child=self.plane('RepeatedChild',(0,0,0),.04,self.collection)
        child.parent=self.body
        self.save()
        import render_registered
        self.assertEqual(render_registered.main(['--source',str(self.source),'--spec',str(self.specpath),
                         '--output',str(self.output)]),2)
        self.assertFalse(self.output.exists())

    def test_camera_hidden_nested_instancer_is_refused_not_resurrected(self):
        inner=bpy.data.collections.new('InnerMaster')
        self.plane('NestedMesh',(.65,.4,0),.22,inner)
        middle=bpy.data.collections.new('MiddleMaster')
        nested=bpy.data.objects.new('HiddenNestedEmitter',None)
        nested.instance_type='COLLECTION'
        nested.instance_collection=inner
        nested.visible_camera=False
        middle.objects.link(nested)
        top=bpy.data.objects.new('TopEmitter',None)
        top.instance_type='COLLECTION'
        top.instance_collection=middle
        self.collection.objects.link(top)
        self.save()
        import render_registered
        self.assertEqual(render_registered.main(['--source',str(self.source),'--spec',str(self.specpath),
                         '--output',str(self.output)]),2)
        self.assertFalse(self.output.exists())

    def test_valid_float32_rotation_roundtrip_is_not_misdiagnosed_as_shear(self):
        self.body.rotation_euler = (-1.2969619035720825, -3.1415927410125732, 0)
        self.save()
        report = self.invoke()
        self.assertEqual(report['mesh_instances'],1)
        self.assertTrue((self.output/'mask.png').is_file())

    def test_blender_style_run_path_does_not_require_script_dir_on_sys_path(self):
        code = ('import runpy,sys; sys.argv=[sys.argv[1],"--help"]; '
                'runpy.run_path(sys.argv[0],run_name="__main__")')
        result = subprocess.run([sys.executable, '-c', code, str(SCRIPT)], cwd=self.root,
                                text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('--source', result.stdout)

    def test_cli_material_mask_and_actual_landmark_projection(self):
        self.save()
        expected_matrix = [list(row) for row in self.camera.matrix_world]
        report = self.invoke(subprocess_cli=True)
        self.assertEqual(report['kind'], 'registered_camera_render')
        self.assertEqual(report['schema_version'], 1)
        self.assertEqual(report['source'], dict(path=str(self.source), sha256=self.sourcehash))
        self.assertEqual(report['camera']['matrix_world'], expected_matrix)
        self.assertEqual(report['camera']['sensor_fit'], 'HORIZONTAL')
        self.assertEqual(report['image_size'], [96,64])
        self.assertEqual(report['registration_note'], self.spec['registration_note'])
        for key in ('mask','detail'):
            row = report['artifacts'][key]
            self.assertEqual(row['path'], key+'.png')
            self.assertEqual(row['sha256'], hashlib.sha256((self.output / row['path']).read_bytes()).hexdigest())
        mask, detail = self.pixels('mask.png'), self.pixels('detail.png')
        self.assertEqual(set(np.unique(mask[:,:,:3])), {0.,1.})
        self.assertTrue(np.all(mask[:,:,3] == 1))
        x,y = self.projected((-.6,.15,0))
        self.assertTrue(np.all(mask[y,x,:3] == 1), 'known projected landmark must be foreground')
        self.assertGreater(detail[y,x,0], .8)
        self.assertLess(detail[y,x,1], .02)
        ys,xs = np.where(mask[:,:,0] > .5)
        self.assertLess(abs(xs.mean()-(x+.0)), 2)
        self.assertLess(abs(ys.mean()-(y+.0)), 2)
        self.assertTrue(np.all(mask[0,0,:3] == 0))

    def test_isolates_instances_exclusions_outsiders_and_transparent_master(self):
        master_collection = bpy.data.collections.new('UnlinkedMaster')
        master = self.plane('TransparentMaster', (0,0,0), .22, master_collection)
        material = bpy.data.materials.new('Invisible material')
        if bpy.app.version < (5,0,0):
            material.use_nodes = True
        tree = material.node_tree
        tree.nodes.clear()
        transparent = tree.nodes.new('ShaderNodeBsdfTransparent')
        out = tree.nodes.new('ShaderNodeOutputMaterial')
        tree.links.new(transparent.outputs[0], out.inputs['Surface'])
        master.data.materials.append(material)
        instancer = bpy.data.objects.new('Chosen instance', None)
        instancer.instance_type = 'COLLECTION'
        instancer.instance_collection = master_collection
        instancer.location = (.65,.4,0)
        self.collection.objects.link(instancer)
        outside = bpy.data.collections.new('Clutter')
        self.scene.collection.children.link(outside)
        self.plane('Outsider', (.9,-.8,0), .22, outside)
        duplicate = bpy.data.objects.new('Unrelated same master', None)
        duplicate.instance_type = 'COLLECTION'
        duplicate.instance_collection = master_collection
        duplicate.location = (-1,-.7,0)
        outside.objects.link(duplicate)
        excluded = bpy.data.collections.new('Excluded variant')
        self.collection.children.link(excluded)
        self.plane('Excluded covers frame', (0,0,1), 20, excluded)
        bpy.context.view_layer.layer_collection.children['Subject'].children[excluded.name].exclude = True
        hidden = self.plane('Hidden part', (0,-.9,0), .2, self.collection)
        hidden.hide_render = True
        self.save()
        report = self.invoke()
        self.assertEqual(report['mesh_instances'], 2)
        mask, detail = self.pixels('mask.png'), self.pixels('detail.png')
        x,y = self.projected((.65,.4,0))
        self.assertEqual(mask[y,x,0], 1, 'alpha-transparent instanced master must have an opaque geometry mask')
        np.testing.assert_allclose(detail[y,x,:3], detail[0,0,:3], atol=.01,
                                   err_msg='transparent master must retain actual material over diagnostic background')
        for point in ((.9,-.8,0),(-1,-.7,0),(0,-.9,0)):
            x,y = self.projected(point)
            self.assertEqual(mask[y,x,0], 0, 'outsider/excluded/hidden geometry contaminated mask')
        self.assertTrue(np.all(mask[0,0,:3] == 0))

    def test_ortho_vertical_fit_portrait_and_static_parent_evaluated_pose(self):
        parent = bpy.data.objects.new('Static camera rig', None)
        self.scene.collection.objects.link(parent)
        parent.location = (.12,.03,.4)
        parent.rotation_euler.z = .17
        self.camera.parent = parent
        self.camera.data.type = 'ORTHO'
        self.camera.data.sensor_fit = 'VERTICAL'
        self.camera.data.ortho_scale = 3
        self.camera.data.sensor_width = 32
        self.camera.data.sensor_height = 18
        self.scene.render.resolution_x, self.scene.render.resolution_y = 64,96
        self.spec['resolution'] = [64,96]
        self.save()
        expected = [list(row) for row in self.camera.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world]
        report = self.invoke()
        np.testing.assert_allclose(report['camera']['matrix_world'], expected, rtol=0, atol=1e-6)
        self.assertEqual(report['camera']['type'], 'ORTHO')
        self.assertEqual(report['camera']['sensor_fit'], 'VERTICAL')
        self.assertEqual(report['camera']['ortho_scale'], 3)
        self.assertEqual(report['camera']['sensor_height_mm'], 18)
        mask = self.pixels('mask.png')
        from bpy_extras.object_utils import world_to_camera_view
        # Project the mesh centre with the actual original camera, not report reconstruction.
        from mathutils import Vector
        p = world_to_camera_view(bpy.context.scene,bpy.data.objects['Registered'],Vector((-.6,.15,0)))
        self.assertEqual(mask[int(p.y*96),int(p.x*64),0], 1)

    def assert_rejected(self):
        import render_registered
        self.save()
        self.assertEqual(render_registered.main(['--source',str(self.source),'--spec',str(self.specpath),
                                                  '--output',str(self.output)]), 2)
        self.assertFalse(os.path.lexists(self.output))
        self.assertEqual(list(self.root.glob('.registered-*')), [], 'failed render leaked staging directory')
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.sourcehash)

    def test_rejects_animated_camera_parent_and_camera_data(self):
        # Keyframes could otherwise change on render depsgraph evaluation.
        self.camera.data.keyframe_insert('lens', frame=1)
        self.camera.data.lens = 55
        self.camera.data.keyframe_insert('lens', frame=2)
        self.assert_rejected()

    def test_rejects_animated_camera_parent(self):
        parent = bpy.data.objects.new('Animated rig', None)
        self.scene.collection.objects.link(parent)
        self.camera.parent = parent
        parent.keyframe_insert('location', frame=1)
        parent.location.x = .4
        parent.keyframe_insert('location', frame=2)
        self.assert_rejected()

    def test_rejects_camera_mutation_during_actual_render(self):
        @bpy.app.handlers.persistent
        def change_camera(scene, *unused):
            if scene.name.startswith('RegisteredDiagnostic'):
                scene.camera.data.lens += 1
        bpy.app.handlers.render_pre.append(change_camera)
        self.addCleanup(lambda: bpy.app.handlers.render_pre.remove(change_camera))
        self.assert_rejected()

    def test_rejects_holdout_ancestor_of_selected_collection(self):
        parent = bpy.data.collections.new('Holdout ancestor')
        self.scene.collection.children.link(parent)
        self.scene.collection.children.unlink(self.collection)
        parent.children.link(self.collection)
        bpy.context.view_layer.layer_collection.children[parent.name].holdout = True
        self.assert_rejected()

    def test_rejects_render_viewport_modifier_divergence(self):
        modifier = self.body.modifiers.new('Render only geometry', 'SOLIDIFY')
        modifier.show_viewport = False
        modifier.show_render = True
        self.assert_rejected()

    def test_rejects_empty_mask_without_refitting_camera(self):
        self.camera.location.x = 100
        self.assert_rejected()

    def test_rejects_no_eligible_mesh(self):
        bpy.data.objects.remove(self.body, do_unlink=True)
        empty = bpy.data.objects.new('Only empty', None)
        self.collection.objects.link(empty)
        self.assert_rejected()

    def test_invalid_scene_render_modes_and_sizes(self):
        self.save()
        baseline = self.source.read_bytes()
        changes = [lambda s: setattr(s.render, 'resolution_percentage', 50),
                   lambda s: setattr(s.render, 'resolution_x', 128),
                   lambda s: setattr(s.render, 'use_border', True),
                   lambda s: setattr(s.render, 'use_crop_to_border', True),
                   lambda s: setattr(s.render, 'pixel_aspect_x', 2),
                   lambda s: setattr(s.objects['Registered'].data, 'type', 'PANO')]
        import render_registered
        for change in changes:
            with self.subTest(change=change):
                self.source.write_bytes(baseline)
                bpy.ops.wm.open_mainfile(filepath=str(self.source), use_scripts=False)
                change(bpy.context.scene)
                self.assert_rejected()

    def test_spec_numeric_bool_empty_and_unfilled_validation(self):
        import render_registered
        template = SCRIPT.parent.parent / 'assets' / 'registered-render-spec.json'
        with self.assertRaises(ValueError):
            render_registered.validate_spec(json.loads(template.read_text()))
        cases = [('schema_version',True), ('samples',True), ('samples',0), ('samples',1.5),
                 ('samples',float('inf')), ('samples',float('nan')), ('resolution',[96,True]),
                 ('resolution',[96,64.]), ('resolution',[96,-1]), ('resolution',[96,10**1000]),
                 ('camera',''), ('collection',None), ('registration_note','TODO'),
                 ('registration_note',None)]
        for key,value in cases:
            with self.subTest(key=key,value=str(value)):
                with self.assertRaises(ValueError):
                    render_registered.validate_spec(dict(self.spec, **{key:value}))

    def test_refuses_existing_source_spec_and_symlink_output(self):
        import render_registered
        self.save()
        existing = self.root / 'existing'
        existing.mkdir()
        sentinel = existing / 'keep'
        sentinel.write_text('unchanged')
        symlink = self.root / 'link'
        symlink.symlink_to(existing, target_is_directory=True)
        dangling = self.root / 'dangling'
        dangling.symlink_to(self.root / 'missing', target_is_directory=True)
        for path in (self.source,self.specpath,existing,symlink,dangling):
            with self.subTest(path=path):
                self.assertEqual(render_registered.main(['--source',str(self.source),'--spec',str(self.specpath),
                                                          '--output',str(path)]),2)
        self.assertEqual(sentinel.read_text(),'unchanged')
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),self.sourcehash)

    def test_rejects_unrepresentable_geometry_shear_instead_of_distorting(self):
        parent = bpy.data.objects.new('Nonuniform parent', None)
        self.scene.collection.objects.link(parent)
        parent.scale = (2,1,1)
        self.body.parent = parent
        self.body.rotation_euler.z = .5
        self.assert_rejected()

    def test_preserves_source_world_and_only_visible_source_lights(self):
        world = bpy.data.worlds.new('Source world')
        world.color = (.03,.05,.07)
        self.scene.world = world
        for name, hidden in [('Visible light',False),('Hidden render scope light',True)]:
            group = bpy.data.collections.new(name)
            group.hide_render = hidden
            self.scene.collection.children.link(group)
            data = bpy.data.lights.new(name,'AREA')
            data.energy = 40
            obj = bpy.data.objects.new(name,data)
            group.objects.link(obj)
            obj.location.z = 3
        self.save()
        report = self.invoke()
        self.assertEqual(report['lighting'], {'world':'source copy','visible_source_lights':1})

    def test_nested_collection_instance_retains_world_pose(self):
        nested = bpy.data.collections.new('Nested master')
        self.plane('Nested mesh', (0,0,0), .16, nested)
        middle = bpy.data.collections.new('Middle master')
        inner = bpy.data.objects.new('Nested instancer',None)
        inner.instance_type = 'COLLECTION'
        inner.instance_collection = nested
        inner.location = (.3,.2,0)
        middle.objects.link(inner)
        outer = bpy.data.objects.new('Chosen outer',None)
        outer.instance_type = 'COLLECTION'
        outer.instance_collection = middle
        outer.location = (.3,.2,0)
        self.collection.objects.link(outer)
        self.save()
        report = self.invoke()
        mask = self.pixels('mask.png')
        x,y = self.projected((.6,.4,0))
        self.assertEqual(mask[y,x,0],1,'nested instancer world placement was lost')
        self.assertEqual(report['mesh_instances'],2)

    def test_camera_ray_invisible_geometry_is_not_resurrected(self):
        hidden = self.plane('Camera hidden',(.6,-.5,0),.2,self.collection)
        hidden.visible_camera = False
        self.save()
        report = self.invoke()
        mask = self.pixels('mask.png')
        x,y = self.projected((.6,-.5,0))
        self.assertEqual(mask[y,x,0],0)
        self.assertEqual(report['mesh_instances'],1)

    def test_instanced_collection_hide_render_is_honored(self):
        master = bpy.data.collections.new('Instance master')
        self.plane('Instance visible', (.6,.5,0), .16, master)
        hidden = bpy.data.collections.new('Hidden instance child')
        hidden.hide_render = True
        master.children.link(hidden)
        self.plane('Instance hidden', (.6,-.5,0), .16, hidden)
        instancer = bpy.data.objects.new('Instance', None)
        instancer.instance_type = 'COLLECTION'
        instancer.instance_collection = master
        self.collection.objects.link(instancer)
        self.save()
        report = self.invoke()
        mask = self.pixels('mask.png')
        x,y = self.projected((.6,-.5,0))
        self.assertEqual(mask[y,x,0],0,'hide_render child of instanced master was incorrectly reenabled')
        self.assertEqual(report['mesh_instances'],2)

    def test_rejects_indirect_only_selected_scope(self):
        bpy.context.view_layer.layer_collection.children['Subject'].indirect_only = True
        self.assert_rejected()

    def test_does_not_execute_embedded_auto_run_text(self):
        sentinel = self.root / 'executed'
        text = bpy.data.texts.new('embedded.py')
        text.write('from pathlib import Path\nPath('+repr(str(sentinel))+').write_text("bad")\n')
        text.use_module = True
        self.save()
        self.invoke(subprocess_cli=True)
        self.assertFalse(sentinel.exists())
        self.assertFalse(bpy.context.preferences.filepaths.use_scripts_auto_execute)

    def test_atomic_publication_refuses_race_created_empty_directory(self):
        import render_registered
        stage = self.root / 'stage'
        stage.mkdir()
        (stage / 'evidence').write_text('ready')
        self.output.mkdir()
        with self.assertRaises(OSError):
            render_registered.publish_directory(stage,self.output)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertTrue((stage / 'evidence').is_file())


if __name__ == '__main__':
    unittest.main()
