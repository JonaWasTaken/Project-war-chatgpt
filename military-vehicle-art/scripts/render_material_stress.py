"""Source-preserving fixed-camera material stress renders under explicit light plans."""
import argparse,hashlib,json,math,os,re,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import render_registered as renderer
from reconstruct_vehicle import keys,number,float32

def unique(pairs):
    value={}
    for key,item in pairs:
        if key in value: raise ValueError('duplicate JSON key: '+key)
        value[key]=item
    return value

def vector(value,label,color=False):
    if not isinstance(value,list) or len(value)!=3: raise ValueError(label+' requires three numbers')
    for item in value:
        number(item,label); float32(item)
        if color and not 0<=item<=1: raise ValueError(label+' requires linear RGB in [0,1]')
        if not color and abs(item)>1e8: raise ValueError(label+' exceeds coordinate execution bound')

def validate(spec):
    keys(spec,('schema_version','render','profiles'))
    if type(spec['schema_version']) is not int or spec['schema_version']!=1: raise ValueError('schema_version must be integer 1')
    renderer.validate_spec(spec['render'])
    if not isinstance(spec['profiles'],list) or not 2<=len(spec['profiles'])<=8: raise ValueError('require 2..8 explicit light profiles')
    labels=set(); plans=set()
    for profile in spec['profiles']:
        keys(profile,('label','world_color','world_strength','lights'))
        label=profile['label']
        if not isinstance(label,str) or not re.fullmatch('[a-z][a-z0-9_-]{0,39}',label) or label in labels:
            raise ValueError('profile labels must be unique lowercase path-safe identifiers')
        labels.add(label); vector(profile['world_color'],'world_color',True)
        strength=number(profile['world_strength'],'world_strength')
        if not 0<=strength<=1e6: raise ValueError('world_strength must be in [0,1000000]')
        if not isinstance(profile['lights'],list) or not 1<=len(profile['lights'])<=8: raise ValueError('require 1..8 explicit area lights per profile')
        for light in profile['lights']:
            keys(light,('position','target','power_w','size','color'))
            vector(light['position'],'position'); vector(light['target'],'target'); vector(light['color'],'light color',True)
            if math.dist(light['position'],light['target'])<1e-6: raise ValueError('light position/target direction is numerically degenerate')
            if math.dist([float32(v) for v in light['position']],[float32(v) for v in light['target']])<1e-6:
                raise ValueError('light direction collapses at Blender float32 precision')
            for key in ('power_w','size'):
                n=number(light[key],key,positive=True)
                if n>1e8 or float32(n)<=0: raise ValueError(key+' exceeds supported positive float32 bounds')
        # Compare numeric storage values, not JSON spelling or list order.
        lights=tuple(sorted(tuple(float32(v) for key in ('position','target','power_w','size','color')
                                  for v in (light[key] if isinstance(light[key],list) else [light[key]]))
                            for light in profile['lights']))
        encoded=(tuple(float32(v) for v in profile['world_color']),float32(strength),lights)
        if encoded in plans: raise ValueError('duplicate light plans at Blender float32 precision are not separate stress conditions')
        plans.add(encoded)
    if spec['render']['resolution'][0]*spec['render']['resolution'][1]*len(spec['profiles'])>134217728:
        raise ValueError('combined pixel execution bound exceeded')
    return spec

def image_inputs():
    """Hash original file/packed image inputs; no reload, mutation or guessed map role."""
    import bpy
    rows=[]
    for image in bpy.data.images:
        if image.source in ('MOVIE','SEQUENCE','TILED'): raise ValueError('animated/tiled image inputs unsupported: '+image.name)
        if image.source!='FILE': continue
        if image.packed_file:
            rows.append({'image':image.name,'storage':'packed','sha256':hashlib.sha256(image.packed_file.data).hexdigest()})
        else:
            path=Path(bpy.path.abspath(image.filepath,library=image.library)).resolve()
            if not path.is_file(): raise ValueError('missing file image input: '+str(path))
            rows.append({'image':image.name,'storage':'file','path':str(path),'sha256':renderer.digest(path)})
    return sorted(rows,key=lambda r:r['image'])

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','spec','output'): parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        source,specpath,output=renderer.check_paths(args.source,args.spec,args.output)
        if os.path.samefile(source,specpath): raise ValueError('source/spec hardlink alias refused')
        source_hash=renderer.digest(source); spec_hash=renderer.digest(specpath)
        spec=validate(json.loads(specpath.read_text(encoding='utf8'),object_pairs_hook=unique))
        if renderer.digest(specpath)!=spec_hash: raise ValueError('spec changed during validation')
        tool_paths=[Path(__file__).resolve(),Path(renderer.__file__).resolve(),
                    Path(renderer.__file__).resolve().with_name('reconstruct_vehicle.py')]
        tool_hashes={path.name:renderer.digest(path) for path in tool_paths}
        import bpy
        bpy.context.preferences.filepaths.use_scripts_auto_execute=False
        bpy.ops.wm.open_mainfile(filepath=str(source),load_ui=False,use_scripts=False)
        images=image_inputs()
        report={'schema_version':1,'command':'render-material-stress','source':str(source),'source_sha256':source_hash,
            'spec_sha256':spec_hash,'tool_sha256':tool_hashes,'blender_version':bpy.app.version_string,'image_inputs':images,'profiles':[],
            'limitations':'Explicit area-light response diagnostics, not calibrated photo matching or photorealism certification. Same saved camera and Cycles CPU/Standard exposure-zero pipeline for every profile. Coordinates/sizes in Blender units, area-light energy in Blender watts; not a measured lighting reconstruction. No arbitrary source light/world/compositor copied. Image hashes cover loaded file/packed images, not every Blender external dependency. Geometry mask is opaque, not material transparency or shadows.'}
        with tempfile.TemporaryDirectory(prefix='.material-stress-',dir=output.parent) as temporary:
            stage=Path(temporary)/'result'; stage.mkdir()
            for profile in spec['profiles']:
                folder=stage/profile['label']; folder.mkdir()
                result=renderer.render_loaded(spec['render'],source,folder,diagnostic_lighting=profile)
                path=folder/'render-manifest.json'; path.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
                report['profiles'].append({'label':profile['label'],'render_manifest':{'path':profile['label']+'/render-manifest.json','sha256':renderer.digest(path)}})
                if renderer.digest(source)!=source_hash or renderer.digest(specpath)!=spec_hash or image_inputs()!=images:
                    raise ValueError('source/spec/image inputs changed during stress rendering')
                if any(renderer.digest(path)!=tool_hashes[path.name] for path in tool_paths):
                    raise ValueError('tool source files changed during stress rendering')
            (stage/'material-stress.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
            renderer.publish_directory(stage,output)
        print('WROTE',output)
        return 0
    except (ValueError,KeyError,OSError,RuntimeError,ImportError,TypeError) as exc:
        print('ERROR:',exc,file=sys.stderr); return 2

if __name__=='__main__':
    cli=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]
    raise SystemExit(main(cli))
