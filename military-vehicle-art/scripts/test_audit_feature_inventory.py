"""Evidence-to-geometry trace tests; no claim of automatic feature recognition."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

try:
    import bpy
    from PIL import Image
except ImportError:
    bpy = None

MODULE = Path(__file__).with_name('audit_feature_inventory.py')

@unittest.skipIf(bpy is None, 'requires actual bpy and Pillow')
class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), 'feature inventory helper not implemented')
        spec=importlib.util.spec_from_file_location('feature_inventory', MODULE)
        self.tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.tool)
        self.tmp=tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.root=Path(self.tmp.name)
        self.source=self.root/'source.blend';self.spec_path=self.root/'features.json';self.report=self.root/'report.json'
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add(size=1,location=(2,3,4))
        bpy.context.object.name='Fastener'
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        Image.new('RGB',(32,24),(128,130,132)).save(self.root/'reference.png')
        self.before=self.sha(self.source)
    def tearDown(self):
        if hasattr(self,'tmp'):self.tmp.cleanup()
    def sha(self,p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    def config(self):
        return {'schema_version':1,'scene':'Scene','view_layer':'ViewLayer','evaluation_frame':1,
                'subject':'Authored fixture, not a real photographic reconstruction',
                'scope_note':'One authored fixture feature; image is synthetic, not evidence of real subject accuracy.',
                'evidence':[{'id':'ref','path':'reference.png','sha256':self.sha(self.root/'reference.png')}],
                'regions':[{'id':'front','coverage_note':'Only the declared fixture fastener, not exhaustive surface coverage.'}],
                'features':[{'id':'fastener-1','region':'front','description':'Fixture fastener',
                  'epistemic':'authored','uncertainty':'Synthetic fixture; not a real-world observation.',
                  'observations':[{'evidence':'ref','region_px':[0,0,16,16]}],
                  'model':{'object':'Fastener','anchor':'bounds_center','vertex_index':None,
                           'target_world':[2,3,4],'tolerance':.001,'position_basis':'Authored fixture coordinates in Blender world units.'}}]}
    def run_tool(self,spec=None):
        self.spec_path.write_text(json.dumps(spec if spec is not None else self.config()))
        error=io.StringIO()
        with contextlib.redirect_stderr(error):
            code=self.tool.main(['--source',str(self.source),'--spec',str(self.spec_path),'--report',str(self.report)])
        self.error=error.getvalue();return code
    def test_invalid_crops_and_numeric_position_specs_are_refused(self):
        cases=[]
        for crop in ([0,0,0,16],[-1,0,2,3],[0,0,33,24],[0,0,1.0,2],[False,0,2,3],None):
            cfg=self.config();cfg['features'][0]['observations'][0]['region_px']=crop;cases.append(cfg)
        for key,value in (('target_world',[True,3,4]),('target_world',[float('nan'),3,4]),
                          ('tolerance',-1),('tolerance',True),('vertex_index',True),('vertex_index',-1),('vertex_index',3)):
            cfg=self.config();cfg['features'][0]['model'][key]=value;cases.append(cfg)
        cfg=self.config();cfg['features'][0]['model']['position_basis']='';cases.append(cfg)
        for cfg in cases:
            with self.subTest(cfg=cfg['features'][0]):
                try:self.assertEqual(self.run_tool(cfg),2,self.error)
                finally:
                    if self.report.exists():self.report.unlink()
    def test_empty_duplicate_and_unbound_inventory_records_are_refused(self):
        cases=[]
        for name in ('features','regions','evidence'):
            cfg=self.config();cfg[name]=[];cases.append((name,cfg))
        cfg=self.config();cfg['features']*=2;cases.append(('duplicate feature',cfg))
        cfg=self.config();cfg['regions']*=2;cases.append(('duplicate region',cfg))
        cfg=self.config();cfg['features'][0]['region']='missing';cases.append(('unbound region',cfg))
        cfg=self.config();cfg['features'][0]['observations'][0]['evidence']='missing';cases.append(('unbound evidence',cfg))
        cfg=self.config();cfg['features'][0]['epistemic']='observed';cfg['features'][0]['observations']=[];cases.append(('observed without evidence',cfg))
        cfg=self.config();other=copy.deepcopy(cfg['features'][0]);other['id']='different-id';cfg['features'].append(other);cases.append(('reused geometry anchor',cfg))
        for label,cfg in cases:
            with self.subTest(label=label):
                try:
                    code=self.run_tool(cfg)
                    self.assertEqual(code,2,self.error)
                finally:
                    if self.report.exists():self.report.unlink()
    def test_evidence_paths_are_confined_to_the_spec_directory(self):
        external=self.root.parent/(self.root.name+'-outside.png')
        Image.new('RGB',(32,24)).save(external)
        try:
            cfg=self.config();cfg['evidence'][0].update(path=str(external),sha256=self.sha(external))
            self.assertEqual(self.run_tool(cfg),2,self.error)
            self.assertFalse(self.report.exists())
        finally:external.unlink()
    def test_hidden_ancestor_collection_and_degenerate_mesh_are_refused(self):
        obj=bpy.data.objects['Fastener']
        parent=bpy.data.collections.new('HiddenParent');child=bpy.data.collections.new('Child')
        bpy.context.scene.collection.children.link(parent);parent.children.link(child)
        for collection in list(obj.users_collection):collection.objects.unlink(obj)
        child.objects.link(obj);parent.hide_render=True
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        self.assertEqual(self.run_tool(),2,self.error)
        self.assertFalse(self.report.exists())
    def test_truncated_jpeg_header_is_not_usable_crop_evidence(self):
        import random
        pixels=random.Random(4).randbytes(128*128*3)
        image=Image.frombytes('RGB',(128,128),pixels);path=self.root/'reference.jpg'
        image.save(path,quality=90);path.write_bytes(path.read_bytes()[:700])
        with Image.open(path) as reference:reference.verify()
        with self.assertRaises(OSError):
            with Image.open(path) as reference:reference.load()
        cfg=self.config();cfg['evidence'][0].update(path='reference.jpg',sha256=self.sha(path))
        self.assertEqual(self.run_tool(cfg),2,self.error)
        self.assertFalse(self.report.exists())
    def test_excluded_render_path_cannot_make_viewport_only_geometry_count(self):
        obj=bpy.data.objects['Fastener']
        visible=bpy.data.collections.new('ViewportOnly');visible.hide_render=True
        excluded=bpy.data.collections.new('ExcludedRenderPath')
        bpy.context.scene.collection.children.link(visible)
        bpy.context.scene.collection.children.link(excluded)
        for collection in list(obj.users_collection):collection.objects.unlink(obj)
        visible.objects.link(obj);excluded.objects.link(obj)
        bpy.context.view_layer.layer_collection.children['ExcludedRenderPath'].exclude=True
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        self.assertEqual(self.run_tool(),2,self.error)
        self.assertFalse(self.report.exists())
    def test_world_collapsed_mesh_cannot_count_as_a_feature(self):
        bpy.data.objects['Fastener'].scale=(0,0,0)
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        self.assertEqual(self.run_tool(),2,self.error)
        self.assertFalse(self.report.exists())
    def test_degenerate_mesh_cannot_count_as_present_feature(self):
        obj=bpy.data.objects['Fastener'];obj.data.clear_geometry()
        obj.data.from_pydata([(0,0,0),(1,0,0),(2,0,0)],[],[(0,1,2)])
        bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        self.assertEqual(self.run_tool(),2,self.error)
        self.assertFalse(self.report.exists())
    def test_unknown_missing_and_out_of_tolerance_features_remain_separate(self):
        cfg=self.config();rows=cfg['features']
        missing=copy.deepcopy(rows[0]);missing.update(id='missing',model=None)
        unknown=copy.deepcopy(missing);unknown.update(id='hidden',epistemic='unknown',observations=[])
        drift=copy.deepcopy(rows[0]);drift['id']='drift';drift['model']['anchor']='evaluated_vertex';drift['model']['vertex_index']=0
        drift['model']['target_world']=[20,30,40]
        rows.extend([missing,unknown,drift])
        self.assertEqual(self.run_tool(cfg),0,self.error)
        data=json.loads(self.report.read_text())
        self.assertEqual([r['state'] for r in data['features']],['position_within_tolerance','not_modelled','unresolved','position_outside_tolerance'])
        self.assertEqual(data['summary']['unknown'],1)
    def test_requested_animation_frame_and_modifier_bounds_are_evaluated(self):
        obj=bpy.data.objects['Fastener'];obj.location=(2,3,4);obj.keyframe_insert('location',frame=1)
        obj.location=(4,5,6);obj.keyframe_insert('location',frame=10)
        modifier=obj.modifiers.new('Array','ARRAY');modifier.count=2
        modifier.relative_offset_displace=(1,0,0)
        bpy.context.scene.frame_set(1);bpy.ops.wm.save_as_mainfile(filepath=str(self.source))
        cfg=self.config();cfg['evaluation_frame']=10;cfg['features'][0]['model']['target_world']=[4.5,5,6]
        self.assertEqual(self.run_tool(cfg),0,self.error)
        data=json.loads(self.report.read_text());self.assertEqual(data['features'][0]['measured_world'],[4.5,5,6])
    def test_existing_report_is_not_overwritten(self):
        self.report.write_bytes(b'winner')
        self.assertEqual(self.run_tool(),2,self.error)
        self.assertEqual(self.report.read_bytes(),b'winner')
    def test_stale_evidence_and_duplicate_json_keys_are_refused(self):
        cfg=self.config();cfg['evidence'][0]['sha256']='0'*64
        self.assertEqual(self.run_tool(cfg),2,self.error)
        self.assertFalse(self.report.exists())
        self.spec_path.write_text('{"schema_version":1,"schema_version":1}')
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.tool.main(['--source',str(self.source),'--spec',str(self.spec_path),'--report',str(self.report)]),2)
        self.assertFalse(self.report.exists())
    def test_symlink_evidence_is_refused_even_within_directory(self):
        alias=self.root/'alias.png';alias.symlink_to(self.root/'reference.png')
        cfg=self.config();cfg['evidence'][0]['path']='alias.png'
        self.assertEqual(self.run_tool(cfg),2,self.error)
    def test_report_binds_the_executed_tool_sources(self):
        self.assertEqual(self.run_tool(),0,self.error)
        data=json.loads(self.report.read_text())
        self.assertIn('tool_sha256',data,'report lacks executed tool fingerprints')
        for name in ('audit_feature_inventory.py','probe_geometry.py'):
            self.assertEqual(data['tool_sha256'][name],self.sha(MODULE.parent/name))
    def test_real_scene_feature_anchor_is_measured_without_accuracy_claim(self):
        self.assertEqual(self.run_tool(),0,self.error)
        data=json.loads(self.report.read_text())
        self.assertEqual(data['features'][0]['state'],'position_within_tolerance')
        self.assertEqual(data['features'][0]['measured_world'],[2,3,4])
        self.assertEqual(data['summary']['authored'],1)
        self.assertNotIn('accuracy_percent',data)
        self.assertEqual(self.sha(self.source),self.before)
