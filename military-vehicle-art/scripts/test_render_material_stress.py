"""Real Blender controlled-lighting regressions; synthetic mechanics, not art approval."""
import copy,hashlib,importlib.util,json,os,sys,tempfile,unittest
from pathlib import Path
try:
    import bpy
except ImportError:
    bpy=None

@unittest.skipIf(bpy is None,'requires real bpy')
class MaterialStressTests(unittest.TestCase):
    def setUp(self):
        module=Path(__file__).with_name('render_material_stress.py')
        self.assertTrue(module.is_file(),'controlled material-lighting system not implemented')
        loader=importlib.util.spec_from_file_location('material_stress',module)
        self.tool=importlib.util.module_from_spec(loader); loader.loader.exec_module(self.tool)
        self.temp=tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.source=self.root/'source.blend'; self.specpath=self.root/'filled.json'; self.output=self.root/'output'
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add(); target=bpy.context.object; target.name='TestProduct'
        collection=bpy.data.collections.new('Product'); bpy.context.scene.collection.children.link(collection)
        collection.objects.link(target); bpy.context.scene.collection.objects.unlink(target)
        material=bpy.data.materials.new('Coating')
        if material.node_tree is None: material.use_nodes=True
        shader=next(n for n in material.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
        shader.inputs['Base Color'].default_value=(.2,.08,.035,1); shader.inputs['Roughness'].default_value=.35
        target.data.materials.append(material)
        camera=bpy.data.objects.new('ReviewCamera',bpy.data.cameras.new('ReviewCamera'))
        bpy.context.scene.collection.objects.link(camera)
        from mathutils import Vector
        camera.location=(3,-4,3); camera.rotation_euler=(-camera.location).to_track_quat('-Z','Y').to_euler()
        camera.data.type='ORTHO'; camera.data.ortho_scale=4.2; bpy.context.scene.camera=camera
        bpy.context.scene.render.resolution_x=bpy.context.scene.render.resolution_y=32
        bpy.context.scene.render.resolution_percentage=100
        bpy.context.preferences.filepaths.save_version=0
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source)); self.sourcehash=self.sha(self.source)

    def sha(self,path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    def spec(self):
        profile={'label':'neutral','world_color':[.08,.08,.08],'world_strength':.15,
            'lights':[{'position':[3,-4,5],'target':[0,0,0],'power_w':500,'size':2,'color':[1,1,1]}]}
        opposite=copy.deepcopy(profile); opposite['label']='grazing'; opposite['lights'][0]['position']=[-4,2,.3]
        return {'schema_version':1,'render':{'schema_version':1,'camera':'ReviewCamera','collection':'Product','resolution':[32,32],'samples':2,
            'registration_note':'Synthetic fixed-camera lighting test; not photographic registration.'},'profiles':[profile,opposite]}
    def run_tool(self,spec=None):
        self.specpath.write_text(json.dumps(self.spec() if spec is None else spec))
        return self.tool.main(['--source',str(self.source),'--spec',str(self.specpath),'--output',str(self.output)])

    def test_actual_two_light_profiles_preserve_source_camera_and_masks(self):
        from PIL import Image,ImageChops
        self.assertEqual(self.run_tool(),0)
        self.assertEqual(self.sha(self.source),self.sourcehash)
        report=json.loads((self.output/'material-stress.json').read_text())
        self.assertEqual(report['command'],'render-material-stress')
        self.assertEqual(report['source_sha256'],self.sourcehash)
        self.assertEqual(len(report['profiles']),2)
        left,right=[row['render_manifest'] for row in report['profiles']]
        a=json.loads((self.output/left['path']).read_text()); b=json.loads((self.output/right['path']).read_text())
        self.assertEqual(a['camera'],b['camera'])
        self.assertEqual(a['lighting']['mode'],'explicit_diagnostic')
        self.assertEqual(a['lighting']['settings'],self.spec()['profiles'][0])
        ia=Image.open(self.output/'neutral/detail.png').convert('RGB'); ib=Image.open(self.output/'grazing/detail.png').convert('RGB')
        self.assertIsNotNone(ImageChops.difference(ia,ib).getbbox())
        ma=Image.open(self.output/'neutral/mask.png').convert('L'); mb=Image.open(self.output/'grazing/mask.png').convert('L')
        self.assertIsNone(ImageChops.difference(ma,mb).getbbox())

    def test_report_binds_actual_driver_renderer_and_snapshot_helper_hashes(self):
        self.assertEqual(self.run_tool(),0)
        report=json.loads((self.output/'material-stress.json').read_text())
        self.assertIn('tool_sha256',report,'documented tool fingerprints are missing')
        folder=Path(self.tool.__file__).parent
        names=('render_material_stress.py','render_registered.py','reconstruct_vehicle.py')
        self.assertEqual(report['tool_sha256'],{name:self.sha(folder/name) for name in names})

    def test_numeric_and_float32_duplicate_light_plans_are_refused(self):
        original=self.spec()['profiles'][0]
        for label,value in [('numeric',500.0),('float32',500.0000001)]:
            spec=self.spec();duplicate=copy.deepcopy(original);duplicate['label']='duplicate'
            duplicate['lights'][0]['power_w']=value;spec['profiles'][1]=duplicate
            with self.subTest(label=label),self.assertRaisesRegex(ValueError,'duplicate light'):
                self.tool.validate(spec)
        first=copy.deepcopy(original['lights'][0]);second=copy.deepcopy(first);second['position']=[-3,2,4]
        spec=self.spec();spec['profiles'][0]['lights']=[first,second]
        duplicate=copy.deepcopy(spec['profiles'][0]);duplicate['label']='reordered';duplicate['lights'].reverse();spec['profiles'][1]=duplicate
        with self.assertRaisesRegex(ValueError,'duplicate light'):self.tool.validate(spec)

    def test_light_direction_must_survive_blender_float32_coordinates(self):
        spec=self.spec()
        spec['profiles'][0]['lights'][0].update(position=[100000000,0,0],target=[99999999,0,0])
        with self.assertRaisesRegex(ValueError,'float32'):
            self.tool.validate(spec)

    def test_strict_controls_and_conflicting_profiles_refuse(self):
        variants=[]
        for key,value in [('schema_version',True),('profiles',[]),('extra',1)]:
            spec=self.spec(); spec[key]=value; variants.append(spec)
        for key,value in [('label','../escape'),('world_strength',True),('world_color',[1,1,2]),('lights',[])]:
            spec=self.spec(); spec['profiles'][0][key]=value; variants.append(spec)
        for key,value in [('power_w',True),('power_w',float('nan')),('size',0),('size',1e-100),('target',[3,-4,5])]:
            spec=self.spec(); spec['profiles'][0]['lights'][0][key]=value; variants.append(spec)
        same=self.spec(); same['profiles'][1]=copy.deepcopy(same['profiles'][0]); same['profiles'][1]['label']='duplicate'; variants.append(same)
        for spec in variants:
            with self.subTest(spec=spec),self.assertRaises(ValueError): self.tool.validate(spec)

    def test_existing_directory_and_dangling_symlink_are_never_replaced(self):
        self.output.mkdir(); keep=self.output/'keep'; keep.write_bytes(b'keep')
        self.assertEqual(self.run_tool(),2); self.assertEqual(keep.read_bytes(),b'keep')
        keep.unlink(); self.output.rmdir(); self.output.symlink_to(self.root/'absent')
        self.assertEqual(self.run_tool(),2); self.assertTrue(self.output.is_symlink())
        self.assertEqual(self.sha(self.source),self.sourcehash)

    def test_missing_camera_failure_publishes_no_partial_output(self):
        spec=self.spec(); spec['render']['camera']='MissingCamera'
        self.assertEqual(self.run_tool(spec),2); self.assertFalse(self.output.exists())
        self.assertEqual(self.sha(self.source),self.sourcehash)

    def test_original_lights_are_ignored_and_preserved(self):
        original=bpy.data.objects.new('OriginalSun',bpy.data.lights.new('OriginalSun','SUN'))
        bpy.context.scene.collection.objects.link(original); original.data.energy=1234
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source)); self.sourcehash=self.sha(self.source)
        self.assertEqual(self.run_tool(),0)
        row=json.loads((self.output/'neutral/render-manifest.json').read_text())
        self.assertEqual(row['lighting']['visible_source_lights'],0)
        self.assertEqual(row['lighting']['explicit_lights'],1)
        bpy.ops.wm.open_mainfile(filepath=str(self.source),use_scripts=False)
        self.assertEqual(bpy.data.objects['OriginalSun'].data.energy,1234)
        self.assertEqual(self.sha(self.source),self.sourcehash)

    def test_changed_file_image_input_refuses_publication(self):
        from PIL import Image
        imagepath=self.root/'input.png'; Image.new('RGB',(4,4),'red').save(imagepath)
        image=bpy.data.images.load(str(imagepath)); image.use_fake_user=True
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source)); self.sourcehash=self.sha(self.source)
        @bpy.app.handlers.persistent
        def change_after_render(*_):
            Image.new('RGB',(4,4),'blue').save(imagepath)
        bpy.app.handlers.render_post.append(change_after_render)
        try:
            self.assertEqual(self.run_tool(),2); self.assertFalse(self.output.exists())
        finally: bpy.app.handlers.render_post.remove(change_after_render)
        self.assertEqual(self.sha(self.source),self.sourcehash)

    def test_cli_help_from_unrelated_cwd_and_unfilled_template(self):
        import subprocess
        module=Path(self.tool.__file__)
        result=subprocess.run([sys.executable,str(module),'--help'],cwd=self.root,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('--source',result.stdout)
        template=module.parent.parent/'assets/material-stress.json'
        self.assertTrue(template.is_file(),'unfilled template not provided')
        with self.assertRaises(ValueError): self.tool.validate(json.loads(template.read_text()))

if __name__=='__main__': unittest.main()
